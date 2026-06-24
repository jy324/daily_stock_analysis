import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AnalysisReport, MarketReviewPayload } from '../../types/analysis';
import {
  downloadTextFile,
  formatMarketReviewForExport,
  formatReportAsMarkdown,
  marketReviewExportFilename,
  reportExportFilename,
} from '../reportExport';

const makeReport = (): AnalysisReport => ({
  meta: {
    id: 123,
    queryId: 'q1',
    stockCode: '600519',
    stockName: '贵州茅台',
    reportType: 'detailed',
    reportLanguage: 'zh',
    createdAt: '2026-04-10T12:00:00',
    modelUsed: 'deepseek-chat',
    marketPhaseSummary: {
      market: 'cn',
      phase: 'postmarket',
      sessionDate: '2026-04-10',
      effectiveDailyBarDate: '2026-04-09',
      isPartialBar: false,
      warnings: [],
    },
  },
  summary: {
    analysisSummary: '核心结论文本',
    operationAdvice: '持有',
    actionLabel: '持有',
    trendPrediction: '震荡偏强',
    sentimentScore: 72,
    sentimentLabel: '乐观',
  },
  strategy: { idealBuy: '1500', secondaryBuy: '1450', stopLoss: '1400', takeProfit: '1700' },
  details: {
    newsContent: '- 新闻一\n- 新闻二',
    analysisContextPackOverview: {
      packVersion: '1.0',
      subject: { code: '600519' },
      blocks: [],
      counts: {
        available: 5, missing: 1, notSupported: 0, fallback: 0,
        stale: 0, estimated: 0, partial: 0, fetchFailed: 0,
      },
      dataQuality: { overallScore: 82, level: 'usable', blockScores: {}, limitations: [] },
      warnings: [],
      metadata: { newsResultCount: 6 },
    },
  },
});

describe('formatReportAsMarkdown', () => {
  it('emits a self-describing metadata header and the body sections', () => {
    const md = formatReportAsMarkdown(makeReport(), 'zh', { diagnosticStatus: 'normal' });

    expect(md).toContain('# 贵州茅台（600519）分析报告');
    expect(md).toContain('- 生成时间: 2026-04-10T12:00:00');
    expect(md).toContain('- 报告类型: detailed');
    expect(md).toContain('- 分析模型: deepseek-chat');
    expect(md).toContain('- 报告可信度: 可用 (82/100)');
    expect(md).toContain('- 数据质量: 可用');
    expect(md).toContain('- 数据日期: 2026-04-09');
    expect(md).toContain('- 记录 ID: 123');

    expect(md).toContain('## 核心洞察');
    expect(md).toContain('核心结论文本');
    expect(md).toContain('持有（持有）');
    expect(md).toContain('## 策略点位');
    expect(md).toContain('- 理想买入: 1500');
    expect(md).toContain('## 资讯动态');
    expect(md).toContain('新闻一');
    expect(md).toContain('> 仅供参考，不构成投资建议');
  });

  it('downgrades the credibility header when diagnostics failed', () => {
    const md = formatReportAsMarkdown(makeReport(), 'zh', { diagnosticStatus: 'failed' });
    expect(md).toContain('- 报告可信度: 较差');
  });

  it('hides the model row for placeholder model values', () => {
    const report = makeReport();
    report.meta.modelUsed = 'unknown';
    const md = formatReportAsMarkdown(report, 'zh');
    expect(md).not.toContain('分析模型');
  });
});

describe('formatMarketReviewForExport', () => {
  it('prepends a header and sanitizes the markdown body', () => {
    const payload: MarketReviewPayload = {
      rootTitle: '# 🎯 大盘复盘',
      title: '大盘复盘',
      generatedAt: '2026-04-10T16:00:00',
      date: '2026-04-10',
    };
    // literal escaped newlines should be normalized away by sanitize
    const md = formatMarketReviewForExport('## 2026-04-10 大盘复盘\\n\\n> 今日震荡。', payload, 'zh');

    expect(md).toContain('# 🎯 大盘复盘');
    expect(md).toContain('- 生成时间: 2026-04-10T16:00:00');
    expect(md).toContain('今日震荡');
    expect(md).not.toContain('\\n');
    expect(md).toContain('> 仅供参考，不构成投资建议');
  });
});

describe('export filenames', () => {
  const stamp = new Date(2026, 3, 10, 9, 5);

  it('builds a stock report filename from the name and timestamp', () => {
    expect(reportExportFilename(makeReport(), stamp)).toBe('贵州茅台_20260410_0905.md');
  });

  it('builds a market review filename, stripping the heading marker', () => {
    expect(marketReviewExportFilename('# 🎯 大盘复盘', stamp)).toBe('🎯_大盘复盘_20260410_0905.md');
  });
});

describe('downloadTextFile', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('creates an object URL, clicks an anchor, and revokes the URL', () => {
    const createObjectURL = vi.fn(() => 'blob:mock');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL });
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    downloadTextFile('report_x.md', '# hi');

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock');
  });
});
