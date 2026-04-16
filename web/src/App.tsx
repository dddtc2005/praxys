import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { TooltipProvider } from './components/ui/tooltip';
import { AuthProvider, useAuth } from './hooks/useAuth';
import { SettingsProvider } from './contexts/SettingsContext';
import { ScienceProvider } from './contexts/ScienceContext';
import Layout from './components/Layout';
import Today from './pages/Today';
import Training from './pages/Training';
import Goal from './pages/Goal';
import History from './pages/History';
import Science from './pages/Science';
import Settings from './pages/Settings';
import Setup from './pages/Setup';
import Admin from './pages/Admin';
import Login from './pages/Login';
import { useSetupStatus } from './hooks/useSetupStatus';

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    // Show nothing while checking auth state to avoid flash.
    return null;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return <>{children}</>;
}

export default function App() {
  return (
    <AuthProvider>
      <TooltipProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginGuard />} />
            <Route
              element={
                <RequireAuth>
                  <SettingsProvider>
                    <ScienceProvider>
                      <Layout />
                    </ScienceProvider>
                  </SettingsProvider>
                </RequireAuth>
              }
            >
              <Route index element={<TodayOrSetup />} />
              <Route path="setup" element={<Setup />} />
              <Route path="training" element={<Training />} />
              <Route path="goal" element={<Goal />} />
              <Route path="history" element={<History />} />
              <Route path="science" element={<Science />} />
              <Route path="settings" element={<Settings />} />
              <Route path="admin" element={<Admin />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </TooltipProvider>
    </AuthProvider>
  );
}

/** Show Setup page if onboarding incomplete, otherwise Today. */
function TodayOrSetup() {
  const setup = useSetupStatus();

  if (setup.loading) return null;
  if (!setup.allDone) return <Setup />;
  return <Today />;
}

/** If already authenticated, redirect away from login page. */
function LoginGuard() {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) return null;
  if (isAuthenticated) return <Navigate to="/" replace />;

  return <Login />;
}
