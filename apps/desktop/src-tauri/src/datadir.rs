//! 数据目录解析（与 Python 侧 mochi_server/paths.py 语义对齐）。
//!
//! 便携模式（Windows zip 版）：可执行文件所在目录（或有限级父目录）
//! 存在 `mochi.portable` 标记时，解压目录即数据目录——config.toml、
//! skins/、数据库、runtime.json 全部落在解压目录，拷走整个文件夹
//! 即完成迁移。未命中回落 Tauri `app_data_dir`（安装版行为不变）。
//!
//! 探测层级上限与 Python 侧一致：桌面壳 exe 在解压根目录（1 层即命中）；
//! sidecar 在 `<root>/resources/sidecar/`（Python 侧自行向上 3 层）。

use std::path::{Path, PathBuf};

use tauri::{AppHandle, Manager, Runtime};

pub const PORTABLE_MARKER: &str = "mochi.portable";
const PORTABLE_MAX_LEVELS: usize = 4;

/// 解析数据目录：便携标记优先，回落 Tauri app_data_dir。
/// 消费方：runtime.rs（runtime.json 端口发现）、diagnostics.rs（诊断包）。
pub fn resolve_data_dir<R: Runtime>(app: &AppHandle<R>) -> Option<PathBuf> {
    portable_data_dir().or_else(|| app.path().app_data_dir().ok())
}

/// 便携模式探测入口：从当前可执行文件向上找标记。
pub fn portable_data_dir() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    find_portable_marker(exe.parent()?)
}

/// 纯函数：从 `start` 逐级向上（≤ PORTABLE_MAX_LEVELS 层）找便携标记。
pub fn find_portable_marker(start: &Path) -> Option<PathBuf> {
    let mut dir = start;
    for _ in 0..PORTABLE_MAX_LEVELS {
        if dir.join(PORTABLE_MARKER).is_file() {
            return Some(dir.to_path_buf());
        }
        dir = dir.parent()?;
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_root(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("mochi-portable-test-{tag}"));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn exe_同目录命中标记返回该目录() {
        let root = temp_root("same-level");
        std::fs::write(root.join(PORTABLE_MARKER), "").unwrap();
        assert_eq!(find_portable_marker(&root), Some(root.clone()));
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn 安装布局向上探测命中根目录标记() {
        // Windows NSIS 安装布局：<root>/resources/sidecar/mochi-server.exe
        let root = temp_root("nested");
        let sidecar_dir = root.join("resources").join("sidecar");
        std::fs::create_dir_all(&sidecar_dir).unwrap();
        std::fs::write(root.join(PORTABLE_MARKER), "").unwrap();
        assert_eq!(find_portable_marker(&sidecar_dir), Some(root.clone()));
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn 无标记返回_none_层级外标记不命中() {
        let root = temp_root("no-marker");
        let nested = root.join("a").join("b").join("c").join("d");
        std::fs::create_dir_all(&nested).unwrap();
        assert_eq!(find_portable_marker(&nested), None);

        // 超出层级上限的标记不算（d 向上 5 层才到 root）
        std::fs::write(root.join(PORTABLE_MARKER), "").unwrap();
        assert_eq!(find_portable_marker(&nested), None);
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn 目录不存在标记不命中() {
        let ghost = std::env::temp_dir().join("mochi-portable-ghost");
        assert_eq!(find_portable_marker(&ghost), None);
    }
}
