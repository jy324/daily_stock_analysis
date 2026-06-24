import type { AnalysisContextPackDataQualityLevel, RunDiagnosticStatus } from '../types/analysis';

/**
 * Unified report-credibility synthesis shared by the credibility module (#5)
 * and the report export metadata header (#7).
 *
 * It folds the two independent transparency signals we already have — the
 * analysis-context data-quality level and the run-diagnostics status — into a
 * single verdict by taking the worse of the two. No backend/schema change.
 */

export type CredibilityLevel = 'good' | 'usable' | 'limited' | 'poor' | 'unknown';
export type CredibilityTone = 'success' | 'info' | 'warning' | 'danger' | 'neutral';

export interface ReportCredibilityResult {
  level: CredibilityLevel;
  tone: CredibilityTone;
  /** Underlying data-quality score (0-100) when available. */
  score?: number;
}

const LEVEL_TONE: Record<CredibilityLevel, CredibilityTone> = {
  good: 'success',
  usable: 'info',
  limited: 'warning',
  poor: 'danger',
  unknown: 'neutral',
};

/** Higher = worse; used to pick the most conservative verdict. */
const SEVERITY: Record<Exclude<CredibilityLevel, 'unknown'>, number> = {
  good: 0,
  usable: 1,
  limited: 2,
  poor: 3,
};

const QUALITY_TO_LEVEL: Record<AnalysisContextPackDataQualityLevel, Exclude<CredibilityLevel, 'unknown'>> = {
  good: 'good',
  usable: 'usable',
  limited: 'limited',
  poor: 'poor',
};

export const credibilityTone = (level: CredibilityLevel): CredibilityTone => LEVEL_TONE[level];

export function resolveReportCredibility(input: {
  qualityLevel?: AnalysisContextPackDataQualityLevel | null;
  qualityScore?: number | null;
  diagStatus?: RunDiagnosticStatus | null;
}): ReportCredibilityResult {
  const { qualityLevel, qualityScore, diagStatus } = input;
  const score = typeof qualityScore === 'number' ? qualityScore : undefined;

  const candidates: Array<Exclude<CredibilityLevel, 'unknown'>> = [];
  if (qualityLevel && QUALITY_TO_LEVEL[qualityLevel]) {
    candidates.push(QUALITY_TO_LEVEL[qualityLevel]);
  }
  // A failed/degraded pipeline caps credibility regardless of input data quality;
  // a healthy run contributes a 'good' floor, while 'unknown' adds no constraint.
  if (diagStatus === 'failed') {
    candidates.push('poor');
  } else if (diagStatus === 'degraded') {
    candidates.push('limited');
  } else if (diagStatus === 'normal') {
    candidates.push('good');
  }

  if (candidates.length === 0) {
    return { level: 'unknown', tone: LEVEL_TONE.unknown, score };
  }

  const worst = candidates.reduce((acc, item) => (SEVERITY[item] > SEVERITY[acc] ? item : acc), candidates[0]);
  return { level: worst, tone: LEVEL_TONE[worst], score };
}
