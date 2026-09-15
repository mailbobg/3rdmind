import { createContext, useContext } from "react";
import type { Environment } from "../api/studio";
import type { TraceStore } from "./useTrace";
import type { BacktestStore } from "./useBacktests";
import type { BasketStore } from "./useFactorBasket";
import type { useLayoutState } from "./useLayoutState";

export interface StudioContextValue {
  env: Environment | null;
  reloadEnv: () => Promise<void>;
  trace: TraceStore;
  backtests: BacktestStore;
  basket: BasketStore;
  layout: ReturnType<typeof useLayoutState>;
}
export const StudioContext = createContext<StudioContextValue | null>(null);
export function useStudio() {
  const value = useContext(StudioContext);
  if (!value) throw new Error("useStudio must be used inside StudioShell");
  return value;
}

export function download(name: string, content: string, type = "text/plain") {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
export const shortName = (id: string) => id.split("/").slice(1).join("/") || id;
export const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));
