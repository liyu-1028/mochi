fn main() {
    // `bundle.resources` 引用的 sidecar onedir 产物目录（scripts/package-sidecar.sh
    // 的输出）是 gitignore 的运行期构建产物。tauri-build 在编译期校验 resources
    // 路径必须存在，而 fresh clone / CI（clippy、cargo check）尚未构建 sidecar，
    // 故在此幂等确保空目录存在以通过校验。
    //
    // 真实 `tauri build` 时 beforeBuildCommand 会先运行 package-sidecar.sh 填充
    // 该目录，随后 cargo build 才执行到本脚本——create_dir_all 对已存在目录为
    // 无操作，不影响正式产物。
    let _ = std::fs::create_dir_all("binaries/sidecar");
    // 前端产物内嵌进二进制（tauri::generate_context!）。cargo 默认不感知
    // ../dist 变化，纯前端改动后的 tauri build 可能复用旧 crate、继续内嵌
    // 旧前端——显式声明依赖，保证前端变更触发重编译重内嵌。
    println!("cargo:rerun-if-changed=../dist");
    tauri_build::build()
}
