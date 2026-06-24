import { describe, expect, it } from 'vitest';
import { resolveReportCredibility } from '../credibility';

describe('resolveReportCredibility', () => {
  it('returns good when data quality is good and the run is normal', () => {
    expect(resolveReportCredibility({ qualityLevel: 'good', qualityScore: 91, diagStatus: 'normal' })).toEqual({
      level: 'good',
      tone: 'success',
      score: 91,
    });
  });

  it('takes the worse of data quality and diagnostics', () => {
    // healthy data but a degraded pipeline caps credibility at 受限
    expect(resolveReportCredibility({ qualityLevel: 'good', diagStatus: 'degraded' }).level).toBe('limited');
    // usable data with a normal run stays 可用
    expect(resolveReportCredibility({ qualityLevel: 'usable', diagStatus: 'normal' }).level).toBe('usable');
    // a failed run dominates even good data
    expect(resolveReportCredibility({ qualityLevel: 'good', diagStatus: 'failed' }).level).toBe('poor');
  });

  it('uses data quality alone when diagnostics status is unknown', () => {
    expect(resolveReportCredibility({ qualityLevel: 'limited', diagStatus: 'unknown' }).level).toBe('limited');
  });

  it('returns unknown when neither signal is present', () => {
    expect(resolveReportCredibility({}).level).toBe('unknown');
    expect(resolveReportCredibility({ qualityScore: 50 })).toEqual({ level: 'unknown', tone: 'neutral', score: 50 });
  });

  it('carries the underlying quality score through', () => {
    expect(resolveReportCredibility({ qualityLevel: 'usable', qualityScore: 82, diagStatus: 'normal' }).score).toBe(82);
  });
});
