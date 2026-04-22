import { useCallback, useEffect, useRef, useState } from 'react';
import { View, Text, Button, Input } from '@tarojs/components';
import Taro, { useDidShow } from '@tarojs/taro';

import {
  runLaunchLogin,
  saveToken,
  wechatLinkWithPassword,
  wechatRegister,
} from '@/lib/auth';
import type { ApiError } from '@/lib/api-client';
import { applyThemeChrome, themeClassName } from '@/lib/theme';
import './index.scss';

type Stage =
  | { kind: 'loading' }
  | { kind: 'choose'; ticket: string }
  | { kind: 'link'; ticket: string }
  | { kind: 'register'; ticket: string }
  | { kind: 'error'; message: string };

export default function LoginPage() {
  const [stage, setStage] = useState<Stage>({ kind: 'loading' });
  useDidShow(() => applyThemeChrome());

  // Guard against React.StrictMode double-invocation: a let/const inside the
  // effect would be reinitialized on each invocation, defeating the purpose.
  // A useRef survives both invocations so the second call aborts early.
  // Tencent's js_code is single-use (see api/routes/wechat.py), so letting
  // both run would burn the code and the second exchange would 40163.
  const inFlight = useRef(false);

  const runLogin = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const result = await runLaunchLogin();
      if (result.status === 'ok' && result.access_token) {
        saveToken(result.access_token);
        Taro.reLaunch({ url: '/pages/today/index' });
        return;
      }
      if (result.status === 'needs_setup' && result.wechat_login_ticket) {
        setStage({ kind: 'choose', ticket: result.wechat_login_ticket });
        return;
      }
      setStage({ kind: 'error', message: 'Unexpected login response' });
    } catch (e) {
      const msg = (e as Partial<ApiError>)?.detail ?? String(e);
      setStage({ kind: 'error', message: msg });
    } finally {
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    void runLogin();
  }, [runLogin]);

  const onRetry = () => {
    setStage({ kind: 'loading' });
    void runLogin();
  };

  if (stage.kind === 'loading') {
    return (
      <View className={`login-root ${themeClassName()}`}>
        <Text className="login-title">Signing you in…</Text>
      </View>
    );
  }

  if (stage.kind === 'error') {
    return (
      <View className={`login-root ${themeClassName()}`}>
        <Text className="login-title ts-destructive">Sign-in failed</Text>
        <Text className="login-detail">{stage.message}</Text>
        <Button className="ts-button" onClick={onRetry}>
          Retry
        </Button>
      </View>
    );
  }

  if (stage.kind === 'choose') {
    return (
      <View className={`login-root ${themeClassName()}`}>
        <Text className="login-title">Welcome to Praxys</Text>
        <Text className="login-detail">
          Let's connect your WeChat to a Praxys account.
        </Text>
        <Button
          className="ts-button login-cta"
          onClick={() => setStage({ kind: 'link', ticket: stage.ticket })}
        >
          I already have an account
        </Button>
        <Button
          className="ts-button ts-button--secondary login-cta"
          onClick={() => setStage({ kind: 'register', ticket: stage.ticket })}
        >
          I'm new
        </Button>
      </View>
    );
  }

  if (stage.kind === 'link') {
    return (
      <LinkForm
        ticket={stage.ticket}
        onBack={() => setStage({ kind: 'choose', ticket: stage.ticket })}
      />
    );
  }

  return (
    <RegisterForm
      ticket={stage.ticket}
      onBack={() => setStage({ kind: 'choose', ticket: stage.ticket })}
    />
  );
}

// ---------------------------------------------------------------------------
// Link subform — existing web users bind WeChat to their account.
// ---------------------------------------------------------------------------

interface FormProps {
  ticket: string;
  onBack: () => void;
}

function LinkForm({ ticket, onBack }: FormProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit() {
    if (!email || !password) {
      setError('Email and password are required');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const r = await wechatLinkWithPassword(ticket, email, password);
      saveToken(r.access_token);
      Taro.reLaunch({ url: '/pages/today/index' });
    } catch (e) {
      setError((e as Partial<ApiError>)?.detail ?? String(e));
      setSubmitting(false);
    }
  }

  return (
    <View className={`login-root ${themeClassName()}`}>
      <Text className="login-title">Link your account</Text>
      <Text className="login-detail">
        Enter the email + password you use on praxys.app.
      </Text>
      <Input
        className="ts-input login-input"
        type="text"
        placeholder="email"
        placeholderStyle="color: #8b93a7;"
        value={email}
        onInput={(e) => setEmail(e.detail.value)}
      />
      <Input
        className="ts-input login-input"
        password
        placeholder="password"
        placeholderStyle="color: #8b93a7;"
        value={password}
        onInput={(e) => setPassword(e.detail.value)}
      />
      {error && <Text className="login-error ts-destructive">{error}</Text>}
      <Button className="ts-button login-cta" loading={submitting} onClick={onSubmit}>
        Link
      </Button>
      <Button className="ts-button ts-button--secondary login-cta" onClick={onBack}>
        Back
      </Button>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Register subform — new users with an invitation code.
// ---------------------------------------------------------------------------

function RegisterForm({ ticket, onBack }: FormProps) {
  const [invitationCode, setInvitationCode] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit() {
    setSubmitting(true);
    setError(null);
    try {
      const r = await wechatRegister(
        ticket,
        invitationCode,
        email || undefined,
        password || undefined,
      );
      saveToken(r.access_token);
      Taro.reLaunch({ url: '/pages/today/index' });
    } catch (e) {
      setError((e as Partial<ApiError>)?.detail ?? String(e));
      setSubmitting(false);
    }
  }

  return (
    <View className={`login-root ${themeClassName()}`}>
      <Text className="login-title">Create your account</Text>
      <Text className="login-detail">
        Praxys is invite-only while in beta. Email + password are optional
        (you can add them later to also log in on the web).
      </Text>
      <Input
        className="ts-input login-input"
        type="text"
        placeholder="invitation code (required)"
        placeholderStyle="color: #8b93a7;"
        value={invitationCode}
        onInput={(e) => setInvitationCode(e.detail.value.toUpperCase())}
      />
      <Input
        className="ts-input login-input"
        type="text"
        placeholder="email (optional)"
        placeholderStyle="color: #8b93a7;"
        value={email}
        onInput={(e) => setEmail(e.detail.value)}
      />
      <Input
        className="ts-input login-input"
        password
        placeholder="password (optional)"
        placeholderStyle="color: #8b93a7;"
        value={password}
        onInput={(e) => setPassword(e.detail.value)}
      />
      {error && <Text className="login-error ts-destructive">{error}</Text>}
      <Button className="ts-button login-cta" loading={submitting} onClick={onSubmit}>
        Sign up
      </Button>
      <Button className="ts-button ts-button--secondary login-cta" onClick={onBack}>
        Back
      </Button>
    </View>
  );
}
