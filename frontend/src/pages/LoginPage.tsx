import { FormEvent, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { resendVerification } from '../api/auth';
import { getApiErrorCode } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { useAuthConfig } from '../hooks/useAuthConfig';
import { authErrorMessage, loginErrorMessage } from '../utils/authFlow';
import { sanitizeNextPath } from '../utils/nextPath';
import AuthLayout from '../components/AuthLayout';
import OAuthButtons from '../components/OAuthButtons';
import StatusToasts from '../components/StatusToasts';
import PasswordInput from '../components/PasswordInput';

export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [searchParams] = useSearchParams();
  // The OAuth callback redirects here with ?error=<code>.
  const [error, setError] = useState(() => loginErrorMessage(searchParams.get('error')));
  const [success, setSuccess] = useState('');
  const [needsVerification, setNeedsVerification] = useState(
    () => searchParams.get('error') === 'email_not_verified',
  );
  const [submitting, setSubmitting] = useState(false);
  const [resending, setResending] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();
  const config = useAuthConfig();
  // Where Protected wanted to send them. Validated, never trusted — an
  // unchecked ?next= is an open redirect aimed at a user who has just typed
  // their password. See utils/nextPath.ts.
  const next = sanitizeNextPath(searchParams.get('next'));

  async function onSubmit(event: FormEvent) {
    event.preventDefault();

    try {
      setSubmitting(true);
      setError('');
      setSuccess('');
      setNeedsVerification(false);
      await login(email, password);
      navigate(next, { replace: true });
    } catch (err) {
      setNeedsVerification(getApiErrorCode(err) === 'email_not_verified');
      setError(authErrorMessage(err, 'Unable to sign in'));
    } finally {
      setSubmitting(false);
    }
  }

  async function onResend() {
    if (!email.trim()) {
      setError('Enter your email address above, then ask for the link again.');
      return;
    }
    try {
      setResending(true);
      setError('');
      const res = await resendVerification(email.trim());
      setSuccess(res.detail || 'If that account needs verifying, a new link is on its way.');
    } catch (err) {
      setError(authErrorMessage(err, 'Unable to resend the verification email'));
    } finally {
      setResending(false);
    }
  }

  return (
    <AuthLayout title="Login">
      <div>
        <p className="eyebrow">Sign in</p>
        <h2 className="page-title">Access the workspace</h2>
        <p className="section-copy">Sign in to load your invoicing workspace.</p>
      </div>

      <OAuthButtons providers={config.providers} next={next} />

      <form onSubmit={onSubmit} className="stack">
        <div className="field--full">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            className="input"
            type="email"
            placeholder="you@example.com"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            autoComplete="email"
          />
        </div>

        <div className="field--full">
          <label htmlFor="password">Password</label>
          <PasswordInput
            id="password"
            className="input"
            placeholder="Enter password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
          />
        </div>

        <StatusToasts error={error} success={success} onClearError={() => setError('')} onClearSuccess={() => setSuccess('')} />

        {needsVerification ? (
          <button
            type="button"
            className="button button--ghost"
            onClick={() => void onResend()}
            disabled={resending}
          >
            {resending ? 'Sending...' : 'Resend verification email'}
          </button>
        ) : null}

        <button className="button button--primary" disabled={submitting} title="Open dashboard" aria-label="Open dashboard">
          {submitting ? 'Signing in...' : 'Open dashboard'}
        </button>
      </form>

      {config.password_signup_enabled ? (
        <p className="muted-text" style={{ margin: 0 }}>
          <Link to="/forgot-password">Forgot password?</Link>
          {' · '}
          <Link to="/register">Create account</Link>
        </p>
      ) : null}
    </AuthLayout>
  );
}
