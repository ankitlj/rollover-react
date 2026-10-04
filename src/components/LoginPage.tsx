import { useState, useEffect } from 'react';
import { useStore } from '../store';
import ShaderBackground from './ShaderBackground';

export default function LoginPage() {
  const { login } = useStore();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(false);
  const [clock, setClock] = useState(new Date().toLocaleTimeString());

  useEffect(() => {
    const id = setInterval(() => setClock(new Date().toLocaleTimeString()), 1000);
    return () => clearInterval(id);
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!login(username.trim(), password)) {
      setError(true);
    }
  };

  return (
    <>
      <ShaderBackground variant="aurora" />
      <div className="login-screen">
        <div className="login-container">
          <div className="login-logo">
            <img src="/logo.png" alt="Logo" />
          </div>
          <div className="login-title">Rollover Terminal</div>
          <div className="login-subtitle">Execution System</div>
          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label className="form-label">Username</label>
              <input
                type="text"
                value={username}
                onChange={e => setUsername(e.target.value)}
                autoComplete="off"
                required
              />
            </div>
            <div className="form-group">
              <label className="form-label">Password</label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                required
              />
            </div>
            <div className={`login-error${error ? ' show' : ''}`}>Invalid credentials</div>
            <button type="submit" className="login-btn">AUTHENTICATE</button>
          </form>
          <div className="login-footer">
            <span><span className="status-dot" />System Online</span>
            <span>{clock}</span>
          </div>
        </div>
      </div>
    </>
  );
}
