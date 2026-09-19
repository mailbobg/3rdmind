import type { CorrelationMatrix, FactorAnalysis, FactorWeight, LibraryFactor } from "../api/studio";

export const NOISE_RANK_IC = 0.005;
export const NOISE_ICIR = 0.05;
/** A Rank IC whose t statistic is below this is treated as noise (the same bar the factor page shows). */
export const NOISE_T = 2.0;
export const DUPLICATE_CORR = 0.7;

export interface Ranked { factor: LibraryFactor; icir: number; rankIc: number; t: number; horizon: number }

/** Rank IC t statistic of an analysis: stored when the analysis is recent, else ICIR × √days. */
export function rankIcT(a: FactorAnalysis): number {
  return a.rank_ic.t ?? (a.rank_ic.ir ?? 0) * Math.sqrt(a.days || 0);
}

/** The gate's t bars per horizon (studio_gate.py): t is scaled to n / horizon observations, so the bar falls with it. */
export const T_SIGNAL_BY_HORIZON: Record<number, number> = { 1: 3.0, 5: 2.5, 10: 2.0, 20: 2.0 };
export const T_WEAK_BY_HORIZON: Record<number, number> = { 1: 2.0, 5: 1.75, 10: 1.5, 20: 1.5 };
const bar = (table: Record<number, number>, horizon: number) => table[horizon] ?? table[1];

/**
 * What the gate reads from an analysis: the size-neutral Rank IC at the horizon where |t| clears its own bar by
 * the widest margin (t, horizon, Rank IC, weak bar, signal bar). Older analyses without horizons fall back to
 * the 1-day raw Rank IC.
 */
export function gateStats(a: FactorAnalysis): { t: number; horizon: number; ic: number; tWeak: number; tSignal: number } {
  let best: { t: number; horizon: number; ic: number } | null = null;
  let bestRatio = -1;
  for (const h of a.horizons || []) {
    const stats = h.residual_rank_ic || h.rank_ic;
    if (!stats || stats.t == null) continue;
    const ratio = Math.abs(stats.t) / bar(T_SIGNAL_BY_HORIZON, h.days);
    if (ratio > bestRatio) { bestRatio = ratio; best = { t: stats.t, horizon: h.days, ic: stats.mean }; }
  }
  const picked = best || { t: rankIcT(a), horizon: 1, ic: a.rank_ic.mean };
  return { ...picked, tWeak: bar(T_WEAK_BY_HORIZON, picked.horizon), tSignal: bar(T_SIGNAL_BY_HORIZON, picked.horizon) };
}

/**
 * Step 1 of 自动挑候选: drop factors without an analysis or whose Rank IC is indistinguishable from zero at
 * every horizon (the gate's weak bar), keep one per name (the stronger one when two experiments produced the
 * same factor name), and order by how far |t| clears its horizon's bar.
 */
export function rankCandidates(all: LibraryFactor[]): { ranked: Ranked[]; noise: LibraryFactor[]; unanalyzed: LibraryFactor[] } {
  const unanalyzed: LibraryFactor[] = [];
  const noise: LibraryFactor[] = [];
  const byName = new Map<string, Ranked & { ratio: number }>();
  for (const f of all) {
    const a = f.analysis;
    if (!a) { unanalyzed.push(f); continue; }
    const icir = a.rank_ic.ir ?? 0;
    const g = gateStats(a);
    if (Math.abs(g.t) < g.tWeak) { noise.push(f); continue; }
    const ratio = Math.abs(g.t) / g.tSignal;
    const current = byName.get(f.name);
    if (!current || ratio > current.ratio) byName.set(f.name, { factor: f, icir, rankIc: g.ic, t: g.t, horizon: g.horizon, ratio });
  }
  const ranked = [...byName.values()].sort((x, y) => y.ratio - x.ratio).map(({ ratio: _r, ...rest }) => rest);
  return { ranked, noise, unanalyzed };
}

/**
 * Step 2: walk the ranking and keep a factor only if it is not a near-duplicate (|ρ| ≥ threshold) of one
 * already kept, until `max` are chosen. Returns the picks with the sign of their Rank IC as the weight,
 * and the names each dropped factor duplicated.
 */
export function pickByCorrelation(ranked: Ranked[], corr: CorrelationMatrix, max = 8, threshold = DUPLICATE_CORR):
  { picked: FactorWeight[]; duplicates: { name: string; of: string; rho: number }[] } {
  const index = new Map(corr.names.map((n, i) => [n, i]));
  const kept: Ranked[] = [];
  const duplicates: { name: string; of: string; rho: number }[] = [];
  for (const r of ranked) {
    if (kept.length >= max) break;
    const i = index.get(r.factor.name);
    const clash = i === undefined ? undefined : kept.find((k) => { const j = index.get(k.factor.name); return j !== undefined && Math.abs(corr.matrix[i][j]) >= threshold; });
    if (clash && i !== undefined) { const j = index.get(clash.factor.name)!; duplicates.push({ name: r.factor.name, of: clash.factor.name, rho: corr.matrix[i][j] }); continue; }
    kept.push(r);
  }
  const picked = kept.map((k) => ({ name: k.factor.name, trace: k.factor.trace, loop_id: k.factor.loop_id, kind: "factor" as const, weight: k.rankIc < 0 ? -1 : 1 }));
  return { picked, duplicates };
}
