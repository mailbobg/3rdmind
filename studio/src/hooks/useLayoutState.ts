import { useCallback, useState } from "react";
import { persistStudioState, restoreStudioState } from "./studioStorage";

/**
 * Whether the results panel is open (remembered) and whether it is expanded over the work column
 * (session only: a fresh load always starts with both columns). Width is owned by useResizablePanel.
 */
export function useLayoutState() {
  const [resultsOpen, setOpen] = useState<boolean>(() => restoreStudioState().layout?.resultsOpen ?? false);
  const [resultsExpanded, setResultsExpanded] = useState(false);
  const setResultsOpen = useCallback((open: boolean) => {
    setOpen(open);
    if (!open) setResultsExpanded(false);
    persistStudioState({ layout: { ...(restoreStudioState().layout || {}), resultsOpen: open } });
  }, []);
  const toggleResults = useCallback(() => setResultsOpen(!resultsOpen), [resultsOpen, setResultsOpen]);
  const openResults = useCallback(() => { if (!resultsOpen) setResultsOpen(true); }, [resultsOpen, setResultsOpen]);
  const toggleExpanded = useCallback(() => setResultsExpanded((v) => !v), []);
  return { resultsOpen, setResultsOpen, toggleResults, openResults, resultsExpanded, toggleExpanded };
}
