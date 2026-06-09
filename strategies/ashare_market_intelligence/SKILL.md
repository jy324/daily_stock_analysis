---
name: ashare-market-intelligence
description: Use deterministic A-share market intelligence evidence for sector flow and market dragon-tiger context.
default-active: false
default-router: false
user-invocable: true
required-tools: get_ashare_market_intelligence
---

# A 股市场情报

用于用户明确要求查看 A 股市场层面的板块资金、龙虎榜或市场情报证据时调用。默认不参与自动路由。

## Instructions

- 优先遵循仓库根目录 `AGENTS.md`。
- 只使用 `get_ashare_market_intelligence` 返回的结构化结果，不从 LLM 文本补造金额、排名或来源。
- 必须保留并解释 `data_status`、`source`、`coverage`、`cache_hit`、`snapshot_id`。
- `partial`、`stale`、`empty` 和 `unavailable` 都是有效状态；缺失数据不解释为 0。
- 不把资金流向解释为真实机构持仓，只能表述为 provider 返回的资金流证据。
