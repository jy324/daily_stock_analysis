# A 股情报扩展集成说明

## 决策

A 股情报扩展默认关闭，DSA 应用层仅暴露能力探测和运行时门禁。关闭时不导入 `astock_data`、不创建 provider client、不访问缓存目录、不写数据库快照，也不改变现有大盘复盘、报告、Agent 工具和调度行为。

## 配置边界

`.env` 只保留顶层开关和路径：

- `ASHARE_INTELLIGENCE_ENABLED=false`
- `ASHARE_PROVIDER_PRIORITY=astock_data`
- `ASHARE_CACHE_DIR=./data/ashare_cache`
- `ASHARE_CONFIG_FILE=config/ashare_intelligence.yaml`
- `ASHARE_SCORING_ENABLED=false`

报告、Agent tools、评分、TTL、预算和后续细项放在 `config/ashare_intelligence.yaml`，避免一次性膨胀 `.env`。评分需要 `.env` 顶层开关和 YAML `scoring.enabled` 同时开启才会对外显示可用。

## API 语义

`GET /api/v1/capabilities` 是轻量能力探测端点，不触发 provider 请求。返回：

- `ashare_intelligence.enabled`
- `ashare_intelligence.provider_installed`
- `ashare_intelligence.report_enabled`
- `ashare_intelligence.agent_tools_enabled`
- `ashare_intelligence.scoring_enabled`

`scoring_enabled` 仅表示确定性评分 service 可用；第一版评分默认关闭，不接入 LLM 文本，也不用于历史回测。

A 股情报路由默认注册，但运行时门禁：

- 功能关闭：`403 feature_disabled`
- package 缺失：`503 dependency_unavailable`
- 后续 provider 熔断：`503 provider_unavailable`
- 后续 refresh 限流：`429 rate_limited`
- 大盘复盘已运行：`409 duplicate_market_review`

首批 API 路由：

- `GET /api/v1/market/ashare/status`
- `GET /api/v1/market/ashare/sector-flow`
- `GET /api/v1/stocks/{code}/capital-flow`
- `GET /api/v1/stocks/{code}/risk-events`
- `POST /api/v1/market/ashare/review`

`sector-flow` 的 `limit` 硬上限为 50，`capital-flow` 和 `risk-events` 的 `lookback` 硬上限为 120。`refresh=true` 只透传 service，不绕过 feature gate、provider dependency 检查或 provider 限流。

`risk-events` 聚合公告、解禁和个股龙虎榜结构化记录，统一输出 `announcement`、`lockup_expiry`、`dragon_tiger` taxonomy，并按公告 ID、规范化 URL、标题 hash、`code+date+event_type` 去重。全部来源不可用时返回 `503 provider_unavailable`；部分来源成功时返回 `200 status=partial`。

`POST /api/v1/market/ashare/review` 返回 `202 Accepted`，复用现有大盘复盘后台任务队列和共享 lock，固定以 CN 大盘复盘运行。支持 `Idempotency-Key`：相同 key 会派生稳定 task id，已有任务直接返回原 `task_id/trace_id`，不会重复提交。

## Agent Tools 边界

Agent A 股工具默认不注册，只有 `ASHARE_INTELLIGENCE_ENABLED=true` 且 `config/ashare_intelligence.yaml` 中 `agent_tools.enabled=true` 时注册。当前工具：

- `get_ashare_market_intelligence`
- `get_ashare_stock_capital_flow`

Agent 工具禁止刷新 provider：即使传入 `refresh=true`，handler 也按 `refresh=false` 调用 service。市场查询 `limit` 硬上限 50，个股资金流 `lookback` 硬上限 120。工具返回包含 `snapshot_id`、`cache_hit`、`data_status`、`coverage`、`source` 和 `data`。

## Web 边界

Web 新增 `capabilitiesApi.getCapabilities()`，从 `GET /api/v1/capabilities` 读取运行时能力，不通过 snapshot/data endpoint 探测功能可用性。

大盘复盘详情将 `ashare_capital_evidence` section 从正文解读中抽出，放入默认折叠的“输入证据”区域；`llm_interpretation` 保持在正文 sections 中。

## Provider 边界

DSA 顶层不直接 import `astock_data`。provider factory 通过 `import_module("astock_data")` 延迟导入，且 route、tool、service import 阶段不得创建 client 或访问外部网络。

第一版 provider manager 的读取顺序为：运行时 gate、参数组装、内存缓存、文件缓存、provider 请求、写回缓存、provider 失败时 stale fallback。关闭状态下 manager 不访问缓存目录、不创建 provider。

缓存 key 包含 provider、capability、code、trade_date、market_phase、as_of_bucket、schema_version 和 query params。`refresh=true` 只绕过 fresh cache 命中，不绕过 provider gate、限流或失败降级；provider 返回的 `empty` 会保留为合法空结果，不降级成 `unavailable`。

## Snapshot 边界

DB snapshot 第一版仅新增 `ashare_intelligence_snapshot` 表和 repository，不修改既有表列。唯一槽位为 `(snapshot_type, trade_date, as_of_bucket, schema_version, provider_set)`；同槽位重复写入会保留 `snapshot_id` 并递增 `revision`。回滚代码时允许保留该孤立表。

## 市场复盘接入

`MarketAnalyzer` 仅在 `region == "cn"` 且 `ASHARE_INTELLIGENCE_ENABLED=true` 时构建 A 股情报 service。关闭时市场复盘 payload、报告正文、历史写入和通知渲染保持原行为。

开启后，市场复盘结构化 payload 可追加 `ashare_intelligence.capital_evidence`，并将资金情绪拆成固定 section：`ashare_capital_evidence`（程序生成的客观数据表）和 `llm_interpretation`（LLM 原解释）。程序只格式化 provider 返回的金额和排名，不让 LLM 计算金额、排名或持续性；`partial`、`stale`、`empty` 状态会保留在证据表中。

`a-stock-data/SKILL.md` 后续应收敛为薄说明层，只指导调用 `astock_data` package，不承载运行时复制或 `exec` 的网络代码。

## 评分边界

A 股评分第一版默认关闭。`AShareScoringService` 只接受结构化特征，输出固定包含 `score`、`confidence`、`coverage`、`version`、`features`、`warnings` 和 `risk_pressure_score`。当 `coverage < 60%` 时 `score=null`；`risk_pressure_score` 分数越高表示风险压力越大。3/5 日等持续性指标必须来自真实历史样本，历史不足时返回 `null` 并附加 `insufficient_history`，不使用当日分钟数据伪造多日持续性。
