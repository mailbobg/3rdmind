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
export interface Round { loop_id: number; factors: string[]; metrics: Record<string, number> }
export interface FactorWeight { name: string; weight: number }
export interface BacktestRequest {
  trace: string; loop_id: number; factors: FactorWeight[];
  start: string; end: string; market: "csi300" | "csi500" | "all";
  topk: number; n_drop: number; account: number; open_cost: number; close_cost: number;
}
export interface BacktestSummary { id: string; status: string; config: BacktestRequest & { provider_uri?: string } }
export interface BacktestRow {
  date: string; equity: number; benchmark: number; drawdown: number;
  return: number; cost: number; turnover: number; account: number;
}
export interface BacktestResult extends BacktestSummary {
  error?: string; log?: string; method?: string; rows?: BacktestRow[];
  metrics?: {
    total_return: number; annualized_return: number; sharpe: number | null;
    max_drawdown: number; benchmark_return: number; days: number;
  };
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

export const traces = () => api<string[]>("/traces");
export const traceSnapshot = (id: string) => api<TraceEvent[]>("/trace", { id, snapshot: true });
export const startResearch = (form: FormData) => api<{ id: string }>("/upload", form);
export const stopResearch = (id: string) => api<{ status: string }>("/control", { id, action: "stop" });
export const submitInteraction = (id: string, payload: unknown) =>
  api<{ status: string }>("/user_interaction/submit", { id, payload });
export const stdoutUrl = (id: string) => `/stdout?${new URLSearchParams({ id })}`;
export const environment = () => api<Environment>("/studio/environment");
export const strategySource = () => api<{ name: string; code: string }>("/studio/strategy");
export const rounds = (trace: string) => api<Round[]>(`/studio/rounds?${new URLSearchParams({ trace })}`);
export const backtests = () => api<BacktestSummary[]>("/studio/backtests");
export const backtest = (id: string) => api<BacktestResult>(`/studio/backtests/${id}`);
export const runBacktest = (config: BacktestRequest) => api<{ id: string }>("/studio/backtests", config);
