# 决策信号查询 / 管理 API

结构化决策信号 `DecisionSignal`（方向、入场类型、止盈止损、有效期、生命周期状态）
此前由分析流程生产、持久化并被回测消费，但缺少查询与人工管理入口。本组 API 在
**不改动信号数据模型**的前提下暴露查询与人工状态管理能力。

所有写操作复用既有前向状态机 `SignalStateMachine`，非法状态流转一律拒绝（与日终
自动推进同一套校验），不做静默 no-op。

## 端点

### `GET /api/v1/signals`
按条件分页查询，最新优先（`generated_at`、`id` 降序）。

| 参数 | 说明 |
| --- | --- |
| `code` | 股票代码 |
| `market` | 市场 |
| `action` | 八态动作（buy/add/hold/sell/reduce/watch/avoid/alert） |
| `state` | 生命周期状态；**持仓中 = `entered`** |
| `source` | `llm_structured` / `normalized_fallback` |
| `active_only` | 仅未终结信号（排除 target_hit/stop_hit/expired/invalidated） |
| `limit` | 1–500，默认 100 |
| `offset` | 默认 0 |

响应：`{ total, limit, offset, items: [DecisionSignalItem] }`，`total` 为未分页匹配总数。

### `GET /api/v1/signals/latest?code={code}`
返回某只股票最近一条**未终结**信号（当前可执行信号）；无则 404。

### `GET /api/v1/signals/{signal_id}`
按主键返回单条信号；不存在 404。

### `PATCH /api/v1/signals/{signal_id}/state`
人工更新生命周期状态。

请求体：`{ "state": "<目标状态>", "note": "<可选备注>" }`

合法转移（前向）：

```
generated     -> waiting_entry | entered | expired | invalidated
waiting_entry -> entered | expired | invalidated
entered       -> target_hit | stop_hit | expired | invalidated
```

- 目标信号不存在：`404`
- 非法状态流转：`409`
- 成功：返回更新后的 `DecisionSignalItem`；状态流转写入 `state_history`（`source=manual`，
  含 `from`/`to`/`at`/`note`）。转入 `entered` 自动补 `entered_date`，转入终态自动补 `closed_date`
  （仅在原值为空时）。

## DecisionSignalItem 字段
包含信号标识/溯源、决策（direction/action/仓位/置信度）、入场出场价、有效期、约束
（invalidation_conditions/applicable_phases/quality_constraints）、生命周期（state、
state_history、entered/closed 日期与价格）。详见 `api/v1/schemas/decision_signal.py`。
