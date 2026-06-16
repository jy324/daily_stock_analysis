# Fork 能力增强总览

本文件汇总本 fork 在上游股票智能分析系统基础上新增的功能，作为"这个 fork 多了什么"
的统一索引。主线目标：把系统从"生成观点"升级为**可验证、可执行、可回测、可复盘的决策系统**，
并补齐数据源与运行过程的可观测性。

所有新增能力遵循同一原则：**不配置也可运行，配置后增强**；新数据源/新表/新字段一律
追加式，默认不改变既有分析主流程、报告渲染和客户端契约。

---

## 一、A 股情报扩展（默认关闭，gate 开启后增强）

围绕 `a-stock-data` 正式 facade 接入 A 股资金面 / 事件面证据，统一缓存、快照与降级。

- Provider 适配与多级 fallback、内存+文件缓存、损坏缓存隔离、容量清理、single-flight。
- 唯一槽位快照表（append-only revision，自动迁移旧 SQLite 快照、补建索引）。
- 能力：分钟/日资金流、板块资金流、个股与市场龙虎榜、公告、解禁。
- A 股确定性评分契约（默认关闭，低覆盖不出分）。
- 大盘复盘 payload 注入可选资金证据 section；Agent 工具（只读，禁止发起 refresh）。

**主要 API**：`GET /api/v1/market/ashare/status`、`/market/ashare/sector-flow`、
`/stocks/{code}/capital-flow`、`/stocks/{code}/risk-events`、`POST /market/ashare/review`
（支持 `Idempotency-Key`）。

**配置**：`ASHARE_INTELLIGENCE_ENABLED`（默认 `false`）、`ASHARE_PROVIDER_PRIORITY`、
`ASHARE_CACHE_DIR`、`ASHARE_SCORING_ENABLED`、`ASHARE_CONFIG_FILE`。

详见 [A 股情报接入](ashare-intelligence-integration.md)。

---

## 二、结构化决策信号 DecisionSignal（workflow B）

把自由文本 `operation_advice` 升级为可执行、可回测、可生命周期推进的结构化信号。

- **B.1 生成与持久化**：每次分析在保存历史后生成 `DecisionSignal`（方向、八态动作、入场
  类型 precise/zone/market/none、入场价/区间、止损止盈、有效期、`quality_constraints`、
  生命周期状态），追加表 `decision_signals`，生成失败不影响主流程。
- **B.2 生命周期状态机 + 日终推进**：前向状态机
  `generated → waiting_entry → entered → target_hit | stop_hit | expired | invalidated`
  （止损优先、停牌跳过、记录入场/出场价与状态流转历史），挂入 `--schedule` 日终任务，
  单只失败隔离。
- **B.3 回测优先消费结构化信号**：方向/仓位直接取自信号、入场按真实成交模型（限价/区间/
  市价含跳空，未触发记为未入场零收益）；无信号的旧记录回退关键词推断法，`signal_based`
  区分来源。
- **查询 / 管理 API**：`GET /api/v1/signals`（按 code/market/action/state/source 过滤分页、
  `active_only`）、`GET /api/v1/signals/latest?code=`（个股最新活跃信号）、
  `GET /api/v1/signals/{id}`、`PATCH /api/v1/signals/{id}/state`（人工状态流转，复用同一
  前向状态机，非法转移 409、目标不存在 404）。详见 [决策信号 API](decision-signals-api.md)。

---

## 三、数据质量决策策略（workflow C）

把数据质量从"展示"升级为"决策约束"。

- **C.1 Quality Policy Engine**：按只读数据质量概览（数据块 status + overall_score）与市场
  阶段评估 YAML 策略，产出结构化 `QualityPolicyDecision`，动作含 `prohibit_precise_entry` /
  `cap_confidence` / `downgrade_event_signal` / `observation_only` / `require_alert_confirmation`。
  `QUALITY_POLICY_FILE` 缺失或解析失败即关闭全部策略。
- **C.2 策略约束信号字段**：行情降级→精确入场降级为 `none`；核心块 ≥2 降级→仅观察
  （`direction=neutral`）；置信度按最紧上限收敛；命中策略与影响记入 `quality_constraints`。

**配置**：`QUALITY_POLICY_FILE`（默认 `config/quality_policies.yaml`）。
详见 [数据质量策略引擎](quality-policy-engine.md)。

---

## 四、回测 / 模型评估 2.0（workflow D，v2 opt-in）

`BACKTEST_ENGINE_VERSION=v1` 为默认（毛收益、不计成本/基准），`v2` 显式开启增强能力，
v1 历史数据隔离可查。

- **D.2 版本归因元数据**：`analysis_history` 追加 `model_used` / `prompt_version_hash` /
  `strategy_version`（追加列，旧行视为 unknown）。
- **D.1a 风险/收益指标**：最大回撤、波动率、夏普、索提诺、卡玛、盈利因子、盈亏比、持有期
  统计（基于已完成交易模拟收益序列，确定性公式）。
- **D.1b v2 交易成本模型**：佣金双边 + 印花税卖出单边 + 滑点，对已成交多头往返计提净收益，
  记 `cost_pct`。配置 `BACKTEST_COMMISSION_RATE` / `BACKTEST_STAMP_TAX_RATE` /
  `BACKTEST_SLIPPAGE_BP`。
- **D.1c 基准超额 + 不可成交标记**：按市场映射基准指数（A股→沪深300，
  `config/benchmark_config.yaml` 可配）算 `excess_return_pct`；入场/出场落在涨跌停封板
  （一价无区间）记 `unfillable`；指数不可得记 NULL 不阻断。
- **D.3 版本归因查询 + API**：`GET /api/v1/backtest/performance/by/{dimension}`
  （dimension ∈ model / prompt / strategy，追加式，旧响应不变，NULL 归 `unknown`）。
- **v2 可交易性汇总指标**：基准覆盖率、平均超额收益、alpha 命中率、平均交易成本、不可成交率、
  可成交胜率（剔除封板不可成交后的胜率），聚合进汇总并经 `PerformanceMetrics`/归因 API 暴露。

per-result 字段（`signal_based` / `cost_pct` / `benchmark_code` / `benchmark_return_pct` /
`excess_return_pct` / `unfillable`）经 `BacktestResultItem` 暴露并同步 Web 类型。

---

## 五、可观测性与稳定性

- **运行流快照 Run Flow**：分析任务与历史报告的统一运行流（lanes / nodes / edges / events /
  summary，summary 含 elapsed_ms、bottleneck、failed_attempts、fallback_count、model 等），
  API `GET /api/v1/analysis/tasks/{task_id}/flow`、`GET /api/v1/history/{record_id}/flow`，
  Web 端有运行流视图入口。
- **运行诊断 run_diagnostics**：provider / LLM / 通知 / 历史持久化的组件级状态与脱敏
  copy-text，API `GET /api/v1/history/{record_id}/diagnostics`。详见
  [运行诊断](run-diagnostics-p0.md)。
- **数据源健康聚合 API**：`GET /api/v1/providers/health`，聚合最近窗口已持久化的 provider
  调用诊断（成功率/降级/陈旧/平均延迟/最近错误）与实时熔断器只读状态（closed/open/half_open +
  剩余冷却），只读、无新增存储。详见 [数据源健康](provider-health.md)。
- **依赖治理**：暂时锁定 `fastapi<0.137.0`（0.137 在导入期拒绝 `history.py` 空路径路由），
  待迁移空路径路由后放宽上限。

---

## 配置开关一览

| 开关 | 默认 | 作用 |
| --- | --- | --- |
| `ASHARE_INTELLIGENCE_ENABLED` | `false` | A 股情报扩展总门禁 |
| `ASHARE_SCORING_ENABLED` | `false` | A 股确定性评分 |
| `QUALITY_POLICY_FILE` | `config/quality_policies.yaml` | 数据质量策略文件；缺失=全关 |
| `STRATEGY_VERSION` | `v1` | 归因用策略版本标记 |
| `BACKTEST_ENGINE_VERSION` | `v1` | `v2` 开启成本/基准/不可成交/可交易性指标 |
| `BACKTEST_COMMISSION_RATE` / `BACKTEST_STAMP_TAX_RATE` / `BACKTEST_SLIPPAGE_BP` | A股默认费率 | v2 成本模型 |

均为"不配置也可运行，配置后增强"。

---

## 功能与 PR 对照

| PR | 主题 |
| --- | --- |
| #1 | A 股情报就绪 gate 加固 |
| #2 / #3 | DecisionSignal 生成持久化 / 生命周期状态机 + 日终推进（B.1 / B.2） |
| #4 | 回测优先消费结构化信号（B.3） |
| #5 / #6 | 数据质量策略引擎 / 策略约束信号字段（C.1 / C.2） |
| #7 | 版本归因元数据（D.2） |
| #9 / #10 | 风险指标 / v2 交易成本模型（D.1a / D.1b） |
| #11 | 归因查询 + API（D.3） |
| #12 | v2 基准超额 + 封板不可成交 + 字段暴露（D.1c） |
| #13 | 锁定 `fastapi<0.137`（止血） |
| #14 | 数据源健康聚合 API |
| #15 | 决策信号查询/管理 API |
| #16 | 回测 v2 可交易性汇总指标 |

> 上游同步：#8 选择性并入 4 个独立上游功能（运行流、Tencent 直连 fetcher、AlphaSift 等），
> 搁置与本地 `DecisionSignal` 路线冲突的上游 DecisionSignal 两提交。
