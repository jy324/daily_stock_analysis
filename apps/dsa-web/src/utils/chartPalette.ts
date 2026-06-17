import { useMemo } from 'react';
import { useTheme } from 'next-themes';

/**
 * Categorical chart palette for non-semantic series (so a slice color never
 * implies good/bad). Defined in JS because Recharts applies `fill` as an SVG
 * presentation attribute, which cannot resolve CSS `var()`.
 *
 * Selected synchronously from the active theme so it stays correct on live
 * theme toggles — reading resolved CSS custom properties from the DOM in an
 * effect is racy here, because next-themes applies the theme class in an
 * ancestor effect that commits after this (descendant) component, yielding a
 * stale read. Hues are tuned brighter for dark and deeper for light.
 */
const DARK_PALETTE = [
  'hsl(190 100% 50%)',
  'hsl(152 69% 45%)',
  'hsl(37 92% 55%)',
  'hsl(247 84% 70%)',
  'hsl(349 90% 63%)',
  'hsl(213 90% 62%)',
];

const LIGHT_PALETTE = [
  'hsl(193 100% 40%)',
  'hsl(152 60% 38%)',
  'hsl(37 92% 46%)',
  'hsl(247 70% 60%)',
  'hsl(350 80% 55%)',
  'hsl(217 83% 55%)',
];

export function useChartPalette(): string[] {
  const { resolvedTheme } = useTheme();
  return useMemo(
    () => (resolvedTheme === 'light' ? LIGHT_PALETTE : DARK_PALETTE),
    [resolvedTheme],
  );
}
