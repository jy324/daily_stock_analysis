---
name: ashare-market-intelligence
description: Query A-share market-level capital and sentiment evidence through the DSA A-share intelligence service.
default-active: false
default-router: false
user-invocable: true
required-tools: get_ashare_market_intelligence
---

# A 股大盘情报

用于用户明确要求查看 A 股市场级资金、板块资金流或情绪证据时调用。默认不参与自动路由。

## Usage

```text
/ashare-market-intelligence [trade_date] [limit]
```

## Instructions

- 优先遵循仓库根目录 `AGENTS.md`。
- 仅在运行时 capability 显示 A 股情报和 Agent tools 均开启时使用。
- 调用 `get_ashare_market_intelligence`，不要直接导入 provider package 或访问外部数据源。
- 不传 `refresh=true`；Agent 工具必须复用 service 的缓存、限流、预算和熔断语义。
- 返回中必须保留 `snapshot_id`、`cache_hit`、`data_status`、`coverage`、`source` 和 provider 原始结构化数据。
- `empty` 是合法空结果；`unavailable` 才代表查询不可用。
- 不把缺失值解释为 0，不让 LLM 计算金额、排名、持续性或机构净额。
