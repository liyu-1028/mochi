/**
 * i18n 字典（M1-CTX，功能清单 7.8 前置）——无库方案的事实源。
 *
 * - zh-CN 为源语言；缺失键回退 zh-CN → 键本身（translate 纯函数，可直测）；
 * - 插值占位符写作 `{name}`，由 translate 替换；
 * - 语言选项按惯例以各自语言书写（简体中文 / English），不随当前语言翻译。
 * 范围约束：仅收 UI 文案；docs/脚本/后端 hint 不入字典。
 */

export type Language = "zh-CN" | "en";

export const DEFAULT_LOCALE: Language = "zh-CN";

type StringTable = Record<string, string>;

const zhCN: StringTable = {
  // 通用
  "common.close": "关闭",
  "common.cancel": "取消",
  "common.save": "保存",
  "common.delete": "删除",
  "common.back": "返回",

  // 连接状态栏
  "status.connected": "已连接 · 点击 Mochi 聊天",
  "status.connecting": "连接中…",
  "status.disconnected": "未连接",
  "status.setupPending": "待完成初始设置…",

  // 输入条
  "chat.placeholder": "和 Mochi 说点什么…",
  "chat.placeholderConnecting": "连接中…",
  "chat.stop": "停止生成",
  "chat.sendTitle": "发送（Enter）",
  "chat.sendAria": "发送",
  "chat.collapseTitle": "收起（Esc）",
  "chat.collapseAria": "收起",

  // 右键菜单
  "menu.history": "聊天回忆",
  "menu.skins": "换个装扮",
  "menu.settings": "设置",

  // 设置面板
  "settings.title": "设置",
  "settings.sectionGeneral": "通用",
  "settings.sectionModel": "模型",
  "settings.language": "界面语言",
  "settings.languageZh": "简体中文",
  "settings.languageEn": "English",
  "settings.feedbackUnreachable": "无法连接 sidecar 配置服务，请确认它正在运行",
  "settings.addedFeedback": "已添加「{name}」",
  "settings.testOk": "「{id}」连接成功 ✓",
  "settings.testFail": "「{id}」暂不可用：{hint}",
  "settings.unknownReason": "未知原因",
  "settings.testError": "测试失败",
  "settings.switchedFeedback": "已切换到「{id}」，立即生效",
  "settings.deletedFeedback": "已删除「{id}」",
  "settings.trialMode": "试用模式",
  "settings.trialDesc": "内置 echo 桩，无需任何 Key",
  "settings.inUse": "使用中",
  "settings.setDefault": "设为默认",
  "settings.testing": "测试中…",
  "settings.test": "测试",
  "settings.addProvider": "+ 添加模型提供方",
  "settings.kindOllama": "Ollama 本地",
  "settings.kindOpenAiCompat": "OpenAI 兼容",
  "settings.kindAnthropic": "Anthropic",

  // 提供方表单
  "providerForm.errId": "ID 仅限小写字母/数字/下划线/连字符，且以字母数字开头",
  "providerForm.errModel": "请填写模型名称",
  "providerForm.errSave": "保存失败",
  "providerForm.kind": "类型",
  "providerForm.kindOpenAi": "OpenAI 兼容接口",
  "providerForm.kindOllama": "Ollama（本地）",
  "providerForm.kindAnthropic": "Anthropic（M1 支持）",
  "providerForm.id": "ID（唯一标识）",
  "providerForm.idPlaceholder": "如 deepseek",
  "providerForm.displayName": "显示名称",
  "providerForm.displayNamePlaceholder": "如 我的云端模型",
  "providerForm.ollamaBaseUrl": "服务地址（默认 127.0.0.1:11434）",
  "providerForm.baseUrl": "Base URL",
  "providerForm.model": "模型",
  "providerForm.modelPlaceholderOllama": "如 qwen3:8b",
  "providerForm.modelPlaceholderOpenAi": "如 gpt-4o-mini",
  "providerForm.apiKey": "API Key（存入系统钥匙串，不落文件）",
  "providerForm.saving": "保存中…",

  // 引导向导
  "onboarding.welcome": "欢迎来到 Mochi 🍡",
  "onboarding.searching": "正在寻找可用的模型…",
  "onboarding.enableOllama": "发现本地 Ollama（{model}），一键启用",
  "onboarding.enabling": "启用中…",
  "onboarding.noOllama": "未检测到本地 Ollama。你可以填入自己的模型 Key，或先试用。",
  "onboarding.fillKey": "填入 Key",
  "onboarding.useTrial": "先用试用模式",

  // 聊天回忆面板
  "history.title": "与 Mochi 的对话",
  "history.empty": "还没有对话记录，去和 Mochi 聊聊吧",
  "history.messagesEmpty": "这段对话还没有消息",
  "history.deleteConfirm": "删除这段对话？",

  // 衣橱（换装预告）
  "skins.title": "Mochi 的衣橱",
  "skins.current": "当前装扮",
  "skins.comingSoon": "更多皮肤制作中 ✨",
  "skins.switchDisabled": "换装功能即将开放",
  "skins.creditIllustration": "原画",
  "skins.creditModel": "模型",
  "skins.license": "授权",

  // 角色状态/情绪（CharacterBadge 占位/降级渲染，Live2D 加载失败路径可见）
  "character.state.idle": "待机中",
  "character.state.talking": "说话中",
  "character.state.thinking": "思考中",
  "character.state.working": "工作中",
  "character.state.error": "出错了",
  "character.state.sleeping": "打盹中",
  "character.emotion.happy": "开心",
  "character.emotion.sad": "难过",
  "character.emotion.confused": "困惑",
  "character.emotion.surprised": "惊讶",
  "character.emotion.embarrassed": "害羞",
  "character.emotion.angry": "生气",
};

const en: StringTable = {
  // Common
  "common.close": "Close",
  "common.cancel": "Cancel",
  "common.save": "Save",
  "common.delete": "Delete",
  "common.back": "Back",

  // Status bar
  "status.connected": "Connected · Click Mochi to chat",
  "status.connecting": "Connecting…",
  "status.disconnected": "Not connected",
  "status.setupPending": "Waiting for initial setup…",

  // Chat input bar
  "chat.placeholder": "Say something to Mochi…",
  "chat.placeholderConnecting": "Connecting…",
  "chat.stop": "Stop generating",
  "chat.sendTitle": "Send (Enter)",
  "chat.sendAria": "Send",
  "chat.collapseTitle": "Collapse (Esc)",
  "chat.collapseAria": "Collapse",

  // Context menu
  "menu.history": "Chat Memories",
  "menu.skins": "Change Outfit",
  "menu.settings": "Settings",

  // Settings panel
  "settings.title": "Settings",
  "settings.sectionGeneral": "General",
  "settings.sectionModel": "Model",
  "settings.language": "Language",
  "settings.languageZh": "简体中文",
  "settings.languageEn": "English",
  "settings.feedbackUnreachable": "Cannot reach the sidecar config service. Is it running?",
  "settings.addedFeedback": "Added “{name}”",
  "settings.testOk": "“{id}” connected ✓",
  "settings.testFail": "“{id}” unavailable: {hint}",
  "settings.unknownReason": "Unknown reason",
  "settings.testError": "Test failed",
  "settings.switchedFeedback": "Switched to “{id}” — effective immediately",
  "settings.deletedFeedback": "Deleted “{id}”",
  "settings.trialMode": "Trial mode",
  "settings.trialDesc": "Built-in echo stub, no key needed",
  "settings.inUse": "In use",
  "settings.setDefault": "Set as default",
  "settings.testing": "Testing…",
  "settings.test": "Test",
  "settings.addProvider": "+ Add provider",
  "settings.kindOllama": "Ollama (local)",
  "settings.kindOpenAiCompat": "OpenAI compatible",
  "settings.kindAnthropic": "Anthropic",

  // Provider form
  "providerForm.errId":
    "ID must start with a lowercase letter or digit, using only lowercase letters, digits, _ or -",
  "providerForm.errModel": "Please enter a model name",
  "providerForm.errSave": "Save failed",
  "providerForm.kind": "Type",
  "providerForm.kindOpenAi": "OpenAI compatible",
  "providerForm.kindOllama": "Ollama (local)",
  "providerForm.kindAnthropic": "Anthropic (coming in M1)",
  "providerForm.id": "ID (unique)",
  "providerForm.idPlaceholder": "e.g. deepseek",
  "providerForm.displayName": "Display name",
  "providerForm.displayNamePlaceholder": "e.g. My cloud model",
  "providerForm.ollamaBaseUrl": "Server URL (default 127.0.0.1:11434)",
  "providerForm.baseUrl": "Base URL",
  "providerForm.model": "Model",
  "providerForm.modelPlaceholderOllama": "e.g. qwen3:8b",
  "providerForm.modelPlaceholderOpenAi": "e.g. gpt-4o-mini",
  "providerForm.apiKey": "API Key (stored in OS keychain, never in files)",
  "providerForm.saving": "Saving…",

  // Onboarding wizard
  "onboarding.welcome": "Welcome to Mochi 🍡",
  "onboarding.searching": "Looking for available models…",
  "onboarding.enableOllama": "Found local Ollama ({model}) — enable in one click",
  "onboarding.enabling": "Enabling…",
  "onboarding.noOllama": "No local Ollama detected. Enter your model key, or try it out first.",
  "onboarding.fillKey": "Enter key",
  "onboarding.useTrial": "Try it first",

  // Chat memories panel
  "history.title": "Chats with Mochi",
  "history.empty": "No chats yet — go talk to Mochi!",
  "history.messagesEmpty": "No messages in this conversation",
  "history.deleteConfirm": "Delete this conversation?",

  // Wardrobe (outfit preview)
  "skins.title": "Mochi's Wardrobe",
  "skins.current": "Current outfit",
  "skins.comingSoon": "More skins on the way ✨",
  "skins.switchDisabled": "Outfit switching coming soon",
  "skins.creditIllustration": "Illustration",
  "skins.creditModel": "Model",
  "skins.license": "License",

  // Character state/emotion (CharacterBadge fallback rendering)
  "character.state.idle": "Idle",
  "character.state.talking": "Talking",
  "character.state.thinking": "Thinking",
  "character.state.working": "Working",
  "character.state.error": "Error",
  "character.state.sleeping": "Dozing",
  "character.emotion.happy": "Happy",
  "character.emotion.sad": "Sad",
  "character.emotion.confused": "Confused",
  "character.emotion.surprised": "Surprised",
  "character.emotion.embarrassed": "Embarrassed",
  "character.emotion.angry": "Angry",
};

export const STRINGS: Record<Language, StringTable> = { "zh-CN": zhCN, en };
