// Conventional Commits 规范见 docs/specs/commit-convention.md
export default {
  extends: ["@commitlint/config-conventional"],
  rules: {
    "type-enum": [
      2,
      "always",
      [
        "feat",
        "fix",
        "docs",
        "style",
        "refactor",
        "perf",
        "test",
        "build",
        "ci",
        "chore",
        "revert",
      ],
    ],
    // scope 可省略；填写时建议使用以下范围
    "scope-enum": [
      1,
      "always",
      ["desktop", "protocol", "server", "skin", "voice", "docs", "ci", "repo"],
    ],
    "subject-case": [0],
  },
};
