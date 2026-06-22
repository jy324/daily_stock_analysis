import type React from 'react';

/**
 * A-share up/down color semantics (red = up/涨, green = down/跌), shared across
 * the stock report and the market review so both surfaces use one convention.
 * Returns undefined for 0 / missing so the caller keeps the neutral text color.
 */
export function getChangeColorStyle(
  changePct?: number | null,
): React.CSSProperties | undefined {
  if (changePct === undefined || changePct === null || !Number.isFinite(changePct)) {
    return undefined;
  }
  if (changePct > 0) {
    return { color: 'var(--home-price-up)' };
  }
  if (changePct < 0) {
    return { color: 'var(--home-price-down)' };
  }
  return undefined;
}
