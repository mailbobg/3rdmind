import type { Toast } from "../hooks/useToasts";

/** Bottom-right stack of completion notices; click one to jump, × to dismiss. */
export function Toasts({ toasts, onOpen, onDismiss }: { toasts: Toast[]; onOpen: (t: Toast) => void; onDismiss: (id: string) => void }) {
  if (!toasts.length) return null;
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast--${t.tone}`} role="status">
          <button type="button" className="toast__body" onClick={() => { onOpen(t); onDismiss(t.id); }}>
            <span className="toast__title">{t.title}</span>
            {t.body && <span className="toast__text">{t.body}</span>}
          </button>
          <button type="button" className="toast__close" aria-label="关闭" onClick={() => onDismiss(t.id)}>×</button>
        </div>
      ))}
    </div>
  );
}
