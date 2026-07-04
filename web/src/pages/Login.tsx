import type React from 'react';
import { useState, useId, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { Link } from 'react-router-dom';
import { Trans, useLingui } from '@lingui/react/macro';
import { useLocale } from '@/contexts/LocaleContext';
import { useTheme } from '@/hooks/useTheme';
import './Login.css';

const SUPPORT_EMAIL = 'support@praxys.run';
const API_BASE = import.meta.env.VITE_API_URL || '';

type Mode = 'login' | 'invite';
type InviteMode = 'waitlist' | 'code';

export default function Login() {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const { t } = useLingui();
  const { locale, setLocale } = useLocale();
  const { theme, setTheme } = useTheme();

  // A ?invite=CODE deep link lands the user straight on the code path with the
  // code prefilled (computed once, before state init, so the effect below never
  // has to setState synchronously).
  const initialInvite = new URLSearchParams(window.location.search).get('invite');

  // Form state
  const [mode, setMode] = useState<Mode>(initialInvite ? 'invite' : 'login');
  const [inviteMode, setInviteMode] = useState<InviteMode>(initialInvite ? 'code' : 'waitlist');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [invitationCode, setInvitationCode] = useState(initialInvite ? initialInvite.toUpperCase() : '');
  const [waitlistNote, setWaitlistNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [waitlistSuccess, setWaitlistSuccess] = useState(false);
  const [agreedTerms, setAgreedTerms] = useState(false);
  const [registrationOpen, setRegistrationOpen] = useState(false);
  const [verifyPending, setVerifyPending] = useState(false);
  const [honeypot, setHoneypot] = useState('');
  const [showResend, setShowResend] = useState(false);
  const [resendState, setResendState] = useState<'idle' | 'sending' | 'sent'>('idle');

  const formId = useId();

  // CLI callback URL (browser-based CLI login flow).
  // SECURITY: Only allow localhost callbacks to prevent open redirect token theft
  const searchParams = new URLSearchParams(window.location.search);
  const rawCallback = searchParams.get('cli_callback');
  const CLI_CALLBACK_RE = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?\/callback/;
  const cliCallback = rawCallback && CLI_CALLBACK_RE.test(rawCallback) ? rawCallback : null;

  // Fetch the public registration gate + honor a ?invite= deep link on mount.
  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/api/public/config`)
      .then((r) => (r.ok ? r.json() : null))
      .then((cfg) => {
        if (cancelled || !cfg) return;
        if (cfg.registration_open) {
          setRegistrationOpen(true);
          // Open registration: default the "get access" view to the signup
          // form rather than the waitlist.
          setInviteMode('code');
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const handleResend = async () => {
    setResendState('sending');
    try {
      // The endpoint returns 202 regardless of whether the address exists, to
      // avoid account enumeration — so we always show "sent".
      await fetch(`${API_BASE}/api/auth/request-verify-token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim() }),
      });
    } catch {
      /* best-effort */
    }
    setResendState('sent');
  };

  const handleAuthSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setShowResend(false);

    if (!email.trim() || !password.trim()) {
      setError(t`Email and password are required.`);
      return;
    }

    if (mode !== 'login' && !agreedTerms) {
      setError(t`You must accept the Terms of Service to register.`);
      return;
    }

    setSubmitting(true);

    const result = mode === 'login'
      ? await login(email.trim(), password)
      : await register(email.trim(), password, invitationCode.trim(), agreedTerms, honeypot);

    setSubmitting(false);

    // Unverified login: prompt to verify and offer a resend.
    if (mode === 'login' && result.error === 'LOGIN_USER_NOT_VERIFIED') {
      setError(t`Please verify your email before signing in. Check your inbox for the link.`);
      setShowResend(true);
      setResendState('idle');
      return;
    }

    if (!result.ok) {
      setError(result.error || t`An unexpected error occurred.`);
      return;
    }

    // Open, code-less signup: account created but must verify email first.
    if ('verificationRequired' in result && result.verificationRequired) {
      setVerifyPending(true);
      return;
    }

    if (cliCallback) {
      const token =
        localStorage.getItem('praxys-auth-token') ??
        localStorage.getItem('trainsight-auth-token');
      if (token) {
        window.location.href = `${cliCallback}?token=${encodeURIComponent(token)}`;
        return;
      }
    }
    navigate('/today', { replace: true });
  };

  const handleWaitlistSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!email.trim()) {
      setError(t`Email is required.`);
      return;
    }

    setSubmitting(true);
    try {
      const res = await fetch(`${API_BASE}/api/auth/waitlist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: email.trim(),
          note: waitlistNote.trim().slice(0, 500),
          locale,
        }),
      });
      if (!res.ok) {
        if (res.status === 429) {
          setError(t`Too many attempts from this network. Please email us instead.`);
          return;
        }
        if (res.status === 422) {
          // pydantic validation errors come back as detail: [{loc, msg, type}, …]
          // — show a generic note rather than the raw array.
          setError(t`Please check your email format and try again.`);
          return;
        }
        const data = await res.json().catch(() => null);
        const detail = data?.detail;
        setError(
          typeof detail === 'string'
            ? detail
            : t`Could not save your email. Please email us instead.`,
        );
        return;
      }
      setWaitlistSuccess(true);
    } catch {
      setError(t`Network error. Please email ${SUPPORT_EMAIL} directly.`);
    } finally {
      setSubmitting(false);
    }
  };

  const switchMode = (next: Mode) => {
    setMode(next);
    setError(null);
    setWaitlistSuccess(false);
    setVerifyPending(false);
    setShowResend(false);
  };

  return (
    <div className="login-shell">
      {/* ──────────────────────── HERO PANE (left on desktop) ──────────────────────── */}
      <aside className="login-hero" aria-hidden={false}>
        <div className="login-hero-eyebrow">
          <span className="login-hero-eyebrow-dot" aria-hidden />
          {registrationOpen
            ? <Trans>Now open · Create your account</Trans>
            : <Trans>Private alpha · Invitation only</Trans>}
        </div>

        <div className="login-mark-row">
          {/* h1 below provides the accessible name; mark is decorative.
              stroke-width 3 matches the brand-guide construction spec for
              this display-size band (16px favicon=4, 48px sidebar=3,
              200px hero=1.8). */}
          <svg className="login-mark" viewBox="0 0 48 48" aria-hidden="true">
            <line
              className="login-mark-pole"
              x1="14" y1="42" x2="16" y2="5"
              stroke="var(--lg-cobalt)"
              strokeWidth="3"
              strokeLinecap="round"
              fill="none"
            />
            <path
              className="login-mark-flag"
              d="M 16 6 L 40 8 Q 33 14, 40 20 L 15 22 Z"
              fill="var(--lg-primary)"
            />
          </svg>

          <h1 className="login-wordmark" aria-label="Praxys">
            <span className="login-wordmark-letter">P</span>
            <span className="login-wordmark-letter">r</span>
            <span className="login-wordmark-letter">a</span>
            <span className="login-wordmark-letter login-wordmark-x">x</span>
            <span className="login-wordmark-letter">y</span>
            <span className="login-wordmark-letter">s</span>
          </h1>
        </div>

        <p className="login-tagline">
          {/* Canonical brand-guide primary tagline (docs/brand/index.html
              "cover-tag"). The accented phrase is the warm half of the
              brand's adaptive voice — the system meets the reader before
              it pushes. */}
          <Trans>
            Sports science that <span className="login-tagline-accent">meets you</span> where you are.
          </Trans>
        </p>

        <ul className="login-pillars">
          <li className="login-pillar">
            <span className="login-pillar-tag">01</span>
            <span className="login-pillar-text">
              <Trans>
                <strong>Today's signal</strong> · go, modify, or rest.
              </Trans>
            </span>
          </li>
          <li className="login-pillar">
            <span className="login-pillar-tag">02</span>
            <span className="login-pillar-text">
              <Trans>
                <strong>Diagnosis &amp; forecast</strong> you can verify.
              </Trans>
            </span>
          </li>
          <li className="login-pillar">
            <span className="login-pillar-tag">03</span>
            <span className="login-pillar-text">
              <Trans>
                <strong>Cited science.</strong> No hype.
              </Trans>
            </span>
          </li>
        </ul>

      </aside>

      {/* ──────────────────────── FORM PANE (right on desktop) ──────────────────────── */}
      <main className="login-form-pane">
        <div className="login-form-inner">
          <div className="login-form-brand-mobile">
            <svg className="login-form-brand-mark" viewBox="0 0 48 48" aria-hidden>
              <line
                x1="14" y1="42" x2="16" y2="5"
                stroke="var(--lg-cobalt)"
                strokeWidth="4"
                strokeLinecap="round"
                fill="none"
              />
              <path
                d="M 16 6 L 40 8 Q 33 14, 40 20 L 15 22 Z"
                fill="var(--lg-primary)"
              />
            </svg>
            <span className="login-form-brand-name">
              Pra<span>x</span>ys
            </span>
          </div>

          {cliCallback && (
            <div className="login-cli-banner">
              <span className="login-cli-banner-dot" aria-hidden />
              <span><Trans>Sign in to connect your CLI plugin.</Trans></span>
            </div>
          )}

          <div className="login-form-heading">
            <span className="login-form-eyebrow">
              {mode === 'login'
                ? <Trans>Sign in</Trans>
                : <Trans>Get access</Trans>}
            </span>
            <h2 className="login-form-title">
              {mode === 'login'
                ? <Trans>Welcome back.</Trans>
                : registrationOpen
                ? <Trans>Create your account.</Trans>
                : <Trans>Praxys is in private alpha.</Trans>}
            </h2>
          </div>

          <div
            className="login-tabs-list"
            role="group"
            aria-label={t`Authentication mode`}
          >
            <button
              type="button"
              aria-pressed={mode === 'login'}
              data-state={mode === 'login' ? 'active' : 'inactive'}
              className="login-tab"
              onClick={() => switchMode('login')}
            >
              <Trans>Sign in</Trans>
            </button>
            <button
              type="button"
              aria-pressed={mode === 'invite'}
              data-state={mode === 'invite' ? 'active' : 'inactive'}
              className="login-tab"
              onClick={() => switchMode('invite')}
            >
              {registrationOpen ? <Trans>Create account</Trans> : <Trans>Request invite</Trans>}
            </button>
          </div>

          {/* ───────────── Sign-in form ───────────── */}
          {mode === 'login' && (
            <form className="login-form" onSubmit={handleAuthSubmit} noValidate>
              {error && (
                <div className="login-error" role="alert">{error}</div>
              )}

              <div className="login-field">
                <label htmlFor={`${formId}-login-email`} className="login-field-label">
                  <Trans>Email</Trans>
                </label>
                <input
                  id={`${formId}-login-email`}
                  type="email"
                  autoComplete="email"
                  placeholder={t`you@example.com`}
                  className="login-input"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  disabled={submitting}
                  required
                />
              </div>

              <div className="login-field">
                <label htmlFor={`${formId}-login-pass`} className="login-field-label">
                  <Trans>Password</Trans>
                </label>
                <input
                  id={`${formId}-login-pass`}
                  type="password"
                  autoComplete="current-password"
                  className="login-input"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={submitting}
                  required
                />
              </div>

              <button type="submit" className="login-submit" disabled={submitting}>
                {submitting && <span className="login-submit-spinner" aria-hidden />}
                {submitting ? <Trans>Signing in…</Trans> : <Trans>Sign in</Trans>}
              </button>

              {showResend && (
                <div className="login-aside" role="status" aria-live="polite">
                  {resendState === 'sent' ? (
                    <Trans>Verification email sent. Check your inbox.</Trans>
                  ) : (
                    <>
                      <Trans>Didn't get the email?</Trans>{' '}
                      <button
                        type="button"
                        className="login-aside-link"
                        onClick={handleResend}
                        disabled={resendState === 'sending'}
                      >
                        {resendState === 'sending' ? <Trans>Sending…</Trans> : <Trans>Resend verification email</Trans>}
                      </button>
                    </>
                  )}
                </div>
              )}

              <div className="login-aside">
                <Trans>New to Praxys?</Trans>{' '}
                <button
                  type="button"
                  className="login-aside-link"
                  onClick={() => switchMode('invite')}
                >
                  {registrationOpen ? <Trans>Create an account</Trans> : <Trans>Request an invite</Trans>}
                </button>
              </div>
            </form>
          )}

          {/* ───────────── Request-invite tab ───────────── */}
          {mode === 'invite' && inviteMode === 'waitlist' && !waitlistSuccess && (
            <form className="login-form" onSubmit={handleWaitlistSubmit} noValidate>
              <div className="login-waitlist-intro">
                <span className="login-waitlist-intro-headline">
                  <Trans>Join the waitlist</Trans>
                </span>
                <Trans>
                  We're inviting runners in waves while we tighten the science.
                  Drop your email and we'll reach back when a slot opens.
                </Trans>
              </div>

              {error && (
                <div className="login-error" role="alert">{error}</div>
              )}

              <div className="login-field">
                <label htmlFor={`${formId}-wl-email`} className="login-field-label">
                  <Trans>Email</Trans>
                </label>
                <input
                  id={`${formId}-wl-email`}
                  type="email"
                  autoComplete="email"
                  placeholder={t`you@example.com`}
                  className="login-input"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  disabled={submitting}
                  required
                />
              </div>

              <div className="login-field">
                <label htmlFor={`${formId}-wl-note`} className="login-field-label">
                  <Trans>What's your training goal? (optional)</Trans>
                </label>
                <input
                  id={`${formId}-wl-note`}
                  type="text"
                  maxLength={500}
                  placeholder={t`Sub-3 marathon · 100K · stay healthy…`}
                  className="login-input"
                  value={waitlistNote}
                  onChange={(e) => setWaitlistNote(e.target.value)}
                  disabled={submitting}
                />
              </div>

              <button type="submit" className="login-submit" disabled={submitting}>
                {submitting && <span className="login-submit-spinner" aria-hidden />}
                {submitting ? <Trans>Saving…</Trans> : <Trans>Join the waitlist</Trans>}
              </button>

              <div className="login-aside">
                <Trans>Already have an invitation code?</Trans>{' '}
                <button
                  type="button"
                  className="login-aside-link"
                  onClick={() => { setInviteMode('code'); setError(null); }}
                >
                  <Trans>Use it</Trans>
                </button>
              </div>
            </form>
          )}

          {mode === 'invite' && inviteMode === 'waitlist' && waitlistSuccess && (
            <div className="login-form" role="status" aria-live="polite">
              <div className="login-waitlist-success">
                <span className="login-waitlist-success-mark" aria-hidden>✓</span>
                <span className="login-waitlist-success-body">
                  <Trans>
                    <strong>You're on the list.</strong> We'll reach out from{' '}
                    <a href={`mailto:${SUPPORT_EMAIL}`}>{SUPPORT_EMAIL}</a>{' '}
                    when a slot opens.
                  </Trans>
                </span>
              </div>
              <div className="login-aside">
                <Trans>Already have an invitation code?</Trans>{' '}
                <button
                  type="button"
                  className="login-aside-link"
                  onClick={() => {
                    setInviteMode('code');
                    setWaitlistSuccess(false);
                    setError(null);
                  }}
                >
                  <Trans>Use it</Trans>
                </button>
              </div>
            </div>
          )}

          {mode === 'invite' && verifyPending && (
            <div className="login-form" role="status" aria-live="polite">
              <div className="login-waitlist-success">
                <span className="login-waitlist-success-mark" aria-hidden>✓</span>
                <span className="login-waitlist-success-body">
                  <Trans>
                    <strong>Almost there.</strong> We sent a verification link to your
                    email. Click it to activate your account, then sign in.
                  </Trans>
                </span>
              </div>
              <div className="login-aside">
                <button
                  type="button"
                  className="login-aside-link"
                  onClick={() => { setVerifyPending(false); switchMode('login'); }}
                >
                  <Trans>Back to sign in</Trans>
                </button>
              </div>
            </div>
          )}

          {mode === 'invite' && inviteMode === 'code' && !verifyPending && (
            <form className="login-form" onSubmit={handleAuthSubmit} noValidate>
              {error && (
                <div className="login-error" role="alert">{error}</div>
              )}

              <div className="login-field">
                <label htmlFor={`${formId}-reg-email`} className="login-field-label">
                  <Trans>Email</Trans>
                </label>
                <input
                  id={`${formId}-reg-email`}
                  type="email"
                  autoComplete="email"
                  placeholder={t`you@example.com`}
                  className="login-input"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  disabled={submitting}
                  required
                />
              </div>

              <div className="login-field">
                <label htmlFor={`${formId}-reg-pass`} className="login-field-label">
                  <Trans>Password</Trans>
                </label>
                <input
                  id={`${formId}-reg-pass`}
                  type="password"
                  autoComplete="new-password"
                  className="login-input"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={submitting}
                  required
                />
              </div>

              <div className="login-field">
                <label htmlFor={`${formId}-reg-code`} className="login-field-label">
                  {registrationOpen ? <Trans>Invitation code (optional)</Trans> : <Trans>Invitation code</Trans>}
                </label>
                <input
                  id={`${formId}-reg-code`}
                  type="text"
                  placeholder="TS-XXXX-XXXX"
                  className="login-input login-input-mono"
                  value={invitationCode}
                  onChange={(e) => setInvitationCode(e.target.value.toUpperCase())}
                  disabled={submitting}
                  required={!registrationOpen}
                />
              </div>

              {/* Honeypot: hidden from real users; a filled value flags a bot. */}
              <div aria-hidden="true" style={{ position: 'absolute', left: '-9999px', width: 1, height: 1, overflow: 'hidden' }}>
                <label htmlFor={`${formId}-website`}>Website</label>
                <input
                  id={`${formId}-website`}
                  type="text"
                  tabIndex={-1}
                  autoComplete="off"
                  value={honeypot}
                  onChange={(e) => setHoneypot(e.target.value)}
                />
              </div>

              <label className="login-terms">
                <input
                  type="checkbox"
                  checked={agreedTerms}
                  onChange={(e) => setAgreedTerms(e.target.checked)}
                  disabled={submitting}
                />
                <span>
                  <Trans>
                    I agree to the{' '}
                    <Link to="/terms" target="_blank" className="login-aside-link">Terms of Service</Link>{' '}
                    and{' '}
                    <Link to="/privacy" target="_blank" className="login-aside-link">Privacy Policy</Link>.
                  </Trans>
                </span>
              </label>

              <button type="submit" className="login-submit" disabled={submitting || !agreedTerms}>
                {submitting && <span className="login-submit-spinner" aria-hidden />}
                {submitting ? <Trans>Creating account…</Trans> : <Trans>Create account</Trans>}
              </button>

              <div className="login-aside">
                {registrationOpen ? <Trans>Prefer to wait?</Trans> : <Trans>No code yet?</Trans>}{' '}
                <button
                  type="button"
                  className="login-aside-link"
                  onClick={() => { setInviteMode('waitlist'); setError(null); }}
                >
                  <Trans>Join the waitlist</Trans>
                </button>
              </div>
            </form>
          )}

          {/* ───────────── Form footer ───────────── */}
          <div className="login-form-foot">
            <a href={`mailto:${SUPPORT_EMAIL}`}>
              <Trans>Need help? {SUPPORT_EMAIL}</Trans>
            </a>
            <div className="login-form-foot-controls" role="group" aria-label={t`Display preferences`}>
              <button
                type="button"
                className="login-form-foot-button"
                onClick={() => setLocale(locale === 'en' ? 'zh' : 'en')}
                aria-label={t`Switch language`}
                title={t`Switch language`}
              >
                {locale === 'en' ? '中文' : 'EN'}
              </button>
              <button
                type="button"
                className="login-form-foot-button login-form-foot-icon"
                onClick={() => {
                  const next = theme === 'light' ? 'dark' : theme === 'dark' ? 'system' : 'light';
                  setTheme(next);
                }}
                aria-label={
                  theme === 'light'
                    ? t`Switch to dark theme`
                    : theme === 'dark'
                    ? t`Switch to system theme`
                    : t`Switch to light theme`
                }
                title={
                  theme === 'light'
                    ? t`Light theme (click for dark)`
                    : theme === 'dark'
                    ? t`Dark theme (click for system)`
                    : t`System theme (click for light)`
                }
              >
                {theme === 'light' ? (
                  <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <circle cx="8" cy="8" r="3" />
                    <path d="M8 1v2M8 13v2M1 8h2M13 8h2M3.05 3.05l1.41 1.41M11.54 11.54l1.41 1.41M3.05 12.95l1.41-1.41M11.54 4.46l1.41-1.41" />
                  </svg>
                ) : theme === 'dark' ? (
                  <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M13 9.5A5.5 5.5 0 0 1 6.5 3a5.5 5.5 0 1 0 6.5 6.5z" />
                  </svg>
                ) : (
                  <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <rect x="2" y="3" width="12" height="9" rx="1" />
                    <path d="M5 14h6" />
                  </svg>
                )}
              </button>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
