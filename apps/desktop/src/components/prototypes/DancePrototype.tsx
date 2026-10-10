/**
 * PROTOTYPE — 验证现成 VRM + Samba 的动作自然度；入口 ?prototype=vrm-dance。
 * 本次只比较真实动作效果，不制作无关的界面变体。状态不持久化。
 */
import { useEffect, useRef, useState } from "react";
import { createDanceStage, type DanceStage, type DanceSnapshot } from "./danceStage";
import "./dancePrototype.css";

export default function DancePrototype() {
  const hostRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<DanceStage | null>(null);
  const [status, setStatus] = useState("正在准备舞台…");
  const [error, setError] = useState("");
  const [speed, setSpeed] = useState("1");
  const [snapshot, setSnapshot] = useState<DanceSnapshot>({
    time: 0,
    duration: 0,
    fps: 0,
    tracks: 0,
    playing: true,
  });

  useEffect(() => {
    document.title = "Mochi · VRM 舞蹈实验";
    if (!hostRef.current) return;
    try {
      const stage = createDanceStage(hostRef.current, setSnapshot, setStatus, setError);
      stageRef.current = stage;
      return () => {
        stageRef.current = null;
        stage.dispose();
      };
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, []);

  const ready = snapshot.duration > 0;
  return (
    <main className="dance-prototype">
      <header className="dance-prototype__header">
        <div>
          <span className="dance-prototype__eyebrow">MOCHI / MOTION STUDY 01</span>
          <h1>让角色，跳起来。</h1>
          <p>全身 Samba 舞蹈 · 转动视角，看看每一个动作。</p>
        </div>
        <a href="/">返回 Mochi</a>
      </header>
      <section className="dance-prototype__stage" aria-label="舞蹈预览">
        <div ref={hostRef} className="dance-prototype__canvas" />
        <div className="dance-prototype__badge">
          <span className={ready ? "dance-prototype__dot" : ""} />
          {status}
        </div>
        {error && (
          <div className="dance-prototype__error" role="alert">
            加载失败：{error}
            <br />
            请在项目根目录运行 pnpm dev:dance 后刷新。
          </div>
        )}
        {!ready && !error && (
          <div className="dance-prototype__loading" role="status">
            {status}
          </div>
        )}
        <div className="dance-prototype__views" aria-label="观察视角">
          <button onClick={() => stageRef.current?.view(0)}>正面</button>
          <button onClick={() => stageRef.current?.view(Math.PI / 2)}>侧面</button>
          <button onClick={() => stageRef.current?.view(Math.PI)}>背面</button>
        </div>
        <span className="dance-prototype__hint">拖动旋转 · 滚轮缩放</span>
      </section>
      <section className="dance-prototype__controls" aria-label="播放控制">
        <div className="dance-prototype__timeline">
          <label htmlFor="dance-time">{snapshot.time.toFixed(1)}s</label>
          <input
            id="dance-time"
            aria-label="舞蹈进度"
            type="range"
            min="0"
            max={snapshot.duration || 1}
            step="0.01"
            value={snapshot.time}
            disabled={!ready}
            onChange={(event) => stageRef.current?.seek(Number(event.target.value))}
          />
          <span>{snapshot.duration.toFixed(1)}s</span>
        </div>
        <div className="dance-prototype__toolbar">
          <button
            className="dance-prototype__play"
            disabled={!ready}
            onClick={() => stageRef.current?.toggle()}
          >
            {snapshot.playing ? "暂停" : "播放"}
          </button>
          <button disabled={!ready} onClick={() => stageRef.current?.restart()}>
            从头播放
          </button>
          <label>
            速度{" "}
            <select
              aria-label="播放速度"
              value={speed}
              onChange={(event) => {
                setSpeed(event.target.value);
                stageRef.current?.setSpeed(Number(event.target.value));
              }}
            >
              <option value="0.25">0.25×</option>
              <option value="0.5">0.5×</option>
              <option value="1">1×</option>
              <option value="1.5">1.5×</option>
            </select>
          </label>
          <label>
            <input
              type="checkbox"
              defaultChecked
              onChange={(event) => stageRef.current?.setLoop(event.target.checked)}
            />
            循环
          </label>
          <label>
            <input
              type="checkbox"
              defaultChecked
              onChange={(event) => stageRef.current?.setGrid(event.target.checked)}
            />
            地面网格
          </label>
          <output className="dance-prototype__metrics">
            {snapshot.fps} FPS · {snapshot.tracks} 动作轨道
          </output>
        </div>
      </section>
      <footer className="dance-prototype__footer">
        <p>观察重点：脚步落地、髋部重心、手臂转动和头发随动。拖动进度条可定格检查。</p>
        <p>
          角色：pixiv VRM 示例 · 动作：Samba Dancing / Mixamo（Three.js 示例）· Three.js + VRM
          实时渲染
        </p>
        <small>
          本地效果原型，无配乐；保留原始舞蹈，尚未做专属脚部 IK、衣物碰撞或循环接缝修整。
        </small>
      </footer>
    </main>
  );
}
