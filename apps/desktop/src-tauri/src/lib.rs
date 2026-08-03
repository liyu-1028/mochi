//! Mochi 桌面壳入口。
//!
//! 窗口拖拽走前端 `data-tauri-drag-region` 声明式方案（见 App.tsx 角色舞台），
//! 位置记忆由 tauri-plugin-window-state 持久化（功能清单 1.3）。
//!
//! TODO(M1)：系统托盘菜单（功能清单 1.4）

mod sidecar;

use sidecar::SidecarState;
use tauri::{Manager, RunEvent};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .manage(SidecarState::new())
        .setup(|app| {
            // dev 模式尝试自动拉起 sidecar；release 打包方案见 sidecar.rs TODO(M1)
            if cfg!(debug_assertions) {
                let state = app.state::<SidecarState>();
                sidecar::try_spawn_dev_sidecar(&state);
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Mochi desktop application");

    app.run(|app_handle, event| {
        if matches!(event, RunEvent::Exit) {
            app_handle.state::<SidecarState>().kill();
        }
    });
}
