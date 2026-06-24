import type React from 'react';
import { ShieldCheck } from 'lucide-react';
import type {
  AnalysisContextPackOverview,
  ReportLanguage,
  ReportMeta,
  RunDiagnosticStatus,
  RunDiagnosticSummary,
} from '../../types/analysis';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';
import { resolveReportCredibility, type CredibilityTone } from '../../utils/credibility';
import { Badge, Card, StatusDot } from '../common';

interface ReportCredibilityProps {
  meta: ReportMeta;
  contextOverview?: AnalysisContextPackOverview | null;
  diagnosticSummary?: RunDiagnosticSummary;
  language?: ReportLanguage;
}

type BadgeVariant = NonNullable<React.ComponentProps<typeof Badge>['variant']>;

const TONE_TO_VARIANT: Record<CredibilityTone, BadgeVariant> = {
  success: 'success',
  info: 'info',
  warning: 'warning',
  danger: 'danger',
  neutral: 'default',
};

const DIAG_TONE: Record<RunDiagnosticStatus, CredibilityTone> = {
  normal: 'success',
  degraded: 'warning',
  failed: 'danger',
  unknown: 'neutral',
};

const MODEL_PLACEHOLDERS = new Set(['unknown', 'error', 'none', 'null', 'n/a']);

/**
 * Unified report-credibility verdict bar (#5). Synthesizes a single top-line
 * credibility level from data quality + run diagnostics, with the underlying
 * detail cards kept below as drill-down.
 */
export const ReportCredibility: React.FC<ReportCredibilityProps> = ({
  meta,
  contextOverview,
  diagnosticSummary,
  language = 'zh',
}) => {
  const reportLanguage = normalizeReportLanguage(language);
  const text = getReportText(reportLanguage);

  const quality = contextOverview?.dataQuality;
  const credibility = resolveReportCredibility({
    qualityLevel: quality?.level,
    qualityScore: quality?.overallScore,
    diagStatus: diagnosticSummary?.status,
  });

  const modelUsed = (meta.modelUsed || '').trim();
  const showModel = Boolean(modelUsed && !MODEL_PLACEHOLDERS.has(modelUsed.toLowerCase()));

  const phase = meta.marketPhaseSummary;
  const freshness = (phase?.effectiveDailyBarDate || phase?.sessionDate || '').trim();

  const diagStatus = diagnosticSummary?.status;
  const newsCount = contextOverview?.metadata?.newsResultCount;

  const levelLabel = text.credibilityLevel[credibility.level];
  const chips: React.ReactNode[] = [];

  if (diagStatus) {
    chips.push(
      <span key="run" className="home-accent-chip inline-flex items-center gap-1.5 px-2 py-0.5">
        <StatusDot tone={DIAG_TONE[diagStatus]} className="h-1.5 w-1.5" />
        {text.runStatus} {text.runStatusLevel[diagStatus]}
      </span>,
    );
  }
  if (showModel) {
    chips.push(
      <span key="model" className="home-accent-chip px-2 py-0.5">
        {text.analysisModel}: {modelUsed}
      </span>,
    );
  }
  if (freshness) {
    chips.push(
      <span key="freshness" className="home-accent-chip px-2 py-0.5">
        {text.dataDate}: {freshness}{phase?.isPartialBar ? ` (${text.partialBarNote})` : ''}
      </span>,
    );
  }
  if (quality?.level) {
    chips.push(
      <span key="quality" className="home-accent-chip px-2 py-0.5">
        {text.dataQuality}: {text.credibilityLevel[quality.level]}
      </span>,
    );
  }
  if (typeof newsCount === 'number') {
    chips.push(
      <span key="news" className="home-accent-chip px-2 py-0.5">
        {text.newsCount} {newsCount}{text.newsCountUnit}
      </span>,
    );
  }

  return (
    <Card variant="bordered" padding="md" className="home-panel-card text-left">
      <div data-testid="report-credibility">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-cyan/10 text-cyan">
            <ShieldCheck className="h-4 w-4" aria-hidden="true" />
          </span>
          <span className="label-uppercase">{text.credibility}</span>
        </div>
        <Badge variant={TONE_TO_VARIANT[credibility.tone]} className="gap-1.5 shadow-none">
          <StatusDot tone={credibility.tone} className="h-1.5 w-1.5" />
          {levelLabel}
          {typeof credibility.score === 'number' ? ` ${credibility.score}/100` : ''}
        </Badge>
      </div>

      {chips.length > 0 ? (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-text">
          {chips}
        </div>
      ) : null}

      <p className="mt-3 text-xs leading-5 text-muted-text">{text.disclaimer}</p>
      </div>
    </Card>
  );
};
