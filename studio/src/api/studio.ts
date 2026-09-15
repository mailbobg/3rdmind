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
}
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
export interface BacktestSummary { id: string; status: string; config: BacktestRequest & { provider_uri?: string }; total_return?: number | null }
export interface BacktestRow {
  date: string; equity: number; benchmark: number; drawdown: number;
  return: number; cost: number; turnover: number; account: number;
}
export interface Trade extends Record<string, unknown> { date: string; instrument: string; direction: "buy" | "sell"; amount: number; price: number; value: number; cost: number }
export interface Holding extends Record<string, unknown> { instrument: string; amount: number; price: number; value: number; weight: number }
export interface InstrumentSummary extends Record<string, unknown> {
  instrument: string; trades: number; buy_value: number; sell_value: number; cost: number; holding_value: number; pnl: number; held: boolean;
}
export interface BacktestResult extends BacktestSummary {
  error?: string; log?: string; method?: string; rows?: BacktestRow[];
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
export const backtests = () => api<BacktestSummary[]>("/studio/backtests");
export const backtest = (id: string) => api<BacktestResult>(`/studio/backtests/${id}`);
export const runBacktest = (config: BacktestRequest) => api<{ id: string }>("/studio/backtests", config);
