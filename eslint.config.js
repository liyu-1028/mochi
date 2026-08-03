// @ts-check
// ESLint 9 flat config —— 规范见 docs/specs/code-style.md
import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: [
      "**/dist/**",
      "**/node_modules/**",
      "**/target/**",
      "**/src-tauri/**",
      "server/**",
      // 下载的第三方产物（Live2D Cubism Core 等专有代码，见 .gitignore）
      "apps/desktop/public/**",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    // scripts/ 下的 Node 脚本（下载/构建工具）
    files: ["scripts/**/*.mjs"],
    languageOptions: {
      globals: {
        console: "readonly",
        process: "readonly",
        fetch: "readonly",
        Buffer: "readonly",
      },
    },
  },
  {
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      // 事件协议常量必须从 @mochi/protocol 导入，禁止散落字符串字面量（软性约定，review 把关）
    },
  },
);
