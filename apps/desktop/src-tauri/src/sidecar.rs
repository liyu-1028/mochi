//! Sidecar（Python Agent 服务）生命周期管理。
//!
//! M0-S1 范围：dev 模式尝试自动拉起 `uv run uvicorn`；失败则降级为
//! 开发者手动启动（`pnpm dev:server`），前端默认连 127.0.0.1:8199。
//! 健康探测交由前端 WS 客户端的重连机制负责，Rust 侧保持最小逻辑。
//!
//! TODO(M1)：
//! - 生产模式打包 Python 运行时（PyInstaller，见 docs/specs/monorepo-structure.md §7）
//! - runtime.json 端口发现（sidecar 就绪后写 <userData>/runtime.json）

use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

pub const SIDECAR_PORT: u16 = 8199;

pub struct SidecarState {
    child: Mutex<Option<Child>>,
}

impl SidecarState {
    pub fn new() -> Self {
        Self {
            child: Mutex::new(None),
        }
    }

    /// 退出时回收 sidecar 子进程（幂等）。
    pub fn kill(&self) {
        if let Some(mut child) = self.child.lock().expect("sidecar lock poisoned").take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

/// dev 模式自动拉起 sidecar（依赖 PATH 中的 uv）。
/// 失败仅打印提示——开发者可手动 `pnpm dev:server`，前端重连机制会接住。
pub fn try_spawn_dev_sidecar(state: &SidecarState) {
    let Some(server_dir) = locate_server_dir() else {
        eprintln!("[mochi] 未定位到 server/ 目录，请手动执行 pnpm dev:server");
        return;
    };

    let port = SIDECAR_PORT.to_string();
    match Command::new("uv")
        .args(["run", "uvicorn", "mochi_server.main:app", "--port", &port])
        .current_dir(server_dir)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
    {
        Ok(child) => {
            eprintln!("[mochi] sidecar 已自动拉起（端口 {SIDECAR_PORT}）");
            *state.child.lock().expect("sidecar lock poisoned") = Some(child);
        }
        Err(err) => {
            eprintln!("[mochi] 自动拉起 sidecar 失败（{err}），请手动执行 pnpm dev:server");
        }
    }
}

/// dev 模式下 cargo 在 apps/desktop/src-tauri 运行，工作区根目录上三级。
/// 以 pyproject.toml 存在与否作为定位校验，避免误拉起。
fn locate_server_dir() -> Option<PathBuf> {
    let cwd = std::env::current_dir().ok()?;
    let candidate = cwd.join("..").join("..").join("..").join("server");
    candidate
        .canonicalize()
        .ok()
        .filter(|p| p.join("pyproject.toml").exists())
}
