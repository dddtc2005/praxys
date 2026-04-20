import type React from 'react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Trans, useLingui } from '@lingui/react/macro';

export default function Login() {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const { t } = useLingui();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [invitationCode, setInvitationCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [activeTab, setActiveTab] = useState('login');

  // Check for CLI callback URL (browser-based CLI login flow)
  // SECURITY: Only allow localhost callbacks to prevent open redirect token theft
  const searchParams = new URLSearchParams(window.location.search);
  const rawCallback = searchParams.get('cli_callback');
  const CLI_CALLBACK_RE = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?\/callback/;
  const cliCallback = rawCallback && CLI_CALLBACK_RE.test(rawCallback) ? rawCallback : null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!email.trim() || !password.trim()) {
      setError(t`Email and password are required.`);
      return;
    }

    setSubmitting(true);

    const result = activeTab === 'login'
      ? await login(email, password)
      : await register(email, password, invitationCode);

    setSubmitting(false);

    if (result.ok) {
      // If this was a CLI login flow, redirect token to the CLI's local server
      if (cliCallback) {
        const token = localStorage.getItem('praxys-auth-token') ?? localStorage.getItem('trainsight-auth-token');
        if (token) {
          window.location.href = `${cliCallback}?token=${encodeURIComponent(token)}`;
          return;
        }
      }
      navigate('/', { replace: true });
    } else {
      setError(result.error || t`An unexpected error occurred.`);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-6 sm:px-6 lg:px-8 bg-background">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <CardTitle className="text-xl font-bold text-foreground">Praxys</CardTitle>
          <CardDescription>
            {cliCallback
              ? <Trans>Log in to connect your CLI plugin</Trans>
              : <Trans>Power-based training dashboard</Trans>}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs value={activeTab} onValueChange={(v) => { setActiveTab(v as string); setError(null); }}>
            <TabsList className="w-full">
              <TabsTrigger value="login" className="flex-1"><Trans>Login</Trans></TabsTrigger>
              <TabsTrigger value="register" className="flex-1"><Trans>Register</Trans></TabsTrigger>
            </TabsList>

            <TabsContent value="login">
              <form onSubmit={handleSubmit} className="space-y-4 mt-4">
                {error && (
                  <Alert variant="destructive">
                    <AlertDescription>{error}</AlertDescription>
                  </Alert>
                )}
                <div className="space-y-2">
                  <Label htmlFor="login-email"><Trans>Email</Trans></Label>
                  <Input
                    id="login-email"
                    type="email"
                    placeholder={t`you@example.com`}
                    autoComplete="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    disabled={submitting}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="login-password"><Trans>Password</Trans></Label>
                  <Input
                    id="login-password"
                    type="password"
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    disabled={submitting}
                  />
                </div>
                <Button type="submit" className="w-full" disabled={submitting}>
                  {submitting ? <Trans>Signing in...</Trans> : <Trans>Sign in</Trans>}
                </Button>
              </form>
            </TabsContent>

            <TabsContent value="register">
              <form onSubmit={handleSubmit} className="space-y-4 mt-4">
                {error && (
                  <Alert variant="destructive">
                    <AlertDescription>{error}</AlertDescription>
                  </Alert>
                )}
                <div className="space-y-2">
                  <Label htmlFor="register-email"><Trans>Email</Trans></Label>
                  <Input
                    id="register-email"
                    type="email"
                    placeholder={t`you@example.com`}
                    autoComplete="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    disabled={submitting}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="register-password"><Trans>Password</Trans></Label>
                  <Input
                    id="register-password"
                    type="password"
                    autoComplete="new-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    disabled={submitting}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="register-invitation"><Trans>Invitation Code</Trans></Label>
                  <Input
                    id="register-invitation"
                    type="text"
                    placeholder="TS-XXXX-XXXX"
                    value={invitationCode}
                    onChange={(e) => setInvitationCode(e.target.value.toUpperCase())}
                    disabled={submitting}
                    className="font-data tracking-wider"
                  />
                  <p className="text-[10px] text-muted-foreground">
                    <Trans>Leave blank for the first account. Required after that.</Trans>
                  </p>
                </div>
                <Button type="submit" className="w-full" disabled={submitting}>
                  {submitting ? <Trans>Creating account...</Trans> : <Trans>Create account</Trans>}
                </Button>
              </form>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  );
}
