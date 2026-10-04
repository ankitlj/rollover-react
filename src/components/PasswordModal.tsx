import { useState } from 'react';
import { useStore } from '../store';

interface Props {
  onUnlock: () => void;
  onClose: () => void;
}

export default function PasswordModal({ onUnlock, onClose }: Props) {
  const { currentUser, addToast } = useStore();
  const [password, setPassword] = useState('');
  const [error, setError] = useState(false);

  const handleUnlock = () => {
    const pass = password.trim();
    if (!pass) {
      setError(true);
      addToast('error', 'Enter password');
      return;
    }

    const user = currentUser.split('@')[0];
    const expectedPass = user + '@321';

    if (pass === expectedPass) {
      onUnlock();
    } else {
      setError(true);
      addToast('error', 'Incorrect password');
      setTimeout(() => setError(false), 2000);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleUnlock();
    if (e.key === 'Escape') onClose();
  };

  return (
    <div className="modal-overlay open" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 400 }}>
        <div className="modal-header">
          <h3>Settings Access</h3>
          <p>Enter your password to continue</p>
        </div>
        <div className="modal-body">
          <div className="modal-grid">
            <div className="modal-field full">
              <label>Password</label>
              <input
                type="password"
                value={password}
                onChange={ev => { setPassword(ev.target.value); setError(false); }}
                onKeyDown={handleKeyDown}
                placeholder="Enter password..."
                autoFocus
                style={{ borderColor: error ? 'var(--danger)' : undefined }}
              />
            </div>
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn-modal-cancel" onClick={onClose}>Cancel</button>
          <button className="btn-modal-submit" onClick={handleUnlock}>Unlock</button>
        </div>
      </div>
    </div>
  );
}
