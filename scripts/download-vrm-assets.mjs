#!/usr/bin/env node
// 内置 VRM 角色模型（不下载动作）：按固定来源下载并校验；许可登记见 LICENSE-Live2D.md §2。
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";

const root = new URL("../", import.meta.url);
const files = [
  {
    name: "mochi-vrm 角色模型",
    url: "https://raw.githubusercontent.com/pixiv/three-vrm/1b4fc0cc7ef39a49d62bb7a66dcfeca8f65316f7/packages/three-vrm/examples/models/VRM1_Constraint_Twist_Sample.vrm",
    target: "assets/skins/mochi-vrm/model.vrm",
    // 已在 assets/prototypes/vrm-dance/sample.vrm（舞蹈原型）校验过的同一文件可本地复用
    localMirror: "assets/prototypes/vrm-dance/sample.vrm",
    sha: "12c2b97e95e700783a6a550dc0eee2d7880aeedccef9ae67bc4c5a2f0f2631a2",
  },
];
const hash = (buffer) => createHash("sha256").update(buffer).digest("hex");
let failed = false;
for (const file of files) {
  const target = new URL(file.target, root);
  mkdirSync(new URL(".", target), { recursive: true });
  if (existsSync(target)) {
    const sha = hash(readFileSync(target));
    if (sha === file.sha) {
      console.log(`[vrm-assets] ${file.target} 校验通过`);
      continue;
    }
    console.warn(`[vrm-assets] ${file.target} SHA 不一致，重新获取`);
  }
  let buffer = null;
  if (file.localMirror) {
    const mirror = new URL(file.localMirror, root);
    if (existsSync(mirror)) buffer = readFileSync(mirror);
  }
  if (!buffer) {
    console.log(`[vrm-assets] 下载 ${file.name}…`);
    try {
      const response = await fetch(file.url, { signal: globalThis.AbortSignal.timeout(120_000) });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      buffer = Buffer.from(await response.arrayBuffer());
    } catch (error) {
      console.error(`[vrm-assets] ${file.name}: ${error.message}`);
      failed = true;
      continue;
    }
  }
  if (hash(buffer) !== file.sha) {
    console.error(`[vrm-assets] ${file.name}: SHA256 不一致，未写入`);
    failed = true;
    continue;
  }
  writeFileSync(target, buffer);
  console.log(`[vrm-assets] 已保存 ${fileURLToPath(target)}`);
}
if (failed) process.exitCode = 1;
