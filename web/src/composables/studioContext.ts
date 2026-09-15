import { inject } from "vue";
import type { Ref } from "vue";
import type { Environment } from "../api/studio";
import type { useTrace } from "./useTrace";
import type { useBacktests } from "./useBacktests";
import type { useFactorBasket } from "./useFactorBasket";

/** Typed access to the singletons StudioLayout provides to every section view. */
export function useStudioContext() {
  return {
    env: inject<Ref<Environment | null>>("env")!,
    trace: inject<ReturnType<typeof useTrace>>("trace")!,
    backtests: inject<ReturnType<typeof useBacktests>>("backtests")!,
    basket: inject<ReturnType<typeof useFactorBasket>>("basket")!,
  };
}

export function download(name: string, content: string, type = "text/plain") {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
