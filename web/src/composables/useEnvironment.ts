import { ref } from "vue";
import * as studio from "../api/studio";
import type { Environment } from "../api/studio";

export function useEnvironment() {
  const env = ref<Environment | null>(null);
  const error = ref("");
  async function load() {
    try { env.value = await studio.environment(); error.value = ""; }
    catch (e: any) { env.value = null; error.value = e.message; }
  }
  return { env, error, load };
}
