#!/usr/bin/env node
// 无头冒烟（ADR-0010 教训④ 方法论）：CDP 驱动系统 Chrome（SwiftShader 软件
// WebGL），等待 VRM 舞台就绪打点，截图落盘。观测判据：
//   [mochi] character-ready(vrm) +ms —— 舞台就绪（模型/stance/循环全通）
//   [VrmStage] 模型加载失败 —— 降级路径
// 用法（前置：sidecar 8199 与 vite 1420 已运行）：
//   node --experimental-websocket scripts/vrm-smoke.mjs [url] [--out xxx.png]
//   [--cue <actionId>]：就绪后经 sidecar /dev/cue 广播 body 动作，验证
//   调度→解析→（资产）加载→播放全链路（如 dance 走 Mixamo 重定向）。
import { spawn } from "node:child_process";
import { writeFileSync } from "node:fs";
import { setTimeout as delay } from "node:timers/promises";

const args = process.argv.slice(2);
const url = args.find((a) => !a.startsWith("--")) ?? "http://localhost:1420/";
const out = args[args.indexOf("--out") + 1] ?? "vrm-smoke.png";
const CHROME =
  process.env.CHROME_BIN ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PORT = 9777;

const chrome = spawn(
  CHROME,
  [
    "--headless=new",
    "--disable-gpu",
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
    `--remote-debugging-port=${PORT}`,
    "--no-first-run",
    "about:blank",
  ],
  { stdio: "ignore" },
);

const exit = async (code, message) => {
  console.log(message);
  chrome.kill();
  process.exit(code);
};

try {
  // 等 DevTools 端点就绪
  let version = null;
  for (let i = 0; i < 40; i += 1) {
    try {
      version = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json();
      break;
    } catch {
      await delay(250);
    }
  }
  if (!version) await exit(1, "[smoke] DevTools 端点未就绪");

  const { webSocketDebuggerUrl } = version;
  const ws = new globalThis.WebSocket(webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = reject;
  });

  let seq = 0;
  const pending = new Map();
  const events = [];
  const send = (method, params = {}, sessionId) =>
    new Promise((resolve, reject) => {
      const id = ++seq;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    });

  const logs = [];
  ws.onmessage = (message) => {
    const data = JSON.parse(message.data);
    if (data.id && pending.has(data.id)) {
      const { resolve, reject } = pending.get(data.id);
      pending.delete(data.id);
      if (data.error) reject(new Error(data.error.message));
      else resolve(data.result);
      return;
    }
    if (data.method === "Runtime.consoleAPICalled") {
      const text = data.params.args.map((a) => a.value ?? a.description ?? "").join(" ");
      logs.push(text);
      if (/character-ready|加载失败|error/i.test(text)) events.push(text);
    }
    if (data.method === "Runtime.exceptionThrown") {
      const detail = data.params.exceptionDetails;
      logs.push(`EXCEPTION: ${detail.text} ${detail.exception?.description ?? ""}`);
      events.push(logs[logs.length - 1]);
    }
  };

  const { targetId } = await send("Target.createTarget", { url });
  const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
  await send("Runtime.enable", {}, sessionId);
  await send("Page.enable", {}, sessionId);

  // 等就绪打点（模型 10.7MB + SwiftShader 解码，headless 下宽限 60s）
  let readyLog = null;
  for (let i = 0; i < 120 && !readyLog; i += 1) {
    await delay(500);
    readyLog = logs.find((l) => l.includes("character-ready(vrm)")) ?? null;
  }

  // cue 冒烟：广播 body 动作，收 [director] accept + 后续无加载错误。
  // 稳定期：页面 WS 注册与业务握手完成后再广播（就绪打点只代表模型加载完）
  const cueAction = args.includes("--cue") ? args[args.indexOf("--cue") + 1] : null;
  const cueDelayMs = Number(args[args.indexOf("--cue-delay") + 1] ?? 15000);
  if (cueAction && readyLog) {
    if (cueDelayMs > 0) await delay(cueDelayMs);
    const resp = await fetch("http://127.0.0.1:8199/dev/cue", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ channel: "body", actionId: cueAction }),
    }).catch((err) => ({ ok: false, status: err.message }));
    let respBody = {};
    try {
      respBody = await resp.json();
    } catch {
      /* 非 JSON */
    }
    logs.push(`[smoke] /dev/cue ${cueAction} -> ${resp.status} ${JSON.stringify(respBody)}`);
    await delay(8000); // dance.fbx 3.7MB 加载 + 重定向 + 播放头
    // 观测钩子断言（dev 构建）：__mochiDirector.lastPlayMotion 由 VrmStage 写入
    const evalRes = await send(
      "Runtime.evaluate",
      {
        expression: "JSON.stringify(window.__mochiDirector?.lastPlayMotion ?? null)",
        returnByValue: true,
      },
      sessionId,
    );
    logs.push(`[smoke] lastPlayMotion = ${evalRes.result.value}`);
  }

  const shot = await send(
    "Page.captureScreenshot",
    { format: "png", captureBeyondViewport: false },
    sessionId,
  );
  writeFileSync(out, Buffer.from(shot.data, "base64"));
  const failed = logs.find((l) => l.includes("加载失败"));

  console.log("---- console 摘要 ----");
  for (const l of logs.filter(
    (l) =>
      l.startsWith("[mochi]") ||
      l.includes("EXCEPTION") ||
      l.startsWith("[smoke]") ||
      l.includes("[director]") ||
      l.includes("[locomotion]"),
  )) {
    console.log(" ", l.slice(0, 160));
  }
  const cueAccepted = logs.find((l) => l.startsWith("[smoke] lastPlayMotion = {"));
  const loadError = logs.find((l) => l.includes("加载失败") || l.includes("EXCEPTION"));
  if (readyLog && !loadError) {
    console.log(
      `[smoke] PASS ${readyLog}；截图 ${out}` +
        (cueAction
          ? `；cue=${cueAction} ${cueAccepted ? "已受理" : "未受理（查 sidecar /dev/cue）"}`
          : ""),
    );
    await chrome.kill();
    process.exit(0);
  }
  if (failed) {
    console.log(`[smoke] FAIL 走降级路径：${failed}`);
    await chrome.kill();
    process.exit(1);
  }
  console.log("[smoke] FAIL 60s 内未见就绪打点（无降级日志——加载悬挂或日志缺失）");
  await chrome.kill();
  process.exit(1);
} catch (error) {
  await exit(1, `[smoke] 异常：${error.message}`);
}
