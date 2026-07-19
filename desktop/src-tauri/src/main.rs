// Spacekeeper 데스크탑 앱.
// 앱에 포함된 로컬 Python 서버 sidecar를 자식 프로세스로 띄우고, 서버가 준비되면
// 웹뷰를 대시보드로 이동시킵니다. 메뉴바(트레이)에 상주하며, 창을 닫아도 트레이에
// 남아 있다가 "종료"를 누르면 서버까지 함께 정리합니다.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use tauri::menu::{MenuBuilder, MenuItemBuilder};
use tauri::tray::TrayIconBuilder;
use tauri::{Manager, RunEvent, WindowEvent};

const PORT: u16 = 8765;
const URL: &str = "http://127.0.0.1:8765";

// 앱과 함께 종료할 수 있도록 서버 자식 프로세스를 보관한다.
struct ServerProcess(Mutex<Option<Child>>);

fn server_is_up() -> bool {
    let addr: SocketAddr = ([127, 0, 0, 1], PORT).into();
    TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok()
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

fn spawn_server() -> Option<Child> {
    if server_is_up() {
        return None; // 이미 떠 있으면 그대로 사용
    }
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
            *app.state::<ServerProcess>().0.lock().unwrap() = spawn_server();

            // 서버가 준비되면 웹뷰를 대시보드로 이동시킨다.
            if let Some(window) = app.get_webview_window("main") {
                let win = window.clone();
                std::thread::spawn(move || {
                    for _ in 0..240 {
                        if server_is_up() {
                            if let Ok(url) = URL.parse() {
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
