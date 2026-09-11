# Changelog

> 手写维护（docs/specs/commit-convention.md §4）：每个 tag 一个条目，
> 格式 `## v<版本> - <日期>`，分点简述本版改动；新版本条目追加在顶部。
> release.yml 发布时自动提取对应段落作为 GitHub Release Notes，
> 缺少条目会在构建前拦截（先写 changelog 再打 tag）。

## v0.12.0 - 2026-09-11

细节交互与便携分发专项：思考动作可见化、Windows 便携版 zip

**新增**

- 思考状态可见化（Live2D）：提问后大模型推理期间角色歪头微低、
  缓慢摆动（周期 ~5.7s）+ 身体微倾，叠加既有的 confused 表情与
  视线上瞟，呈现完整「沉思」表现；模型自带 Think 动作组时优先
  播放，缺失则参数姿态（Hiyori 回退不变）
- Windows 便携版 zip（GitHub Release 新产物，推荐 Win10/11）：
  解压目录即工作目录——配置、皮肤、会话记录全部落在解压目录，
  拷贝整个文件夹即可迁移；根目录内置使用说明；卸载即删文件夹。
  实现为 mochi.portable 标记探测（Rust datadir.rs 与 Python
  paths.py 双侧对齐），安装版数据目录（%APPDATA%）行为不变

**说明**

- 便携版依赖系统 WebView2 运行时（Windows 11 自带；Windows 10
  通常已随 Edge 安装），缺失时请先安装官方运行时
- 窗口位置记忆（window-state 插件）仍存储于 %APPDATA%，
  便携版不随文件夹迁移（后续版本考虑自定义存储）

## v0.11.0 - 2026-09-10

桌面宠物「活起来」专项：点击区域收敛、静态皮肤动态化与 Live2D 显示修复

**新增**

- 透明区域鼠标穿透：alpha 掩码命中判定（提取/膨胀/查询，阈值 16、
  半径 2），cursorPosition 60ms 轮询切换 setIgnoreCursorEvents；
  仅角色本体可点击/拖拽，透明区域事件直达底层应用；dock/气泡/
  菜单交互不受影响；跨域皮肤图片 CORS 修复（canvas 污染静默失败）
- 静态皮肤动态化：视线侧倾（鼠标位置跟随）+ 点击果冻弹跳
  （700ms 挤压弹性）；闲置小动作（张望/伸懒腰/打盹/扭动），
  静置 20s 触发、间隔 12-30s 随机，对话中不打扰
- 窗口宽度下限 320px（输入条可用性）；dev 构建角色菜单 DevTools 项
- README 重写为 lobe-chat 风格，补 9 张功能演示图

**修复**

- Live2D 尺寸语义统一到 internalModel.originalWidth/Height（混用
  Container 缩放语义导致双重缩放 → 裁切/时显时不显）
- Live2D 每帧重取基准位置：窗口异步收紧后自动归位
- Live2D autoUpdate 绑定 app.ticker（Vite ESM 无全局 PIXI，动作/
  呼吸/眼球平滑此前从未推进），省电降档/隐藏时随渲染一起停
- 快速换肤崩溃：模型缓存命中微秒级就绪时 setReady(false)/(true)
  被 React 合并为一次渲染，effect 闭包残留已销毁舞台（ticker=null
  报错卸载）——stageEpoch 舞台换代计数强制重建
- 静态皮肤掩码/视线基准重拟合到精灵显示区（修复拉伸错位）

## v0.10.0 - 2026-08-27

M1 Beta 验收版 🎯：P0 功能全绿收口，非功能基线报告出具

**新增**

- 性能护栏（2.6）：帧耗时滚动 5s 均值自动降档（60→30→15）+
  暂停装饰动画，负载回落后自动回升（双阈值回滞防抖）；
  设置-通用新增「省电模式」开关（钉 15fps）；决策纯函数化带单测
- 诊断包导出（1.8）：设置-通用一键导出 zip（系统信息/日志/
  脱敏配置/库文件大小）；密钥形态/凭据头/TOML 密钥赋值三重
  脱敏红线，Rust 单测含解包验证
- 设置导入导出（7.1 尾巴）：general/character/voice 三段 JSON
  往返，导入走既有 PUT 端点服务端校验原子落盘；providers 钥匙串
  绑定不随文件迁移（跨机导入后补录 Key）
- Live2D 分区交互（2.4）：Head/Body 命中差异化反应——摸头眼笑
  包络 1.2s、戳身衰减摆动 0.9s（纯函数带单测）；内置静态皮肤
  维持整体点击反应（分区语义限定 Live2D，验收已补注）
- 非功能基线工具（§8）：perf_report（进程三路归集采样 RSS/CPU
  +回归斜率判泄漏）、soak（WS 对话泵，72h 夜间分段协议）、
  渲染层 __mochiStats 钩子

**实测（详见 docs/test-reports/2026--08-27）**

- 常驻内存 391MB（红线 600）、空闲 CPU 0%（红线 5%）、
  冷启动 0.99s（红线 5s）全绿；soak 工具验证 11 轮 0 错误；
  72h 分段挂机按夜间协议推进；Windows 仅 CI 冒烟（已知缺口，
  Beta Release Notes 标注）

**兼容说明**

- 协议零改动；[general] power_save 为可选字段，旧配置零迁移

## v0.9.0 - 2026-08-27

M1-S4 后半收口：P0 功能缺口清零 🎯

**新增**

- 上下文管理（4.4）：token 预算裁剪——启发式估算（CJK 1/字）不引
  tokenizer；预算 = context_window（provider 可配，缺省 8192）−
  system/记忆 − 本轮输入 − 25% 安全余量；超限从新往旧截断并注入
  「较早对话已省略」标记，长对话不报错、对用户无感
- 情绪推断（2.5，ADR-0009）：回复后置独立分类器，run.finished 后
  补发 emotion 事件（不阻塞回合与 TTS）；7 类情绪、intensity 0.75；
  失败/超时降级 neutral 零回归；[agent] emotion = auto|off
- 任务进度呈现（6.6）：工具 chip「步骤 N · 工具名 · 运行计时」
  （进行中跳秒、终态定格悬停）；working 期间醒目「停止任务」按钮
- 记忆自动沉淀重开（6.4）：v0.7.1 回退后带三道质量闸门恢复——
  [memory] auto_extract 开关（默认开）、每日自动上限 20 条（手动
  不受限）、子串去重；fire-and-forget 不阻塞回合收口

**验证**

- deepseek-v4-flash 真实模型实测：情绪后置补发尾序
  run.finished → emotion(happy/0.75) 符合设计
- 测试：server 414 项、desktop 182 项全绿

**兼容说明**

- 协议零改动（后置 emotion 为既有事件类型，runId 可选）
- [agent]/[memory] 配置段新增均为可选字段，旧配置零迁移

## v0.8.0 - 2026-08-27

M1-S4 Agent 编排：Mochi 会干活了 🔧

**新增**

- Agent 编排层迁 LangGraph（ADR-0008）：StateGraph 自搭 ReAct 回环
  （agent → tools 条件路由），run 级 SQLite checkpoint
  （mochi-checkpoints.db）支撑确认暂停与崩溃恢复；LLM I/O 迁 langchain
  封装（anthropic/openai 兼容/ollama 三家归一），旧适配器退役
- 工具调用框架（6.5）：注册表声明/执行双轨 + 危险分级；dangerous 工具
  执行前 interrupt 挂起，桌面端三键确认框（拒绝/允许/总是允许），
  「总是允许」白名单落盘 config.toml 热生效；工具 chip 行实时展示
  执行中/成功/失败/被拒
- 内置工具对：get_current_time（safe 直通）、read_text_file（dangerous
  确认流；256KB 上限、二进制探测、截断注记）
- 协议 additive：新增客户端命令 tool.confirm；tool.call.start 增
  requiresConfirmation 字段（协议 v0.1 §9.1 合规）

**修复**

- 工具确认竞态：客户端秒回 tool.confirm 时挂起项尚未注册，确认被丢弃
  导致回合死锁；挂起项改随 tool.call.start 事件发出前预注册（E2E 实测
  发现，附回归测试）
- 小模型工具幻觉：qwen2.5:1.5b 带人格提示时把工具调用当文本输出甚至
  编造结果；绑定工具时追加工具使用提示恢复结构化调用（无工具路径零变更）
- SessionStore 自定义 db_path 补 Path 包装

**验收**

- 真实模型端到端：deepseek-v4-flash 14/14 场景全过（safe 直通/deny
  善后/allow+remember/白名单直通）；qwen2.5:1.5b 对照确认流通路全过
- 打包：PyInstaller 产物 83MB，冷启动实测 0.99s（红线 5s）；产物内
  langgraph 动态导入与确认流 PASS（ADR-0008 D7 核销）
- 测试：server 387 项、desktop 179 项全绿

**兼容说明**

- 协议仅 additive 新增，旧客户端忽略未知字段不受影响
- 本地小模型工具功能建议 ≥7b 级（1.5b 结构化调用成功率 ~30–60%，
  纯对话不受影响）

## v0.7.1 - 2026-08-13

记忆功能修正：当前版本改为仅手动添加 🧠

**变更**

- 记忆改为**仅手动添加**：移除对话后自动提取（自动沉淀留后续版本）
- 修复停用词集合 bug：`frozenset([长字符串])` 改为 `frozenset(字符串)`
  逐字符拆分，使中文停用词过滤真正生效
- 修复 2-gram 停用词过滤丢失（linter 曾移除 gram[0]/gram[1] 检查）
- 记忆空状态文案更新为手动添加语义（中英双语）

## v0.7.0 - 2026-08-13

M1-S3 记忆技能：Mochi 会记住你了 🧠

**新增**

- 记忆技能（6.4）：跨会话长期记忆——对话后自动提取用户事实/偏好，
  新会话对话时自动召回注入 system prompt，让 Mochi 越来越懂你
- 记忆管理面板（右键 → 记忆）：查看/编辑/删除任一条记忆、手动添加、一键清空
- `/memories` REST API：列表/创建/编辑/删除/清空
- SQLite migration v2：memories 表（id/category/content/source/timestamps）
- 关键词检索：CJK 单字 + 2-gram + Latin 词，停用词过滤，LIKE OR 匹配

**修复**

- main.tsx 面板白名单遗漏 memory（点击记忆菜单后回退渲染设置页）
- 记忆召回搜索逻辑：整句 LIKE 改为关键词分词 OR 匹配
- memory ↔ agent 循环导入（TYPE_CHECKING 打断）

## v0.6.0 - 2026-08-13

内置皮肤换新：宝可梦精灵图登场 ⚡

**变更**

- 内置皮肤全量替换为 [pokesprite](https://github.com/msikma/pokesprite) 宝可梦
  精灵图：pikachu（皮卡丘，默认）/ eevee（伊布）/ snorlax（卡比兽）
- 移除旧内置皮肤 hiyori（Live2D 模型）、ruby、spade 及全部关联资源
- DEFAULT_SKIN_ID：hiyori → pikachu（前后端 + 全量测试适配）
- 功能清单 3.2 更新：去掉 Live2D 必备与「版权干净」表述，改为 ≥3 静态皮肤
- LICENSE-Live2D.md 资产登记表替换为三只宝可梦版权声明

**版权说明**

- 精灵图 © Nintendo / Creatures Inc. / GAME FREAK inc.
  （来源 pokesprite 仓库，非自由许可，仅供粉丝/个人用途）

## v0.5.0 - 2026-08-07

M1-S2 TTS 语音：Mochi 会说话了 🎙

**新增**

- TTS 语音输出（5.1，ADR-0007）：edge-tts 默认（免费无 Key）→ 本地
  say/SAPI 兜底 → 纯文本降级不阻塞对话；音频走独立 HTTP 流通道
  （`POST /tts/stream` / `GET /tts/voices` 五音色精选），不占 WS 协议
- 设置「语音」tab（7.1 转实）：启用/静音/音色/音量/语速/试听，即改即生效
  持久化；托盘静音与 TTS 静音共享配置、翻转立即停播
- 音量驱动口型（2.7）：播报期 AnalyserNode RMS 音量直驱嘴型，告别棒读；
  播报期角色保持说话态、播完回落
- 内置静态皮肤 ruby/spade（3.2 达标）：DG-RA CC0 chibi 系列，透明底、风格统一

**修复**

- 浏览器降级视图小部件居中；窄窗口输入条溢出致角色水平偏移（.app 宽度钉回容器）

**兼容说明**

- 协议包零改动（音频经独立 HTTP 通道，agent-events-v0.1 §10 既定）

## v0.4.0 - 2026-08-06

M1-S1 皮肤系统：给 Mochi 换上新衣服 🍡

**新增**

- 皮肤系统（功能清单 3.1–3.5）：skin.json v1 清单规范 + 服务端注册表，
  皮肤列表端点 `/skins` 与资源双轨分发（内置 `/skins/<id>`、用户
  `/user-skins/<id>`）
- 衣橱面板：查看当前着装、一键换肤（热切换不闪白）、导入 PNG/zip 皮肤、
  删除用户皮肤（内联两步确认）；激活皮肤经 `/config/character` 持久化，
  跨窗口事件同步主界面
- 图片即皮肤：一张 PNG 秒变静态皮肤（建议透明底），服务端校验魔数与
  尺寸（64–4096）；zip 包校验清单、资源存在性与逐成员 zip-slip 防护，
  id 冲突 409，错误文案全部可读
- 静态皮肤自带轻动画质感（漂浮/呼吸/摇摆，随对话状态切换），支持清单
  逐状态 `animation` 开关与 `emotionMapping` 情绪表达
- 导入尺寸归一化：长边 >2048 自动降采样后上传（PNG 无损保透明通道）；
  渲染侧小图放大封顶 2 倍，宁矮不糊、窗口贴合无空窗；<256px 软提示
  不阻断导入

**变更**

- 开发验证用的内置静态皮肤不随版提供，内置名录仅保留 hiyori；静态皮肤
  由用户导入承载，正式内置静态美术待后续专项

**修复**

- 皮肤列表端点曾遗漏清单字段（modelFile 等），导致静态资源 404、角色
  回退 emoji；SkinSummary 改为全量继承清单并加防回归断言
- 衣橱删除按钮在 Tauri webview 中依赖不可靠的系统对话框，改为内联
  两步确认（对齐回忆面板模式）
- Tauri API 模块动态导入已无代码分割效果引发的 vite 构建告警，改静态
  导入并保留运行时守卫；构建零警告

**兼容说明**

- 皮肤配置字段 `activeSkin` 默认 `"default"`（别名解析为 hiyori），
  旧配置零迁移；协议包零改动（皮肤是内容不是协议）

## v0.3.0 - 2026-08-06

人格系统：捏出你的专属 AI 伙伴 🍡

**新增**

- 人格系统（6.13/7.9）：设置新增「角色」tab，可从灵魂/性格/说话风格三维度
  定义 Mochi 人设——每维内置 4 个预设卡片单选、跨维任意组合，或逐维自定义
  人设文本（≤500 字）；保存后下一回合对话即生效，无需重启
- 设置面板重构为左 tab 右内容五分组：通用 / 模型 / 角色 / 语音 / 隐私
  （语音与隐私为占位，敬请期待）
- 服务端 `/config/persona` 读写端点：预设目录服务端唯一事实源、名称随界面
  语言双语呈现；非法预设返回 422、自定义超长拦截，配置原子落盘
- 功能清单补充实现状态列（✅/🚧/⬜），架构前提回退为已冻结决策，里程碑
  标注 M0 验收与 M1 实际进度

**兼容说明**

- 未配置人格时与默认人设逐字一致（Zero Config），既有配置自动补齐无需迁移
- 试用模式（echo 桩）保存人格不报错但不生效；真实模型（Ollama /
  OpenAI 兼容 / Anthropic）全量支持

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
