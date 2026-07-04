import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Trans } from '@lingui/react/macro';

const API_BASE = import.meta.env.VITE_API_URL || '';

type Status = 'verifying' | 'success' | 'error';

/**
 * Email-ownership verification landing page. The invitation/verification email
 * links here with ?token=...; we POST it to /api/auth/verify and report the
 * outcome. Open self-signups cannot log in until this succeeds.
 */
export default function Verify() {
  const [params] = useSearchParams();
  const token = params.get('token');
  // Seed from token presence so the effect never calls setState synchronously.
  const [status, setStatus] = useState<Status>(token ? 'verifying' : 'error');

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/auth/verify`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token }),
        });
        if (!cancelled) setStatus(res.ok ? 'success' : 'error');
      } catch {
        if (!cancelled) setStatus('error');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm text-center space-y-4">
        {status === 'verifying' && (
          <p className="text-muted-foreground">
            <Trans>Verifying your email…</Trans>
          </p>
        )}
        {status === 'success' && (
          <>
            <h1 className="text-xl font-semibold text-foreground">
              <Trans>Email verified</Trans>
            </h1>
            <p className="text-muted-foreground">
              <Trans>Your account is active. You can now sign in.</Trans>
            </p>
            <Link to="/login" className="inline-block text-primary underline">
              <Trans>Go to sign in</Trans>
            </Link>
          </>
        )}
        {status === 'error' && (
          <>
            <h1 className="text-xl font-semibold text-foreground">
              <Trans>Verification failed</Trans>
            </h1>
            <p className="text-muted-foreground">
              <Trans>This link is invalid or has expired. Try signing in to request a new link.</Trans>
            </p>
            <Link to="/login" className="inline-block text-primary underline">
              <Trans>Back to sign in</Trans>
            </Link>
          </>
        )}
      </div>
    </div>
  );
}