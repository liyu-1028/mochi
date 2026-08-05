# Changelog

> 手写维护（docs/specs/commit-convention.md §4）：每个 tag 一个条目，
> 格式 `## v<版本> - <日期>`，分点简述本版改动；新版本条目追加在顶部。
> release.yml 发布时自动提取对应段落作为 GitHub Release Notes，
> 缺少条目会在构建前拦截（先写 changelog 再打 tag）。

## v0.1.2 - 2026-08-05

首个公开发布版本 🍡

**新增**

- 桌面伙伴 Mochi：Live2D 角色（状态机动画、口型、视线跟随），LangGraph sidecar 驱动对话
- 功能面板独立窗口：设置 / 聊天回忆 / 衣橱与初始设置向导，屏幕居中、无边框卡片风格
- 模型 provider 管理：新增 / 连通性测试 / 设为默认 / 删除，默认模型热切换生效
- 界面语言切换（简体中文 / English），多窗口实时同步
- 一键启用 Ollama 或试用模式，零配置上手
- sidecar 运行日志落盘，异常与重启在状态栏提示

**修复**

- 右键菜单点击窗口外部、切换其他应用后立即隐藏
- provider 名称过长不再撑出横向滚动；删光 provider 后状态栏即时提示待设置
- macOS 添加模型时钥匙串写入失败（Load failed）
