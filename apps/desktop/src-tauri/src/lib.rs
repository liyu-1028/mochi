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
            // 窗口尺寸以 tauri.conf.json 为唯一事实源：tauri-plugin-window-state
            // 会恢复旧版本保存的尺寸，布局改版后需强制覆盖（位置记忆保留，
            // min/max 约束同时兜底），保证气泡/角色布局对齐。
            if let Some(window) = app.get_webview_window("character") {
                if let Some(cfg) = app.config().app.windows.first() {
                    let _ = window.set_size(tauri::LogicalSize::new(cfg.width, cfg.height));
                }
            }
            // dev：尝试拉起 uv + uvicorn；release：拉起打包产物并监督重启（1.2）
            if cfg!(debug_assertions) {
                let state = app.state::<SidecarState>();
                sidecar::try_spawn_dev_sidecar(&state);
            } else {
                sidecar::spawn_release_sidecar(app.handle());
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Mochi desktop application");

    app.run(|app_handle, event| {
        if matches!(event, RunEvent::Exit) {
            let state = app_handle.state::<SidecarState>();
            state.begin_shutdown(); // 先停监督线程的重启意图，再回收子进程
            state.kill();
        }
    });
}
