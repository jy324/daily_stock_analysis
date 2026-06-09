---
name: ashare-risk-events
description: Inspect A-share risk event evidence such as announcements, lockups, and dragon-tiger signals.
default-active: false
default-router: false
user-invocable: true
required-tools: get_ashare_stock_risk_events
---

# A 股风险事件

用于用户明确要求检查 A 股个股风险事件、公告、解禁或龙虎榜压力时调用。默认不参与自动路由。

## Instructions

- 优先遵循仓库根目录 `AGENTS.md`。
- 使用 `get_ashare_stock_risk_events` 返回的确定性 taxonomy 和去重结果。
- 返回事件必须匹配请求股票代码；发现 provider 返回其他股票数据时视为不可用或已过滤。
- 不把缺失事件解释为没有风险，只能说明当前覆盖范围内未返回事件。
- 不使用 LLM 文本补造结构化公告、解禁或龙虎榜事件。
