//! Sidecar（Python Agent 服务）生命周期管理（功能清单 1.2）。
//!
//! - **dev 模式**：尝试自动拉起 `uv run uvicorn`；失败则降级为开发者手动
//!   启动（`pnpm dev:server`），前端默认连 127.0.0.1:8199。
//! - **release 模式（M0-S4）**：拉起 bundle.resources 打进安装包的 PyInstaller
//!   onedir 产物（`<resource_dir>/sidecar/mochi-server[.exe]`）。子进程由
//!   监督线程看管：异常退出自动重启（≤3 次，1/2/4s 退避），超限或启动失败
//!   时发 `mochi://sidecar-status` 事件，前端呈现可读提示（1.2 验收）。
//!
//! 监督线程用 `try_wait` 轮询而非阻塞 `wait`：避免持锁等待导致 Exit 时
//! `kill()` 死锁。
//!
//! 端口发现（M1-S0）：sidecar 就绪后写 <userData>/runtime.json，
//! 由 runtime.rs 轮询读取并通知前端（`mochi://sidecar-ready`）。

use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager, Runtime};

pub const SIDECAR_PORT: u16 = 8199;
const MAX_RESTARTS: u32 = 3;
const POLL_INTERVAL_MS: u64 = 200;
pub const STATUS_EVENT: &str = "mochi://sidecar-status";

/// 发给前端的 sidecar 状态事件负载。
#[derive(Clone, Serialize)]
pub struct StatusPayload {
    /// started / restarting / failed
    pub status: &'static str,
    pub detail: String,
}

fn emit_status<R: Runtime>(app: &AppHandle<R>, status: &'static str, detail: String) {
    let _ = app.emit(STATUS_EVENT, StatusPayload { status, detail });
}

pub struct SidecarState {
    child: Mutex<Option<Child>>,
    restarts: AtomicU32,
    shutting_down: AtomicBool,
}

impl SidecarState {
    pub fn new() -> Self {
        Self {
            child: Mutex::new(None),
            restarts: AtomicU32::new(0),
            shutting_down: AtomicBool::new(false),
        }
    }

    /// 标记进入退出流程：监督线程停止重启。须在 `kill()` 前调用。
    pub fn begin_shutdown(&self) {
        self.shutting_down.store(true, Ordering::SeqCst);
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

// ---------------------------------------------------------------------------
// release 模式：打包产物 + 监督重启（M0-S4）
// ---------------------------------------------------------------------------

/// release 模式拉起打包进安装包的 sidecar，并启动监督线程。
/// 任何失败都经 STATUS_EVENT 告知前端（用户可读提示，1.2 验收）。
pub fn spawn_release_sidecar<R: Runtime>(app: &AppHandle<R>) {
    let state = app.state::<SidecarState>();
    let Some(bin) = locate_release_binary(app) else {
        eprintln!("[mochi] release sidecar 产物缺失");
        emit_status(
            app,
            "failed",
            "后端服务组件缺失，请重新安装 Mochi".to_string(),
        );
        return;
    };

    match spawn_sidecar_process(&bin) {
        Ok(child) => {
            eprintln!("[mochi] release sidecar 已拉起：{}", bin.display());
            *state.child.lock().expect("sidecar lock poisoned") = Some(child);
            let app_handle = app.clone();
            std::thread::spawn(move || supervise(app_handle, bin));
        }
        Err(err) => {
            eprintln!("[mochi] release sidecar 启动失败：{err}");
            emit_status(
                app,
                "failed",
                format!("后端服务启动失败：{err}，请重启 Mochi"),
            );
        }
    }
}

fn spawn_sidecar_process(bin: &PathBuf) -> std::io::Result<Child> {
    Command::new(bin)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
}

/// 定位 bundle.resources 中的 sidecar 可执行文件。
/// 布局由 tauri.conf.json `bundle.resources` 与 scripts/package-sidecar.sh 约定：
/// macOS `Mochi.app/Contents/Resources/sidecar/mochi-server`；
/// Windows `<安装目录>/resources/sidecar/mochi-server.exe`。
fn locate_release_binary<R: Runtime>(app: &AppHandle<R>) -> Option<PathBuf> {
    let exe_name = if cfg!(windows) {
        "mochi-server.exe"
    } else {
        "mochi-server"
    };
    let candidate = app.path().resource_dir().ok()?.join("sidecar").join(exe_name);
    candidate.exists().then_some(candidate)
}

/// 监督线程：轮询子进程退出；非正常退出（应用未在关闭流程中）则按
/// 1/2/4s 退避重启，≤3 次；超限发 failed 事件交由用户处置。
fn supervise<R: Runtime>(app: AppHandle<R>, bin: PathBuf) {
    loop {
        // 短持锁轮询，避免阻塞 Exit 时的 kill()
        let exit_status = {
            let state = app.state::<SidecarState>();
            let mut guard = state.child.lock().expect("sidecar lock poisoned");
            match guard.as_mut() {
                Some(child) => child.try_wait().ok().flatten(),
                None => return, // 子进程已被外部回收（退出流程）
            }
        };

        let Some(status) = exit_status else {
            std::thread::sleep(Duration::from_millis(POLL_INTERVAL_MS));
            continue;
        };

        let state = app.state::<SidecarState>();
        if state.shutting_down.load(Ordering::SeqCst) {
            return;
        }

        let attempt = state.restarts.fetch_add(1, Ordering::SeqCst);
        if attempt >= MAX_RESTARTS {
            eprintln!("[mochi] sidecar 重启次数超限（{status}），停止重试");
            emit_status(
                &app,
                "failed",
                "后端服务多次异常退出，请重启 Mochi；若仍出现请反馈日志".to_string(),
            );
            return;
        }

        let delay_s = 1u64 << attempt; // 1s / 2s / 4s
        eprintln!("[mochi] sidecar 异常退出（{status}），{delay_s}s 后重启");
        emit_status(
            &app,
            "restarting",
            format!("后端服务异常，正在自动重启（第 {} 次）…", attempt + 1),
        );
        std::thread::sleep(Duration::from_secs(delay_s));
        if state.shutting_down.load(Ordering::SeqCst) {
            return;
        }

        match spawn_sidecar_process(&bin) {
            Ok(child) => {
                *state.child.lock().expect("sidecar lock poisoned") = Some(child);
                emit_status(&app, "started", "后端服务已恢复".to_string());
            }
            Err(err) => {
                eprintln!("[mochi] sidecar 重启失败：{err}");
                // 继续循环消耗重启次数，超限后统一发 failed
            }
        }
    }
}
