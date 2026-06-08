---
name: ashare-market-review
description: Generate or inspect an A-share market review with deterministic A-share intelligence evidence when the feature gate is enabled.
default-active: false
default-router: false
user-invocable: true
required-tools: get_ashare_market_intelligence
---

# A 股大盘复盘证据

用于用户明确要求 A 股大盘复盘接入资金与情绪证据时调用。默认不参与自动路由。

## Usage

```text
/ashare-market-review [trade_date]
```

## Instructions

- 优先遵循仓库根目录 `AGENTS.md`。
- 复盘仅在 `region == "cn"` 且 A 股情报 gate 开启时附加结构化证据。
- 客观证据使用 `ashare_capital_evidence` section；LLM 解读使用 `llm_interpretation` section。
- 不依赖 LLM 标题正则插入资金表格，不让 LLM 计算金额、排名或持续性。
- `partial`、`stale`、`empty` 必须在报告证据中明示。
- 若 capability 显示关闭，按原大盘复盘路径处理，不探测 snapshot/data endpoint。
