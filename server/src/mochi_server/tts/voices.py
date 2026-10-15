"""TTS 音色目录（ADR-0007 修订：百炼 CosyVoice v3 系统音色）。

目录来自官方音色列表（help.aliyun.com → CosyVoice 音色列表，cosyvoice-v3-flash
系统音色集），按品类分组；v3.5 系不支持系统音色，故模型锁 v3-flash。
CosyVoice 另支持复刻音色（mix_* 等）——/tts/stream 不做目录白名单校验，
未知 id 由云端 400 → 纯文本降级兜底，目录演进免发版。
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_VOICE_ID = "longxing_v3"

#: 品类 key → 前端 optgroup（i18n voice.category* 键）
CATEGORIES: tuple[str, ...] = ("companion", "assistant", "support", "dialect", "child")


@dataclass(frozen=True)
class VoiceOption:
    """可选音色：id 为 CosyVoice 音色名，前端 select 直接回传。"""

    id: str
    name: str
    lang: str
    gender: str
    category: str


VOICES: tuple[VoiceOption, ...] = (
    # —— 社交陪伴：官方为陪伴场景设计的品类，Mochi 首选 ——
    VoiceOption("longxing_v3", "龙星 · 温婉邻家女", "zh-CN", "female", "companion"),
    VoiceOption("longanrou_v3", "龙安柔 · 温柔闺蜜女", "zh-CN", "female", "companion"),
    VoiceOption("longanhuan_v3", "龙安欢 · 欢脱元气女", "zh-CN", "female", "companion"),
    VoiceOption("longwan_v3", "龙婉 · 细腻柔声女", "zh-CN", "female", "companion"),
    VoiceOption("longyan_v3", "温暖春风女", "zh-CN", "female", "companion"),
    VoiceOption("longanling_v3", "思维灵动女", "zh-CN", "female", "companion"),
    VoiceOption("longanqin_v3", "亲和活泼女", "zh-CN", "female", "companion"),
    VoiceOption("longhua_v3", "龙华 · 元气甜美女", "zh-CN", "female", "companion"),
    VoiceOption("longantai_v3", "龙安台 · 嗲甜台湾女", "zh-CN", "female", "companion"),
    VoiceOption("longfeifei_v3", "甜美娇气女", "zh-CN", "female", "companion"),
    VoiceOption("longqiang_v3", "浪漫风情女", "zh-CN", "female", "companion"),
    VoiceOption("longanya_v3", "高雅气质女", "zh-CN", "female", "companion"),
    VoiceOption("longanyang", "龙安洋 · 阳光大男孩", "zh-CN", "male", "companion"),
    VoiceOption("longzhe_v3", "呆板大暖男", "zh-CN", "male", "companion"),
    VoiceOption("longze_v3", "温暖元气男", "zh-CN", "male", "companion"),
    VoiceOption("longcheng_v3", "龙橙 · 智慧青年男", "zh-CN", "male", "companion"),
    VoiceOption("longhao_v3", "多情忧郁男", "zh-CN", "male", "companion"),
    VoiceOption("longhan_v3", "温暖痴情男", "zh-CN", "male", "companion"),
    VoiceOption("longtian_v3", "磁性理智男", "zh-CN", "male", "companion"),
    VoiceOption("longanzhi_v3", "睿智轻熟男", "zh-CN", "male", "companion"),
    # —— 语音助手 ——
    VoiceOption("longxiaochun_v3", "龙小淳 · 知性积极女", "zh-CN", "female", "assistant"),
    VoiceOption("longxiaoxia_v3", "龙小夏 · 沉稳权威女", "zh-CN", "female", "assistant"),
    VoiceOption("longyumi_v3", "YUMI · 正经青年女", "zh-CN", "female", "assistant"),
    VoiceOption("longanwen_v3", "优雅知性女", "zh-CN", "female", "assistant"),
    VoiceOption("longanli_v3", "利落从容女", "zh-CN", "female", "assistant"),
    VoiceOption("longanyun_v3", "居家暖男", "zh-CN", "male", "assistant"),
    VoiceOption("longanlang_v3", "清爽利落男", "zh-CN", "male", "assistant"),
    VoiceOption("longyingmu_v3", "优雅知性女（助手）", "zh-CN", "female", "assistant"),
    # —— 客服 ——
    VoiceOption("longyingling_v3", "龙应聆 · 温和共情女", "zh-CN", "female", "support"),
    VoiceOption("longyingtao_v3", "龙应桃 · 温柔淡定女", "zh-CN", "female", "support"),
    VoiceOption("longyingjing_v3", "低调冷静女", "zh-CN", "female", "support"),
    VoiceOption("longyingxiao_v3", "清甜推销女", "zh-CN", "female", "support"),
    VoiceOption("longyingxun_v3", "年轻青涩男", "zh-CN", "male", "support"),
    # —— 方言 ——
    VoiceOption("longjiaxin_v3", "龙嘉欣 · 粤语女", "zh-CN", "female", "dialect"),
    VoiceOption("longjiayi_v3", "粤语女（嘉仪）", "zh-CN", "female", "dialect"),
    VoiceOption("longanyue_v3", "粤语男", "zh-CN", "male", "dialect"),
    VoiceOption("longlaotie_v3", "龙老铁 · 东北男", "zh-CN", "male", "dialect"),
    VoiceOption("longshange_v3", "陕北男", "zh-CN", "male", "dialect"),
    # —— 童声 ——
    VoiceOption("longhuhu_v3", "龙呼呼 · 萌系童声", "zh-CN", "female", "child"),
)

#: 旧音色 id（edge / CosyVoice v2）→ v3 等价音色；迁移与 PUT voice、
#: /tts/stream 合成时共用（存量 v2 配置不重跑迁移也能在合成时归一）。
_LEGACY_VOICE_MAP: dict[str, str] = {
    # edge-tts 时代
    "zh-CN-XiaoxiaoNeural": "longxing_v3",
    "zh-CN-YunxiNeural": "longanyang",
    "zh-CN-YunjianNeural": "longze_v3",
    "en-US-AriaNeural": "longanwen_v3",
    "en-US-GuyNeural": "longtian_v3",
    # CosyVoice v2 目录（语音重构期间的过渡 id）
    "longwan_v2": "longwan_v3",
    "longtong_v2": "longwan_v3",
    "longcheng_v2": "longanling_v3",  # v2 喜剧女 → v3 龙橙变男声，改灵动女
    "longxiaoxia_v2": "longxiaoxia_v3",
    "longxiaochun_v2": "longxiaochun_v3",
    "longxiang_v2": "longanyang",  # 少年音
    "longqi_v2": "longtian_v3",
    "longhua_v2": "longtian_v3",  # v2 磁性男；v3 龙华变女声
    "loongbella_v2": "longanwen_v3",
    "loongstella_v2": "longanwen_v3",
}


def normalize_voice_id(voice_id: str) -> str:
    """旧 id（edge/v2）映射到 v3；未知非空值原样返回（兼容复刻音色），空值回默认。"""
    if not voice_id:
        return DEFAULT_VOICE_ID
    return _LEGACY_VOICE_MAP.get(voice_id, voice_id)


def voice_catalog() -> list[dict[str, str]]:
    """GET /tts/voices 响应体（camelCase 与前端约定一致，按品类分组排序）。"""
    by_category = {category: [] for category in CATEGORIES}
    others: list[VoiceOption] = []
    for v in VOICES:
        if v.category in by_category:
            by_category[v.category].append(v)
        else:
            others.append(v)
    ordered = [v for category in CATEGORIES for v in by_category[category]] + others
    return [
        {"id": v.id, "name": v.name, "lang": v.lang, "gender": v.gender, "category": v.category}
        for v in ordered
    ]
