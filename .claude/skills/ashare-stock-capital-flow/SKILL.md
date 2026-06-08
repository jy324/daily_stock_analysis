---
name: ashare-stock-capital-flow
description: Query A-share stock-level capital flow evidence through the DSA A-share intelligence service.
default-active: false
default-router: false
user-invocable: true
required-tools: get_ashare_stock_capital_flow
---

# A 股个股资金流

用于用户明确要求查看 A 股个股资金流、近端主力净流入或资金持续性证据时调用。默认不参与自动路由。

## Usage

```text
/ashare-stock-capital-flow <code> [trade_date] [lookback]
```

## Instructions

- 优先遵循仓库根目录 `AGENTS.md`。
- 仅在运行时 capability 显示 A 股情报和 Agent tools 均开启时使用。
- 调用 `get_ashare_stock_capital_flow`，不要直接导入 provider package 或访问外部数据源。
- Agent 调用不允许 `refresh=true`；`lookback` 不超过 service/tool 硬上限。
- 返回中必须保留 `snapshot_id`、`cache_hit`、`data_status`、`coverage`、`source` 和 provider 原始结构化数据。
- `""`、`"-"`、`None` 不转成 0；金额必须保留 provider 单位或显式 `unit`。
- 资金流只能表述为 provider 指标，不解释为真实机构持仓。
