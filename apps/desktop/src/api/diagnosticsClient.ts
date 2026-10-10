/**
 * diagnosticsClient —— 诊断包导出与设置导入导出（功能清单 1.8 / 7.1 尾巴）。
 *
 * 路径选择走 dialog 插件（保存/打开对话框），文件落盘与打包在 Rust 命令
 * （src-tauri/src/diagnostics.rs）；设置 JSON 内容来自 GET /config/export 的可迁移快照，
 * 模型连接、key_ref 与密钥不进入备份文件。
 *
 * 导入应用范围：语言、省电、角色、语音、回复长度与人格（服务端一次校验与保存）；
 * 模型连接涉及钥匙串绑定不随文件迁移，
 * 跨机导入后需在设置里补录 Key。
 */
import { save, open } from "@tauri-apps/plugin-dialog";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { emit } from "@tauri-apps/api/event";
import {
  EVENT_LANGUAGE_CHANGED,
  EVENT_POWER_SAVE_CHANGED,
  EVENT_SKIN_CHANGED,
} from "../panelWindow";
import { configApi } from "./configClient";

/** 导出诊断包；返回写入字节数（用于反馈），取消保存返回 null。 */
export async function exportDiagnostics(): Promise<number | null> {
  const path = await save({
    title: "导出诊断包",
    defaultPath: "mochi-diagnostics.zip",
    filters: [{ name: "ZIP", extensions: ["zip"] }],
  });
  if (path === null) return null;
  const written = await invoke<number>("export_diagnostics", { path });
  return written;
}

/** Export the server's portable camelCase snapshot. Cancelled dialogs return null. */
export async function exportSettings(): Promise<number | null> {
  const payload = await configApi.exportSettings();
  const json = JSON.stringify(payload, null, 2);
  const bytes = new TextEncoder().encode(json).length;
  if (isTauri()) {
    const path = await save({
      title: "导出设置",
      defaultPath: "mochi-settings.json",
      filters: [{ name: "JSON", extensions: ["json"] }],
    });
    if (path === null) return null;
    await invoke("write_text_file", { path, contents: json });
  } else {
    const url = URL.createObjectURL(new Blob([json], { type: "application/json;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "mochi-settings.json";
    document.body.appendChild(link);
    link.click();
    link.remove();
    // Let the browser finish consuming the download before releasing the blob.
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return bytes;
}

/** Select/read a backup, then validate and apply it in one server transaction. */
export async function importSettings(file?: File): Promise<boolean | null> {
  let raw: string;
  if (file) {
    if (file.size > 2 * 1024 * 1024) throw new Error("settings-file-too-large");
    raw = await file.text();
  } else {
    const path = await open({
      title: "导入设置",
      multiple: false,
      directory: false,
      filters: [{ name: "JSON", extensions: ["json"] }],
    });
    if (path === null) return null;
    raw = await invoke<string>("read_text_file", { path });
  }
  if (new TextEncoder().encode(raw).length > 2 * 1024 * 1024) {
    throw new Error("settings-file-too-large");
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw.replace(/^\uFEFF/, ""));
  } catch {
    throw new Error("invalid-json");
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error("invalid-json");
  }
  const applied = await configApi.importSettings(parsed);
  if (isTauri()) {
    await Promise.allSettled([
      emit(EVENT_LANGUAGE_CHANGED, { language: applied.general.language }),
      emit(EVENT_POWER_SAVE_CHANGED, { powerSave: applied.general.powerSave }),
      emit(EVENT_SKIN_CHANGED, applied.character.activeSkin),
    ]);
  }
  return true;
}
