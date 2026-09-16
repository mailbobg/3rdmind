export interface TraceEvent {
  tag: string;
  timestamp: string;
  loop_id?: number | string | null;
  evo_id?: number;
  content: any;
}
export interface Environment {
  chat_model: string; provider_uri: string; data_ready: boolean;
  start: string | null; end: string | null; python: string;
}
export interface Round { loop_id: number; factors: string[]; metrics: Record<string, number>; prediction: boolean }
export type SignalKind = "factor" | "prediction";
/** One signal in the portfolio: a research factor's result.h5, or a round's Qlib model prediction (pred.pkl). */
export interface FactorWeight { name: string; weight: number; trace: string; loop_id: number; kind?: SignalKind }
export interface IcStats { mean: number; std: number; ir: number | null; positive_ratio: number }
/** Single-factor analysis: daily IC of the factor against next-day return, computed server-side and cached. */
export interface FactorAnalysis {
  coverage: { start: string; end: string }; days: number; rows: number;
  ic: IcStats; rank_ic: IcStats; monthly: { month: string; ic: number | null; rank_ic: number | null }[];
}
export interface LibraryFactor extends Record<string, unknown> {
  trace: string; loop_id: number; name: string;
  description: string | null; formulation: string | null; variables: Record<string, string> | null;
  hypothesis: string | null; decision: boolean | null; reason: string | null;
  metrics: Record<string, number>; code: string | null; analysis: FactorAnalysis | null;
  /** Set once the factor was recomputed on the latest data; the Studio then reads that copy instead of the workspace. */
  refreshed: RefreshMeta | null;
  /** Date span of the signal the Studio reads: the recomputed copy's, else the cached analysis's. */
  coverage: { start: string; end: string } | null;
}
export interface RefreshMeta { name: string; start: string; end: string; rows: number; computed_at: string; data: { start: string; end: string; rows: number } }
export interface FactorRef { trace: string; loop_id: number; name: string }
export interface CorrelationMatrix { names: string[]; matrix: number[][]; days: number }
export interface LgbmParams {
  learning_rate: number; num_leaves: number; max_depth: number; colsample_bytree: number; subsample: number;
  subsample_freq: number; lambda_l1: number; lambda_l2: number; n_estimators: number; early_stopping_rounds: number;
}
/** How the selected signals become one portfolio score: weighted rank blend, or a LightGBM model trained on them. */
export type SignalModel =
  | { method: "rank" }
  | { method: "lgbm"; train: [string, string]; valid: [string, string]; params?: Partial<LgbmParams> };
export interface BacktestRequest {
  factors: FactorWeight[];
  model?: SignalModel;
  start: string; end: string; market: "csi300" | "csi500" | "all"; benchmark: string;
  topk: number; n_drop: number; account: number; open_cost: number; close_cost: number;
  /** Legacy request-level defaults; new requests carry trace/loop_id on each factor. */
  trace?: string; loop_id?: number;
}
export interface BacktestSummary { id: string; status: string; config: BacktestRequest & { provider_uri?: string }; total_return?: number | null; created?: string }
export interface BacktestRow {
  date: string; equity: number; benchmark: number; drawdown: number;
  return: number; cost: number; turnover: number; account: number;
}
export interface Trade extends Record<string, unknown> { date: string; instrument: string; direction: "buy" | "sell"; amount: number; price: number; value: number; cost: number }
export interface Holding extends Record<string, unknown> { instrument: string; amount: number; price: number; value: number; weight: number }
export interface InstrumentSummary extends Record<string, unknown> {
  instrument: string; trades: number; buy_value: number; sell_value: number; cost: number; holding_value: number; pnl: number; held: boolean;
}
/** Per-signal read-out computed on every multi-signal run: IC on the window and agreement with the final score. */
export interface SignalDiagnosis { name: string; kind: SignalKind; weight: number; ic: number | null; rank_ic: number | null; corr_with_score: number | null }
export interface VariantMetrics {
  total_return?: number; annualized_return?: number; sharpe?: number | null; max_drawdown?: number; benchmark_return?: number; days?: number;
  signal_ic?: number | null; signal_rank_ic?: number | null; error?: string;
  /** [date, equity] pairs of this variant's net-of-cost curve. */
  equity?: [string, number][];
}
/** The take-apart diagnosis: each signal alone and the portfolio without it, on the same window. */
export interface Breakdown {
  status: "queued" | "running" | "completed" | "failed"; done?: number; total?: number; error?: string;
  names?: string[]; method?: string; base?: VariantMetrics; alone?: Record<string, VariantMetrics>; without?: Record<string, VariantMetrics>;
}
export interface BacktestResult extends BacktestSummary {
  error?: string; log?: string; method?: string; rows?: BacktestRow[];
  diagnosis?: { signals: SignalDiagnosis[]; correlation: CorrelationMatrix } | null;
  breakdown?: Breakdown | null;
  trades?: Trade[]; holdings?: { positions: Holding[]; cash: number | null; total: number | null }; instruments?: InstrumentSummary[];
  metrics?: {
    total_return: number; annualized_return: number; sharpe: number | null;
    max_drawdown: number; benchmark_return: number; days: number;
    signal_ic?: number | null; signal_rank_ic?: number | null;
  };
  model?: {
    best_iteration: number; valid_l2: number; train_rows: number; valid_rows: number;
    feature_importance: Record<string, number>;
  } | null;
}

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function api<T = any>(path: string, body?: unknown): Promise<T> {
  const init: RequestInit =
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: body instanceof FormData ? {} : { "Content-Type": "application/json" },
          body: body instanceof FormData ? body : JSON.stringify(body),
        };
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError("本地后端未连接。运行 scripts/start-backend.sh 后重试。", 0);
  }
  if ([502, 503, 504].includes(response.status))
    throw new ApiError("本地后端未连接。运行 scripts/start-backend.sh 后重试。", response.status);
  const text = await response.text();
  let value: any;
  try {
    value = JSON.parse(text);
  } catch {
    throw new ApiError("服务未返回 JSON，请确认 RD-Agent 服务及 Vite 代理已启动。", response.status);
  }
  if (!response.ok) throw new ApiError(value?.error || `HTTP ${response.status}`, response.status);
  return value as T;
}

export type ExperimentStatus = "starting" | "running" | "completed" | "stopped" | "failed" | "ended";
export interface ExperimentSummary {
  id: string; scenario: string; rounds: number; accepted: number; status: ExperimentStatus;
  updated: string | null; hypothesis: string | null; messages: number;
}

export const traces = () => api<string[]>("/traces");
export const experiments = () => api<ExperimentSummary[]>("/studio/experiments");
export const traceSnapshot = (id: string) => api<TraceEvent[]>("/trace", { id, snapshot: true });
export const startResearch = (form: FormData) => api<{ id: string }>("/upload", form);
export const stopResearch = (id: string) => api<{ status: string }>("/control", { id, action: "stop" });
/** Continue a finished loop experiment for `loops` more rounds, appending to the same trace. */
export const resumeResearch = (id: string, loops: number) => api<{ id: string; loops: number; loop_n: number }>("/resume", { id, loops });
export const submitInteraction = (id: string, payload: unknown) =>
  api<{ status: string }>("/user_interaction/submit", { id, payload });
export const stdoutUrl = (id: string) => `/stdout?${new URLSearchParams({ id })}`;
export const environment = () => api<Environment>("/studio/environment");
export const strategySource = () => api<{ name: string; code: string }>("/studio/strategy");
export const factorLibrary = () => api<LibraryFactor[]>("/studio/factors");
export const factorAnalysis = (ref: FactorRef, market = "csi300") =>
  api<FactorAnalysis>(`/studio/factors/analysis?${new URLSearchParams({ trace: ref.trace, loop_id: String(ref.loop_id), name: ref.name, market })}`);
export const factorCorrelation = (factors: FactorRef[]) => api<CorrelationMatrix>("/studio/factors/correlation", { factors });
export const traceStatusInfo = (trace: string) =>
  api<{ loaded: boolean; alive: boolean; messages: number }>(`/studio/trace-status?${new URLSearchParams({ trace })}`);
export const rounds = (trace: string) => api<Round[]>(`/studio/rounds?${new URLSearchParams({ trace })}`);
export interface Coverage { start: string; end: string }
export const predictionCoverage = (trace: string, loop_id: number) =>
  api<Coverage & { days: number; rows: number }>(`/studio/predictions/coverage?${new URLSearchParams({ trace, loop_id: String(loop_id) })}`);
export const refreshFactor = (ref: FactorRef) => api<RefreshMeta>("/studio/factors/refresh", { trace: ref.trace, loop_id: ref.loop_id, name: ref.name });
export const factorCoverage = (ref: FactorRef) =>
  api<Coverage & { days: number; rows: number }>(`/studio/factors/coverage?${new URLSearchParams({ trace: ref.trace, loop_id: String(ref.loop_id), name: ref.name })}`);
export const backtests = () => api<BacktestSummary[]>("/studio/backtests");
export const backtest = (id: string) => api<BacktestResult>(`/studio/backtests/${id}`);
export const runBacktest = (config: BacktestRequest) => api<{ id: string }>("/studio/backtests", config);
export type SearchObjective = "sharpe" | "total_return";
export interface SearchRequest extends BacktestRequest { search: { objective: SearchObjective; split?: number } }
export interface SearchStep { step: number; kind: "single" | "start" | "add" | "drop"; tried: string | null; members: string[]; accepted: boolean | null; total_return?: number | null; sharpe?: number | null; max_drawdown?: number | null; days?: number | null; error?: string }
export interface SearchPortfolio { members: string[]; weights?: Record<string, number>; search: VariantMetrics; validation: VariantMetrics }
export interface SearchSummary { id: string; status: string; created: string; config: SearchRequest; recommended?: string[] | null; validation_return?: number | null }
export interface SearchResult extends SearchSummary {
  error?: string; log?: string; done?: number; total?: number; steps?: SearchStep[];
  objective?: SearchObjective; windows?: { search: [string, string]; validation: [string, string] };
  candidates?: string[]; recommended_portfolio?: SearchPortfolio; everything?: SearchPortfolio;
}
export const searches = () => api<SearchSummary[]>("/studio/searches");
export const search = async (id: string): Promise<SearchResult> => {
  // The worker's "recommended" is the portfolio; the list's "recommended" is just its member names.
  const raw = await api<Record<string, unknown>>(`/studio/searches/${id}`);
  const { recommended, ...rest } = raw;
  const portfolio = recommended && typeof recommended === "object" ? (recommended as SearchPortfolio) : undefined;
  return { ...(rest as unknown as SearchResult), recommended: portfolio?.members ?? null, recommended_portfolio: portfolio };
};
export const runSearch = (config: SearchRequest) => api<{ id: string }>("/studio/searches", config);
export interface StrategyParams { market: "csi300" | "csi500" | "all"; benchmark: string; topk: number; n_drop: number; account: number; open_cost: number; close_cost: number }
export interface StrategyRun { id: string; kind: "evidence" | "update"; status?: string; start?: string; end?: string; total_return?: number | null; sharpe?: number | null; max_drawdown?: number | null; benchmark_return?: number | null; error?: string; created?: string }
export interface Strategy {
  id: string; name: string; note: string; created: string; updated: string;
  factors: FactorWeight[]; model: SignalModel; params: StrategyParams;
  evidence: { backtest_id?: string; search_id?: string; start?: string; end?: string };
  runs?: { backtest_id: string; kind: string }[]; run_details?: StrategyRun[];
  latest?: StrategyRun | null; run_count?: number;
}
export interface StrategyDraft { name: string; note?: string; factors: FactorWeight[]; model: SignalModel; params: StrategyParams; evidence?: Strategy["evidence"] }
export const strategies = () => api<Strategy[]>("/studio/strategies");
export const strategy = (id: string) => api<Strategy>(`/studio/strategies/${id}`);
export const saveStrategy = (draft: StrategyDraft) => api<Strategy>("/studio/strategies", draft);
export const renameStrategy = (id: string, fields: { name?: string; note?: string }) =>
  fetch(`/studio/strategies/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(fields) }).then(async (r) => { const v = await r.json(); if (!r.ok) throw new ApiError(v?.error || `HTTP ${r.status}`, r.status); return v as Strategy; });
export const deleteStrategy = (id: string) =>
  fetch(`/studio/strategies/${id}`, { method: "DELETE" }).then(async (r) => { const v = await r.json(); if (!r.ok) throw new ApiError(v?.error || `HTTP ${r.status}`, r.status); return v as { deleted: string }; });
export const updateStrategy = (id: string, body: { start?: string; end?: string; refresh?: boolean } = {}) =>
  api<{ backtest_id: string; refreshed: string[]; failures: string[]; start: string; end: string }>(`/studio/strategies/${id}/update`, body);
export const diagnoseBacktest = (id: string) => api<{ status: string }>(`/studio/backtests/${id}/diagnose`, {});
