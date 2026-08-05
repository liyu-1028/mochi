#!/usr/bin/env node
/**
 * 生成系统托盘图标（功能清单 1.4，M1-S0）。
 *
 * 产物（提交入库，勿手工改）：
 * - apps/desktop/src/trayIcons.ts —— 前端内联 base64（唯一运行时来源；
 *   release 下 webview 走 tauri:// 资源协议，fetch 静态资源不可靠，故内联）
 * - apps/desktop/public/tray-icon-*.png —— 预览/留档副本
 *
 * 图标语义：tray-icon-template 为 macOS 菜单栏 template 图
 * （纯黑 + alpha 轮廓，系统按深浅色自动着色）：带耳朵的团子剪影；
 * tray-icon-color 为其余平台托盘用的彩色应用图标。
 *
 * 用法：node scripts/make-tray-icon.mjs
 */
import { deflateSync } from "node:zlib";
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const PUBLIC_DIR = join(ROOT, "apps", "desktop", "public");
mkdirSync(PUBLIC_DIR, { recursive: true });

// --- macOS template：44x44（菜单栏 @2x），黑色剪影 + alpha -----------------

const W = 44;
const H = 44;

/** 团子剪影：两只圆耳 + 超椭圆胖身体。坐标为连续域，供超采样抗锯齿。 */
function inside(x, y) {
  const earL = (x - 12) ** 2 + (y - 11) ** 2 <= 30;
  const earR = (x - 32) ** 2 + (y - 11) ** 2 <= 30;
  const dx = (x - 22) / 15.5;
  const dy = (y - 27) / 12.5;
  const body = Math.abs(dx) ** 2.4 + Math.abs(dy) ** 2.4 <= 1;
  return earL || earR || body;
}

const pixels = Buffer.alloc(W * H * 4);
for (let y = 0; y < H; y++) {
  for (let x = 0; x < W; x++) {
    let hits = 0;
    for (let sy = 0; sy < 4; sy++) {
      for (let sx = 0; sx < 4; sx++) {
        if (inside(x + (sx + 0.5) / 4, y + (sy + 0.5) / 4)) hits++;
      }
    }
    const i = (y * W + x) * 4;
    pixels[i] = 0; // R
    pixels[i + 1] = 0; // G
    pixels[i + 2] = 0; // B
    pixels[i + 3] = Math.round((hits / 16) * 255); // A（template 只看 alpha）
  }
}

// --- 最小 PNG 编码（IHDR + IDAT + IEND，filter 0）--------------------------

const CRC_TABLE = new Int32Array(256).map((_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c;
});

function crc32(buf) {
  let crc = 0xffffffff;
  for (const b of buf) crc = CRC_TABLE[(crc ^ b) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const typeBuf = Buffer.from(type, "ascii");
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])));
  return Buffer.concat([len, typeBuf, data, crc]);
}

function encodePng(width, height, rgba) {
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // color type: RGBA
  const stride = width * 4;
  const raw = Buffer.alloc(height * (stride + 1));
  for (let y = 0; y < height; y++) {
    raw[y * (stride + 1)] = 0; // filter: none
    rgba.copy(raw, y * (stride + 1) + 1, y * stride, (y + 1) * stride);
  }
  return Buffer.concat([
    signature,
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

const templatePng = encodePng(W, H, pixels);
const templatePath = join(PUBLIC_DIR, "tray-icon-template.png");
writeFileSync(templatePath, templatePng);
console.log(`✓ ${templatePath}`);

// --- 其余平台彩色图标：复用应用图标 ----------------------------------------

const colorSrc = join(ROOT, "apps", "desktop", "src-tauri", "icons", "32x32.png");
const colorDst = join(PUBLIC_DIR, "tray-icon-color.png");
copyFileSync(colorSrc, colorDst);
console.log(`✓ ${colorDst}`);

// --- 前端内联常量（运行时唯一来源）------------------------------------------

const iconsTs = join(ROOT, "apps", "desktop", "src", "trayIcons.ts");
writeFileSync(
  iconsTs,
  `/**
 * 托盘图标内联 base64 —— 由 scripts/make-tray-icon.mjs 生成，勿手改。
 * template：macOS 菜单栏剪影（系统按深浅色着色）；color：其余平台托盘图标。
 */
export const TRAY_ICON_TEMPLATE_B64 = "${templatePng.toString("base64")}";
export const TRAY_ICON_COLOR_B64 = "${readFileSync(colorSrc).toString("base64")}";
`,
);
console.log(`✓ ${iconsTs}`);
