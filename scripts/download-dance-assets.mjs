#!/usr/bin/env node
// 本地评估资源；许可和来源见 assets/prototypes/vrm-dance/README.md。
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";

const directory = new URL("../assets/prototypes/vrm-dance/", import.meta.url);
const files = [
  {
    name: "sample.vrm",
    url: "https://raw.githubusercontent.com/pixiv/three-vrm/1b4fc0cc7ef39a49d62bb7a66dcfeca8f65316f7/packages/three-vrm/examples/models/VRM1_Constraint_Twist_Sample.vrm",
    sha: "12c2b97e95e700783a6a550dc0eee2d7880aeedccef9ae67bc4c5a2f0f2631a2",
  },
  {
    name: "samba.fbx",
    url: "https://raw.githubusercontent.com/mrdoob/three.js/r180/examples/models/fbx/Samba%20Dancing.fbx",
    sha: "b9003ee562c87bf03051c3a502411b0808d3513f1d74a2011f7530d9f067069f",
  },
];
const hash = (buffer) => createHash("sha256").update(buffer).digest("hex");
mkdirSync(directory, { recursive: true });
try {
  for (const file of files) {
    const target = new URL(file.name, directory);
    if (existsSync(target) && hash(readFileSync(target)) === file.sha) {
      console.log(`[dance] ${file.name} 校验通过`);
      continue;
    }
    console.log(`[dance] 下载 ${file.name}…`);
    const response = await fetch(file.url, { signal: globalThis.AbortSignal.timeout(60_000) });
    if (!response.ok) throw new Error(`${file.name}: HTTP ${response.status}`);
    const buffer = Buffer.from(await response.arrayBuffer());
    if (hash(buffer) !== file.sha) throw new Error(`${file.name}: SHA256 不一致，未写入`);
    writeFileSync(target, buffer);
    console.log(`[dance] 已保存 ${fileURLToPath(target)}`);
  }
} catch (error) {
  console.error(`[dance] ${error instanceof Error ? error.message : error}`);
  process.exitCode = 1;
}
