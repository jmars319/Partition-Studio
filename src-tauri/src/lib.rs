mod domain;

#[tauri::command]
fn execution_status() -> domain::ExecutionStatus {
    domain::ExecutionStatus::disabled()
}

#[tauri::command]
fn supported_scanner_adapters() -> Vec<domain::ScannerAdapterStatus> {
    vec![
        domain::ScannerAdapterStatus::mock_json(),
        domain::ScannerAdapterStatus::future("tenra Partition Lab JSON import"),
        domain::ScannerAdapterStatus::future("Windows PowerShell Storage module"),
        domain::ScannerAdapterStatus::future("Linux lsblk/parted/sgdisk"),
        domain::ScannerAdapterStatus::future("macOS diskutil"),
    ]
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            execution_status,
            supported_scanner_adapters
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
