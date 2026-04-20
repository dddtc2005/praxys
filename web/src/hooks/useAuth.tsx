import { useState, useCallback, useEffect, createContext, useContext } from 'react';
import type { ReactNode } from 'react';
import { KEYS, getCompatItem, setCompatItem, removeCompatItem } from '../lib/storage-compat';

interface AuthState {
  token: string | null;
  email: string | null;
  isAdmin: boolean;
  isDemo: boolean;
  isAuthenticated: boolean;
  isLoading: boolean;
}

interface AuthContextType extends AuthState {
  login: (email: string, password: string) => Promise<{ ok: boolean; error?: string }>;
  register: (email: string, password: string, invitationCode?: string) => Promise<{ ok: boolean; error?: string }>;
  logout: () => void;
}

// The API base URL may be empty (same origin via SWA linked backend)
// or set via import.meta.env.VITE_API_URL for development/non-SWA deployments.
const API_BASE = import.meta.env.VITE_API_URL || '';

const AuthContext = createContext<AuthContextType>({
  token: null,
  email: null,
  isAdmin: false,
  isDemo: false,
  isAuthenticated: false,
  isLoading: true,
  login: async () => ({ ok: false }),
  register: async () => ({ ok: false }),
  logout: () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [isDemo, setIsDemo] = useState(false);
  const [email, setEmail] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // On mount, restore token from localStorage and verify it with the server.
  useEffect(() => {
    const stored = getCompatItem(KEYS.authToken.new, KEYS.authToken.legacy);
    const storedEmail = getCompatItem(KEYS.authEmail.new, KEYS.authEmail.legacy);
    if (storedEmail) setEmail(storedEmail);

    if (!stored) {
      setIsLoading(false);
      return;
    }

    setToken(stored);

    // Verify token and fetch fresh profile (admin status, active status)
    fetch(`${API_BASE}/api/auth/me`, { headers: { Authorization: `Bearer ${stored}` } })
      .then((r) => {
        if (r.status === 401) {
          // Token expired or user deactivated — clear auth state
          removeCompatItem(KEYS.authToken.new, KEYS.authToken.legacy);
          removeCompatItem(KEYS.authEmail.new, KEYS.authEmail.legacy);
          removeCompatItem(KEYS.authAdmin.new, KEYS.authAdmin.legacy);
          setToken(null);
          setEmail(null);
          setIsAdmin(false);
          setIsDemo(false);
          return null;
        }
        return r.ok ? r.json() : null;
      })
      .then((data) => {
        if (data) {
          setIsAdmin(data.is_superuser);
          setIsDemo(data.is_demo ?? false);
          setCompatItem(KEYS.authAdmin.new, KEYS.authAdmin.legacy, String(data.is_superuser));
        }
      })
      .catch(() => {})
      .finally(() => setIsLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string): Promise<{ ok: boolean; error?: string }> => {
    try {
      const res = await fetch(`${API_BASE}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ username: email, password }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        const detail = data?.detail;
        if (detail === 'LOGIN_BAD_CREDENTIALS') {
          return { ok: false, error: 'Invalid email or password.' };
        }
        return { ok: false, error: detail || `Login failed (HTTP ${res.status}).` };
      }

      const data = await res.json();
      const accessToken = data.access_token;
      if (accessToken) {
        setCompatItem(KEYS.authToken.new, KEYS.authToken.legacy, accessToken);
        setCompatItem(KEYS.authEmail.new, KEYS.authEmail.legacy, email);
        setToken(accessToken);
        setEmail(email);
        // Fetch admin status
        fetch(`${API_BASE}/api/auth/me`, { headers: { Authorization: `Bearer ${accessToken}` } })
          .then((r) => r.ok ? r.json() : null)
          .then((me) => {
            if (me) {
              setIsAdmin(me.is_superuser);
              setIsDemo(me.is_demo ?? false);
              setCompatItem(KEYS.authAdmin.new, KEYS.authAdmin.legacy, String(me.is_superuser));
            }
          })
          .catch(() => {});
      }
      return { ok: true };
    } catch {
      return { ok: false, error: 'Network error. Is the server running?' };
    }
  }, []);

  const register = useCallback(async (email: string, password: string, invitationCode?: string): Promise<{ ok: boolean; error?: string }> => {
    try {
      const res = await fetch(`${API_BASE}/api/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, invitation_code: invitationCode || '' }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        const detail = data?.detail;
        if (detail === 'REGISTER_USER_ALREADY_EXISTS') {
          return { ok: false, error: 'An account with this email already exists.' };
        }
        if (detail === 'REGISTER_INVITATION_REQUIRED') {
          return { ok: false, error: 'An invitation code is required to register.' };
        }
        if (detail === 'REGISTER_INVALID_INVITATION') {
          return { ok: false, error: 'Invalid or already used invitation code.' };
        }
        return { ok: false, error: detail || `Registration failed (HTTP ${res.status}).` };
      }

      // Auto-login after successful registration.
      return login(email, password);
    } catch {
      return { ok: false, error: 'Network error. Is the server running?' };
    }
  }, [login]);

  const logout = useCallback(() => {
    removeCompatItem(KEYS.authToken.new, KEYS.authToken.legacy);
    removeCompatItem(KEYS.authEmail.new, KEYS.authEmail.legacy);
    removeCompatItem(KEYS.authAdmin.new, KEYS.authAdmin.legacy);
    setToken(null);
    setEmail(null);
    setIsAdmin(false);
    setIsDemo(false);
  }, []);

  const isAuthenticated = token !== null;

  return (
    <AuthContext.Provider
      value={{ token, email, isAdmin, isDemo, isAuthenticated, isLoading, login, register, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
