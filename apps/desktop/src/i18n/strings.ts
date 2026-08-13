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
  "common.edit": "编辑",
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
  "menu.memory": "记忆",
  "menu.skins": "换个装扮",
  "menu.settings": "设置",

  // 设置面板
  "settings.title": "设置",
  "settings.sectionGeneral": "通用",
  "settings.sectionModel": "模型",
  "settings.sectionCharacter": "角色",
  "settings.sectionVoice": "语音",
  "settings.sectionPrivacy": "隐私",
  "settings.comingSoon": "敬请期待",
  "settings.language": "界面语言",
  "settings.languageZh": "简体中文",
  "settings.languageEn": "English",
  "voice.enabled": "语音输出",
  "voice.muted": "静音",
  "voice.voice": "音色",
  "voice.volume": "音量",
  "voice.rate": "语速",
  "voice.test": "试听",
  "voice.testText": "你好，我是 Mochi，很高兴见到你。",
  "voice.hint": "默认引擎免费无需 Key；失败自动降级为纯文本，不阻塞对话。",
  "settings.feedbackUnreachable": "无法连接 sidecar 配置服务，请确认它正在运行",
  "settings.addedFeedback": "已添加「{name}」",
  "settings.updatedFeedback": "已更新「{name}」，立即生效",
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

  // 人格选择（设置「角色」tab，功能清单 6.13）
  "persona.intro": "为 Mochi 挑选灵魂、性格与说话风格，也可组合或自定义。保存后下一轮对话即生效。",
  "persona.soul": "灵魂",
  "persona.soulDesc": "Mochi 内在是个怎样的存在",
  "persona.personality": "性格",
  "persona.personalityDesc": "Mochi 待人处事的方式",
  "persona.style": "说话风格",
  "persona.styleDesc": "Mochi 表达的语气与口吻",
  "persona.custom": "自定义",
  "persona.customDesc": "用你自己的话描述",
  "persona.customPlaceholder": "写下你想要的设定（不超过 500 字）…",
  "persona.save": "保存",
  "persona.resetDefault": "恢复默认",
  "persona.saved": "已保存，下一轮对话即生效",
  "persona.resetDone": "已恢复为默认 Mochi",
  "persona.errorLoad": "人格设置加载失败",
  "persona.errorSave": "保存失败",

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
  "providerForm.apiKeyEditPlaceholder": "留空则保持原 Key 不变",
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

  // 衣橱（M1-S1：换肤/导入/删除）
  "skins.title": "Mochi 的衣橱",
  "skins.builtin": "内置",
  "skins.user": "用户",
  "skins.activate": "穿上",
  "skins.switching": "换装中…",
  "skins.import": "导入皮肤（PNG / zip）",
  "skins.importing": "导入中…",
  "skins.transparencyHint": "透明底 PNG 穿上更好看；带底图的图片会原样展示。",
  "skins.smallImageHint": "图片分辨率较低，穿上后可能不够清晰",
  "skins.errorLoad": "皮肤列表加载失败",
  "skins.errorSave": "皮肤操作失败",
  "skins.creditIllustration": "原画",
  "skins.creditModel": "模型",
  "skins.license": "授权",

  // 记忆管理（M1-S3，功能清单 6.4）
  "memory.title": "Mochi 的记忆",
  "memory.empty": "还没有记忆。和 Mochi 聊天时会自动记住关于你的重要信息。",
  "memory.loading": "加载中…",
  "memory.add": "添加",
  "memory.addPlaceholder": "手动添加一条记忆…",
  "memory.categoryFact": "事实",
  "memory.categoryPreference": "偏好",
  "memory.sourceAuto": "自动",
  "memory.sourceManual": "手动",
  "memory.count": "共 {n} 条记忆",
  "memory.clearAll": "清空全部",
  "memory.clearAllConfirm": "确认清空？",
  "memory.errorLoad": "记忆加载失败",
  "memory.errorSave": "记忆操作失败",

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

  // 系统托盘（功能清单 1.4）
  "tray.showHide": "显示 / 隐藏 Mochi",
  "tray.openChat": "打开对话",
  "tray.mute": "静音",
  "tray.quit": "退出 Mochi",
};

const en: StringTable = {
  // Common
  "common.close": "Close",
  "common.cancel": "Cancel",
  "common.save": "Save",
  "common.edit": "Edit",
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
  "menu.memory": "Memories",
  "menu.skins": "Change Outfit",
  "menu.settings": "Settings",

  // Settings panel
  "settings.title": "Settings",
  "settings.sectionGeneral": "General",
  "settings.sectionModel": "Model",
  "settings.sectionCharacter": "Character",
  "settings.sectionVoice": "Voice",
  "settings.sectionPrivacy": "Privacy",
  "settings.comingSoon": "Coming soon",
  "settings.language": "Language",
  "settings.languageZh": "简体中文",
  "settings.languageEn": "English",
  "voice.enabled": "Voice output",
  "voice.muted": "Mute",
  "voice.voice": "Voice",
  "voice.volume": "Volume",
  "voice.rate": "Speed",
  "voice.test": "Test",
  "voice.testText": "Hi, I'm Mochi. Nice to meet you.",
  "voice.hint":
    "The default engine is free and keyless; on failure it degrades to text without blocking chat.",
  "settings.feedbackUnreachable": "Cannot reach the sidecar config service. Is it running?",
  "settings.addedFeedback": "Added “{name}”",
  "settings.updatedFeedback": "Updated “{name}” — effective immediately",
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

  // Persona selection (Settings > Character tab, feature 6.13)
  "persona.intro":
    "Pick Mochi's soul, personality and speaking style — mix presets or write your own. Takes effect from the next reply.",
  "persona.soul": "Soul",
  "persona.soulDesc": "What Mochi is at the core",
  "persona.personality": "Personality",
  "persona.personalityDesc": "How Mochi behaves with you",
  "persona.style": "Speaking style",
  "persona.styleDesc": "The tone and voice Mochi uses",
  "persona.custom": "Custom",
  "persona.customDesc": "Describe it in your own words",
  "persona.customPlaceholder": "Write the setting you want (up to 500 chars)…",
  "persona.save": "Save",
  "persona.resetDefault": "Reset to default",
  "persona.saved": "Saved — takes effect from the next reply",
  "persona.resetDone": "Reset to the default Mochi",
  "persona.errorLoad": "Failed to load persona settings",
  "persona.errorSave": "Save failed",

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
  "providerForm.apiKeyEditPlaceholder": "Leave blank to keep the current key",
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

  // Wardrobe (M1-S1: switch/import/delete)
  "skins.title": "Mochi's Wardrobe",
  "skins.builtin": "Built-in",
  "skins.user": "User",
  "skins.activate": "Wear",
  "skins.switching": "Switching…",
  "skins.import": "Import skin (PNG / zip)",
  "skins.importing": "Importing…",
  "skins.transparencyHint":
    "Transparent-background PNGs look best; images with a background are shown as-is.",
  "skins.smallImageHint": "Low-resolution image — it may look blurry when worn",
  "skins.errorLoad": "Failed to load skins",
  "skins.errorSave": "Skin operation failed",
  "skins.creditIllustration": "Illustration",
  "skins.creditModel": "Model",
  "skins.license": "License",

  // Memories (M1-S3, feature 6.4)
  "memory.title": "Mochi's Memories",
  "memory.empty":
    "No memories yet. Mochi will automatically remember important things about you as you chat.",
  "memory.loading": "Loading…",
  "memory.add": "Add",
  "memory.addPlaceholder": "Add a memory manually…",
  "memory.categoryFact": "Fact",
  "memory.categoryPreference": "Preference",
  "memory.sourceAuto": "Auto",
  "memory.sourceManual": "Manual",
  "memory.count": "{n} memories",
  "memory.clearAll": "Clear All",
  "memory.clearAllConfirm": "Confirm clear?",
  "memory.errorLoad": "Failed to load memories",
  "memory.errorSave": "Memory operation failed",

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

  // System tray (feature list 1.4)
  "tray.showHide": "Show / Hide Mochi",
  "tray.openChat": "Open Chat",
  "tray.mute": "Mute",
  "tray.quit": "Quit Mochi",
};

export const STRINGS: Record<Language, StringTable> = { "zh-CN": zhCN, en };
