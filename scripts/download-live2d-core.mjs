#!/usr/bin/env node
/**
 * 下载 Live2D Cubism Core（专有代码，不入 git，见 LICENSE-Live2D.md §1 与 ADR-0003 D2）。
 *
 * 用法：node scripts/download-live2d-core.mjs
 * 行为：幂等（校验和一致则跳过）；失败只告警不报错——
 *       Core 缺失时前端降级回 emoji 占位，不阻塞开发（ADR-0003）。
 */

import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const TARGET = join(ROOT, "apps", "desktop", "public", "live2d", "live2d.min.js");

// Cubism Core 5.2（Live2D 官方 Legacy URL，与 pixi-live2d-display 0.4 年代匹配）。
// 文件名 live2d.min.js 保持社区惯例（库文档以 window.Live2D 全局为契约，与文件名无关）。
const CORE_URL = "https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js";
const CORE_SHA256 = "25ae938cb4fe282ce189b357bcc97e603d1e1f7ec78bf04150d401c23cdc792f";

const sha256 = (buf) => createHash("sha256").update(buf).digest("hex");

function warn(msg) {
  console.warn(`⚠ [live2d-core] ${msg}`);
  console.warn("  角色将降级为 emoji 占位；联网后重跑 node scripts/download-live2d-core.mjs");
}

try {
  const existing = readFileSync(TARGET);
  if (sha256(existing) === CORE_SHA256) {
    console.log("✓ [live2d-core] 已存在且校验通过，跳过下载");
    process.exit(0);
  }
  warn("本地文件校验和不匹配，重新下载…");
} catch {
  // 文件不存在，继续下载
}

try {
  const resp = await fetch(CORE_URL, { redirect: "follow" });
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
  const buf = Buffer.from(await resp.arrayBuffer());
  const digest = sha256(buf);
  if (digest !== CORE_SHA256) {
    warn(
      `下载成功但校验和不匹配（${digest.slice(0, 12)}…），已丢弃——官方 Core 可能已更新，请人工核对后更新脚本内 CORE_SHA256`,
    );
    process.exit(0);
  }
  mkdirSync(dirname(TARGET), { recursive: true });
  writeFileSync(TARGET, buf);
  console.log(`✓ [live2d-core] 已下载并通过 SHA256 校验（${buf.length} 字节）`);
} catch (err) {
  rmSync(TARGET, { force: true });
  warn(`下载失败：${err instanceof Error ? err.message : String(err)}`);
}
