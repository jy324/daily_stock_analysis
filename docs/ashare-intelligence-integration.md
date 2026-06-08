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

DSA 顶层不直接 import `astock_data`。后续 provider factory 必须通过 `import_module("astock_data")` 延迟导入，且 route、tool、service import 阶段不得创建 client 或访问外部网络。

`a-stock-data/SKILL.md` 后续应收敛为薄说明层，只指导调用 `astock_data` package，不承载运行时复制或 `exec` 的网络代码。
