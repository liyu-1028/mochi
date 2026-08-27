/**
 * diagnosticsClient —— 诊断包导出与设置导入导出（功能清单 1.8 / 7.1 尾巴）。
 *
 * 路径选择走 dialog 插件（保存/打开对话框），文件落盘与打包在 Rust 命令
 * （src-tauri/src/diagnostics.rs）；设置 JSON 内容来自脱敏的 GET /config
 * （providers 仅 key_ref 引用名，密钥永不落盘——§8 安全红线）。
 *
 * 导入应用范围：general / character / voice 三段（走既有 PUT 端点，
 * 服务端校验 + 原子落盘）；providers 涉及钥匙串绑定不随文件迁移，
 * 跨机导入后需在设置里补录 Key。
 */
import { save, open } from "@tauri-apps/plugin-dialog";
import { invoke } from "@tauri-apps/api/core";
import { configApi } from "./configClient";
import type { VoiceSettings } from "./configClient";

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

/** 设置 JSON 的可迁移形状（脱敏视图的子集）。 */
export interface SettingsExport {
  exportedAt: string;
  general?: { language?: string; powerSave?: boolean };
  character?: { activeSkin?: string };
  voice?: Partial<VoiceSettings>;
}

/** 导出设置为 JSON；取消返回 null。 */
export async function exportSettings(): Promise<number | null> {
  const path = await save({
    title: "导出设置",
    defaultPath: "mochi-settings.json",
    filters: [{ name: "JSON", extensions: ["json"] }],
  });
  if (path === null) return null;

  const config = await configApi.getConfig();
  const payload: SettingsExport = {
    exportedAt: new Date().toISOString(),
    general: {
      language: config.general?.language,
      powerSave: config.general?.powerSave,
    },
    character: config.character,
    voice: config.voice,
  };
  const json = JSON.stringify(payload, null, 2);
  await invoke("write_text_file", { path, contents: json });
  return json.length;
}

/**
 * 导入设置：选择 JSON → 校验形状 → 分段 PUT（服务端逐字段校验，
 * 任一段失败即中止并抛错，已生效段保留——用户可重导）。
 * 返回是否应用了变更（取消选择返回 null）。
 */
export async function importSettings(): Promise<boolean | null> {
  const path = await open({
    title: "导入设置",
    multiple: false,
    directory: false,
    filters: [{ name: "JSON", extensions: ["json"] }],
  });
  if (path === null) return null;

  const raw = await invoke<string>("read_text_file", { path });
  let parsed: SettingsExport;
  try {
    parsed = JSON.parse(raw) as SettingsExport;
  } catch {
    throw new Error("invalid-json");
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error("invalid-json");
  }

  let applied = false;
  const { general, character, voice } = parsed;
  if (general && (general.language !== undefined || general.powerSave !== undefined)) {
    await configApi.updateGeneral({
      ...(general.language !== undefined ? { language: general.language as "zh-CN" | "en" } : {}),
      ...(general.powerSave !== undefined ? { powerSave: general.powerSave } : {}),
    });
    applied = true;
  }
  if (character && typeof character.activeSkin === "string") {
    await configApi.setCharacter({ activeSkin: character.activeSkin });
    applied = true;
  }
  if (voice && typeof voice === "object") {
    await configApi.putVoice(voice);
    applied = true;
  }
  return applied;
}
