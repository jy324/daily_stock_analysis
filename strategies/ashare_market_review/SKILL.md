---
name: ashare-market-review
description: Use A-share intelligence evidence when reviewing the CN market.
default-active: false
default-router: false
user-invocable: true
required-tools: get_ashare_market_intelligence
---

# A 股大盘复盘

用于用户明确要求基于 A 股情报证据做大盘复盘时调用。默认不参与自动路由。

## Instructions

- 优先遵循仓库根目录 `AGENTS.md`。
- 使用确定性市场情报结果解释板块资金与情绪，不重复罗列系统已经注入的表格。
- 对 provider 不可用、数据为空或覆盖不足的情况明确降级说明。
- 不扩大到评分、自动策略路由或历史回测结论。
- 输出应区分客观证据和分析解读。
