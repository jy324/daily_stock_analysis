# 数据源健康聚合 API

`GET /api/v1/providers/health` 提供数据源（行情/资讯 provider）的系统级可观测视图，
回答"最近一段时间哪个 provider 在降级、为什么报告质量下降、当前哪个源被熔断"。

该接口是**只读聚合**，不引入新存储、不改变分析主流程：

- **历史调用聚合**：每次分析的逐次 provider 调用诊断（`ProviderRun`：成功/延迟/降级/陈旧/错误）
  已持久化在 `AnalysisHistory.context_snapshot` 的 `diagnostics.provider_runs` 中。本接口按时间
  窗口聚合这些记录。
- **实时熔断器状态**：内存中的实时行情 / 筹码熔断器（`data_provider/realtime_types.py`）暴露
  每个源的 `closed` / `open` / `half_open` 状态。读取采用只读快照 `CircuitBreaker.describe()`，
  不会触发任何状态转移（与 `is_available` 的副作用区分开）。

## 请求

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `window_hours` | int | 24 | 聚合时间窗口（小时），范围 1–168 |

## 响应

```json
{
  "window_hours": 24,
  "generated_at": "2026-06-15T10:00:00",
  "records_scanned": 42,
  "total_provider_runs": 118,
  "providers": [
    {
      "provider": "efinance",
      "attempts": 60,
      "success_count": 57,
      "fallback_count": 3,
      "stale_count": 1,
      "success_rate_pct": 95.0,
      "fallback_rate_pct": 5.0,
      "stale_rate_pct": 1.67,
      "avg_latency_ms": 180,
      "last_error_type": "Timeout",
      "last_seen_at": "2026-06-15T09:58:12"
    }
  ],
  "circuit_breakers": [
    {
      "breaker": "realtime",
      "source": "akshare",
      "state": "open",
      "failures": 3,
      "seconds_since_failure": 42,
      "cooldown_remaining_seconds": 258
    }
  ]
}
```

字段说明：

- `records_scanned`：窗口内含 provider 诊断的分析记录数。
- `total_provider_runs`：参与聚合的 provider 调用次数。
- `providers`：按调用次数（`attempts`）降序，provider 名为稳定次序键。
  - `fallback_count`：携带 `fallback_from` 或 `fallback_to` 的调用次数。
  - `stale_count`：`stale_seconds` 为正数的调用次数。
  - `avg_latency_ms`：有延迟样本时的平均值，否则 `null`。
- `circuit_breakers`：`breaker` 分组为 `realtime` / `chip`；`cooldown_remaining_seconds` 仅在
  `open` 状态给出（到期为 0）。

## 边界与降级

- 没有命中诊断或历史为空时，`providers` 与 `circuit_breakers` 返回空数组，不报错。
- 读取历史或某个熔断器异常时记 warning 并跳过，保证观测面不因单点失败而中断。
- 熔断器状态为内存态，仅反映当前运行进程；历史聚合则来自持久化记录。
