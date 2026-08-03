/**
 * CharacterBadge —— 角色占位表现（S3 替换为 Live2D 渲染层）。
 *
 * 只消费 store 中的 characterState / emotion，与 Live2D 状态机
 * 的输入契约一致（功能清单 2.2），S3 换渲染层不改数据流。
 */
import type { CharacterState, Emotion } from "@mochi/protocol";
import { useConversation } from "../store/conversation";

const STATE_LABELS: Record<CharacterState, string> = {
  idle: "待机中",
  talking: "说话中",
  thinking: "思考中",
  working: "工作中",
  error: "出错了",
  sleeping: "打盹中",
};

const STATE_CLASS: Record<CharacterState, string> = {
  idle: "badge--idle",
  talking: "badge--talking",
  thinking: "badge--thinking",
  working: "badge--working",
  error: "badge--error",
  sleeping: "badge--sleeping",
};

const EMOTION_LABELS: Partial<Record<Emotion, string>> = {
  happy: "开心",
  sad: "难过",
  confused: "困惑",
  surprised: "惊讶",
  embarrassed: "害羞",
  angry: "生气",
};

export function CharacterBadge() {
  const characterState = useConversation((s) => s.characterState);
  const emotion = useConversation((s) => s.emotion);
  const emotionLabel = emotion !== null ? EMOTION_LABELS[emotion] : undefined;

  return (
    <div className="character">
      <div className={`character__badge ${STATE_CLASS[characterState]}`}>
        <span className="character__face" aria-hidden>
          🍡
        </span>
      </div>
      <div className="character__meta">
        <span className="character__state">{STATE_LABELS[characterState]}</span>
        {emotionLabel !== undefined ? (
          <span className="character__emotion">{emotionLabel}</span>
        ) : null}
      </div>
    </div>
  );
}
