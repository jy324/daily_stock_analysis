import type { SystemConfigItem } from '../types/systemConfig';

/**
 * Frontend-derived sub-grouping for heavy settings categories.
 *
 * The config schema only carries `category` + `displayOrder` (no group field),
 * but keys share strong provider/function prefixes. We map those to ordered,
 * collapsible groups so categories with many fields (notification ~62,
 * ai_model ~28, …) become navigable. Unmatched keys fall into a trailing
 * "Other" group, so newly added keys never disappear.
 */

interface FieldGroupDef {
  id: string;
  labelZh: string;
  labelEn: string;
  /** Exact keys that belong to this group. */
  keys?: string[];
  /** Key prefixes that belong to this group. */
  prefixes?: string[];
  /** Open by default (e.g. the primary group of a category). */
  defaultOpen?: boolean;
}

export interface ResolvedFieldGroup {
  id: string;
  label: string;
  defaultOpen: boolean;
  items: SystemConfigItem[];
}

const OTHER_GROUP = { id: 'other', labelZh: '其它', labelEn: 'Other' };

const GROUP_DEFS: Record<string, FieldGroupDef[]> = {
  ai_model: [
    { id: 'primary', labelZh: '主模型与通用', labelEn: 'Primary & general', prefixes: ['LITELLM_', 'LLM_'], keys: ['AGENT_LITELLM_MODEL'], defaultOpen: true },
    { id: 'aihubmix', labelZh: 'AIHubmix', labelEn: 'AIHubmix', keys: ['AIHUBMIX_KEY'] },
    { id: 'anspire', labelZh: 'Anspire 大模型', labelEn: 'Anspire', prefixes: ['ANSPIRE_'] },
    { id: 'deepseek', labelZh: 'DeepSeek', labelEn: 'DeepSeek', prefixes: ['DEEPSEEK_'] },
    { id: 'gemini', labelZh: 'Gemini', labelEn: 'Gemini', prefixes: ['GEMINI_'] },
    { id: 'anthropic', labelZh: 'Anthropic', labelEn: 'Anthropic', prefixes: ['ANTHROPIC_'] },
    { id: 'openai', labelZh: 'OpenAI 兼容', labelEn: 'OpenAI-compatible', prefixes: ['OPENAI_'] },
  ],
  data_source: [
    { id: 'market', labelZh: '行情数据', labelEn: 'Market data', keys: ['TUSHARE_TOKEN', 'STOCK_INDEX_REMOTE_UPDATE_ENABLED'], prefixes: ['PYTDX_'], defaultOpen: true },
    { id: 'realtime', labelZh: '实时行情', labelEn: 'Realtime quotes', keys: ['REALTIME_SOURCE_PRIORITY', 'ENABLE_REALTIME_QUOTE', 'ENABLE_REALTIME_TECHNICAL_INDICATORS', 'ENABLE_CHIP_DISTRIBUTION'] },
    { id: 'news', labelZh: '资讯与研究', labelEn: 'News & research', prefixes: ['NEWS_'], keys: ['TICKFLOW_API_KEY', 'ANSPIRE_API_KEYS', 'BIAS_THRESHOLD'] },
    { id: 'search', labelZh: '搜索引擎', labelEn: 'Search engines', prefixes: ['TAVILY_', 'SERPAPI_', 'BRAVE_', 'BOCHA_', 'SEARXNG_', 'MINIMAX_'] },
  ],
  notification: [
    { id: 'wecom', labelZh: '企业微信', labelEn: 'WeCom', prefixes: ['WECHAT_'] },
    { id: 'feishu', labelZh: '飞书', labelEn: 'Feishu', prefixes: ['FEISHU_'] },
    { id: 'dingtalk', labelZh: '钉钉', labelEn: 'DingTalk', prefixes: ['DINGTALK_'] },
    { id: 'telegram', labelZh: 'Telegram', labelEn: 'Telegram', prefixes: ['TELEGRAM_'] },
    { id: 'email', labelZh: '邮件', labelEn: 'Email', prefixes: ['EMAIL_'] },
    { id: 'discord', labelZh: 'Discord', labelEn: 'Discord', prefixes: ['DISCORD_'] },
    { id: 'slack', labelZh: 'Slack', labelEn: 'Slack', prefixes: ['SLACK_'] },
    { id: 'pushover', labelZh: 'Pushover', labelEn: 'Pushover', prefixes: ['PUSHOVER_'] },
    { id: 'ntfy', labelZh: 'ntfy', labelEn: 'ntfy', prefixes: ['NTFY_'] },
    { id: 'gotify', labelZh: 'Gotify', labelEn: 'Gotify', prefixes: ['GOTIFY_'] },
    { id: 'pushplus', labelZh: 'PushPlus', labelEn: 'PushPlus', prefixes: ['PUSHPLUS_'] },
    { id: 'serverchan', labelZh: 'Server酱', labelEn: 'ServerChan', prefixes: ['SERVERCHAN'] },
    { id: 'astrbot', labelZh: 'AstrBot', labelEn: 'AstrBot', prefixes: ['ASTRBOT_'] },
    { id: 'customWebhook', labelZh: '自定义 Webhook', labelEn: 'Custom webhook', prefixes: ['CUSTOM_WEBHOOK_'], keys: ['WEBHOOK_VERIFY_SSL'] },
    { id: 'report', labelZh: '报告格式', labelEn: 'Report format', prefixes: ['REPORT_'], keys: ['MERGE_EMAIL_NOTIFICATION'] },
    { id: 'routing', labelZh: '路由与频控', labelEn: 'Routing & throttling', prefixes: ['NOTIFICATION_'], keys: ['SINGLE_STOCK_NOTIFY'] },
  ],
  system: [
    { id: 'schedule', labelZh: '调度', labelEn: 'Scheduling', prefixes: ['SCHEDULE_'], keys: ['RUN_IMMEDIATELY', 'TRADING_DAY_CHECK_ENABLED'], defaultOpen: true },
    { id: 'webservice', labelZh: 'Web 服务', labelEn: 'Web service', prefixes: ['WEBUI_'], keys: ['TRUST_X_FORWARDED_FOR'] },
    { id: 'marketReview', labelZh: '市场复盘', labelEn: 'Market review', prefixes: ['MARKET_REVIEW_'] },
    { id: 'runtime', labelZh: '运行与日志', labelEn: 'Runtime & logs', prefixes: ['LOG_'], keys: ['MAX_WORKERS', 'ANALYSIS_DELAY', 'HTTP_PROXY', 'DEBUG', 'SAVE_CONTEXT_SNAPSHOT'] },
  ],
  agent: [
    { id: 'core', labelZh: '基础', labelEn: 'Core', keys: ['AGENT_MODE', 'AGENT_MAX_STEPS', 'AGENT_SKILLS', 'AGENT_SKILL_DIR'], defaultOpen: true },
    { id: 'arch', labelZh: '架构编排', labelEn: 'Architecture', keys: ['AGENT_ARCH'], prefixes: ['AGENT_ORCHESTRATOR_'] },
    { id: 'routing', labelZh: '路由与权重', labelEn: 'Routing & weighting', keys: ['AGENT_NL_ROUTING', 'AGENT_SKILL_ROUTING', 'AGENT_SKILL_AUTOWEIGHT'] },
    { id: 'risk', labelZh: '风控与深研', labelEn: 'Risk & research', keys: ['AGENT_RISK_OVERRIDE'], prefixes: ['AGENT_DEEP_RESEARCH_'] },
    { id: 'memory', labelZh: '记忆与上下文', labelEn: 'Memory & context', keys: ['AGENT_MEMORY_ENABLED'], prefixes: ['AGENT_CONTEXT_'] },
    { id: 'monitor', labelZh: '事件监控', labelEn: 'Event monitor', prefixes: ['AGENT_EVENT_'] },
  ],
};

export function isGroupedCategory(category: string): boolean {
  return Boolean(GROUP_DEFS[category]);
}

function matchGroupId(defs: FieldGroupDef[], key: string): string | undefined {
  const hit = defs.find(
    (def) => def.keys?.includes(key) || def.prefixes?.some((prefix) => key.startsWith(prefix)),
  );
  return hit?.id;
}

function hasConfiguredValue(item: SystemConfigItem): boolean {
  // rawValueExists = the env value is explicitly set (not just a default), so a
  // group the user has actually configured auto-expands.
  return item.rawValueExists || String(item.value ?? '').trim() !== '';
}

/**
 * Group a category's (already category-filtered, display-order-sorted) items
 * into ordered collapsible groups. Returns a single implicit group for
 * categories without a grouping definition.
 */
export function groupItems(
  category: string,
  items: SystemConfigItem[],
  lang: 'zh' | 'en',
): ResolvedFieldGroup[] {
  const defs = GROUP_DEFS[category];
  if (!defs) {
    return [{ id: 'all', label: '', defaultOpen: true, items }];
  }

  const buckets = new Map<string, SystemConfigItem[]>();
  for (const item of items) {
    const id = matchGroupId(defs, item.key) ?? OTHER_GROUP.id;
    const bucket = buckets.get(id);
    if (bucket) {
      bucket.push(item);
    } else {
      buckets.set(id, [item]);
    }
  }

  const toGroup = (def: FieldGroupDef, groupItemsList: SystemConfigItem[]): ResolvedFieldGroup => ({
    id: def.id,
    label: lang === 'en' ? def.labelEn : def.labelZh,
    defaultOpen: Boolean(def.defaultOpen) || groupItemsList.some(hasConfiguredValue),
    items: groupItemsList,
  });

  const result: ResolvedFieldGroup[] = [];
  for (const def of defs) {
    const groupItemsList = buckets.get(def.id);
    if (groupItemsList?.length) {
      result.push(toGroup(def, groupItemsList));
    }
  }
  const others = buckets.get(OTHER_GROUP.id);
  if (others?.length) {
    result.push(toGroup(OTHER_GROUP, others));
  }
  return result;
}
