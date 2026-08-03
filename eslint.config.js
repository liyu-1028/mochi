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
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
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
