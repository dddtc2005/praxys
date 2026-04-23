import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { TooltipProvider } from './components/ui/tooltip';
import { AuthProvider, useAuth } from './hooks/useAuth';
import { SettingsProvider } from './contexts/SettingsContext';
import { ScienceProvider } from './contexts/ScienceContext';
import { LocaleProvider } from './contexts/LocaleContext';
import LocaleSync from './contexts/LocaleSync';
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
import Landing from './pages/Landing';
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
    <LocaleProvider>
      <AuthProvider>
        <TooltipProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/" element={<LandingOrApp />} />
              <Route path="/login" element={<LoginGuard />} />
              <Route
                element={
                  <RequireAuth>
                    <SettingsProvider>
                      <LocaleSync />
                      <ScienceProvider>
                        <Layout />
                      </ScienceProvider>
                    </SettingsProvider>
                  </RequireAuth>
                }
              >
                <Route path="today" element={<TodayOrSetup />} />
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
    </LocaleProvider>
  );
}

/** Show Setup page if onboarding incomplete, otherwise Today. */
function TodayOrSetup() {
  const setup = useSetupStatus();

  if (setup.loading) return null;
  if (!setup.allDone) return <Setup />;
  return <Today />;
}

/** Public landing page for unauthenticated visitors. Real authed users go
 *  straight to the app; **demo** users still see the landing (with a "Continue
 *  to demo" CTA) so they don't get silently trapped in the demo dashboard on
 *  repeat visits to `/`. */
function LandingOrApp() {
  const { isAuthenticated, isDemo, isLoading } = useAuth();

  if (isLoading) return null;
  if (isAuthenticated && !isDemo) return <Navigate to="/today" replace />;
  return <Landing />;
}

/** If already authenticated, redirect away from login page. */
function LoginGuard() {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) return null;

  if (isAuthenticated) {
    // CLI login flow: if already logged in, redirect token to CLI callback immediately
    // SECURITY: Only allow localhost callbacks to prevent open redirect token theft
    const params = new URLSearchParams(window.location.search);
    const rawCallback = params.get('cli_callback');
    if (rawCallback) {
      const CLI_CALLBACK_RE = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?\/callback/;
      if (!CLI_CALLBACK_RE.test(rawCallback)) {
        // Callback provided but rejected — log so a malformed CLI link is
        // debuggable instead of silently redirecting to the dashboard while
        // the CLI hangs waiting for a token that never arrives.
        console.warn('[login] CLI callback rejected (non-localhost):', rawCallback);
      } else {
        const token = localStorage.getItem('praxys-auth-token') ?? localStorage.getItem('trainsight-auth-token');
        if (token) {
          window.location.href = `${rawCallback}?token=${encodeURIComponent(token)}`;
          return null;
        }
        console.warn('[login] CLI callback valid but no token in localStorage; falling through to /today');
      }
    }
    return <Navigate to="/today" replace />;
  }

  return <Login />;
}
