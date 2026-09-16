import type { CorrelationMatrix, FactorWeight, LibraryFactor } from "../api/studio";

export const NOISE_RANK_IC = 0.005;
export const NOISE_ICIR = 0.05;
export const DUPLICATE_CORR = 0.7;

export interface Ranked { factor: LibraryFactor; icir: number; rankIc: number }

/**
 * Step 1 of 自动挑候选: drop factors without an analysis or with no measurable signal, keep one per name
 * (the stronger one when two experiments produced the same factor name), and order by |ICIR|.
 */
export function rankCandidates(all: LibraryFactor[]): { ranked: Ranked[]; noise: LibraryFactor[]; unanalyzed: LibraryFactor[] } {
  const unanalyzed: LibraryFactor[] = [];
  const noise: LibraryFactor[] = [];
  const byName = new Map<string, Ranked>();
  for (const f of all) {
    const a = f.analysis;
    if (!a) { unanalyzed.push(f); continue; }
    const icir = a.rank_ic.ir ?? 0;
    const rankIc = a.rank_ic.mean;
    if (Math.abs(rankIc) < NOISE_RANK_IC || Math.abs(icir) < NOISE_ICIR) { noise.push(f); continue; }
    const current = byName.get(f.name);
    if (!current || Math.abs(icir) > Math.abs(current.icir)) byName.set(f.name, { factor: f, icir, rankIc });
  }
  const ranked = [...byName.values()].sort((x, y) => Math.abs(y.icir) - Math.abs(x.icir));
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
