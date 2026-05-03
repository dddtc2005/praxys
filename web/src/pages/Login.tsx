import type React from 'react';
import { useState, useId } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
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

  // Form state
  const [mode, setMode] = useState<Mode>('login');
  const [inviteMode, setInviteMode] = useState<InviteMode>('waitlist');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [invitationCode, setInvitationCode] = useState('');
  const [waitlistNote, setWaitlistNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [waitlistSuccess, setWaitlistSuccess] = useState(false);

  const formId = useId();

  // CLI callback URL (browser-based CLI login flow).
  // SECURITY: Only allow localhost callbacks to prevent open redirect token theft
  const searchParams = new URLSearchParams(window.location.search);
  const rawCallback = searchParams.get('cli_callback');
  const CLI_CALLBACK_RE = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?\/callback/;
  const cliCallback = rawCallback && CLI_CALLBACK_RE.test(rawCallback) ? rawCallback : null;

  const handleAuthSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!email.trim() || !password.trim()) {
      setError(t`Email and password are required.`);
      return;
    }

    setSubmitting(true);

    const result = mode === 'login'
      ? await login(email.trim(), password)
      : await register(email.trim(), password, invitationCode.trim());

    setSubmitting(false);

    if (result.ok) {
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
    } else {
      setError(result.error || t`An unexpected error occurred.`);
    }
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
  };

  return (
    <div className="login-shell">
      {/* ──────────────────────── HERO PANE (left on desktop) ──────────────────────── */}
      <aside className="login-hero" aria-hidden={false}>
        <div className="login-hero-eyebrow">
          <span className="login-hero-eyebrow-dot" aria-hidden />
          <Trans>Private alpha · Invitation only</Trans>
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
          <Trans>A scientific training system that takes a position.</Trans>
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

        <div className="login-hero-foot">
          <span aria-hidden className="login-hero-foot-rule" />
          <span className="font-data">FIELD · LAB</span>
          <span aria-hidden className="login-hero-foot-rule" />
        </div>
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
              <Trans>Request invite</Trans>
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

              <div className="login-aside">
                <Trans>New to Praxys?</Trans>{' '}
                <button
                  type="button"
                  className="login-aside-link"
                  onClick={() => switchMode('invite')}
                >
                  <Trans>Request an invite</Trans>
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

          {mode === 'invite' && inviteMode === 'code' && (
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
                  <Trans>Invitation code</Trans>
                </label>
                <input
                  id={`${formId}-reg-code`}
                  type="text"
                  placeholder="TS-XXXX-XXXX"
                  className="login-input login-input-mono"
                  value={invitationCode}
                  onChange={(e) => setInvitationCode(e.target.value.toUpperCase())}
                  disabled={submitting}
                />
                <span className="login-field-hint">
                  <Trans>Leave blank if this is the first account on a fresh install.</Trans>
                </span>
              </div>

              <button type="submit" className="login-submit" disabled={submitting}>
                {submitting && <span className="login-submit-spinner" aria-hidden />}
                {submitting ? <Trans>Creating account…</Trans> : <Trans>Create account</Trans>}
              </button>

              <div className="login-aside">
                <Trans>No code yet?</Trans>{' '}
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
                className="login-form-foot-button"
                onClick={() => {
                  const next = theme === 'light' ? 'dark' : theme === 'dark' ? 'system' : 'light';
                  setTheme(next);
                }}
                aria-label={t`Toggle theme`}
                title={t`Toggle theme`}
              >
                {theme === 'light' ? '☀' : theme === 'dark' ? '☾' : '⌖'}
              </button>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
