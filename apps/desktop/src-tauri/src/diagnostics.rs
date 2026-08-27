//! 诊断包导出（功能清单 1.8）与设置文件读写（7.1 设置导入导出尾巴）。
//!
//! export_diagnostics：打包运行时诊断信息 → zip（前端经 dialog 插件选保存路径后调用）：
//! - system.json：OS/arch/app 版本/导出时间；
//! - runtime.json 副本：端口发现现场；
//! - config.sanitized.toml：用户配置副本（事实源本就不落密钥，仅 key_ref
//!   引用名；仍过一遍脱敏扫描防御未来格式变动）；
//! - logs/*.log：app 数据目录下的 sidecar 日志，逐条脱敏；
//! - storage.json：数据库/检查点文件大小（不含内容，隐私红线）。
//!
//! 脱敏红线（§8 安全）：sk-…/rk-… 形态、Bearer 凭据、名为
//! key/secret/token/password 的 TOML 赋值一律替换 [REDACTED]。

use std::fs;
use std::io::{Seek, Write};
use std::sync::OnceLock;

use serde::Serialize;
use tauri::{AppHandle, Manager, Runtime};
use zip::write::SimpleFileOptions;
use zip::ZipWriter;

#[derive(Serialize)]
struct SystemInfo {
    os: &'static str,
    arch: &'static str,
    app_version: String,
    exported_at_unix: u64,
}

fn secret_patterns() -> &'static (regex::Regex, regex::Regex, regex::Regex) {
    static PATTERNS: OnceLock<(regex::Regex, regex::Regex, regex::Regex)> = OnceLock::new();
    PATTERNS.get_or_init(|| {
        (
            // API Key 常见形态（OpenAI sk- / Anthropic sk-ant- 等）
            regex::Regex::new(r"(sk-[A-Za-z0-9_\-]{8,}|rk-[A-Za-z0-9_\-]{8,})").unwrap(),
            // HTTP 凭据头
            regex::Regex::new(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}").unwrap(),
            // TOML 赋值防御：未来若有密钥字段落盘（当前格式不存在）
            regex::Regex::new(r#"(?im)^(\s*(?:api_)?(?:key|secret|token|password)\s*=\s*)"[^"]*""#)
                .unwrap(),
        )
    })
}

/// 三模式逐层脱敏。
fn redact_text(text: &str) -> String {
    let (sk, bearer, toml_key) = secret_patterns();
    let step1 = sk.replace_all(text, "[REDACTED]");
    let step2 = bearer.replace_all(&step1, "Bearer [REDACTED]");
    toml_key
        .replace_all(&step2, "${1}\"[REDACTED]\"")
        .to_string()
}

/// 收集诊断 zip 到 `path`；返回写入内容字节数（供前端反馈）。
#[tauri::command]
pub fn export_diagnostics<R: Runtime>(app: AppHandle<R>, path: String) -> Result<u64, String> {
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("无法定位数据目录：{e}"))?;
    let bytes = build_diagnostic_zip(
        &data_dir,
        &app.package_info().version.to_string(),
    )?;
    fs::write(&path, &bytes).map_err(|e| format!("写入失败：{e}"))?;
    Ok(bytes.len() as u64)
}

/// 纯函数核心：从数据目录收集诊断内容并打包（可单测）。
pub fn build_diagnostic_zip(data_dir: &std::path::Path, app_version: &str) -> Result<Vec<u8>, String> {
    let mut zip = ZipWriter::new(std::io::Cursor::new(Vec::new()));
    let options: SimpleFileOptions =
        SimpleFileOptions::default().compression_method(zip::CompressionMethod::Deflated);


    // 1) system.json
    let sys = SystemInfo {
        os: std::env::consts::OS,
        arch: std::env::consts::ARCH,
        app_version: app_version.to_string(),
        exported_at_unix: std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0),
    };
    add_json(&mut zip, options, "system.json", &sys);

    // 2) runtime.json（端口发现现场；可能尚不存在）
    if let Ok(content) = fs::read_to_string(data_dir.join("runtime.json")) {
        add_text(&mut zip, options, "runtime.json", &redact_text(&content));
    }

    // 3) config.sanitized.toml
    if let Ok(content) = fs::read_to_string(data_dir.join("config.toml")) {
        add_text(&mut zip, options, "config.sanitized.toml", &redact_text(&content));
    }

    // 4) 日志：数据目录 *.log 逐个脱敏
    if let Ok(entries) = fs::read_dir(&data_dir) {
        for entry in entries.flatten() {
            let p = entry.path();
            if p.extension().and_then(|e| e.to_str()) == Some("log") {
                let name = p
                    .file_name()
                    .and_then(|n| n.to_str())
                    .unwrap_or("unknown.log");
                if let Ok(content) = fs::read_to_string(&p) {
                    add_text(
                        &mut zip,
                        options,
                        &format!("logs/{name}"),
                        &redact_text(&content),
                    );
                }
            }
        }
    }

    // 5) storage.json：库文件大小（不含内容）
    let mut storage = serde_json::Map::new();
    for name in ["mochi.db", "mochi-checkpoints.db"] {
        if let Ok(meta) = fs::metadata(data_dir.join(name)) {
            storage.insert(name.to_string(), serde_json::json!(meta.len()));
        }
    }
    add_json(&mut zip, options, "storage.json", &storage);

    // 各条目独立写入，单条失败跳过不阻断（诊断包尽力而为）
    let bytes = zip.finish().map_err(|e| format!("打包失败：{e}"))?;
    Ok(bytes.into_inner())
}

/// 设置导出落盘（7.1）：前端持有 JSON 内容（来自脱敏的 GET /config），
/// Rust 仅负责原子写，路径来自 dialog 插件。
#[tauri::command]
pub fn write_text_file(path: String, contents: String) -> Result<(), String> {
    // 原子写：先写临时文件再改名，避免半截文件
    let tmp = format!("{path}.tmp");
    fs::write(&tmp, contents).map_err(|e| format!("写入失败：{e}"))?;
    fs::rename(&tmp, &path).map_err(|e| format!("落盘失败：{e}"))?;
    Ok(())
}

/// 设置导入读取（7.1）：读 JSON 文本交前端校验应用。
#[tauri::command]
pub fn read_text_file(path: String) -> Result<String, String> {
    if !std::path::Path::new(&path).exists() {
        return Err("文件不存在".into());
    }
    fs::read_to_string(path).map_err(|e| format!("读取失败：{e}"))
}

fn add_text<W: Write + Seek>(
    zip: &mut ZipWriter<W>,
    options: SimpleFileOptions,
    name: &str,
    content: &str,
) -> u64 {
    let _ = zip.start_file(name, options);
    let _ = zip.write_all(content.as_bytes());
    content.len() as u64
}

fn add_json<W: Write + Seek, T: Serialize>(
    zip: &mut ZipWriter<W>,
    options: SimpleFileOptions,
    name: &str,
    value: &T,
) -> u64 {
    match serde_json::to_string_pretty(value) {
        Ok(json) => add_text(zip, options, name, &json),
        Err(_) => 0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[allow(unused_imports)]
    use std::io::Read as _;

    #[test]
    fn 裸密钥与凭据头被抹除() {
        let text = "key sk-abc123def456ghi789 leaked in log\nAuthorization: Bearer abcdef123456XYZ";
        let out = redact_text(text);
        assert!(!out.contains("sk-abc123"));
        assert!(!out.contains("abcdef123456XYZ"));
        assert!(out.contains("[REDACTED]"));
    }

    #[test]
    fn toml_密钥赋值被抹除但保留字段名() {
        let text = "api_key = \"supersecretvalue123\"\nname = \"keep-me\"";
        let out = redact_text(text);
        assert!(out.contains("api_key = \"[REDACTED]\""));
        assert!(out.contains("keep-me"));
    }

    #[test]
    fn 正常文本不受影响() {
        let text = "用户说：你好\nmodel = \"qwen2.5:1.5b\"";
        assert_eq!(redact_text(text), text);
    }

    #[test]
    fn 诊断包含全部条且日志脱敏() {
        let dir = std::env::temp_dir().join("mochi-diag-test");
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join("runtime.json"), r#"{"port": 8199}"#).unwrap();
        fs::write(dir.join("config.toml"), "active_skin = \"pikachu\"\n").unwrap();
        fs::write(dir.join("mochi-server.log"), "error: key sk-abcdef123456 leaked").unwrap();
        fs::write(dir.join("mochi.db"), "x".repeat(1024)).unwrap();

        let bytes = build_diagnostic_zip(&dir, "0.9.0").unwrap();
        assert!(bytes.len() > 100);

        // 解包验证条目与脱敏
        let reader = zip::ZipArchive::new(std::io::Cursor::new(&bytes)).unwrap();
        let names: Vec<String> = reader.file_names().map(str::to_string).collect();
        for expected in [
            "system.json",
            "runtime.json",
            "config.sanitized.toml",
            "logs/mochi-server.log",
            "storage.json",
        ] {
            assert!(names.contains(&expected.to_string()), "缺 {expected}");
        }
        let mut reader = zip::ZipArchive::new(std::io::Cursor::new(&bytes)).unwrap();
        let mut log = String::new();
        reader
            .by_name("logs/mochi-server.log")
            .unwrap()
            .read_to_string(&mut log)
            .unwrap();
        assert!(!log.contains("sk-abcdef"));
        assert!(log.contains("[REDACTED]"));

        let _ = fs::remove_dir_all(&dir);
    }
}
