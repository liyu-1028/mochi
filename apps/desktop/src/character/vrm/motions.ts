/** VRM actions contain imported animation data only; there are no built-in motion factories. */
export interface VrmMotionDef {
  id: string;
  label: string;
  kind: "oneshot" | "loop";
  durationMs: number;
  priority: number;
  cooldownMs: number;
  agentSelectable: boolean;
  tags: readonly string[];
  assetUrl?: string;
  expression?: { preset: string; intensity: number };
}

/** Idle decorations are opt-in imported one-shots, with quiet time between performances. */
export function pickImportedIdleMotion<T extends Pick<VrmMotionDef, "id" | "kind" | "tags">>(
  motions: readonly T[],
  random: number,
): T | null {
  const candidates = motions.filter(
    (motion) =>
      motion.kind === "oneshot" && motion.id !== "idle_neutral" && motion.tags.includes("idle"),
  );
  if (candidates.length === 0 || random < 0 || random >= 0.3) return null;
  return candidates[Math.floor((random / 0.3) * candidates.length)] ?? null;
}
