use serde::Serialize;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ExecutionStatus {
    pub enabled: bool,
    pub reason: String,
}

impl ExecutionStatus {
    pub fn disabled() -> Self {
        Self {
            enabled: false,
            reason: "Execution is not available until tested through tenra Partition Lab.".to_string(),
        }
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ScannerAdapterStatus {
    pub name: String,
    pub available: bool,
    pub mode: String,
}

impl ScannerAdapterStatus {
    pub fn mock_json() -> Self {
        Self {
            name: "Mock JSON".to_string(),
            available: true,
            mode: "read-only".to_string(),
        }
    }

    pub fn future(name: &str) -> Self {
        Self {
            name: name.to_string(),
            available: false,
            mode: "planned".to_string(),
        }
    }
}
