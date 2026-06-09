---
name: ashare-stock-capital-flow
description: Inspect A-share stock capital-flow evidence with source, coverage, and snapshot metadata.
default-active: false
default-router: false
user-invocable: true
required-tools: get_ashare_stock_capital_flow
---

# A 股个股资金流

用于用户明确要求检查 A 股个股资金流证据时调用。默认不参与自动路由。

## Instructions

- 优先遵循仓库根目录 `AGENTS.md`。
- 只解释 `get_ashare_stock_capital_flow` 返回的结构化结果。
- 必须保留 `lookback`、`data_status`、`source`、`coverage`、`cache_hit`、`snapshot_id`。
- 历史不足时说明 `insufficient_history` 或覆盖不足，不伪造连续性。
- 不把主力资金流解释为真实机构持仓。
