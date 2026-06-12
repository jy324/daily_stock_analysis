# 数据质量决策策略引擎（Quality Policy Engine）

把数据质量从“仅展示”升级为对决策的硬约束。引擎根据**只读**的数据质量概览
（各数据块 `status` + `overall_score`）和市场阶段，产出结构化的
`QualityPolicyDecision`，供下游（prompt 注入、决策护栏、信号生成、告警）消费。

本阶段（C.1）只落地**框架 + 评估**：引擎是确定性、无副作用的，只“生产”决策，
消费侧接线在后续工作流中单独接入，便于隔离评审。

## 入口

- Schema：`src/schemas/quality_policy.py`
- Service：`src/services/quality_policy_service.py`
  - `QualityPolicyService(policy_file=None).evaluate(overview, phase=None) -> QualityPolicyDecision`
  - `evaluate_quality_policies(overview, *, phase=None, policy_file=None)`（便捷函数）
- 策略文件：`config/quality_policies.yaml`
- 配置项：`QUALITY_POLICY_FILE`（默认 `config/quality_policies.yaml`）

## “不配置也可运行”

- 删除或清空策略文件 = 关闭全部策略，分析主流程不受影响。
- 解析失败、顶层格式非法、单条策略无效时**干净降级**（记录日志并跳过），
  不会把异常抛进分析链路。
- 文件按 mtime + size 缓存，修改后下次评估自动重载。

## 策略语义

每条策略 = `trigger`（触发条件）+ `actions`（命中后施加的动作）。

`trigger` 下所有给定条件需**同时满足**（逻辑 AND）；trigger 为空则**永不触发**
（避免误配成 match-all）。可用条件：

| 条件 | 含义 |
| --- | --- |
| `overall_score_below: <int>` | `overall_score` 已知且严格小于阈值时满足；**未知分数不触发** |
| `block_status_in: {<block>: [statuses]}` | 指定数据块当前 `status` 命中列表时满足 |
| `min_degraded_core_blocks: <int>` | 降级的核心块（`quote`/`daily_bars`/`technical`）数量 ≥ 阈值 |
| `phase_in: [premarket, intraday, ...]` | 市场阶段命中列表时满足 |

“降级”状态：`stale` / `fallback` / `missing` / `fetch_failed` / `partial` / `estimated`。

可用 `action.type`：

| 动作 | 含义 | 消费方（后续接入） |
| --- | --- | --- |
| `prohibit_precise_entry` | 禁止精确入场价 | 信号生成（C.2 将 `entry_type` 收敛为区间/无） |
| `cap_confidence` | `params.max_level: high\|medium\|low`，取**最紧**上限 | 决策护栏 |
| `downgrade_event_signal` | 事件驱动信号降级 | 信号/报告 |
| `observation_only` | 仅输出观察报告，不出可执行买卖建议 | 决策护栏 |
| `require_alert_confirmation` | 告警需二次确认 | 告警链路 |

## `QualityPolicyDecision` 消费接口

- `is_empty` / `matched_policy_ids` / `reasons`
- 布尔便捷属性：`prohibit_precise_entry` / `observation_only` / `downgrade_event_signal` / `require_alert_confirmation`
- `confidence_cap`：跨所有命中策略的**最紧** confidence 上限（`low` < `medium` < `high`）
- `to_dict()`：JSON-safe 投影，可持久化进 `context_snapshot` 并经 API 暴露

## 默认策略（`config/quality_policies.yaml`）

- `quote` ∈ {stale, fallback, fetch_failed} → `prohibit_precise_entry`
- `fundamentals` ∈ {fetch_failed, missing} → `cap_confidence(medium)`
- `news` ∈ {missing, partial} → `downgrade_event_signal`
- 降级核心块 ≥ 2 → `observation_only`

> 告警数据源 fallback → `require_alert_confirmation` 的策略待告警链路接入后再启用，
> 其输入不在个股分析概览中；框架已支持该 action 类型。
