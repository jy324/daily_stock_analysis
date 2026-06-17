import { useEffect, useState } from 'react';
import { useTheme } from 'next-themes';

/**
 * Categorical chart palette sourced from the --chart-1..6 design tokens.
 *
 * Recharts applies `fill` as an SVG presentation attribute, which does not
 * resolve CSS `var()`, so we read the resolved token values via
 * getComputedStyle and return concrete `hsl(...)` strings. The values are
 * re-resolved whenever the theme changes so the palette adapts to light/dark.
 */
const CHART_VARS = ['--chart-1', '--chart-2', '--chart-3', '--chart-4', '--chart-5', '--chart-6'] as const;

// Dark-theme defaults, used until the effect resolves the live token values
// (e.g. first render before mount). Keeps the palette non-empty so consumers
// can safely index into it.
const FALLBACK_PALETTE = [
  'hsl(190 100% 50%)',
  'hsl(152 69% 45%)',
  'hsl(37 92% 55%)',
  'hsl(247 84% 70%)',
  'hsl(349 90% 63%)',
  'hsl(213 90% 62%)',
];

export function useChartPalette(): string[] {
  const { resolvedTheme } = useTheme();
  const [palette, setPalette] = useState<string[]>(FALLBACK_PALETTE);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    const styles = getComputedStyle(document.documentElement);
    const resolved = CHART_VARS
      .map((name) => styles.getPropertyValue(name).trim())
      .filter(Boolean)
      .map((value) => `hsl(${value})`);
    if (resolved.length > 0) {
      setPalette(resolved);
    }
  }, [resolvedTheme]);

  return palette;
}
