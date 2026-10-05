import { useStore } from './store';
import LoginPage from './components/LoginPage';
import TransitionScreen from './components/TransitionScreen';
import Header from './components/Header';
import ShaderBackground from './components/ShaderBackground';
import AlertsPage from './components/AlertsPage';
import LogPage from './components/LogPage';
import ReconPage from './components/ReconPage';
import SettingsPage from './components/SettingsPage';
import ToastStack from './components/ToastStack';
import NotificationContainer from './components/NotificationContainer';
import NavTabs from './components/NavTabs';
import AlgoConnection from './components/AlgoConnection';

export default function App() {
  const { isLoggedIn, showTransition, currentPage } = useStore();

  if (!isLoggedIn) {
    return <LoginPage />;
  }

  if (showTransition) {
    return <TransitionScreen />;
  }

  return (
    <>
      <ShaderBackground variant="mesh" />
      <div className="bg-grid" />
      <div className="bg-glow bg-glow-1" />
      <div className="bg-glow bg-glow-2" />

      <AlgoConnection />
      <Header />

      <main className="shell">
        <NavTabs />
        {currentPage === 'alerts' && <AlertsPage />}
        {currentPage === 'rollover' && <LogPage />}
        {currentPage === 'recon' && <ReconPage />}
        {currentPage === 'settings' && <SettingsPage />}
      </main>

      <ToastStack />
      <NotificationContainer />
    </>
  );
}
