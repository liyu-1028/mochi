//! Mochi 桌面壳入口。
//!
//! TODO(M0)：
//! - sidecar 生命周期管理（拉起/健康检查/重启 LangGraph 服务，功能清单 1.2）
//! - 系统托盘菜单（功能清单 1.4）
//! - 角色窗口拖拽与位置记忆（功能清单 1.3）

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .run(tauri::generate_context!())
        .expect("error while running Mochi desktop application");
}
