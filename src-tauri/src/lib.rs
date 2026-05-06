mod domain;

use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem, Submenu},
    Manager, Runtime,
};

const APP_NAME: &str = "tenra Partition";
const MENU_SETTINGS: &str = "settings";
const MENU_CLOSE_WINDOW: &str = "close-window";
const MENU_QUIT: &str = "quit";

#[tauri::command]
fn execution_status() -> domain::ExecutionStatus {
    domain::ExecutionStatus::disabled()
}

#[tauri::command]
fn supported_scanner_adapters() -> Vec<domain::ScannerAdapterStatus> {
    vec![
        domain::ScannerAdapterStatus::mock_json(),
        domain::ScannerAdapterStatus::future("Integrated lab JSON import"),
        domain::ScannerAdapterStatus::future("Windows PowerShell Storage module"),
        domain::ScannerAdapterStatus::future("Linux lsblk/parted/sgdisk"),
        domain::ScannerAdapterStatus::future("macOS diskutil"),
    ]
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .menu(build_app_menu)
        .on_menu_event(|app, event| match event.id().as_ref() {
            MENU_SETTINGS => {
                let _ = show_main_window(app);
            }
            MENU_CLOSE_WINDOW => {
                let _ = close_main_window(app);
            }
            MENU_QUIT => app.exit(0),
            _ => {}
        })
        .on_window_event(|window, event| {
            if window.label() == "main" {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            execution_status,
            supported_scanner_adapters
        ])
        .build(tauri::generate_context!())
        .expect("error while building tenra Partition");

    app.run(|app_handle, event| match event {
        #[cfg(target_os = "macos")]
        tauri::RunEvent::Reopen {
            has_visible_windows: false,
            ..
        } => {
            let _ = show_main_window(app_handle);
        }
        _ => {}
    });
}

fn build_app_menu<R: Runtime>(app: &tauri::AppHandle<R>) -> tauri::Result<Menu<R>> {
    let app_menu = Submenu::with_items(
        app,
        APP_NAME,
        true,
        &[
            &MenuItem::with_id(app, MENU_SETTINGS, "Settings...", true, Some("CmdOrCtrl+,"))?,
            &PredefinedMenuItem::separator(app)?,
            &MenuItem::with_id(
                app,
                MENU_CLOSE_WINDOW,
                "Close Window",
                true,
                Some("CmdOrCtrl+W"),
            )?,
            &MenuItem::with_id(app, MENU_QUIT, "Quit", true, Some("CmdOrCtrl+Q"))?,
        ],
    )?;

    Menu::with_items(app, &[&app_menu])
}

fn show_main_window<R: Runtime>(app: &tauri::AppHandle<R>) -> tauri::Result<()> {
    if let Some(window) = app.get_webview_window("main") {
        window.show()?;
        window.set_focus()?;
    }

    Ok(())
}

fn close_main_window<R: Runtime>(app: &tauri::AppHandle<R>) -> tauri::Result<()> {
    if let Some(window) = app.get_webview_window("main") {
        window.hide()?;
    }

    Ok(())
}
