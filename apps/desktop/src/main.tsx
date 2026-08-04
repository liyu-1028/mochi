import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

// 启动里程碑打点（performance.now 相对页面 timeOrigin）：1.1 冷启动验收用
console.info(`[mochi] app-mounted +${Math.round(performance.now())}ms`);
