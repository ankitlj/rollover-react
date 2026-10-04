import { useStore } from '../store';

const ICONS: Record<string, string> = {
  success: '\u2713',
  warning: '\u26A0',
  error: '\u2717',
  info: '\u2139',
};

export default function NotificationContainer() {
  const { notifications, removeNotification } = useStore();

  if (notifications.length === 0) return null;

  return (
    <div className="notification-container">
      {notifications.map(n => (
        <div key={n.id} className={`notification show ${n.type}`}>
          <span className="n-icon">{ICONS[n.type] || ICONS.info}</span>
          <div className="n-content">
            <div className="n-title">{n.title}</div>
            <div className="n-msg">{n.msg}</div>
          </div>
          <button className="n-close" onClick={() => removeNotification(n.id)}>&times;</button>
        </div>
      ))}
    </div>
  );
}
