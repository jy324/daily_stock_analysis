---
name: ashare-risk-events
description: Inspect A-share risk event evidence such as announcements, lockups, and dragon-tiger signals through deterministic service output.
default-active: false
default-router: false
user-invocable: true
required-tools: get_ashare_stock_capital_flow
---

# A 股风险事件

用于用户明确要求检查 A 股个股风险事件、公告、解禁或龙虎榜压力时调用。默认不参与自动路由。

## Usage

```text
/ashare-risk-events <code> [trade_date]
```

## Instructions

- 优先遵循仓库根目录 `AGENTS.md`。
- 当前运行时只暴露个股资金流 Agent 工具；公告、解禁和风险事件 taxonomy 后续接入 API/service 后再扩展工具。
- 风险事件必须使用确定性 taxonomy 和去重依据：公告 ID、规范化 URL、标题 hash、`code+date+event_type`。
- 不把主力资金解释为真实机构持仓，不把缺失值解释为 0。
- 历史不足时持续性结论返回 `null` 并说明 `insufficient_history`。
- 未接入的风险维度应明确标为未覆盖，不使用 LLM 文本补造结构化事件。
