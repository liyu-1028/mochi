/**
 * CharacterBadge —— 角色占位表现（Live2D 加载失败时的降级渲染）。
 *
 * 只消费 store 中的 characterState / emotion，与 Live2D 状态机
 * 的输入契约一致（功能清单 2.2），换渲染层不改数据流。
 * 状态/情绪文案经 i18n 字典（character.state.* / character.emotion.*），
 * 跟随界面语言切换（i18n 审计 2026-08-05：原硬编码中文已接入）。
 */
import type { CharacterState, Emotion } from "@mochi/protocol";
import { useI18n } from "../i18n";
import { useConversation } from "../store/conversation";

/** state → i18n 键（文案事实源在 strings.ts，随语言切换） */
const STATE_LABEL_KEYS: Record<CharacterState, string> = {
  idle: "character.state.idle",
  talking: "character.state.talking",
  thinking: "character.state.thinking",
  working: "character.state.working",
  error: "character.state.error",
  sleeping: "character.state.sleeping",
};

const STATE_CLASS: Record<CharacterState, string> = {
  idle: "badge--idle",
  talking: "badge--talking",
  thinking: "badge--thinking",
  working: "badge--working",
  error: "badge--error",
  sleeping: "badge--sleeping",
};

/** emotion → i18n 键 */
const EMOTION_LABEL_KEYS: Partial<Record<Emotion, string>> = {
  happy: "character.emotion.happy",
  sad: "character.emotion.sad",
  confused: "character.emotion.confused",
  surprised: "character.emotion.surprised",
  embarrassed: "character.emotion.embarrassed",
  angry: "character.emotion.angry",
};

export function CharacterBadge() {
  const { t } = useI18n();
  const characterState = useConversation((s) => s.characterState);
  const emotion = useConversation((s) => s.emotion);
  const emotionKey = emotion !== null ? EMOTION_LABEL_KEYS[emotion] : undefined;

  return (
    <div className="character">
      <div className={`character__badge ${STATE_CLASS[characterState]}`}>
        <span className="character__face" aria-hidden>
          🍡
        </span>
      </div>
      <div className="character__meta">
        <span className="character__state">{t(STATE_LABEL_KEYS[characterState])}</span>
        {emotionKey !== undefined ? (
          <span className="character__emotion">{t(emotionKey)}</span>
        ) : null}
      </div>
    </div>
  );
}
