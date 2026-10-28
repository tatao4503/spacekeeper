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

use tauri::menu::{
    AboutMetadata, Menu, MenuBuilder, MenuItemBuilder, PredefinedMenuItem, SubmenuBuilder,
};
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

// 서버 자식 프로세스가 이미 끝났는지. 아예 못 띄웠어도 끝난 것으로 본다.
fn server_exited<R: tauri::Runtime>(win: &tauri::WebviewWindow<R>) -> bool {
    let state = win.state::<ServerProcess>();
    let mut guard = state.0.lock().unwrap();
    match guard.as_mut() {
        Some(child) => matches!(child.try_wait(), Ok(Some(_))),
        None => true,
    }
}

// 시작 화면에 실패를 알린다. 화면의 스크립트(loading.js)보다 먼저 도착할 수 있어
// 신호를 window.__skFailReason 에 남기고, 잠깐 동안 몇 번 반복해서 보낸다.
fn show_startup_failure<R: tauri::Runtime>(win: &tauri::WebviewWindow<R>) {
    for _ in 0..12 {
        let _ = win.eval(
            "window.__skFailReason = 1; window.__skStartupFailed && window.__skStartupFailed();",
        );
        std::thread::sleep(Duration::from_millis(250));
    }
}

const HOMEPAGE: &str = "https://github.com/tatao4503/spacekeeper";

// 화면 맨 위 앱 메뉴. Tauri가 자동으로 붙이는 영어 기본 메뉴 대신,
// 한국어 맥 앱과 같은 이름·순서로 둔다. 편집 메뉴는 장식이 아니다 —
// 이게 있어야 입력칸에서 ⌘C·⌘V·⌘A가 동작한다.
fn build_app_menu<R: tauri::Runtime>(app: &tauri::AppHandle<R>) -> tauri::Result<Menu<R>> {
    let about = PredefinedMenuItem::about(
        app,
        Some("Spacekeeper에 관하여"),
        Some(AboutMetadata {
            name: Some("Spacekeeper".into()),
            version: Some(app.package_info().version.to_string()),
            copyright: Some("© 2026 윤태웅 · MIT License".into()),
            credits: Some("지우지 않고 격리하는 Mac 저장공간 정리 도구".into()),
            ..Default::default()
        }),
    )?;
    let app_menu = SubmenuBuilder::new(app, "Spacekeeper")
        .item(&about)
        .separator()
        .item(&PredefinedMenuItem::services(app, Some("서비스"))?)
        .separator()
        .item(&PredefinedMenuItem::hide(app, Some("Spacekeeper 가리기"))?)
        .item(&PredefinedMenuItem::hide_others(app, Some("기타 가리기"))?)
        .item(&PredefinedMenuItem::show_all(app, Some("모두 보기"))?)
        .separator()
        .item(&PredefinedMenuItem::quit(app, Some("Spacekeeper 종료"))?)
        .build()?;
    let edit = SubmenuBuilder::new(app, "편집")
        .item(&PredefinedMenuItem::undo(app, Some("실행 취소"))?)
        .item(&PredefinedMenuItem::redo(app, Some("실행 복귀"))?)
        .separator()
        .item(&PredefinedMenuItem::cut(app, Some("잘라내기"))?)
        .item(&PredefinedMenuItem::copy(app, Some("복사하기"))?)
        .item(&PredefinedMenuItem::paste(app, Some("붙여넣기"))?)
        .item(&PredefinedMenuItem::select_all(app, Some("전체 선택"))?)
        .build()?;
    let view = SubmenuBuilder::new(app, "보기")
        .item(&PredefinedMenuItem::fullscreen(app, Some("전체 화면"))?)
        .build()?;
    let window = SubmenuBuilder::new(app, "윈도우")
        .item(&PredefinedMenuItem::minimize(app, Some("최소화"))?)
        .item(&PredefinedMenuItem::maximize(app, Some("확대/축소"))?)
        .separator()
        .item(&PredefinedMenuItem::close_window(app, Some("윈도우 닫기"))?)
        .build()?;
    let help = SubmenuBuilder::new(app, "도움말")
        .item(&MenuItemBuilder::with_id("help_shortcuts", "키보드 단축키").build(app)?)
        .item(&MenuItemBuilder::with_id("help_homepage", "Spacekeeper 홈페이지").build(app)?)
        .build()?;
    Menu::with_items(app, &[&app_menu, &edit, &view, &window, &help])
}

fn main() {
    let app = tauri::Builder::default()
        .manage(ServerProcess(Mutex::new(None)))
        .menu(build_app_menu)
        .on_menu_event(|app, event| match event.id().as_ref() {
            // 대시보드에 이미 있는 단축키 안내창을 연다(? 키와 같은 창).
            "help_shortcuts" => {
                if let Some(w) = app.get_webview_window("main") {
                    let _ = w.show();
                    let _ = w.set_focus();
                    let _ = w.eval(
                        "try { document.getElementById('shortcut-modal')?.showModal(); } catch (_) {}",
                    );
                }
            }
            "help_homepage" => {
                let _ = Command::new("/usr/bin/open").arg(HOMEPAGE).spawn();
            }
            _ => {}
        })
        .setup(|app| {
            let port = available_port().ok_or_else(|| {
                std::io::Error::other("Spacekeeper 로컬 포트를 준비할 수 없습니다")
            })?;
            let api_token = generate_api_token().ok_or_else(|| {
                std::io::Error::other("Spacekeeper 앱 인증 정보를 만들 수 없습니다")
            })?;
            let child = spawn_server(port, &api_token);
            let spawned = child.is_some();
            *app.state::<ServerProcess>().0.lock().unwrap() = child;

            // 서버가 준비되면 웹뷰를 대시보드로 이동시킨다.
            if let Some(window) = app.get_webview_window("main") {
                let win = window.clone();
                std::thread::spawn(move || {
                    let mut ready = false;
                    if spawned {
                        for _ in 0..240 {
                            if server_is_ready(port, &api_token) {
                                ready = true;
                                break;
                            }
                            // 서버가 이미 끝났으면 60초를 다 기다릴 이유가 없다.
                            if server_exited(&win) {
                                break;
                            }
                            std::thread::sleep(Duration::from_millis(250));
                        }
                    }
                    if ready {
                        let dashboard_url = format!("http://127.0.0.1:{port}");
                        if let Ok(url) = dashboard_url.parse() {
                            let _ = win.navigate(url);
                        }
                    } else {
                        show_startup_failure(&win);
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
            // 메뉴바 아이콘은 흑백 템플릿이다. macOS가 라이트/다크·강조색에 맞춰
            // 색을 바꾼다. 컬러 앱 아이콘을 그대로 쓰면 메뉴바에서만 튀어 보인다.
            let tray_icon =
                tauri::image::Image::from_bytes(include_bytes!("../icons/tray-template.png"))?;
            tray = tray.icon(tray_icon).icon_as_template(true);
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
