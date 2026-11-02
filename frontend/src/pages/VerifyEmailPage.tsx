import { FormEvent, useState } from 'react';
import { Link } from 'react-router-dom';
import { readUrlSecret } from '../lib/urlSecrets';
import { resendVerification, verifyEmail } from '../api/auth';
import { authErrorMessage } from '../utils/authFlow';
import AuthLayout from '../components/AuthLayout';
import PasswordInput from '../components/PasswordInput';
import StatusToasts from '../components/StatusToasts';

type Status = 'ready' | 'verified' | 'failed';

const MIN_PASSWORD_LENGTH = 8;

export default function VerifyEmailPage() {
  const [token] = useState(() => readUrlSecret('token'));
  const [status, setStatus] = useState<Status>(token ? 'ready' : 'failed');
  const [message, setMessage] = useState(token ? '' : 'This verification link is missing its token.');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState('');
  const [email, setEmail] = useState('');
  const [resendNote, setResendNote] = useState('');
  const [resendError, setResendError] = useState('');
  const [resending, setResending] = useState(false);

  // A form, not a request on page load: mail scanners open links, and a link alone
  // must never be enough to confirm an account.
  async function onConfirm(event: FormEvent) {
    event.preventDefault();
    if (!token) return;
    if (password.length < MIN_PASSWORD_LENGTH) {
      setFormError(`Password must be at least ${MIN_PASSWORD_LENGTH} characters long`);
      return;
    }
    try {
      setSubmitting(true);
      setFormError('');
      const res = await verifyEmail(token, password);
      setStatus('verified');
      setMessage(res.detail || 'Your email address is verified.');
    } catch (err) {
      setStatus('failed');
      setMessage(authErrorMessage(err, 'This verification link is invalid or has expired.'));
    } finally {
      setSubmitting(false);
    }
  }

  async function onResend(event: FormEvent) {
    event.preventDefault();
    try {
      setResending(true);
      setResendError('');
      const res = await resendVerification(email.trim());
      setResendNote(res.detail || 'If that account needs verifying, a new link is on its way.');
    } catch (err) {
      setResendError(authErrorMessage(err, 'Unable to resend the verification email'));
    } finally {
      setResending(false);
    }
  }

  return (
    <AuthLayout title="Verify email">
      <div>
        <p className="eyebrow">Verify email</p>
        <h2 className="page-title">
          {status === 'ready' ? 'Choose your password' : status === 'verified' ? 'Email verified' : 'Could not verify email'}
        </h2>
        {message ? <p className="section-copy" role={status === 'failed' ? 'alert' : 'status'}>{message}</p> : null}
      </div>

      {status === 'ready' ? (
        <form className="stack" onSubmit={onConfirm}>
          <div className="field--full">
            <label htmlFor="password">Password</label>
            <PasswordInput
              id="password"
              className="input"
              placeholder={`At least ${MIN_PASSWORD_LENGTH} characters`}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="new-password"
            />
          </div>
          <StatusToasts error={formError} success="" onClearError={() => setFormError('')} onClearSuccess={() => undefined} />
          <button className="button button--primary" disabled={submitting}>
            {submitting ? 'Saving...' : 'Confirm email and set password'}
          </button>
        </form>
      ) : null}

      {status === 'verified' ? (
        <Link className="button button--primary" to="/login" style={{ textAlign: 'center', textDecoration: 'none' }}>
          Continue to sign in
        </Link>
      ) : null}

      {status === 'failed' ? (
        <form className="stack" onSubmit={onResend}>
          <div className="field--full">
            <label htmlFor="resend-email">Send a new verification link to</label>
            <input
              id="resend-email"
              className="input"
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="email"
              required
            />
          </div>
          <StatusToasts
            error={resendError}
            success={resendNote}
            onClearError={() => setResendError('')}
            onClearSuccess={() => setResendNote('')}
          />
          <button className="button button--primary" disabled={resending}>
            {resending ? 'Sending...' : 'Resend verification email'}
          </button>
        </form>
      ) : null}

      <p className="muted-text" style={{ margin: 0 }}>
        <Link to="/login">Back to sign in</Link>
      </p>
    </AuthLayout>
  );
}
