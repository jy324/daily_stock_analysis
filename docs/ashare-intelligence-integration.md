# A 股情报扩展集成说明

## 决策

A 股情报扩展默认关闭，DSA 应用层仅暴露能力探测和运行时门禁。关闭时不导入 `astock_data`、不创建 provider client、不访问缓存目录、不写数据库快照，也不改变现有大盘复盘、报告、Agent 工具和调度行为。

## 配置边界

`.env` 只保留顶层开关和路径：

- `ASHARE_INTELLIGENCE_ENABLED=false`
- `ASHARE_PROVIDER_PRIORITY=astock_data`
- `ASHARE_CACHE_DIR=./data/ashare_cache`
- `ASHARE_CACHE_MAX_FILES=1000`
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
- 相同 `Idempotency-Key` 携带不同请求体：`409 idempotency_conflict`

首批 API 路由：

- `GET /api/v1/market/ashare/status`
- `GET /api/v1/market/ashare/sector-flow`
- `GET /api/v1/stocks/{code}/capital-flow`
- `GET /api/v1/stocks/{code}/risk-events`
- `POST /api/v1/market/ashare/review`

`sector-flow` 的 `limit` 硬上限为 50，`capital-flow` 和 `risk-events` 的 `lookback` 硬上限为 120。默认日期按 `Asia/Shanghai` 解析；显式 `trade_date` 必须是合法 `YYYY-MM-DD`，未来日期返回 `422 future_trade_date`。`refresh=true` 只透传 service，不绕过 feature gate、provider dependency 检查或 provider 限流。
显式 `trade_date` 还会复用现有 A 股交易日历校验；非交易日返回 `422 non_trading_day`。交易日历依赖不可用时沿用现有 fail-open 语义。

`risk-events` 聚合公告、解禁和个股龙虎榜结构化记录，统一输出 `announcement`、`lockup_expiry`、`dragon_tiger` taxonomy，并按公告 ID、规范化 URL、标题 hash、`code+date+event_type` 去重。解禁等可能来自全市场列表的数据会按请求股票代码严格过滤。全部来源不可用时返回 `503 provider_unavailable`；部分来源成功时返回 `200 status=partial`。

`POST /api/v1/market/ashare/review` 返回 `202 Accepted`，复用现有大盘复盘后台任务队列和共享 lock，固定以 CN 大盘复盘运行。支持 `Idempotency-Key`：相同 key 会派生稳定 task id，并保存规范化请求体 hash；相同 key + 相同请求体会返回原 `task_id/trace_id`，相同 key + 不同请求体返回 `409 idempotency_conflict`。

## Agent Tools 边界

Agent A 股工具默认不注册，只有 `ASHARE_INTELLIGENCE_ENABLED=true` 且 `config/ashare_intelligence.yaml` 中 `agent_tools.enabled=true` 时注册。当前工具：

- `get_ashare_market_intelligence`
- `get_ashare_stock_capital_flow`
- `get_ashare_stock_risk_events`

Agent 工具禁止刷新 provider：即使传入 `refresh=true`，handler 也按 `refresh=false` 调用 service。市场查询 `limit` 硬上限 50，个股资金流和风险事件 `lookback` 硬上限 120。工具返回包含 `snapshot_id`、`cache_hit`、`data_status`、`coverage`、`source` 和 `data`。

Agent 每次 `run` / `chat` 会从 `agent_tools.market_query_budget` 和 `agent_tools.stock_query_budget` 创建请求级预算上下文；预算通过 `contextvars` 传入并发工具调用，不使用模块全局计数。市场工具消耗 market 预算，个股资金流和个股风险事件共享 stock 预算；超限时工具返回 `error=ashare_query_budget_exceeded`，不会再调用 provider。

DSA runtime skills 位于 `strategies/ashare_*/SKILL.md`，默认不激活、不参与默认路由，仅在用户显式选择时注入。`.claude/skills/ashare-*` 保留为开发辅助 skill，不作为产品 runtime skill 的唯一入口。

## Web 边界

Web 新增 `capabilitiesApi.getCapabilities()`，从 `GET /api/v1/capabilities` 读取运行时能力，不通过 snapshot/data endpoint 探测功能可用性。

大盘复盘详情将 `ashare_capital_evidence` section 从正文解读中抽出，放入默认折叠的“输入证据”区域；`llm_interpretation` 保持在正文 sections 中。若 payload 包含 `ashare_intelligence.capital_evidence`，Web 会展示 status、provider、as_of、cache、coverage、snapshot_id、revision 和 warnings 等证据元数据，避免只呈现 Markdown 表格。

## Provider 边界

DSA 顶层不直接 import `astock_data`。provider factory 通过 `import_module("astock_data")` 延迟导入，并只依赖公开 facade `astock_data.AStockDataClient`；route、tool、service import 阶段不得创建 client 或访问外部网络。`requirements.txt` 使用完整 commit SHA 固定 `a-stock-data` 依赖，不依赖可移动 `main` 或 tag。

provider manager 的读取顺序为：运行时 gate、参数组装、按 provider priority 逐个检查内存/文件缓存、按 cache key single-flight 调用 provider、成功后写回缓存、所有 provider 失败时返回 stale fallback。关闭状态下 manager 不访问缓存目录、不创建 provider。损坏文件缓存会隔离为 `.corrupt-*` 文件，避免重复读取；写入缓存后按 `ASHARE_CACHE_MAX_FILES` 清理最旧文件。

缓存 key 包含 provider、capability、code、trade_date、market_phase、as_of_bucket、schema_version 和 query params。`refresh=true` 只绕过 fresh cache 命中，不绕过 provider gate、限流或失败降级；provider 返回的 `empty` 会保留为合法空结果，不降级成 `unavailable`。若 package 固定返回超过请求 lookback 的历史资金流，adapter 会按交易日期倒序裁剪，并在 coverage 中返回请求与实际数量。

## Snapshot 边界

DB snapshot 使用 append-only repository。逻辑槽位由 `(snapshot_type, trade_date, as_of_bucket, schema_version, provider_set_hash)` 标识，`provider_set` 会排序后写入 `provider_set_json` 并计算 hash；同槽位重复写入会新增一行、递增 `revision`，查询默认返回最新 revision。SQLite 启动时会将旧的同槽位覆盖表结构升级为 append-only 结构，并回填 provider set hash；历史覆盖掉的旧 revision 无法从旧表恢复。Service 层默认注入 repository 并在成功、partial、empty 或 stale 查询后写入快照，保存成功后回填 `snapshot_id` 与 `snapshot_revision`。回滚代码时允许保留该孤立表。

## 市场复盘接入

`MarketAnalyzer` 仅在 `region == "cn"` 且 `ASHARE_INTELLIGENCE_ENABLED=true` 且 `config/ashare_intelligence.yaml` 的 `report.enabled=true` 时构建 A 股情报 service。关闭时市场复盘 payload、报告正文、历史写入和通知渲染保持原行为。

开启后，市场复盘在 LLM 生成前获取一次 `sector_fund_flow` 证据，并将压缩摘要注入 prompt；结构化 payload、Markdown section 和历史快照复用同一份证据，不在 `build_market_review_payload()` 阶段再次请求 provider。payload 可追加 `ashare_intelligence.capital_evidence`，并将资金情绪拆成固定 section：`ashare_capital_evidence`（程序生成的客观数据表）和 `llm_interpretation`（LLM 对同一份证据的解释）。程序只格式化 provider 返回的金额和排名，不让 LLM 计算金额、排名或持续性；`partial`、`stale`、`empty`、`unavailable` 状态会保留在证据表中。

`a-stock-data/SKILL.md` 后续应收敛为薄说明层，只指导调用 `astock_data` package，不承载运行时复制或 `exec` 的网络代码。

## Live Smoke

`.github/workflows/ashare-live-smoke.yml` 是观测型 workflow，工作日定时和手动触发。它安装 `requirements.txt` 中固定 SHA 的 `a-stock-data`，开启 A 股情报 gate，并通过 `AShareIntelligenceManager` 真实调用 `sector_fund_flow` provider path，输出 `ashare-live-smoke.json` artifact。该 workflow 的 provider 调用 step `continue-on-error: true`，不会阻断主 CI；在真实 provider 尚未落地或上游不可用时会通过 step failure 暴露 `unavailable` 状态。

## 评分边界

A 股评分第一版默认关闭。`AShareScoringService` 只接受结构化特征，输出固定包含 `score`、`confidence`、`coverage`、`version`、`features`、`warnings` 和 `risk_pressure_score`。当 `coverage < 60%` 时 `score=null`；`risk_pressure_score` 分数越高表示风险压力越大。3/5 日等持续性指标必须来自真实历史样本，历史不足时返回 `null` 并附加 `insufficient_history`，不使用当日分钟数据伪造多日持续性。
