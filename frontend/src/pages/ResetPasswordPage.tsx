import { FormEvent, useState } from 'react';
import { Link } from 'react-router-dom';
import { readUrlSecret } from '../lib/urlSecrets';
import { resetPassword } from '../api/auth';
import { authErrorMessage } from '../utils/authFlow';
import { MIN_PASSWORD_LENGTH, passwordClientError } from '../utils/verifyEmailForm';
import AuthLayout from '../components/AuthLayout';
import PasswordInput from '../components/PasswordInput';
import StatusToasts from '../components/StatusToasts';

export default function ResetPasswordPage() {
  const [token] = useState(() => readUrlSecret('token'));
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!token) return;
    const clientError = passwordClientError(password);
    if (clientError) {
      setError(clientError);
      return;
    }
    if (password !== confirm) {
      setError('The two passwords must match');
      return;
    }
    try {
      setSubmitting(true);
      setError('');
      await resetPassword(token, password);
      setDone(true);
    } catch (err) {
      setError(authErrorMessage(err, 'This reset link is invalid or has expired.'));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthLayout title="Reset password">
      <div>
        <p className="eyebrow">Account recovery</p>
        <h2 className="page-title">{token ? 'Choose a new password' : 'Open the link from your email'}</h2>
        {done ? <p className="section-copy">Your password has been changed. You can sign in with it now.</p> : null}
        {!token ? (
          <p className="section-copy" role="alert">
            For your security, this page cannot keep your link after a refresh. Open the reset link in your email
            again: it keeps working until you change your password or it expires.
          </p>
        ) : null}
      </div>

      {token && !done ? (
        <form className="stack" onSubmit={onSubmit}>
          <div className="field--full">
            <label htmlFor="new-password">New password</label>
            <PasswordInput
              id="new-password"
              className="input"
              placeholder={`At least ${MIN_PASSWORD_LENGTH} characters`}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="new-password"
            />
          </div>
          <div className="field--full">
            <label htmlFor="confirm-password">Confirm new password</label>
            <PasswordInput
              id="confirm-password"
              className="input"
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
              autoComplete="new-password"
            />
          </div>
          <StatusToasts error={error} onClearError={() => setError('')} onClearSuccess={() => { }} />
          <button className="button button--primary" disabled={submitting}>
            {submitting ? 'Saving...' : 'Set new password'}
          </button>
        </form>
      ) : null}

      <p className="muted-text" style={{ margin: 0 }}>
        {done ? <Link to="/login">Continue to sign in</Link> : <Link to="/forgot-password">Request a new link</Link>}
      </p>
    </AuthLayout>
  );
}
