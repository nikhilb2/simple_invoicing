import { FormEvent, useState } from 'react';
import { Link } from 'react-router-dom';
import { forgotPassword } from '../api/auth';
import { authErrorMessage } from '../utils/authFlow';
import AuthLayout from '../components/AuthLayout';
import StatusToasts from '../components/StatusToasts';

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [error, setError] = useState('');
  const [sent, setSent] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    try {
      setSubmitting(true);
      setError('');
      await forgotPassword(email.trim());
      setSent(true);
    } catch (err) {
      setError(authErrorMessage(err, 'Unable to send the reset link'));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthLayout title="Forgot password">
      <div>
        <p className="eyebrow">Account recovery</p>
        <h2 className="page-title">Forgot your password?</h2>
        <p className="section-copy">
          {sent
            ? 'If an account exists for that address, a reset link is on its way. Check your inbox.'
            : 'Enter your email address and we will send you a link to choose a new password.'}
        </p>
      </div>

      {sent ? null : (
        <form className="stack" onSubmit={onSubmit}>
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
          <StatusToasts error={error} onClearError={() => setError('')} onClearSuccess={() => { }} />
          <button className="button button--primary" disabled={submitting}>
            {submitting ? 'Sending...' : 'Send reset link'}
          </button>
        </form>
      )}

      <p className="muted-text" style={{ margin: 0 }}>
        <Link to="/login">Back to sign in</Link>
      </p>
    </AuthLayout>
  );
}
