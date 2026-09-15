import { useCallback, useState } from "react";
import { persistStudioState, restoreStudioState } from "./studioStorage";

/** Whether the results (end) panel is open; width is owned by Astryx's useResizable with autoSaveId. */
export function useLayoutState() {
  const [resultsOpen, setOpen] = useState<boolean>(() => restoreStudioState().layout?.resultsOpen ?? false);
  const setResultsOpen = useCallback((open: boolean) => {
    setOpen(open);
    persistStudioState({ layout: { ...(restoreStudioState().layout || {}), resultsOpen: open } });
  }, []);
  const toggleResults = useCallback(() => setResultsOpen(!resultsOpen), [resultsOpen, setResultsOpen]);
  const openResults = useCallback(() => { if (!resultsOpen) setResultsOpen(true); }, [resultsOpen, setResultsOpen]);
  return { resultsOpen, setResultsOpen, toggleResults, openResults };
}
