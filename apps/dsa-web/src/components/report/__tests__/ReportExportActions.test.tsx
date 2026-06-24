import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AnalysisReport } from '../../../types/analysis';
import { downloadTextFile } from '../../../utils/reportExport';
import { ReportExportActions } from '../ReportExportActions';

// Keep the real Markdown formatter; only stub the actual file download.
vi.mock('../../../utils/reportExport', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../utils/reportExport')>();
  return { ...actual, downloadTextFile: vi.fn() };
});

const report: AnalysisReport = {
  meta: {
    queryId: 'q',
    stockCode: '600519',
    stockName: '贵州茅台',
    reportType: 'detailed',
    reportLanguage: 'zh',
    createdAt: '2026-04-10T12:00:00',
  },
  summary: {
    analysisSummary: '核心结论',
    operationAdvice: '持有',
    trendPrediction: '震荡',
    sentimentScore: 60,
  },
};

describe('ReportExportActions', () => {
  afterEach(() => {
    vi.clearAllMocks();
    vi.restoreAllMocks();
  });

  it('downloads a markdown file built from the report on click', () => {
    render(<ReportExportActions report={report} diagnosticStatus="normal" />);

    fireEvent.click(screen.getByText('下载 Markdown'));

    expect(vi.mocked(downloadTextFile)).toHaveBeenCalledTimes(1);
    const [filename, content] = vi.mocked(downloadTextFile).mock.calls[0];
    expect(filename).toMatch(/^贵州茅台_\d{8}_\d{4}\.md$/);
    expect(content).toContain('# 贵州茅台（600519）分析报告');
    expect(content).toContain('核心结论');
  });

  it('invokes window.print for the print action', () => {
    const printSpy = vi.spyOn(window, 'print').mockImplementation(() => {});
    render(<ReportExportActions report={report} />);

    fireEvent.click(screen.getByText('打印 / 另存 PDF'));

    expect(printSpy).toHaveBeenCalledTimes(1);
  });
});
