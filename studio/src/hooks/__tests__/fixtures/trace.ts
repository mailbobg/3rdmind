import type { TraceEvent } from "../../../api/studio";
export const events: TraceEvent[] = [
  { tag: "research.hypothesis", timestamp: "1", loop_id: 0, content: { hypothesis: "Short-term reversal", reason: "r" } },
  { tag: "research.tasks", timestamp: "2", loop_id: 0, content: [{ name: "STR_5", description: "d" }] },
  { tag: "evolving.codes", timestamp: "3", loop_id: 0, evo_id: 0,
    content: [{ evo_id: 0, target_task_name: "STR_5", workspace: { "factor.py": "print(1)" } }] },
  { tag: "feedback.metric", timestamp: "4", loop_id: 0,
    content: { result: JSON.stringify({ IC: 0.01 }), workspaces: { experiment: "/e", factors: [{ name: "STR_5", path: "/f" }] } } },
  { tag: "feedback.return_chart", timestamp: "5", loop_id: 0, content: { chart_html: "<html/>" } },
  { tag: "feedback.hypothesis_feedback", timestamp: "6", loop_id: 0, content: { decision: true, reason: "ok" } },
  { tag: "research.hypothesis", timestamp: "7", loop_id: 1, content: { hypothesis: "Second" } },
  { tag: "END", timestamp: "8", content: { end_code: 0 } },
];
