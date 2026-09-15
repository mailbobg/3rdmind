import { useCallback, useState } from "react";
import * as studio from "../api/studio";
import type { Environment } from "../api/studio";

export function useEnvironment() {
  const [env, setEnv] = useState<Environment | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try { setEnv(await studio.environment()); setError(""); }
    catch (e) { setEnv(null); setError(e instanceof Error ? e.message : String(e)); }
  }, []);
  return { env, error, load };
}
