import { FormEvent, useState } from 'react';
import { Link } from 'react-router-dom';
import { registerAccount, resendVerification } from '../api/auth';
import { useAuthConfig } from '../hooks/useAuthConfig';
import { authErrorMessage } from '../utils/authFlow';
import AuthLayout from '../components/AuthLayout';
import OAuthButtons from '../components/OAuthButtons';
import StatusToasts from '../components/StatusToasts';

export default function RegisterPage() {
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submittedEmail, setSubmittedEmail] = useState<string | null>(null);
  const config = useAuthConfig();

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    try {
      setSubmitting(true);
      setError('');
      await registerAccount({ email: email.trim(), full_name: fullName.trim() });
      // The API answers the same whether or not the address was already
      // registered, so this screen must not claim an account was created.
      setSubmittedEmail(email.trim());
    } catch (err) {
      setError(authErrorMessage(err, 'Unable to create the account'));
    } finally {
      setSubmitting(false);
    }
  }

  async function onResend() {
    if (!submittedEmail) return;
    try {
      setError('');
      const res = await resendVerification(submittedEmail);
      setSuccess(res.detail || 'If that account needs verifying, a new link is on its way.');
    } catch (err) {
      setError(authErrorMessage(err, 'Unable to resend the verification email'));
    }
  }

  const toasts = (
    <StatusToasts error={error} success={success} onClearError={() => setError('')} onClearSuccess={() => setSuccess('')} />
  );

  if (submittedEmail) {
    return (
      <AuthLayout title="Check your email">
        <div>
          <p className="eyebrow">Almost there</p>
          <h2 className="page-title">Check your email</h2>
          <p className="section-copy">
            If {submittedEmail} can be registered, we have sent a link to it. Open the link to confirm
            your address and choose your password.
          </p>
        </div>
        {toasts}
        <button type="button" className="button button--ghost" onClick={() => void onResend()}>
          Resend verification email
        </button>
        <p className="muted-text" style={{ margin: 0 }}>
          <Link to="/login">Back to sign in</Link>
        </p>
      </AuthLayout>
    );
  }

  // The route is public, but a deployment without self-registration answers
  // /auth/register with 404, so there is nothing to offer.
  if (!config.isLoading && !config.password_signup_enabled && config.providers.length === 0) {
    return (
      <AuthLayout title="Create account">
        <div>
          <p className="eyebrow">Create account</p>
          <h2 className="page-title">Sign-up is not available</h2>
          <p className="section-copy">This workspace does not accept new sign-ups. Ask an administrator for an account.</p>
        </div>
        <p className="muted-text" style={{ margin: 0 }}>
          <Link to="/login">Back to sign in</Link>
        </p>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title="Create account">
      <div>
        <p className="eyebrow">Create account</p>
        <h2 className="page-title">Start invoicing</h2>
        <p className="section-copy">We will email you a link to choose your password, then you can set up your company.</p>
      </div>

      <OAuthButtons providers={config.providers} next="/" label="Sign up with" />

      {config.password_signup_enabled ? (
        <form onSubmit={onSubmit} className="stack">
          <div className="field--full">
            <label htmlFor="full-name">Full name</label>
            <input
              id="full-name"
              className="input"
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
              autoComplete="name"
              required
            />
          </div>
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
              required
            />
          </div>
          {toasts}

          <button className="button button--primary" disabled={submitting}>
            {submitting ? 'Creating account...' : 'Create account'}
          </button>
        </form>
      ) : (
        toasts
      )}

      <p className="muted-text" style={{ margin: 0 }}>
        Already have an account? <Link to="/login">Sign in</Link>
      </p>
    </AuthLayout>
  );
}
