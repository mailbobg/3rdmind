import type { Toast } from "../hooks/useToasts";
import { t as tr } from "../i18n";

/** Bottom-right stack of completion notices; click one to jump, × to dismiss. */
export function Toasts({ toasts, onOpen, onDismiss }: { toasts: Toast[]; onOpen: (t: Toast) => void; onDismiss: (id: string) => void }) {
  if (!toasts.length) return null;
  return (
    <div className="mm-toasts" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`mm-toast mm-toast--${t.tone}`} role="status">
          <button type="button" className="mm-toast__body" onClick={() => { onOpen(t); onDismiss(t.id); }}>
            <span className="mm-toast__title">{t.title}</span>
            {t.body && <span className="mm-toast__text">{t.body}</span>}
          </button>
          <button type="button" className="mm-toast__close" aria-label={tr("关闭")} onClick={() => onDismiss(t.id)}>×</button>
        </div>
      ))}
    </div>
  );
}
