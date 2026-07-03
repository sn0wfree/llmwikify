/**
 * posNegColor — color text by value sign (positive / negative / zero).
 *
 * Used in MetricCards and GroupMetricsTable to highlight gain/loss.
 * - "primary" (or any neutral)   → zero / NaN
 * - "emerald-500"               → positive (or inverted-negative)
 * - "rose-500"                  → negative (or inverted-positive)
 *
 * Usage:
 *   posNegColor(0.15)                    → "text-emerald-500"
 *   posNegColor(-0.03)                   → "text-rose-500"
 *   posNegColor(0)                       → "text-muted-foreground"
 *   posNegColor(-5, { invert: true })    → "text-emerald-500" (used for MDD: -5% is good)
 */
export function posNegColor(
  v: number,
  opts: { invert?: boolean } = {},
): string {
  if (v === 0 || !Number.isFinite(v)) return "text-muted-foreground";
  const isPos = opts.invert ? v < 0 : v > 0;
  return isPos ? "text-emerald-500" : "text-rose-500";
}
