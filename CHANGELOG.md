# Changelog

> 手写维护（docs/specs/commit-convention.md §4）：每个 tag 一个条目，
> 格式 `## v<版本> - <日期>`，分点简述本版改动；新版本条目追加在顶部。
> release.yml 发布时自动提取对应段落作为 GitHub Release Notes，
> 缺少条目会在构建前拦截（先写 changelog 再打 tag）。

## v0.15.0 - 2026-10-10

角色渲染切换为 **VRM + Three.js**，动作改为可自行导入的 **VRMA**，
同时完善装扮管理、长期记忆与多会话聊天。

**角色与动作**

- 默认角色使用 VRM 三维渲染，只预装风格干净、温柔的 Mochi；支持眨眼、
  视线、表情与口型，保留已有 Live2D 皮肤包的兼容路径。
- 装扮管理支持直接导入 VRM 0.x / 1.0，提供 VRoid Hub、BOOTH 与
  VRoid Studio 制作/下载指引，读取并展示模型作者和许可。
- 移除 VRM 路径中的程序化肢体动作，改为下载 VRMA 后自行导入。可以配置
  角色默认动作或用户扩展、绑定用途、填写署名，并按需开启待机播放及 AI 使用。
  公开安装包不包含本机私有动作素材；未导入动作时保持自然站姿。
- 动作管理重新设计：放大预览、拖动旋转视角、滚轮缩放与重置，提供动作
  分组、搜索、试播/停止和设置编辑；动作时长从文件读取。
- 修复预览比例失真、模型溢出预览区域、动作 ID 占用但列表不显示等问题。
  桌面角色取景贴合全身，并在顶部保留约 20% 余量用于举手和舞蹈。

**对话与体验**

- 聊天回忆增加“新建会话”“继续这段对话”与当前会话标记，重启保留选择；
  切换时停止旧生成和语音，避免迟到回复或历史请求混入新会话。
- 修复手动偏好未被模型召回的问题：已保存的用户偏好与事实跨会话使用，
  支持编辑/删除即时生效，并为召回内容设置条数与上下文预算。
- 功能窗口使用正常层级，切换到其他应用后可退到后面；修复装扮列表加载
  和独立面板的服务端口发现，说明自动换行、长标题省略，避免水平滚动。
- README 更新为当前 VRM 角色截图和实际 VRMA 跳舞 GIF，补充模型与动作
  导入步骤、素材来源，以及只内置一个角色的作者说明。

**升级提示**

已有本地聊天、记忆和用户导入资源继续保留。发布包只带一个默认角色；
演示中的舞蹈与其他外部动作需自行下载并导入，遵循素材作者的许可与署名要求。

## v0.14.0 - 2026-09-29

容器联动（I3/M-H）：窗口扩为活动区 + locomotion 位置指令 + 问号贴图

**新增**

- locomotion 通道启用（M-C 预留字段落地）：五项白名单
  `come_back`/`lean_edge`（靠墙——容器右缘贴边倚靠）/`peek_dock`
  （趴输入框）/`lean_bubble`（靠气泡）/`peek_out`（探头），TS/Py/golden
  三处同提交；容器=角色所在窗口及其内部 UI，非整屏
- 窗口活动区：宽角色窗口放宽为角色宽×2.2（左右各留半个身位余量），
  角色默认居中；透明余量区鼠标穿透不受影响；窄角色保持原语义零回归
- 位移/姿态：CSS transform 平滑移动 + 倚靠/趴伏参数经帧覆写指数趋近
  （包络最优先顺序不变）；说话/思考立即回位，闲置超时 14s 自动回位
- 舞台指示关键词 +11（趴在输入框上/靠墙歇会儿/探出半个脑袋/回到中间
  等）；cue 提示词追加容器动作提示；问号贴图：`question` 动作同期
  头顶浮出「？」浮层（时长对齐包络）

批次 3 动作扩容 + 工作打字演出 + 闲置轮换池（I1+I2）

**新增**

- 词表 +5（总 25 项，L1 包络可演，TS/Py/golden 三处同提交）：跳舞
  `dance`（身体摇摆两拍 + 头部反相随动）、比心 `finger_heart`（举手
  定格 + 笑眼笑嘴）、飞吻 `blow_kiss`（嘟嘴蓄力 → 张手送出 → 眨眼）、
  满脸问号 `question`（歪头 + 双眉不对称 + 眼神游移）、打字 `type`
  （双臂交替 + 低头；真手指手势演出留 L3 资产）
- working 状态绑定持续打字演出（driver `typing` 位：双臂反相交替
  - 低头 + 眼下视，150ms 一敲；与 bodySway 互斥，包络仍最优先可叠加）
- 闲置轮换池（`pickIdleAction` 纯函数 + 25s 低频评估）：权重随闲置
  时长渐进——刚闲置安静 → 中期东张西望/哼歌/伸懒腰 → 久置偏向打盹；
  新增内部动作 `idle_hum`（哼歌摇头，不在语义词表，LLM 不可选）
- 舞台指示关键词 +15（跳舞/比心/飞吻/满脸问号/敲键盘）；cue 提示词
  示例词自动跟随

批次 3 动作扩容前的一条：G5 收口：2b 词表扩容 + Hiyori 示例扩展包 + 实测报告（动作扩展方案 M-G）

**新增**

- 词表 +3（jump/spin/bow，总 20 项）：无内置兑底的「资产解锁」类——
  仅当皮肤扩展包（G4）提供对应 motion3.json 才可演；能力注入（G2）
  保证模型只在皮肤真的有时才会选出；双端 ACTION_LABELS + golden 同步
- DEFAULT_LIVE2D_ACTIONS / reflexRules.DEFAULTS 基线接线；无资产皮肤
  请求 → fallback idle_neutral（vitest 覆盖）
- 舞台指示关键词 +11（跳跃/转圈/鞠躬）；cue 提示词示例词自动跟随
- 示例扩展包 `assets/motion-packs/hiyori-greeting/`：原创 CC0 动作
  （wave 手臂挥动 1.6s / bow 鞠躬 1.8s）+ 打包说明；已在
  `LICENSE-Live2D.md` 登记，双端口径校验通过
- 实测报告：`docs/test-reports/2026-09/2026-09-29_mg-motion-pack-g5_PASS.md`
  （真机 API 级导入 + G2 提示词闭环验证 + 已知行为边界 + GUI checklist）

L3 动作扩展包导入（G4，动作扩展方案 M-G）：给已导入的皮肤追加原创
motion3.json 动作，免重新打包整个皮肤

**新增**

- `POST /skins/import-motion-pack`：zip 内含 `pack.json`
  （targetSkin / license / motions[] / actions[]）；仅用户皮肤可扩展；
  motion3.json 结构强校验（Cubism 3：Version/Duration/Target/Segments
  段标记/末点 ≤ Duration），与 `scripts/validate-motion3.mjs` 同口径
  （资产仓库 CI 用）
- 合并 `FileReferences.Motions`（组名冲突 409 拒绝）、`actions`（id
  冲突 409）与 `capabilities.motionGroups`；`license` 必填并登记进
  `credits[motionPack:<name>]`；合并前备份原 `model3.json`/`skin.json`
  （`*.orig.json`，仅首次保留原始状态，可回滚）
- 前端衣橱面板新增「导入动作扩展包」入口；目标是当前装扮时经
  `EVENT_SKIN_CHANGED` 热更，motion 组集合变化触发舞台重建后即可演，
  无需重启
- 规范：skin manifest 文档新增「动作扩展包」节（pack.json 格式与
  校验/合并规则）

cue 提示词按皮肤能力注入（G2，动作扩展方案 M-G）：模型只被教当前装扮真实可演的动作

**新增**

- 协议新增 `ACTION_LABELS`（动作中文名，TS/Python 双端镜像 + golden 夹具
  `actionLabels` 键同步）：提示词与日志的统一展示名
- `cue_prompt_section(skin)`：传入当前皮肤清单时，动作标记清单/舞台指示
  示例词都按皮肤实际可演动作收窄（`label(id)` 对照 + 收窄声明「不要发明
  清单外动作」），借鉴 Open-LLM-VTuber 用 emo_str 动态替换表情清单的同构
  设计；skin 缺失/无清单/无可演动作 → 回落静态全词表（零回归）
- `stage_directions.action_example_words(id)`：动作 id → 示例指示词
  （长词优先）反查索引，供提示词选词
- 装配：`SkinRegistry` 注入 `AgentFactory` → 闭包每回合读活动皮肤，
  换肤即时生效（无需重建 agent）；provider 异常降级静态词表不阻断回合
- 可观测：每回合打点「cue 提示词按皮肤能力注入：<名>（N 个可演动作）」

**修复**

- 驱动层声明式包络到期死锁：compileParamEnvelope 端点钳制使快照恒非空，
  原「快照为空才清空」的分支永不到达——包络结束后每帧强制重写参数，
  表情与后续动作被锁死在末帧；到期检测改为前置比较 durationMs，
  到期立即交回控制权给状态机
- 声明式包络多轨道末点校验漏洞：原仅校验第 1 轨，后续轨道末点 ≠
  durationMs 会被放行；改为遍历全部轨道严格核验
- 扩展包导入两处边界：pack.json 改精确匹配（防 mypack.json 误识别）；
  目标皮肤 model3.json 的 FileReferences/Motions 为 null 时自愈容错
  （原抛 500）
- 流式舞台指示句首标点边界：首个增量为纯换行/标点时提前置位
  _emitted_any_text，导致首个指示被误判为 sentence_boundary；实质
  正文为空时不再置位

**测试增强**（严厉/边界专项，38 个新用例）

- 桌面端：driver 到期/优先级/缺失参数、actionRegistry 超深降级链与
  循环环路、包络解释器高密插值与 NaN/Infinity 防御、TTS 净化嵌套
  Markdown/围栏代码块、skinsClient 错误路径
- 服务端：包络 1ms/10000ms/±10000 边界与多轨核验、扩展包 4 类曲线段
  与浮点容差与命名混淆防护、舞台指示单字符逐字流式压力与容量封顶
- 协议：词表总数与非空展示名约束
- lint：eslint 忽略 .claude/worktrees（历史遗留，与本仓无关）

- 换装死锁：模型加载失败一次后永久卡在占位图标、换装永远无效——
  失败分支卸载了舞台容器（containerRef 摘除，换装 effect 无法重跑且
  failed 标记不重置）。改为 badge overlay（容器常挂载）+ 换装重试时
  清除失败标记 + 失败时 CSS 隐藏残留画布避免残影
- 舞台指示关键词/提示词/注释错别字：扸捏 → 扭捉

cue 提示词按皮肤能力注入前的一条：L1 参数包络扩容 + 参数发现 + 包络下沉（G1，动作扩展方案 M-G）：任何 Cubism 模型
可演的动作从 1 个增至 6 个

**新增**

- 语义动作词表新增 `pout`（嘟嘴）/`laugh`（大笑）/`shy_shake`（扸捏）/
  `alert`（警觉）：TS/Python 协议同提交 + golden 夹具同步；均参数包络实现，
  任何 Cubism 模型可演（缺参数模型逐参数静默跳过）
- 内置包络表（`BODY_ACTION_ENVELOPES`）新增 5 项：pout/laugh/shy_shake/alert
  - doze 升级（打哈欠/犯困点头：嘴大张 + 眼阖 + 头下垂，此前无诚实实现直接降级）
- 服务端舞台指示关键词字典扩容：嘟嘴/大笑/扸捏/警觉等 17 词 + 犯困点头/瞌睡；
  cue 提示词动作词指导同步
- 参数发现（Phase A）：模型加载后 dump 全部参数 id（`driver.dumpParamIds()`，
  best-effort），`ModelProfile.paramIds` 随档案携带；包络首次播放时打点
  「模型缺失参数，逐参数跳过」日志（可观测降级）

**变更**

- 包络执行从 CharacterStage 帧循环下沉到 driver（`applyAction` 统一入口：
  motion / 皮肤声明包络 / 内置兑底），组件层回归纯调度；face 之后的
  最优先叠写顺序保持不变
- `DEFAULT_LIVE2D_ACTIONS` / `reflexRules.DEFAULTS` 同步 5 项基线
  （含各自真实动作组偏好声明：有则播真 motion，无则包络兑底）

声明式参数包络（G3，动作扩展方案 M-G）：皮肤作者免 Live2D Editor 自定义动作

**新增**

- skin.json v3 字段：`actions[].live2d.paramEnvelope`（参数关键帧包络声明）
  与 `actions[].durationMs`（占位窗口）。服务端 pydantic 强校验（时长范围、
  关键帧点列严格递增/首末点约束、值域 ±10000、参数 id pattern、包络内参数
  唯一），422 可读文案；详见 `docs/specs/skin-manifest-format.md` v3 节
- 前端包络解释器（`live2d/paramEnvelope.ts`）：声明 → 编译为逐帧求值函数，
  linear/smoothstep 逐段插值；对运行时数据防御性容错（畸形声明返回 null，
  回落内置兑底，不阻塞渲染循环）
- 播放优先级：motionGroups 命中 > 皮肤 paramEnvelope > 内置包络兑底（wink）；
  参数缺失的模型运行时静默跳过该参数，包络声明不参与动作命中判定

**变更**

- `Live2dActionBinding`（TS/Python 双端）：`motionGroups` 改为可选（包络-only
  绑定合法）；`Live2dActionPlan` 透传 `paramEnvelope`
- `buildCue` 占位窗口：skin 条目 `durationMs` 优先（包络动作不再空占通用
  2500ms 窗口）

舞台指示驱动动作（M-F）：角色回复里的「（眨眨眼）（点头）」变成实时表演

**新增**

- 服务端舞台指示扫描器（`stage_directions.py`）：解析人格回复中的全角括号
  舞台指示，经封闭关键词字典映射为白名单 `character.cue`（body/face 双通道），
  与 `[[cue:id]]` 标记路径平行运行；能做的动作才映射，「掏申请表」类描写
  静默忽略；cue 路径关闭时完全旁路（M-C 终点零回归）
- 语义动作词表新增 `wink`（眨眼）：TS/Python 协议同提交 + golden 夹具同步；
  无需模型自带 motion——前端新增 body 通道参数包络兑底（`BODY_ACTION_ENVELOPES`，
  皮肤声明的 motion/expression 实现优先），任何 Cubism 模型都能演出
- TTS 前端剥离全角舞台指示（借鉴 Open-LLM-VTuber `tts_filter`）：
  「（眨眨眼）」保留气泡展示、不再被读出来；服务端分句计数同步括号感知，
  `sentenceIndex` 与剥离后文本对齐，句对齐节拍不漂移
- cue 路径提示词同步指导模型使用可识别的动作词（眨眨眼/点头/耷拉/脸红…）

**变更**

- `DEFAULT_LIVE2D_ACTIONS` / `reflexRules.DEFAULTS` 增加 `wink` 基线
  （priority 50 / cooldown 2.5s / 包络时长 700ms）

## v0.13.0 - 2026-09-28

静态皮肤类型下线（只保留 Live2D 及未来动态类型）+ 回复长度约束专项

**破坏性变更**

- 角色装扮只保留 Live2D（及未来扩展的动态类型）：内置三只静态皮肤
  （pikachu / eevee / snorlax）与 PNG「图片即皮肤」导入一并移除，
  应用不再打包任何静态装扮
- 皮肤导入仅接受 zip Live2D 皮肤包；`skin.json` 清单 `resourceType`
  仅接受 `"live2d"`，static 清单导入时给出「已下线」可读文案
- 升级影响：此前把静态皮肤设为当前装扮的用户，升级后回到未设置状态
  （导入 Live2D 皮肤包即可恢复）；历史配置值 `active_skin = "default"`
  不再解析到任何皮肤
- 动作幅度包络、闲置小动作等静态渲染链路（actionEnvelopes /
  idleBehaviors / staticDriver 等）随类型一并移除

**新增**

- 回复长度上限用户可配：设置 → 角色 →「单次回复上限（字符）」，
  50–4000（默认 200），下一回合生效；超限服务端截断 +「…」收尾，
  且 system prompt 同步告知模型真实上限（否则模型一边被截断一边
  自称别的长度标准）
- 回复气泡正文最大高度（200px 内部滚动）+ 窗口级 overflow 兜底：
  长回复不再撑破窗口、不再出现页面级滚动条

**变更**

- 皮肤设置面板仅接受 zip 皮肤包导入；删除当前皮肤后清空选择
  （不再回退到内置默认皮肤）

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
