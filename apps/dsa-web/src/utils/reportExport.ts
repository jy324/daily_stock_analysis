import type {
  AnalysisReport,
  MarketReviewPayload,
  ReportLanguage,
  RunDiagnosticStatus,
} from '../types/analysis';
import { getSentimentLabel } from '../types/analysis';
import { getReportText, normalizeReportLanguage } from './reportLanguage';
import { resolveReportCredibility } from './credibility';
import { sanitizeReportMarkdown } from './markdown';

const MODEL_PLACEHOLDERS = new Set(['unknown', 'error', 'none', 'null', 'n/a']);

/** Trigger a browser download of a text file, cleaning up the object URL afterwards. */
export function downloadTextFile(filename: string, content: string, mime = 'text/markdown;charset=utf-8'): void {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

/** `YYYYMMDD_HHmm` stamp used in export filenames. */
export function exportFilenameStamp(date = new Date()): string {
  const pad = (n: number) => n.toString().padStart(2, '0');
  const day = `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}`;
  const time = `${pad(date.getHours())}${pad(date.getMinutes())}`;
  return `${day}_${time}`;
}

/** Sanitize an arbitrary label into a safe filename fragment. */
export function toFilenameSlug(value: string, fallback: string): string {
  const slug = (value || '').replace(/[\\/:*?"<>|\s]+/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '').slice(0, 48);
  return slug || fallback;
}

/**
 * Serialize a structured stock analysis report to portable Markdown, with a
 * metadata header (model / time / unified credibility / disclaimer) so the
 * exported file is self-describing.
 */
export function formatReportAsMarkdown(
  report: AnalysisReport,
  language?: ReportLanguage | string,
  options?: { diagnosticStatus?: RunDiagnosticStatus | null },
): string {
  const reportLanguage = normalizeReportLanguage(language);
  const text = getReportText(reportLanguage);
  const isZh = reportLanguage === 'zh';
  const { meta, summary, strategy, details } = report;

  const name = (meta.stockName || meta.stockCode || '').trim();
  const titleName = name || meta.stockCode;
  const lines: string[] = [
    isZh
      ? `# ${titleName}（${meta.stockCode}）${text.exportTitleSuffix}`
      : `# ${titleName} (${meta.stockCode}) ${text.exportTitleSuffix}`,
    '',
  ];

  // --- Metadata header (credibility, model, freshness, ...) ---
  const quality = details?.analysisContextPackOverview?.dataQuality;
  const credibility = resolveReportCredibility({
    qualityLevel: quality?.level,
    qualityScore: quality?.overallScore,
    diagStatus: options?.diagnosticStatus,
  });
  const modelUsed = (meta.modelUsed || '').trim();
  const showModel = Boolean(modelUsed && !MODEL_PLACEHOLDERS.has(modelUsed.toLowerCase()));
  const freshness = (meta.marketPhaseSummary?.effectiveDailyBarDate || meta.marketPhaseSummary?.sessionDate || '').trim();

  const meta_rows: string[] = [];
  if (meta.createdAt) meta_rows.push(`- ${text.exportGeneratedAt}: ${meta.createdAt}`);
  meta_rows.push(`- ${text.exportReportType}: ${meta.reportType}`);
  if (showModel) meta_rows.push(`- ${text.analysisModel}: ${modelUsed}`);
  meta_rows.push(`- ${text.exportLanguageLabel}: ${reportLanguage}`);
  meta_rows.push(
    `- ${text.credibility}: ${text.credibilityLevel[credibility.level]}`
      + (typeof credibility.score === 'number' ? ` (${credibility.score}/100)` : ''),
  );
  if (quality?.level) meta_rows.push(`- ${text.dataQuality}: ${text.credibilityLevel[quality.level]}`);
  if (freshness) meta_rows.push(`- ${text.dataDate}: ${freshness}`);
  if (typeof meta.id === 'number') meta_rows.push(`- ${text.recordId}: ${meta.id}`);
  lines.push(...meta_rows, '', '---', '');

  // --- Body ---
  if (summary?.analysisSummary) {
    lines.push(`## ${text.keyInsights}`, '', summary.analysisSummary.trim(), '');
  }
  if (summary?.operationAdvice) {
    const actionLabel = (summary.actionLabel || '').trim();
    lines.push(
      `## ${text.actionAdvice}`,
      '',
      actionLabel ? `${summary.operationAdvice.trim()}（${actionLabel}）` : summary.operationAdvice.trim(),
      '',
    );
  }
  if (summary?.trendPrediction) {
    lines.push(`## ${text.trendPrediction}`, '', summary.trendPrediction.trim(), '');
  }
  if (typeof summary?.sentimentScore === 'number') {
    const label = summary.sentimentLabel || getSentimentLabel(summary.sentimentScore, reportLanguage);
    lines.push(`## ${text.marketSentiment}`, '', `${summary.sentimentScore} / 100（${label}）`, '');
  }

  const strategyRows = [
    strategy?.idealBuy ? `- ${text.idealBuy}: ${strategy.idealBuy}` : null,
    strategy?.secondaryBuy ? `- ${text.secondaryBuy}: ${strategy.secondaryBuy}` : null,
    strategy?.stopLoss ? `- ${text.stopLoss}: ${strategy.stopLoss}` : null,
    strategy?.takeProfit ? `- ${text.takeProfit}: ${strategy.takeProfit}` : null,
  ].filter((row): row is string => Boolean(row));
  if (strategyRows.length > 0) {
    lines.push(`## ${text.strategyPoints}`, '', ...strategyRows, '');
  }

  if (details?.newsContent && details.newsContent.trim()) {
    lines.push(`## ${text.newsFeed}`, '', details.newsContent.trim(), '');
  }

  lines.push('---', '', `> ${text.disclaimer}`);
  return sanitizeReportMarkdown(lines.join('\n')).trim() + '\n';
}

/** Build the download filename for a stock report. */
export function reportExportFilename(report: AnalysisReport, date = new Date()): string {
  const base = toFilenameSlug(report.meta.stockName || report.meta.stockCode, 'report');
  return `${base}_${exportFilenameStamp(date)}.md`;
}

/**
 * Serialize the daily market review to Markdown for export. The review already
 * carries a full markdown body, so we sanitize it and prepend a short header.
 */
export function formatMarketReviewForExport(
  content: string,
  payload: MarketReviewPayload | null | undefined,
  language?: ReportLanguage | string,
): string {
  const reportLanguage = normalizeReportLanguage(language);
  const text = getReportText(reportLanguage);
  const rawTitle = (payload?.rootTitle || payload?.title || text.exportMarketReviewTitle).replace(/^#+\s*/, '').trim();

  const lines: string[] = [`# ${rawTitle}`, ''];
  const generated = payload?.generatedAt || payload?.date;
  if (generated) lines.push(`- ${text.exportGeneratedAt}: ${generated}`);
  if (payload?.date && payload.date !== generated) lines.push(`- ${text.dataDate}: ${payload.date}`);
  lines.push('', '---', '', sanitizeReportMarkdown(content || '').trim(), '', '---', '', `> ${text.disclaimer}`);
  return lines.join('\n').trim() + '\n';
}

/** Build the download filename for a market review. */
export function marketReviewExportFilename(title: string, date = new Date()): string {
  const base = toFilenameSlug(title.replace(/^#+\s*/, ''), 'market-review');
  return `${base}_${exportFilenameStamp(date)}.md`;
}
