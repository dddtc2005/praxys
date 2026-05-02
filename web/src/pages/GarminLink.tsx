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
 *  1. Settings POSTs credentials, gets a session_id, redirects here.
 *  2. We open WS to /api/settings/connections/garmin/interactive/{id}/ws
 *     with our JWT in the query string (WS can't set Authorization).
 *  3. Render frames on a canvas; capture clicks/keystrokes scaled to
 *     the server-side viewport coordinate system.
 *  4. Backend emits {type: "complete", success: true} when tokens are
 *     captured and persisted; we redirect back to Settings.
 *  5. {type: "error"} surfaces a message and offers retry.
 *
 * The page intentionally lives outside Layout — we want the viewport to
 * dominate so coordinate math stays simple.
 */
import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Trans } from '@lingui/react/macro';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { API_BASE } from '@/hooks/useApi';
import { KEYS, getCompatItem } from '@/lib/storage-compat';

// Must match backend api/routes/garmin_link.py constants. The session
// captures at this resolution; we display at the same logical pixels
// to keep click coordinate math 1:1 with the Playwright viewport.
const VIEWPORT_W = 1024;
const VIEWPORT_H = 768;

type ConnState = 'connecting' | 'live' | 'complete' | 'error' | 'closed';

export default function GarminLink() {
  const [params] = useSearchParams();
  const sessionId = params.get('session');
  const navigate = useNavigate();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const [state, setState] = useState<ConnState>('connecting');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Open the WS once we have a session id and a token; tear it down on
  // unmount so we don't leak Playwright sessions when the user navigates
  // away mid-flow.
  useEffect(() => {
    if (!sessionId) {
      setState('error');
      setErrorMsg('Missing session id');
      return;
    }

    const token = getCompatItem(KEYS.authToken.new, KEYS.authToken.legacy);
    if (!token) {
      setState('error');
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

    ws.onopen = () => setState('live');
    ws.onmessage = (ev) => {
      let msg: { type?: string; b64?: string; success?: boolean; message?: string };
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type === 'frame' && msg.b64) {
        drawFrame(canvasRef.current, msg.b64);
      } else if (msg.type === 'complete' && msg.success) {
        setState('complete');
        setTimeout(() => navigate('/settings'), 1500);
      } else if (msg.type === 'error') {
        setState('error');
        setErrorMsg(msg.message || 'Login failed');
      }
    };
    ws.onerror = () => {
      setState('error');
      setErrorMsg('Connection error — try again.');
    };
    ws.onclose = () => {
      setState((s) => (s === 'complete' || s === 'error' ? s : 'closed'));
    };

    return () => {
      try { ws.close(); } catch { /* ignore */ }
    };
  }, [sessionId, navigate]);

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

  // Forward keyboard on canvas focus. We don't capture passwords here —
  // those are pre-filled server-side from the credentials the user
  // already submitted to /interactive — so the keyboard relay is for
  // CAPTCHA / MFA / occasional in-page typing only.
  function sendKey(e: React.KeyboardEvent<HTMLCanvasElement>) {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    e.preventDefault();
    if (e.key.length === 1) {
      ws.send(JSON.stringify({ type: 'type', text: e.key }));
    } else {
      // Map a few common non-printables to Playwright's keyboard names.
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
          We've started a browser session on our server and pre-filled your
          Garmin credentials. Solve any CAPTCHA or MFA challenge in the
          window below to complete sign-in. We capture the resulting tokens
          automatically — you won't need to do this again unless they expire
          (~30 days).
        </Trans>
      </p>

      {state === 'connecting' && (
        <p className="text-xs text-muted-foreground">
          <Trans>Connecting to browser session…</Trans>
        </p>
      )}

      {state === 'error' && errorMsg && (
        <Alert variant="destructive" className="max-w-3xl">
          <AlertDescription>{errorMsg}</AlertDescription>
        </Alert>
      )}

      {state === 'complete' && (
        <Alert className="max-w-3xl">
          <AlertDescription>
            <Trans>Connected — redirecting to Settings…</Trans>
          </AlertDescription>
        </Alert>
      )}

      <canvas
        ref={canvasRef}
        width={VIEWPORT_W}
        height={VIEWPORT_H}
        tabIndex={0}
        onClick={sendClick}
        onKeyDown={sendKey}
        className="border border-border rounded-md max-w-full h-auto cursor-pointer outline-none focus:ring-2 focus:ring-primary"
        style={{ aspectRatio: `${VIEWPORT_W} / ${VIEWPORT_H}` }}
      />

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
