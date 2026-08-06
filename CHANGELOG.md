# Changelog

> 手写维护（docs/specs/commit-convention.md §4）：每个 tag 一个条目，
> 格式 `## v<版本> - <日期>`，分点简述本版改动；新版本条目追加在顶部。
> release.yml 发布时自动提取对应段落作为 GitHub Release Notes，
> 缺少条目会在构建前拦截（先写 changelog 再打 tag）。

## v0.2.1 - 2026-08-06

测试报告缺陷修复与气泡体验打磨 🍡

**新增**

- 设置面板支持编辑已有模型提供方（此前仅新增/设为默认/删除）
- 窗口尺寸动态贴合 Live2D 角色；气泡按角色所处屏幕位置自动选边贴头

**优化**

- 气泡栈仅保留最新两条 assistant 回复，上一条折叠为两行半透明预览，
  点击可展开——不再堆叠遮挡角色

**修复**

- 回复中 Markdown 超链接的 URL 被彻底剥离、不可见：现点击交系统浏览器
  打开、悬停可见目标 URL，仅放行 http(s)（测试报告 2026-08-06 #1）
- 回忆面板删除活跃会话后主界面状态脱节：旧气泡残留、再提问时旧回复
  重现；桌面端面板在独立窗口、zustand 不跨窗口，现经跨窗口事件同步
  清空主界面（测试报告 2026-08-06 #2）
- 流式生成中途异常中断时气泡光标 ▍ 永久残留的"生成中"假象，终态统一
  收口 streaming 与口型信号（测试报告 2026-08-05）
- 模型提供方返回 402 余额不足映射为可读错误码 ERR_MODEL_QUOTA

## v0.2.0 - 2026-08-05

M1-S0 快赢冲刺 🍡

**新增**

- 系统托盘菜单：显隐 Mochi / 打开对话 / 静音 / 退出，双语文案；
  macOS 用 template 剪影图标，随系统深浅色着色
- Anthropic 模型提供方：独立适配器（ADR-0002 D1），错误映射复用协议
  错误码；真实推理流（thinking block）透传为协议 thinking 事件
- runtime.json 端口发现：sidecar 端口被占自动换空闲口，桌面壳轮询
  发现后通知前端切换重连；release/dev 行为一致
- chat.interrupt 与 chat.cancel 语义分离（interrupted / cancelled）
- [voice] 配置读写端点 GET/PUT /config/voice（托盘静音持久化，S2 TTS 复用）

**修复**

- 托盘不显示：tauri 缺 image-png feature，Image.fromBytes 解码 PNG 的
  命令不响应、invoke 永久挂起，托盘初始化静默卡死
- 安装包可能内嵌旧前端：build.rs 未声明对 dist 的依赖，纯前端改动后
  cargo 复用旧 crate 不重内嵌（现 rerun-if-changed=../dist）

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
