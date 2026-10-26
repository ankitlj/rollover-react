import { useStore } from '../store';
import HealthStrip from './HealthStrip';

export default function Header() {
  const { currentTheme, toggleTheme, muted, toggleMute, currentUser, apiStatus, logout } = useStore();

  const statusLabel = apiStatus === 'connected' ? 'Connected' : apiStatus === 'reconnecting' ? 'Reconnecting' : 'Disconnected';
  const statusClass = apiStatus === 'connected' ? 'status-connected' : apiStatus === 'reconnecting' ? 'status-reconnecting' : 'status-disconnected';

  return (
    <header className="app-header">
      <div className="header-left">
        <div className="header-logo">
          <img src="/logo.png" alt="Logo" />
        </div>
        <span className="header-title">Rollover Terminal</span>
      </div>
      <div className="header-right">
        <button className="logout-btn" onClick={logout}>Logout</button>
        <HealthStrip />
        <span className={`header-conn-status ${statusClass}`}>{statusLabel}</span>
        <span className="header-user">{currentUser}</span>
        <button className="theme-btn mute-btn" onClick={toggleMute} title={muted ? 'Unmute alerts' : 'Mute alerts'}>
          {muted ? '\u{1F507}' : '\u{1F50A}'}
        </button>
        <button className="theme-btn" onClick={toggleTheme}>
          {currentTheme === 'dark' ? 'Light' : 'Dark'}
        </button>
      </div>
    </header>
  );
}
