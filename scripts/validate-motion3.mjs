#!/usr/bin/env node
// motion3.json 结构校验（G4，动作扩展方案 M-G L3 层）。
//
// 与 server/src/mochi_server/skin/motion_pack.py 的 validate_motion3_json
// 同一逻辑：脚本用于资产仓库 CI（原创动作入库前），服务端在导入时兜底——
// 两端口径必须一致，修改时同步。
//
// 用法：node scripts/validate-motion3.mjs <file.motion3.json> [...]

import { readFileSync } from "node:fs";

const SEGMENT_TYPES = new Set([0, 1, 2, 3]);
// 各类型标记之后的坐标数（linear/stepped 1 点、bezier 3 点、type3 至少 1 点）
const MIN_POINTS_AFTER_MARK = { 0: 2, 1: 6, 2: 2, 3: 2 };
const DURATION_EPSILON = 1e-3;

const errors = [];

function fail(file, message) {
  errors.push(`${file}：${message}`);
}

function validateCurve(file, curve, duration) {
  if (typeof curve !== "object" || curve === null || Array.isArray(curve)) {
    fail(file, "Curves 元素须为对象");
    return;
  }
  if (curve.Target !== "Parameter") {
    fail(file, `Curves[].Target 必须为 "Parameter"（收到 ${JSON.stringify(curve.Target)}）`);
    return;
  }
  if (typeof curve.Id !== "string" || curve.Id === "") {
    fail(file, "Curves[].Id 须为非空参数 id");
    return;
  }
  const segments = curve.Segments;
  if (!Array.isArray(segments) || segments.length < 4) {
    fail(file, `参数 ${curve.Id} 的 Segments 须为 ≥4 个数字`);
    return;
  }
  for (const value of segments) {
    if (typeof value !== "number" || !Number.isFinite(value)) {
      fail(file, `参数 ${curve.Id} 的 Segments 含非数字`);
      return;
    }
  }
  let pos = 2;
  let lastT = segments[0];
  while (pos < segments.length) {
    const mark = segments[pos];
    if (!Number.isInteger(mark) || !SEGMENT_TYPES.has(mark)) {
      fail(file, `参数 ${curve.Id} 的段类型标记非法：${mark}（合法 0/1/2/3）`);
      return;
    }
    const need = MIN_POINTS_AFTER_MARK[mark];
    if (pos + 1 + need > segments.length) {
      fail(file, `参数 ${curve.Id} 的段数据不完整（标记 ${mark}）`);
      return;
    }
    lastT = segments[pos + need - 1]; // 段末点时间（消耗数据的倒数第二位）
    pos += 1 + need;
  }
  if (lastT > duration + DURATION_EPSILON) {
    fail(file, `参数 ${curve.Id} 曲线末点 ${lastT}s 超出 Meta.Duration ${duration}s`);
  }
}

function validateFile(path) {
  let raw;
  try {
    raw = JSON.parse(readFileSync(path, "utf-8"));
  } catch (err) {
    fail(path, `不是有效 JSON：${err.message}`);
    return;
  }
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    fail(path, "不是 JSON 对象");
    return;
  }
  if (raw.Version !== 3) {
    fail(path, `Version 必须为 3（收到 ${JSON.stringify(raw.Version)}）`);
    return;
  }
  const meta = raw.Meta;
  if (typeof meta !== "object" || meta === null || Array.isArray(meta)) {
    fail(path, "缺少 Meta 对象");
    return;
  }
  const duration = meta.Duration;
  if (typeof duration !== "number" || !Number.isFinite(duration) || duration <= 0) {
    fail(path, "Meta.Duration 必须为正数");
    return;
  }
  const curves = raw.Curves;
  if (!Array.isArray(curves) || curves.length === 0) {
    fail(path, "Curves 须为非空数组");
    return;
  }
  for (const curve of curves) {
    validateCurve(path, curve, duration);
  }
}

const files = process.argv.slice(2);
if (files.length === 0) {
  console.error("用法：node scripts/validate-motion3.mjs <file.motion3.json> [...]");
  process.exit(2);
}
for (const file of files) {
  validateFile(file);
}
if (errors.length > 0) {
  for (const message of errors) console.error(`✗ ${message}`);
  process.exit(1);
}
console.log(`✓ ${files.length} 个 motion3.json 校验通过`);
