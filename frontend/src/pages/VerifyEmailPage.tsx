import { FormEvent, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { resendVerification, verifyEmail } from '../api/auth';
import { authErrorMessage } from '../utils/authFlow';
import AuthLayout from '../components/AuthLayout';
import StatusToasts from '../components/StatusToasts';

type Status = 'verifying' | 'verified' | 'failed';

export default function VerifyEmailPage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token');
  const [status, setStatus] = useState<Status>(token ? 'verifying' : 'failed');
  const [message, setMessage] = useState(token ? '' : 'This verification link is missing its token.');
  const [email, setEmail] = useState('');
  const [resendNote, setResendNote] = useState('');
  const [resendError, setResendError] = useState('');
  const [resending, setResending] = useState(false);

  useEffect(() => {
    if (!token) return undefined;
    // Guards against a stale response after the token changes or the page
    // unmounts; the token is single-use, so a second POST would report failure.
    let cancelled = false;
    verifyEmail(token)
      .then((res) => {
        if (cancelled) return;
        setStatus('verified');
        setMessage(res.detail || 'Your email address is verified.');
      })
      .catch((err) => {
        if (cancelled) return;
        setStatus('failed');
        setMessage(authErrorMessage(err, 'This verification link is invalid or has expired.'));
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

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
          {status === 'verifying' ? 'Verifying...' : status === 'verified' ? 'Email verified' : 'Could not verify'}
        </h2>
        {message ? <p className="section-copy" role={status === 'failed' ? 'alert' : 'status'}>{message}</p> : null}
      </div>

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
