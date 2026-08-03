# Mochi Agent 事件协议规范 v0.1

| 字段 | 值 |
| --- | --- |
| 协议版本 | `0.1` |
| 状态 | **冻结（M0 基线）** —— 变更须走本文档 §9 兼容性流程 |
| 传输层 | 本地 WebSocket（`ws://127.0.0.1:<port>/ws`），JSON 文本帧 |
| 事实源 | 前端：`packages/protocol/src/index.ts`；后端镜像：`server/src/mochi_server/events.py` |
| 黄金样例 | `packages/protocol/testdata/turn-with-tool-call.jsonl` |

## 1. 设计原则

1. **参考 AG-UI 事件模型，不直接绑定其传输实现。** 业界流式 Agent 协议的事实模式是
   start/delta/end 三阶段生命周期（AG-UI 的 Start-Content-End、Vercel AI SDK 的
   text-start/delta/end 均属此模式）。本协议沿用该模式命名事件，便于未来与 AG-UI
   生态互通或切换。
2. **Mochi 特有语义用独立事件表达**：`thinking.*`（思考动画）与 `emotion`（情绪表情）
   是角色表现力的核心输入，不做任何隐式约定。
3. **客户端必须忽略未知 `type`**（前向兼容的基石，见 §9）。
4. **错误必须可读**：一切错误走 `ErrorPayload`，禁止向前端裸露堆栈（功能清单 6.7）。
5. **角色状态由服务端驱动**：前端动画状态机只消费 `state.change`，不自行推断，
   保证「Agent 状态 → 角色表现」单一映射链路（功能清单 2.2）。

## 2. 连接与握手

```
桌面壳                          sidecar
  │  ws connect /ws               │
  ├──────────────────────────────▶│
  │  hello {versions:["0.1"],…}   │
  ├──────────────────────────────▶│
  │  hello_ack {version:"0.1",…}  │   ← 版本协商成功，连接就绪
  │◀──────────────────────────────┤
```

- 连接建立后，**客户端必须先发 `hello`**，声明支持的协议版本列表（按偏好降序）。
- 服务端选择双方都支持的最高版本回 `hello_ack`；若无交集，回 `hello_error`
  （`code: ERR_VERSION_MISMATCH`）并关闭连接。
- 握手完成前，服务端应拒绝处理其他命令（`ping` 除外）。

## 3. 通用信封（Envelope）

所有帧共享统一外层结构，**字段名一律 camelCase**：

```jsonc
{
  "v": "0.1",              // 协议版本，固定值
  "type": "text.delta",    // 命令/事件类型（§4、§5 的枚举值）
  "id": "uuid-v4",         // 本条消息唯一 ID
  "ts": 1754179200000,     // 发送方毫秒时间戳
  "data": { ... }          // 负载，结构由 type 决定
}
```

服务端事件中与某次对话回合相关的，`data` 内携带 `runId`。

## 4. 客户端 → 服务端：命令

| type | 说明 | data 字段 |
| --- | --- | --- |
| `hello` | 握手 | `versions: string[]`，`client: {name, version}` |
| `ping` | 保活/RTT | `token?: string`（原样回传） |
| `chat.send` | 发起对话回合 | `runId`（客户端生成 UUID），`sessionId`，`text`，`attachments?` |
| `chat.cancel` | 取消生成，丢弃后续输出 | `runId` |
| `chat.interrupt` | 打断播报（停 TTS/展示，保留已生成内容；语音 barge-in 场景） | `runId` |

`chat.cancel` 与 `chat.interrupt` 的语义区别（功能清单 4.2 / 5.3）：

- **cancel**：用户点了「停止生成」→ 服务端终止推理，回合以 `reason: "cancelled"` 结束。
- **interrupt**：用户开口插话 → 停止播报但回合内容保留，随后可接新的 `chat.send`。

## 5. 服务端 → 客户端：事件

### 5.1 连接管理

| type | data |
| --- | --- |
| `hello_ack` | `version`（协商结果），`server: {name, version}` |
| `hello_error` | `error: ErrorPayload` |
| `pong` | `token?` |

### 5.2 回合生命周期（Lifecycle）

| type | data | 说明 |
| --- | --- | --- |
| `run.started` | `runId`，`sessionId` | 回合开始，首个事件 |
| `run.finished` | `runId`，`reason`，`usage?` | 回合结束，末个事件 |
| `run.error` | `runId`，`error` | 回合级错误（其后仍应有 `run.finished`，`reason: "error"`） |

`reason ∈ complete | cancelled | interrupted | error`。

### 5.3 文本流（Text）—— start/delta/end 生命周期

| type | data |
| --- | --- |
| `text.start` | `runId`，`messageId`，`role: "assistant"` |
| `text.delta` | `runId`，`messageId`，`delta: string` |
| `text.end` | `runId`，`messageId`，`fullText: string` |

前端在 `text.start`→`text.end` 期间驱动角色「说话」状态与嘴部动画（功能清单 2.3）。

### 5.4 思考流（Thinking）—— Mochi 扩展

| type | data |
| --- | --- |
| `thinking.start` | `runId`，`messageId` |
| `thinking.delta` | `runId`，`messageId`，`delta: string` |
| `thinking.end` | `runId`，`messageId` |

对应 AG-UI 概念中的 Custom Event。用于展示推理过程并驱动「思考」动画；
UI 可选择折叠展示，但动画状态必须响应。

### 5.5 工具调用（Tool）

| type | data |
| --- | --- |
| `tool.call.start` | `runId`，`toolCallId`，`name`，`args: object` |
| `tool.call.end` | `runId`，`toolCallId`，`status`，`result?`，`error?` |

`status ∈ success | error | denied`。`denied` 表示用户在危险操作确认框中拒绝
（功能清单 6.5）。工具执行期间服务端应发送 `state.change → working`。

### 5.6 角色表现（Mochi 扩展）

| type | data | 说明 |
| --- | --- | --- |
| `emotion` | `runId?`，`emotion`，`intensity: 0~1` | 情绪标签 → 表情映射（功能清单 2.5） |
| `state.change` | `state` | 动画状态机切换（功能清单 2.2） |

枚举定义：

```text
emotion ∈ neutral | happy | sad | confused | surprised | embarrassed | angry
state   ∈ idle | talking | thinking | working | error | sleeping
```

## 6. ErrorPayload 结构

```jsonc
{
  "code": "ERR_MODEL_AUTH",     // §7 标准错误码，或扩展自定义码
  "message": "模型密钥无效，请检查设置",   // 用户可读文案
  "retryable": false,
  "hint": "打开 设置 → 模型 重新填写 Key"  // 可选排查建议
}
```

## 7. 标准错误码

| code | 含义 | retryable 建议 |
| --- | --- | --- |
| `ERR_VERSION_MISMATCH` | 协议版本不兼容 | false |
| `ERR_MODEL_AUTH` | Key 无效/过期 | false |
| `ERR_MODEL_UNAVAILABLE` | 模型服务不可达（含 Ollama 未启动） | true |
| `ERR_MODEL_RATE_LIMIT` | 限流 | true |
| `ERR_NETWORK` | 一般网络错误 | true |
| `ERR_CONTEXT_OVERFLOW` | 上下文超限（应自动摘要，兜底才报此错） | false |
| `ERR_TOOL_DENIED` | 用户拒绝危险操作授权 | false |
| `ERR_TOOL_FAILED` | 工具执行失败 | 视工具而定 |
| `ERR_CANCELLED` | 用户取消 | false |
| `ERR_INTERNAL` | 未分类内部错误 | false |

## 8. 典型时序

### 8.1 普通回合（含工具调用）

见黄金样例 `packages/protocol/testdata/turn-with-tool-call.jsonl`：

```text
hello → hello_ack
chat.send
  run.started → state.change(thinking)
  thinking.start/delta/end
  state.change(working) → tool.call.start → tool.call.end
  state.change(talking) → emotion(happy)
  text.start → text.delta… → text.end
  state.change(idle)
run.finished(complete)
```

### 8.2 取消回合

```text
chat.send → run.started → text.start → text.delta…
chat.cancel
run.finished(reason: "cancelled")   ← 已输出的 delta 前端保留展示
```

## 9. 兼容性规则

1. `0.x` 阶段：**新增事件/字段**随时允许（客户端必须忽略未知 type、容忍未知字段）。
2. `0.x` 阶段：**删除或修改既有语义**须升 minor（0.1 → 0.2），并在本文档追加变更记录；
   服务端应至少同时兼容上一个 minor 版本一个发布周期。
3. 握手协商是兼容性的执行点：桌面壳与 sidecar 可能因自动更新短暂不同步（功能清单 1.7），
   `hello` 携带版本列表即为该场景设计。
4. M1 GA 时评估冻结为 `1.0`，此后遵循严格 SemVer。

## 10. 范围外（本版本不定义）

- 配置读写 RPC（HTTP 端点，见 `docs/specs/config-format.md`）
- 多会话并发的 run 调度策略（M1）
- 语音流（ASR 音频上行 / TTS 音频下行走独立通道，M1 另行规范）

## 变更记录

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| 0.1 | 2026-08-03 | 初版冻结：信封、握手、5 类命令、16 类事件、错误码表 |
