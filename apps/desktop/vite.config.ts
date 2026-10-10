import { cpSync, existsSync, readFileSync, statSync } from "node:fs";
import { extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

const SKINS_DIR = resolve(fileURLToPath(new URL("../../assets/skins", import.meta.url)));
const DANCE_DIR = resolve(
  fileURLToPath(new URL("../../assets/prototypes/vrm-dance", import.meta.url)),
);

/** 评估素材仅提供给开发服务器；不拷入正式发行包。 */
function dancePrototypeAssets(): Plugin {
  return {
    name: "mochi:dance-prototype-assets",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const path = req.url?.split("?")[0];
        const name =
          path === "/prototype-assets/sample.vrm"
            ? "sample.vrm"
            : path === "/prototype-assets/samba.fbx"
              ? "samba.fbx"
              : null;
        if (!name) return next();
        const file = join(DANCE_DIR, name);
        if (!existsSync(file)) {
          res.statusCode = 404;
          return res.end("Run pnpm dev:dance to download prototype assets.");
        }
        res.setHeader("content-type", "application/octet-stream");
        res.end(readFileSync(file));
      });
    },
  };
}

const CONTENT_TYPES: Record<string, string> = {
  ".json": "application/json",
  ".moc3": "application/octet-stream",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".webp": "image/webp",
};

/**
 * 把仓库根 assets/skins/（许可隔离区，见 assets/README.md）以 /skins/* 提供给前端：
 * dev 走中间件直读，build 时整体拷入产物（Tauri 打包随包分发）。
 */
function skinAssets(): Plugin {
  let outDir = "";
  return {
    name: "mochi:skin-assets",
    configResolved(config) {
      outDir = config.build.outDir;
    },
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        // 内置角色资产；用户动作由 sidecar 提供，不复制旧示例动作包。
        const bases: [prefix: string, dir: string][] = [["/skins/", SKINS_DIR]];
        const url = req.url ?? "";
        const hit = bases.find(([prefix]) => url.startsWith(prefix));
        if (!hit) return next();
        const [prefix, dir] = hit;
        const rel = decodeURIComponent(url.slice(prefix.length).split("?")[0]);
        const file = resolve(dir, rel);
        if (!file.startsWith(dir) || !existsSync(file) || !statSync(file).isFile()) {
          return next();
        }
        res.setHeader("content-type", CONTENT_TYPES[extname(file)] ?? "application/octet-stream");
        res.end(readFileSync(file));
      });
    },
    writeBundle() {
      if (existsSync(SKINS_DIR)) {
        cpSync(SKINS_DIR, join(outDir, "skins"), {
          recursive: true,
          filter: (source) => !source.endsWith(".DS_Store"),
        });
      }
    },
  };
}

// Tauri 开发模式固定端口；envPrefix 保留 TAURI_ENV_* 供 Rust 侧构建判断
export default defineConfig({
  plugins: [react(), skinAssets(), dancePrototypeAssets()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
  },
  envPrefix: ["VITE_", "TAURI_ENV_*"],
  build: {
    // Tauri 目标基于 Chromium/WebKit，可用较新语法
    target: "es2022",
    sourcemap: !!process.env.TAURI_ENV_DEBUG,
    // pixi.js v6 体积较大，但桌面应用本地加载无需在意包体
    chunkSizeWarningLimit: 1000,
  },
});
