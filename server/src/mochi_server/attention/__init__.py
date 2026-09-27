"""注意力引擎（M-D，调研报告 §4.1/§8.2/§8.6）——两阶段决策的第一阶段。

把「观察到什么」（信号）与「是否值得打扰、想做什么」（意图）分开：

1. ``submit(signal)``：信号 → 结构化意图（silent / action_intent / speak_intent /
   ask_intent）；
2. ``gate(intent)``：打扰门控规则全表（§8.6 抑制清单）→ 放行或抑制（带原因）。

只有通过门控的 speak/ask intent 才交给上层（RunManager → LangGraph）生成措辞；
action_intent 由上层直接映射 character.cue（不进 LLM）；silent 仅更新内部状态。

时间一律经注入的 clock（epoch ms）获取——门控/冷却/过期全部可测。
"""
