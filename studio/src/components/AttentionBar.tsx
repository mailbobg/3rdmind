import type { AttentionItem } from "../api/studio";
import { ATTENTION_LABELS } from "../hooks/useAttention";
import type { NotifyPrefs } from "../hooks/useAttention";
import { shortName } from "../hooks/studioContext";
import { fmtDuration } from "../hooks/progress";
import { Btn } from "./minimal";

/**
 * The thin banner above every page while a run waits on the user: who is waiting, for what, since when, a
 * jump button, and the two notification switches.
 */
export function AttentionBar({ items, now, prefs, setPrefs, onOpen }: { items: AttentionItem[]; now: number; prefs: NotifyPrefs; setPrefs: (p: Partial<NotifyPrefs>) => void; onOpen: (i: AttentionItem) => void }) {
  if (!items.length) return null;
  const [head, ...rest] = items;
  const since = head.since ? now - new Date(head.since).getTime() : null;
  return (
    <div className="attn" role="status">
      <i className="live__dot attn__dot" aria-hidden />
      <span className="attn__text">
        <strong>{shortName(head.trace)}</strong> 在等你确认{ATTENTION_LABELS[head.kind]}{head.round ? `（第 ${head.round} 轮）` : ""}
        {since != null && since > 30_000 ? <span className="mm-dim"> · 已等 {fmtDuration(since)}</span> : null}
        {rest.length ? <span className="mm-dim"> · 还有 {rest.length} 个</span> : null}
      </span>
      <Btn kind="primary" onClick={() => onOpen(head)}>去确认 →</Btn>
      <span className="attn__prefs">
        <label className="attn__pref"><input type="checkbox" className="mm-check" checked={prefs.desktop} onChange={(e) => setPrefs({ desktop: e.target.checked })} /> 桌面通知</label>
        <label className="attn__pref"><input type="checkbox" className="mm-check" checked={prefs.sound} onChange={(e) => setPrefs({ sound: e.target.checked })} /> 提示音</label>
      </span>
    </div>
  );
}
