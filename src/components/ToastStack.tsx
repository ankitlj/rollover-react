import { useStore } from '../store';

const ICONS: Record<string, string> = {
  success: '\u2713',
  warning: '\u26A0',
  error: '\u2717',
  info: '\u2139',
};

export default function ToastStack() {
  const { toasts, removeToast } = useStore();

  if (toasts.length === 0) return null;

  return (
    <div className="toast-stack">
      {toasts.map(t => (
        <div key={t.id} className="toast-item">
          <span className={`ti-icon ${t.type}`}>{ICONS[t.type] || ICONS.info}</span>
          <div className="ti-body">
            <div className="ti-title">{t.title}</div>
            {t.detail && <div className="ti-detail">{t.detail}</div>}
          </div>
          <button className="ti-close" onClick={() => removeToast(t.id)}>&times;</button>
        </div>
      ))}
    </div>
  );
}
