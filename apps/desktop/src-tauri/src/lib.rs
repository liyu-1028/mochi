//! Mochi 桌面壳入口。
//!
//! 窗口拖拽走前端 `data-tauri-drag-region` 声明式方案（见 App.tsx 角色舞台），
//! 位置记忆由 tauri-plugin-window-state 持久化（功能清单 1.3）。
//!
//! 系统托盘菜单（功能清单 1.4）经前端 JS API 构建（src/tray.ts，i18n 共享），
//! Rust 面仅监听退出事件（RunEvent::Exit 回收 sidecar，ADR-0001）。

mod runtime;
mod sidecar;

use sidecar::SidecarState;
use tauri::{Listener, Manager, RunEvent};
use tauri_plugin_window_state::StateFlags;

/// 托盘「退出 Mochi」事件：前端 emit，Rust 监听后退出（无需命令 ACL）。
/// app.exit 触发 RunEvent::Exit，走既有 sidecar 回收路径。
const TRAY_QUIT_EVENT: &str = "mochi:tray-quit";

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        // 仅记忆 character 窗口：panel 窗口运行期创建、每次 center 居中，
        // 若被插件恢复旧状态会覆盖 center:true。
        // 只持久化位置/可见性，不持久化尺寸：尺寸事实源是前端角色布局
        // （characterLayout 按模型包围盒动态推导），恢复旧尺寸会与之冲突
        .plugin(
            tauri_plugin_window_state::Builder::default()
                .with_filter(|label| label == "character")
                .with_state_flags(StateFlags::POSITION | StateFlags::VISIBLE)
                .build(),
        )
        .manage(SidecarState::new())
        .setup(|app| {
            // 托盘「退出 Mochi」：前端 emit 事件（无命令 ACL 负担，ADR-0001）
            let quit_handle = app.handle().clone();
            app.listen(TRAY_QUIT_EVENT, move |_event| quit_handle.exit(0));

            // dev：尝试拉起 uv + uvicorn；release：拉起打包产物并监督重启（1.2）
            if cfg!(debug_assertions) {
                let state = app.state::<SidecarState>();
                sidecar::try_spawn_dev_sidecar(&state);
            } else {
                // 端口发现（M1-S0）：清陈旧文件 → 拉起 sidecar → 轮询 runtime.json
                runtime::remove_stale_runtime_file(app.handle());
                sidecar::spawn_release_sidecar(app.handle());
                runtime::spawn_runtime_discovery(app.handle().clone());
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
