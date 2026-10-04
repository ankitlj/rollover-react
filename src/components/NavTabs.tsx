import { useState } from 'react';
import { useStore } from '../store';
import type { PageId } from '../types';
import PasswordModal from './PasswordModal';

const TABS: { id: PageId; label: string }[] = [
  { id: 'alerts', label: 'Spread Alerts' },
  { id: 'rollover', label: 'Rollover Log' },
  { id: 'recon', label: 'Daily Reconciliation' },
  { id: 'settings', label: 'Settings' },
];

export default function NavTabs() {
  const { currentPage, setCurrentPage } = useStore();
  const [showPassword, setShowPassword] = useState(false);

  const handleTabClick = (tabId: PageId) => {
    if (tabId === 'settings') {
      setShowPassword(true);
    } else {
      setCurrentPage(tabId);
    }
  };

  const handleUnlock = () => {
    setShowPassword(false);
    setCurrentPage('settings');
  };

  return (
    <>
      <div className="nav-tabs">
        {TABS.map(tab => (
          <button
            key={tab.id}
            className={`nav-tab${currentPage === tab.id ? ' active' : ''}`}
            onClick={() => handleTabClick(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {showPassword && <PasswordModal onUnlock={handleUnlock} onClose={() => setShowPassword(false)} />}
    </>
  );
}
