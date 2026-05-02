/**
 * Interactive Garmin login viewport.
 *
 * Backend (api/routes/garmin_link.py) drives a Playwright Chromium on
 * App Service that talks to sso.garmin.com from our IP — solving Garmin's
 * per-IP CAPTCHA gate that locks our headless flow out. This page is the
 * remote viewer: WebSocket carries JPEG frames at ~5fps and forwards
 * mouse/keyboard events back. The user solves CAPTCHA / MFA inline.
 *
 * Lifecycle:
 *  1. Settings POSTs region, gets a session_id, redirects here.
 *  2. We open WS to /api/settings/connections/garmin/interactive/{id}/ws
 *     with our JWT in the query string (WS can't set Authorization).
 *  3. Render frames on a canvas; capture clicks/keystrokes scaled to
 *     the server-side viewport coordinate system.
 *  4. Backend emits {type: "complete", success: true} when tokens are
 *     captured and persisted; we redirect back to Settings.
 *  5. {type: "error"} surfaces a message and offers retry.
 *
 * Loading choreography
 * --------------------
 * Cold-launching Chromium and navigating to Garmin's SSO page costs
 * ~3-5s on a warm host and longer on first install. A blank page during
 * that window felt broken in user testing, so we sequence the wait
 * across three phases:
 *   1. ``connecting``  — WS handshake in flight.
 *   2. ``launching``   — server-side ``_run_browser_session`` thread is
 *      starting Playwright (state polled from the GET endpoint).
 *   3. ``navigating``  — Playwright is loading the SSO page; we're
 *      between ``state === "ready"`` server-side and the first JPEG
 *      frame arriving.
 *   4. ``live``        — first frame arrived, canvas is interactive.
 *
 * Each transition is gated on a real signal (WS open, GET state poll,
 * first frame) — never timer-driven theatre. Reduced-motion users get
 * the same status text without the breathing dot.
 *
 * The page intentionally lives outside Layout — we want the viewport to
 * dominate so coordinate math stays simple.
 */
import { Fragment, useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Trans, useLingui } from '@lingui/react/macro';
import { msg } from '@lingui/core/macro';
import type { MessageDescriptor } from '@lingui/core';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { API_BASE } from '@/hooks/useApi';
import { KEYS, getCompatItem } from '@/lib/storage-compat';
import { cn } from '@/lib/utils';

// Default viewport while the GET endpoint hasn't yet told us the
// actual session resolution. The backend sizes Playwright per session
// based on the user's available canvas; we mirror that here as the
// canvas's logical pixel size so clicks land 1:1 in the relayed page.
const VIEWPORT_W_DEFAULT = 1280;
const VIEWPORT_H_DEFAULT = 800;

type LinkPhase =
  | 'connecting'
  | 'launching'
  | 'navigating'
  | 'live'
  | 'complete'
  | 'error'
  | 'closed';

const PROGRESS_STEPS: { id: 'connecting' | 'launching' | 'navigating'; label: MessageDescriptor }[] = [
  { id: 'connecting', label: msg`Connecting` },
  { id: 'launching', label: msg`Launching browser` },
  { id: 'navigating', label: msg`Loading Garmin` },
];

// Phase ordinality for the progress strip's "done / active / pending" check.
// ``live`` and ``complete`` count as past every progress step.
function phaseIndex(p: LinkPhase): number {
  switch (p) {
    case 'connecting': return 0;
    case 'launching': return 1;
    case 'navigating': return 2;
    case 'live':
    case 'complete':
      return 3;
    default:
      return -1;
  }
}

export default function GarminLink() {
  const [params] = useSearchParams();
  const sessionId = params.get('session');
  const navigate = useNavigate();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const [phase, setPhase] = useState<LinkPhase>('connecting');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [viewport, setViewport] = useState<{ w: number; h: number }>({
    w: VIEWPORT_W_DEFAULT, h: VIEWPORT_H_DEFAULT,
  });
  const { i18n } = useLingui();

  // Open the WS once we have a session id and a token; tear it down on
  // unmount so we don't leak Playwright sessions when the user navigates
  // away mid-flow.
  useEffect(() => {
    if (!sessionId) {
      setPhase('error');
      setErrorMsg('Missing session id');
      return;
    }

    const token = getCompatItem(KEYS.authToken.new, KEYS.authToken.legacy);
    if (!token) {
      setPhase('error');
      setErrorMsg('Not signed in');
      return;
    }

    // Build the WS URL by swapping http(s)://api → ws(s)://api on the
    // configured API_BASE. When VITE_API_URL is empty (same-origin
    // deploy) we use window.location for the host, since the bare
    // "/api/..." path with no host doesn't form a valid WS URL.
    const baseHttp = API_BASE || window.location.origin;
    const wsBase = baseHttp.replace(/^http/, 'ws');
    const url = `${wsBase}/api/settings/connections/garmin/interactive/${encodeURIComponent(sessionId)}/ws?token=${encodeURIComponent(token)}`;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => setPhase((p) => (p === 'connecting' ? 'launching' : p));
    ws.onmessage = (ev) => {
      let m: { type?: string; b64?: string; success?: boolean; message?: string };
      try {
        m = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (m.type === 'frame' && m.b64) {
        // First frame is the signal that everything's ready end-to-end.
        // Subsequent frames just render; the phase stays ``live``.
        setPhase((p) => (p === 'live' || p === 'complete' ? p : 'live'));
        drawFrame(canvasRef.current, m.b64);
      } else if (m.type === 'complete' && m.success) {
        setPhase('complete');
        setTimeout(() => navigate('/settings'), 1500);
      } else if (m.type === 'error') {
        setPhase('error');
        setErrorMsg(m.message || 'Login failed');
      }
    };
    ws.onerror = () => {
      setPhase('error');
      setErrorMsg('Connection error — try again.');
    };
    ws.onclose = () => {
      setPhase((p) => (p === 'complete' || p === 'error' ? p : 'closed'));
    };

    return () => {
      try { ws.close(); } catch { /* ignore */ }
    };
  }, [sessionId, navigate]);

  // Poll the server-side session state while we're between WS-open and
  // first-frame-received. This drives the ``launching → navigating``
  // transition: the backend flips ``state`` from ``"starting"`` to
  // ``"ready"`` once Playwright has finished the goto() — at that
  // point the user knows the browser exists and we're now waiting on
  // the actual SSO page to render. Cleared the moment we transition
  // into ``live`` (first frame) so we don't keep polling unnecessarily.
  useEffect(() => {
    if (phase !== 'launching' && phase !== 'navigating') return;
    if (!sessionId) return;
    const token = getCompatItem(KEYS.authToken.new, KEYS.authToken.legacy);
    if (!token) return;

    let cancelled = false;
    const tick = async () => {
      try {
        const res = await fetch(
          `${API_BASE}/api/settings/connections/garmin/interactive/${encodeURIComponent(sessionId)}`,
          { headers: { Authorization: `Bearer ${token}` } },
        );
        if (cancelled) return;
        if (!res.ok) return;
        const data = await res.json() as {
          state?: string;
          error_message?: string;
          viewport?: { width?: number; height?: number };
        };
        if (data.viewport?.width && data.viewport?.height) {
          setViewport({ w: data.viewport.width, h: data.viewport.height });
        }
        if (data.state === 'ready') {
          setPhase((p) => (p === 'launching' ? 'navigating' : p));
        } else if (data.state === 'failed') {
          setPhase('error');
          setErrorMsg(data.error_message || 'Browser session failed to start.');
        }
      } catch {
        // Transient network blip during polling isn't fatal — we'll
        // catch the next tick or the WS will surface the failure.
      }
    };
    void tick();
    const interval = setInterval(tick, 1500);
    return () => { cancelled = true; clearInterval(interval); };
  }, [phase, sessionId]);

  // Translate a click on the displayed canvas back to coordinates in
  // Playwright's viewport. The canvas maintains the server's logical
  // pixel size via its width/height attrs, but CSS may scale it for
  // a smaller window — getBoundingClientRect gives us the actual
  // displayed size to scale by.
  function sendClick(e: React.MouseEvent<HTMLCanvasElement>) {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const sx = canvas.width / rect.width;
    const sy = canvas.height / rect.height;
    const x = Math.round((e.clientX - rect.left) * sx);
    const y = Math.round((e.clientY - rect.top) * sy);
    ws.send(JSON.stringify({ type: 'click', x, y }));
  }

  // Forward keyboard on canvas focus — used for typing into Garmin's
  // login form (email, password, MFA code) and any in-page CAPTCHA UI.
  function sendKey(e: React.KeyboardEvent<HTMLCanvasElement>) {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    e.preventDefault();
    if (e.key.length === 1) {
      ws.send(JSON.stringify({ type: 'type', text: e.key }));
    } else {
      const map: Record<string, string> = {
        Enter: 'Enter',
        Backspace: 'Backspace',
        Tab: 'Tab',
        ArrowUp: 'ArrowUp',
        ArrowDown: 'ArrowDown',
        ArrowLeft: 'ArrowLeft',
        ArrowRight: 'ArrowRight',
        Escape: 'Escape',
      };
      const key = map[e.key];
      if (key) ws.send(JSON.stringify({ type: 'key', key }));
    }
  }

  const isLoading = phase !== 'live' && phase !== 'complete' && phase !== 'error';

  return (
    <div className="min-h-screen bg-background flex flex-col items-center p-4 gap-4">
      <div className="w-full max-w-3xl flex items-center justify-between">
        <h1 className="text-lg font-semibold">
          <Trans>Garmin interactive login</Trans>
        </h1>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate('/settings')}
        >
          <Trans>Cancel</Trans>
        </Button>
      </div>

      <p className="text-sm text-muted-foreground max-w-3xl">
        <Trans>
          We've started a browser session on our server. Type your Garmin
          credentials in the window below and complete any CAPTCHA or MFA
          challenge — that lets the challenge resolve against our IP. We
          capture the resulting tokens automatically; you won't need to
          do this again unless they expire (~30 days).
        </Trans>
      </p>

      {/* Progress indicator — three phases, gated on real signals. */}
      {isLoading && (
        <ProgressStrip phase={phase} t={(d) => i18n._(d)} />
      )}

      {phase === 'error' && errorMsg && (
        <Alert variant="destructive" className="max-w-3xl">
          <AlertDescription>{errorMsg}</AlertDescription>
        </Alert>
      )}

      {phase === 'complete' && (
        <Alert className="max-w-3xl">
          <AlertDescription>
            <Trans>Connected — redirecting to Settings…</Trans>
          </AlertDescription>
        </Alert>
      )}

      <div
        className="relative w-full"
        style={{
          maxWidth: `${viewport.w}px`,
          aspectRatio: `${viewport.w} / ${viewport.h}`,
        }}
      >
        <canvas
          ref={canvasRef}
          width={viewport.w}
          height={viewport.h}
          tabIndex={0}
          onClick={sendClick}
          onKeyDown={sendKey}
          className={cn(
            'absolute inset-0 h-full w-full rounded-md border border-border outline-none transition-opacity duration-300',
            phase === 'live' || phase === 'complete'
              ? 'cursor-pointer opacity-100 focus:ring-2 focus:ring-primary'
              : 'opacity-0 pointer-events-none',
          )}
        />
        {isLoading && <ViewportSkeleton />}
      </div>

      <p className="text-xs text-muted-foreground max-w-3xl">
        <Trans>
          Click the viewport to give it focus before typing. The browser
          session expires after 10 minutes — if it does, return to Settings
          and start over.
        </Trans>
      </p>
    </div>
  );
}

function drawFrame(canvas: HTMLCanvasElement | null, b64: string) {
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  const img = new Image();
  img.onload = () => {
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  };
  img.src = `data:image/jpeg;base64,${b64}`;
}

/**
 * Three-step progress strip: ●─○─○. Done steps lock to ``primary``
 * (the action color, same hue used everywhere a step has completed);
 * the active step pulses in ``accent-cobalt`` (the reasoning color —
 * the system showing the user *what it's currently doing*); pending
 * steps stay muted. ``animate-ping`` is provided by Tailwind v4 and
 * respects ``prefers-reduced-motion: reduce`` via the global motion
 * reset, so motion-sensitive users get the same color-coded states
 * without the radial pulse.
 */
function ProgressStrip({
  phase,
  t,
}: {
  phase: LinkPhase;
  t: (d: MessageDescriptor) => string;
}) {
  const currentIdx = phaseIndex(phase);
  return (
    <ol className="flex items-center gap-3 font-data text-[11px] uppercase tracking-wider">
      {PROGRESS_STEPS.map((step, i) => {
        const isDone = i < currentIdx;
        const isActive = i === currentIdx;
        return (
          <Fragment key={step.id}>
            <li
              className={cn(
                'flex items-center gap-2',
                isDone && 'text-primary',
                isActive && 'text-accent-cobalt',
                !isDone && !isActive && 'text-muted-foreground/60',
              )}
            >
              <span className="relative flex h-2 w-2">
                {isActive && (
                  <span className="absolute inset-0 animate-ping rounded-full bg-accent-cobalt/40" />
                )}
                <span
                  className={cn(
                    'relative h-2 w-2 rounded-full',
                    isDone && 'bg-primary',
                    isActive && 'bg-accent-cobalt',
                    !isDone && !isActive && 'bg-muted-foreground/40',
                  )}
                />
              </span>
              <span>{t(step.label)}</span>
            </li>
            {i < PROGRESS_STEPS.length - 1 && (
              <span
                aria-hidden
                className={cn(
                  'h-px w-6 transition-colors duration-200',
                  i < currentIdx ? 'bg-primary' : 'bg-muted-foreground/20',
                )}
              />
            )}
          </Fragment>
        );
      })}
    </ol>
  );
}

/**
 * Calm placeholder behind the canvas. Two design intents:
 *   1. Communicate "the viewport will be HERE" — so the page doesn't
 *      reflow once the first frame arrives.
 *   2. Acknowledge the wait without theatrics: a single breathing
 *      cobalt dot (the reasoning color — the system narrating its
 *      own state) plus a label, no shimmer sweep, no skeleton bars.
 *      Praxys is a "Field Lab" instrument, not a SaaS dashboard.
 *
 * The shimmer sweep is rendered with ``transform`` only and animates
 * for ~1.4s on an ease-out-expo curve, well under the 60fps budget.
 */
function ViewportSkeleton() {
  return (
    <div
      className="absolute inset-0 grid place-items-center overflow-hidden rounded-md border border-border bg-card"
      aria-hidden
    >
      <div
        className="absolute inset-y-0 -left-1/3 w-1/3 bg-gradient-to-r from-transparent via-foreground/[0.04] to-transparent motion-reduce:hidden"
        style={{
          animation: 'garmin-link-sweep 1800ms cubic-bezier(0.16, 1, 0.3, 1) infinite',
        }}
      />
      <div className="relative flex flex-col items-center gap-2 text-center">
        <span className="relative flex h-3 w-3">
          <span className="absolute inset-0 animate-ping rounded-full bg-accent-cobalt/40" />
          <span className="relative h-3 w-3 rounded-full bg-accent-cobalt" />
        </span>
        <span className="font-data text-[10px] uppercase tracking-wider text-muted-foreground">
          <Trans>Preparing browser session</Trans>
        </span>
      </div>
      <style>{`
        @keyframes garmin-link-sweep {
          0%   { transform: translateX(0); }
          100% { transform: translateX(450%); }
        }
      `}</style>
    </div>
  );
}
