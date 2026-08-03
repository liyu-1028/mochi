import { PROTOCOL_VERSION } from "@mochi/protocol";

/**
 * M0 垂直原型前的骨架占位页。
 * 角色渲染（Live2D/pixi）、透明窗口命中测试、对话面板在此之上迭代。
 */
export default function App() {
  return (
    <main className="skeleton">
      <h1>Mochi</h1>
      <p>会成长的桌面智能伙伴 · 骨架已就绪</p>
      <p>
        <code>protocol v{PROTOCOL_VERSION}</code>
      </p>
    </main>
  );
}
