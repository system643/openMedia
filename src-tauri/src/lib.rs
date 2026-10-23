//! La coque native d'openMedia : elle lance le moteur Python (sidecar), garde l'application
//! vivante dans la zone de notification pour le passage quotidien, et gère les deux fenêtres
//! (« main » et la « bulle », languette qui enregistre l'article ouvert dans le navigateur).

mod browser;

use std::net::TcpListener;
use std::sync::Mutex;

use serde::Serialize;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, RunEvent, WindowEvent};
use tauri_plugin_window_state::StateFlags;

#[derive(Clone, Serialize)]
struct BackendInfo {
    url: String,
    token: String,
}

enum Child {
    Dev(std::process::Child),
    Sidecar(tauri_plugin_shell::process::CommandChild),
}

struct Backend {
    info: BackendInfo,
    child: Mutex<Option<Child>>,
}

#[tauri::command]
fn backend_info(state: tauri::State<Backend>) -> BackendInfo {
    state.info.clone()
}

/// Montre la fenêtre principale et y ouvre une vue (« topic:12 », « new », …).
#[tauri::command]
fn open_main(app: AppHandle, route: Option<String>) {
    show_main(&app);
    if let Some(route) = route {
        let _ = app.emit_to("main", "navigate", route);
    }
}

fn show_main(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.unminimize();
        let _ = w.set_focus();
    }
}

fn toggle_bulle(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("bulle") {
        if w.is_visible().unwrap_or(false) {
            let _ = w.hide();
        } else {
            let _ = w.show();
        }
    }
}

fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .unwrap_or(8765)
}

fn spawn_backend(app: &AppHandle, port: u16, token: &str) -> Option<Child> {
    // --parent-pid : le moteur s'arrête de lui-même si l'application disparaît.
    let args = [
        "--port".to_string(),
        port.to_string(),
        "--token".to_string(),
        token.to_string(),
        "--parent-pid".to_string(),
        std::process::id().to_string(),
    ];
    if cfg!(debug_assertions) {
        // En développement : l'environnement virtuel du dossier backend/.
        let backend = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("..").join("backend");
        let python = backend.join(".venv").join("Scripts").join("python.exe");
        let mut cmd = std::process::Command::new(python);
        cmd.current_dir(&backend).args(["-m", "openmedia.server"]).args(&args);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
        }
        cmd.spawn().ok().map(Child::Dev)
    } else {
        use tauri_plugin_shell::ShellExt;
        let (_rx, child) = app.shell().sidecar("openmedia-backend").ok()?.args(args).spawn().ok()?;
        Some(Child::Sidecar(child))
    }
}

fn kill_backend(app: &AppHandle) {
    if let Some(state) = app.try_state::<Backend>() {
        if let Some(child) = state.child.lock().unwrap().take() {
            match child {
                Child::Dev(mut c) => {
                    let _ = c.kill();
                }
                Child::Sidecar(c) => {
                    let _ = c.kill();
                }
            }
        }
    }
}

fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    let open = MenuItem::with_id(app, "open", "Ouvrir openMedia", true, None::<&str>)?;
    let bulle = MenuItem::with_id(app, "bulle", "Afficher ou masquer la languette", true, None::<&str>)?;
    let run_all = MenuItem::with_id(app, "run_all", "Mettre à jour tous les sujets", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quitter", true, None::<&str>)?;
    let sep = PredefinedMenuItem::separator(app)?;
    let menu = Menu::with_items(app, &[&open, &bulle, &run_all, &sep, &quit])?;
    TrayIconBuilder::with_id("tray")
        .icon(app.default_window_icon().unwrap().clone())
        .tooltip("openMedia")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "open" => show_main(app),
            "bulle" => toggle_bulle(app),
            "run_all" => {
                let _ = app.emit_to("main", "tray-run-all", ());
            }
            "quit" => {
                kill_backend(app);
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event {
                show_main(tray.app_handle());
            }
        })
        .build(app)?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| show_main(app)))
        .plugin(
            tauri_plugin_window_state::Builder::default()
                .with_state_flags(StateFlags::SIZE | StateFlags::POSITION | StateFlags::MAXIMIZED)
                // La languette se place elle-même sur le bord droit, à la hauteur choisie.
                .with_denylist(&["bulle"])
                .build(),
        )
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            Some(vec!["--hidden"]),
        ))
        .setup(|app| {
            let port = free_port();
            let token = uuid::Uuid::new_v4().simple().to_string();
            let child = spawn_backend(app.handle(), port, &token);
            app.manage(Backend {
                info: BackendInfo { url: format!("http://127.0.0.1:{port}"), token },
                child: Mutex::new(child),
            });
            app.manage(browser::Watch::default());
            browser::start(app.handle().clone());
            build_tray(app.handle())?;
            // Lancée au démarrage de Windows : rester discrète dans la zone de notification.
            if std::env::args().any(|a| a == "--hidden") {
                if let Some(w) = app.get_webview_window("main") {
                    let _ = w.hide();
                }
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            // Fermer la fenêtre principale la cache : le passage quotidien continue.
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .invoke_handler(tauri::generate_handler![backend_info, open_main, browser::current_page, browser::set_page_watch])
        .build(tauri::generate_context!())
        .expect("impossible de démarrer openMedia");

    app.run(|app, event| {
        if let RunEvent::Exit = event {
            kill_backend(app);
        }
    });
}
