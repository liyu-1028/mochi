//! runtime.json 端口发现（M1-S0）。
//!
//! release 模式的 sidecar 启动就绪后把实际端口写入
//! `<userData>/runtime.json`（Python 侧 mochi_server/runtime.py，
//! 与 Tauri app_data_dir 同目录——ADR-0002 D7）。本模块轮询该文件，
//! 读到后 emit `mochi://sidecar-ready {port}`，前端据此切换连接地址。
//! 独立 webview 可通过 get_sidecar_port 主动查询，避免错过一次性通知。
//!
//! dev 模式不轮询：端口固定 8199，开发者可用 VITE_WS_URL/VITE_API_URL 覆盖。
//!
//! 陈旧文件防御：每次应用启动（spawn sidecar 前）先删除上一轮遗留的
//! runtime.json，避免 sidecar 启动失败时前端读到旧端口误判"就绪"。

use std::path::PathBuf;
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{AppHandle, Emitter, Runtime};

use crate::datadir;

pub const RUNTIME_READY_EVENT: &str = "mochi://sidecar-ready";
const RUNTIME_FILE_NAME: &str = "runtime.json";
const POLL_INTERVAL: Duration = Duration::from_millis(200);
const DISCOVERY_TIMEOUT: Duration = Duration::from_secs(10);

/// 发给前端的就绪负载：实际服务端口。
#[derive(Clone, Serialize)]
pub struct RuntimeReadyPayload {
    pub port: u16,
}

/// 独立窗口启动时读取当前服务端口；冷启动在后台等待，不阻塞 UI 线程。
#[tauri::command]
pub async fn get_sidecar_port(app: AppHandle) -> Option<u16> {
    if cfg!(debug_assertions) {
        return Some(crate::sidecar::SIDECAR_PORT);
    }
    let path = runtime_file_path(&app)?;
    tauri::async_runtime::spawn_blocking(move || wait_for_port(&path, DISCOVERY_TIMEOUT))
        .await
        .ok()
        .flatten()
}

/// 删除上一轮遗留的 runtime.json（启动时调用一次）。
pub fn remove_stale_runtime_file<R: Runtime>(app: &AppHandle<R>) {
    if let Some(path) = runtime_file_path(app) {
        let _ = std::fs::remove_file(path);
    }
}

/// 启动轮询线程：读到 runtime.json 即 emit 就绪事件（一次性）。
/// 超时仅打印提示——前端保持默认端口 + 重连机制兜底，不额外打扰用户。
pub fn spawn_runtime_discovery<R: Runtime>(app: AppHandle<R>) {
    std::thread::spawn(move || {
        let Some(path) = runtime_file_path(&app) else {
            eprintln!("[mochi] 无法解析 app_data_dir，跳过端口发现");
            return;
        };
        if let Some(port) = wait_for_port(&path, DISCOVERY_TIMEOUT) {
            eprintln!("[mochi] sidecar 就绪（runtime.json）：端口 {port}");
            let _ = app.emit(RUNTIME_READY_EVENT, RuntimeReadyPayload { port });
            return;
        }
        eprintln!("[mochi] runtime.json 超时未就绪，前端将按默认端口重试连接");
    });
}

fn wait_for_port(path: &PathBuf, timeout: Duration) -> Option<u16> {
    let deadline = Instant::now() + timeout;
    loop {
        if let Some(port) = read_port(path) {
            return Some(port);
        }
        let remaining = deadline.checked_duration_since(Instant::now())?;
        std::thread::sleep(POLL_INTERVAL.min(remaining));
    }
}

fn runtime_file_path<R: Runtime>(app: &AppHandle<R>) -> Option<PathBuf> {
    // 便携模式（Windows zip 版）下重定向到解压目录，与 sidecar 写入侧对齐
    datadir::resolve_data_dir(app).map(|dir| dir.join(RUNTIME_FILE_NAME))
}

/// 解析 runtime.json 的 port 字段；文件缺失/半截/畸形一律视为未就绪。
fn read_port(path: &PathBuf) -> Option<u16> {
    let content = std::fs::read_to_string(path).ok()?;
    let value: serde_json::Value = serde_json::from_str(&content).ok()?;
    let port: u16 = value.get("port")?.as_u64()?.try_into().ok()?;
    (port > 0).then_some(port)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn independent_window_reads_existing_port_and_waits_for_cold_start() {
        let dir = std::env::temp_dir().join(format!("mochi-runtime-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("runtime.json");
        for content in [
            r#"{"port":0}"#,
            r#"{"port":65536}"#,
            r#"{"port":"8199"}"#,
            r#"{"port":"#,
        ] {
            std::fs::write(&path, content).unwrap();
            assert_eq!(read_port(&path), None);
        }
        std::fs::remove_file(&path).unwrap();
        assert_eq!(wait_for_port(&path, Duration::from_millis(5)), None);
        let writer_path = path.clone();
        let writer = std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(10));
            std::fs::write(writer_path, r#"{"port":56873}"#).unwrap();
        });
        assert_eq!(wait_for_port(&path, Duration::from_secs(1)), Some(56873));
        writer.join().unwrap();
        // 新窗口晚于 ready 事件打开时，快照也无需再次等待通知。
        assert_eq!(wait_for_port(&path, Duration::ZERO), Some(56873));
        std::fs::remove_dir_all(dir).unwrap();
    }
}
