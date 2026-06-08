# A 股情报扩展集成说明

## 决策

A 股情报扩展默认关闭，DSA 应用层仅暴露能力探测和运行时门禁。关闭时不导入 `astock_data`、不创建 provider client、不访问缓存目录、不写数据库快照，也不改变现有大盘复盘、报告、Agent 工具和调度行为。

## 配置边界

`.env` 只保留顶层开关和路径：

- `ASHARE_INTELLIGENCE_ENABLED=false`
- `ASHARE_PROVIDER_PRIORITY=astock_data`
- `ASHARE_CACHE_DIR=./data/ashare_cache`
- `ASHARE_CONFIG_FILE=config/ashare_intelligence.yaml`

报告、Agent tools、评分、TTL、预算和后续细项放在 `config/ashare_intelligence.yaml`，避免一次性膨胀 `.env`。

## API 语义

`GET /api/v1/capabilities` 是轻量能力探测端点，不触发 provider 请求。返回：

- `ashare_intelligence.enabled`
- `ashare_intelligence.provider_installed`
- `ashare_intelligence.report_enabled`
- `ashare_intelligence.agent_tools_enabled`
- `ashare_intelligence.scoring_enabled`

A 股情报路由默认注册，但运行时门禁：

- 功能关闭：`403 feature_disabled`
- package 缺失：`503 dependency_unavailable`
- 后续 provider 熔断：`503 provider_unavailable`
- 后续 refresh 限流：`429 rate_limited`

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
