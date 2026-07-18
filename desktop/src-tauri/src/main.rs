// Spacekeeper 데스크탑 앱.
// 로컬 Python 서버(spacekeeper --serve)를 자식 프로세스로 띄우고, 서버가 준비되면
// 웹뷰를 대시보드로 이동시킵니다. 메뉴바(트레이)에 상주하며, 창을 닫아도 트레이에
// 남아 있다가 "종료"를 누르면 서버까지 함께 정리합니다.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::{SocketAddr, TcpStream};
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::Duration;

use tauri::menu::{MenuBuilder, MenuItemBuilder};
use tauri::tray::TrayIconBuilder;
use tauri::{Manager, RunEvent, WindowEvent};

const PORT: u16 = 8765;
const URL: &str = "http://127.0.0.1:8765";

// 앱과 함께 종료할 수 있도록 서버 자식 프로세스를 보관한다.
struct ServerProcess(Mutex<Option<Child>>);

// 파이썬 런타임은 보호되지 않는 홈 하위 경로에 스테이징한다.
// (저장소가 ~/Desktop 등 TCC 보호 폴더에 있으면, 서명 없는 앱이 스폰한
//  파이썬이 시작 시 그 경로를 훑다가 권한 프롬프트에 막히기 때문이다.)
fn runtime_root() -> std::path::PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".into());
    std::path::PathBuf::from(home).join(".spacekeeper/runtime")
}

fn server_is_up() -> bool {
    let addr: SocketAddr = ([127, 0, 0, 1], PORT).into();
    TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok()
}

fn spawn_server() -> Option<Child> {
    if server_is_up() {
        return None; // 이미 떠 있으면 그대로 사용
    }
    // cwd를 저장소(예: ~/Desktop 하위)로 두면, 서명 없는 앱이 스폰한 파이썬이
    // 시작 시 getcwd()에서 macOS 프라이버시(TCC) 프롬프트를 만나 멈춘다.
    // 중립 디렉터리에서 실행하고 PYTHONPATH로 패키지를 잡아 이 블록을 피한다.
    Command::new("python3")
        .args(["-m", "spacekeeper", "--serve", "--port", "8765"])
        .env("PYTHONPATH", runtime_root())
        .current_dir(std::env::temp_dir())
        .spawn()
        .ok()
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
                    for _ in 0..80 {
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
