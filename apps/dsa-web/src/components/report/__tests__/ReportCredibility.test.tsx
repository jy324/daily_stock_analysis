import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type {
  AnalysisContextPackDataQualityLevel,
  AnalysisContextPackOverview,
  ReportMeta,
  RunDiagnosticStatus,
  RunDiagnosticSummary,
} from '../../../types/analysis';
import { ReportCredibility } from '../ReportCredibility';

const baseMeta: ReportMeta = {
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
};

const makeOverview = (
  level: AnalysisContextPackDataQualityLevel,
  score: number,
  newsResultCount: number,
): AnalysisContextPackOverview => ({
  packVersion: '1.0',
  subject: { code: '600519' },
  blocks: [],
  counts: {
    available: 5,
    missing: 1,
    notSupported: 0,
    fallback: 0,
    stale: 0,
    estimated: 0,
    partial: 0,
    fetchFailed: 0,
  },
  dataQuality: { overallScore: score, level, blockScores: {}, limitations: [] },
  warnings: [],
  metadata: { newsResultCount },
});

const diag = (status: RunDiagnosticStatus): RunDiagnosticSummary => ({
  status,
  statusLabel: '',
  reason: '',
  components: {},
  copyText: '',
});

describe('ReportCredibility', () => {
  it('renders the unified verdict, chips and disclaimer', () => {
    render(
      <ReportCredibility
        meta={baseMeta}
        contextOverview={makeOverview('usable', 82, 6)}
        diagnosticSummary={diag('normal')}
      />,
    );

    expect(screen.getByTestId('report-credibility')).toBeInTheDocument();
    expect(screen.getByText('报告可信度')).toBeInTheDocument();
    expect(screen.getByText(/可用 82\/100/)).toBeInTheDocument();
    expect(screen.getByText('运行 正常')).toBeInTheDocument();
    expect(screen.getByText('分析模型: deepseek-chat')).toBeInTheDocument();
    expect(screen.getByText('数据日期: 2026-04-09')).toBeInTheDocument();
    expect(screen.getByText('数据质量: 可用')).toBeInTheDocument();
    expect(screen.getByText('新闻 6条')).toBeInTheDocument();
    expect(screen.getByText('仅供参考，不构成投资建议')).toBeInTheDocument();
  });

  it('downgrades the verdict to 较差 when diagnostics failed despite good data', () => {
    render(
      <ReportCredibility
        meta={baseMeta}
        contextOverview={makeOverview('good', 95, 0)}
        diagnosticSummary={diag('failed')}
      />,
    );

    expect(screen.getByText(/较差/)).toBeInTheDocument();
  });

  it('hides the model chip for placeholder model values', () => {
    render(
      <ReportCredibility
        meta={{ ...baseMeta, modelUsed: 'unknown' }}
        contextOverview={makeOverview('good', 90, 2)}
        diagnosticSummary={diag('normal')}
      />,
    );

    expect(screen.queryByText(/分析模型/)).not.toBeInTheDocument();
  });

  it('flags a partial daily bar on the freshness chip', () => {
    render(
      <ReportCredibility
        meta={{
          ...baseMeta,
          marketPhaseSummary: { ...baseMeta.marketPhaseSummary!, isPartialBar: true },
        }}
        contextOverview={makeOverview('usable', 70, 1)}
        diagnosticSummary={diag('normal')}
      />,
    );

    expect(screen.getByText('数据日期: 2026-04-09 (日线未完成)')).toBeInTheDocument();
  });

  it('falls back to 未知 when neither quality nor diagnostics are present', () => {
    render(
      <ReportCredibility
        meta={{ queryId: 'q', stockCode: 'x', stockName: 'y', reportType: 'detailed', createdAt: '' }}
      />,
    );

    expect(screen.getByText('未知')).toBeInTheDocument();
    expect(screen.getByText('仅供参考，不构成投资建议')).toBeInTheDocument();
  });

  it('localizes the verdict and disclaimer for english reports', () => {
    render(
      <ReportCredibility
        meta={baseMeta}
        contextOverview={makeOverview('good', 88, 4)}
        diagnosticSummary={diag('normal')}
        language="en"
      />,
    );

    expect(screen.getByText('Report Credibility')).toBeInTheDocument();
    expect(screen.getByText(/Good 88\/100/)).toBeInTheDocument();
    expect(screen.getByText('Run Normal')).toBeInTheDocument();
    expect(screen.getByText('For reference only, not investment advice')).toBeInTheDocument();
  });
});
