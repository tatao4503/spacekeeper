// Spacekeeper 데스크탑 앱.
// 앱에 포함된 로컬 Python 서버 sidecar를 자식 프로세스로 띄우고, 서버가 준비되면
// 웹뷰를 대시보드로 이동시킵니다. 메뉴바(트레이)에 상주하며, 창을 닫아도 트레이에
// 남아 있다가 "종료"를 누르면 서버까지 함께 정리합니다.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fmt::Write as FmtWrite;
use std::fs::File;
use std::io::{Read, Write as IoWrite};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use tauri::menu::{MenuBuilder, MenuItemBuilder};
use tauri::tray::TrayIconBuilder;
use tauri::{Manager, RunEvent, WindowEvent};

// 앱과 함께 종료할 수 있도록 서버 자식 프로세스를 보관한다.
struct ServerProcess(Mutex<Option<Child>>);

fn available_port() -> Option<u16> {
    TcpListener::bind(SocketAddr::from(([127, 0, 0, 1], 0)))
        .ok()?
        .local_addr()
        .ok()
        .map(|addr| addr.port())
}

fn generate_api_token() -> Option<String> {
    let mut random = [0_u8; 32];
    File::open("/dev/urandom")
        .ok()?
        .read_exact(&mut random)
        .ok()?;
    let mut token = String::with_capacity(random.len() * 2);
    for byte in random {
        write!(&mut token, "{byte:02x}").ok()?;
    }
    Some(token)
}

fn server_is_ready(port: u16, api_token: &str) -> bool {
    let addr: SocketAddr = ([127, 0, 0, 1], port).into();
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_millis(300)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(300)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(300)));
    let request = format!(
        "GET /api/system-status HTTP/1.1\r\n\
         Host: 127.0.0.1:{port}\r\n\
         X-Spacekeeper-Token: {api_token}\r\n\
         Connection: close\r\n\r\n"
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut response = [0_u8; 64];
    let Ok(read) = stream.read(&mut response) else {
        return false;
    };
    let status = String::from_utf8_lossy(&response[..read]);
    status.starts_with("HTTP/1.0 200") || status.starts_with("HTTP/1.1 200")
}

fn sidecar_path() -> Option<PathBuf> {
    // macOS 앱이 전치(App Translocation)된 경우에도 현재 실행 파일에서 같은
    // 번들의 Contents/Resources를 찾아가면 외부 설치 경로에 의존하지 않는다.
    if let Ok(executable) = std::env::current_exe() {
        if let Some(contents) = executable.parent().and_then(|macos| macos.parent()) {
            let bundled = contents
                .join("Resources")
                .join("sidecar")
                .join("spacekeeper-server");
            if bundled.is_file() {
                return Some(bundled);
            }
        }
    }

    #[cfg(debug_assertions)]
    {
        let development = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join(".sidecar-dist")
            .join("spacekeeper-server")
            .join("spacekeeper-server");
        if development.is_file() {
            return Some(development);
        }
    }

    None
}

fn spawn_server(port: u16, api_token: &str) -> Option<Child> {
    let sidecar = match sidecar_path() {
        Some(path) => path,
        None => {
            eprintln!("Spacekeeper server sidecar is unavailable");
            return None;
        }
    };

    match Command::new(sidecar)
        .env(
            "SPACEKEEPER_DESKTOP_PARENT_PID",
            std::process::id().to_string(),
        )
        .env("SPACEKEEPER_PORT", port.to_string())
        .env("SPACEKEEPER_API_TOKEN", api_token)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
    {
        Ok(child) => Some(child),
        Err(error) => {
            eprintln!("Failed to start Spacekeeper server sidecar: {error}");
            None
        }
    }
}

fn main() {
    let app = tauri::Builder::default()
        .manage(ServerProcess(Mutex::new(None)))
        .setup(|app| {
            let port = available_port().ok_or_else(|| {
                std::io::Error::other("Spacekeeper 로컬 포트를 준비할 수 없습니다")
            })?;
            let api_token = generate_api_token().ok_or_else(|| {
                std::io::Error::other("Spacekeeper 앱 인증 정보를 만들 수 없습니다")
            })?;
            let child = spawn_server(port, &api_token)
                .ok_or_else(|| std::io::Error::other("Spacekeeper 서버를 시작할 수 없습니다"))?;
            *app.state::<ServerProcess>().0.lock().unwrap() = Some(child);

            // 서버가 준비되면 웹뷰를 대시보드로 이동시킨다.
            if let Some(window) = app.get_webview_window("main") {
                let win = window.clone();
                std::thread::spawn(move || {
                    for _ in 0..240 {
                        if server_is_ready(port, &api_token) {
                            let dashboard_url = format!("http://127.0.0.1:{port}");
                            if let Ok(url) = dashboard_url.parse() {
                                let _ = win.navigate(url);
                            }
                            break;
                        }
                        std::thread::sleep(Duration::from_millis(250));
                    }
                });
            }

            // 메뉴바 트레이
            let open = MenuItemBuilder::with_id("open", "Spacekeeper 열기").build(app)?;
            let quit = MenuItemBuilder::with_id("quit", "종료").build(app)?;
            let menu = MenuBuilder::new(app).items(&[&open, &quit]).build()?;
            let mut tray = TrayIconBuilder::new()
                .menu(&menu)
                .tooltip("Spacekeeper")
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "open" => {
                        if let Some(w) = app.get_webview_window("main") {
                            let _ = w.show();
                            let _ = w.set_focus();
                        }
                    }
                    "quit" => app.exit(0),
                    _ => {}
                });
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.build(app)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            // 창을 닫아도 앱은 트레이에 남는다.
            if let WindowEvent::CloseRequested { api, .. } = event {
                let _ = window.hide();
                api.prevent_close();
            }
        })
        .build(tauri::generate_context!())
        .expect("Spacekeeper 앱을 시작할 수 없습니다");

    app.run(|app_handle, event| {
        if let RunEvent::Exit = event {
            if let Some(mut child) = app_handle.state::<ServerProcess>().0.lock().unwrap().take() {
                let _ = child.kill();
            }
        }
    });
}
