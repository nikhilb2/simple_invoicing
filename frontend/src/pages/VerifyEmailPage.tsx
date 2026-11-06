import { FormEvent, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { readUrlSecret } from '../lib/urlSecrets';
import { fetchVerifyEmailDetails, resendVerification, verifyEmail } from '../api/auth';
import { getApiErrorCode } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { authErrorMessage } from '../utils/authFlow';
import {
  isDeadVerificationLink,
  MIN_PASSWORD_LENGTH,
  passwordClientError,
  verifiedSession,
} from '../utils/verifyEmailForm';
import AuthLayout from '../components/AuthLayout';
import PasswordInput from '../components/PasswordInput';
import StatusToasts from '../components/StatusToasts';

type Status = 'ready' | 'verified' | 'failed';

// urlSecrets holds the token in memory only, so a refresh loses it. That is on
// purpose: keeping it through a refresh means keeping a credential that can set this
// account's password somewhere that outlives the page, to save one click on the email.
const LINK_LOST_MESSAGE =
  'For your security, this page cannot keep your link after a refresh. Open the link in your email again: '
  + 'it keeps working until you set your password or it expires. If you have already set your password, sign in.';

export default function VerifyEmailPage() {
  const [token] = useState(() => readUrlSecret('token'));
  const [status, setStatus] = useState<Status>(token ? 'ready' : 'failed');
  const [message, setMessage] = useState(token ? '' : LINK_LOST_MESSAGE);
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState('');
  const [email, setEmail] = useState('');
  const [resendNote, setResendNote] = useState('');
  const [resendError, setResendError] = useState('');
  const [resending, setResending] = useState(false);
  const [signingIn, setSigningIn] = useState(false);
  const { setSession } = useAuth();
  const navigate = useNavigate();

  // Start the form with the name given at registration, which stays editable: the
  // owner decides what the account is called. If this fails they can still type it.
  useEffect(() => {
    if (!token) return undefined;
    let current = true;
    fetchVerifyEmailDetails(token)
      .then((details) => {
        if (current) setFullName((typed) => typed || details.full_name);
      })
      .catch((err) => {
        if (current && isDeadVerificationLink(getApiErrorCode(err))) {
          setStatus('failed');
          setMessage(authErrorMessage(err, 'This verification link is invalid or has expired.'));
        }
      });
    return () => {
      current = false;
    };
  }, [token]);

  // A form, not a request on page load: mail scanners open links, and a link alone
  // must never be enough to confirm an account.
  async function onConfirm(event: FormEvent) {
    event.preventDefault();
    if (!token) return;
    if (!fullName.trim()) {
      setFormError('Enter your name');
      return;
    }
    const clientError = passwordClientError(password);
    if (clientError) {
      setFormError(clientError);
      return;
    }
    try {
      setSubmitting(true);
      setFormError('');
      const res = await verifyEmail(token, password, fullName.trim());
      setStatus('verified');
      setMessage(res.detail || 'Your email address is verified.');
      const session = verifiedSession(res);
      if (session) {
        setSigningIn(true);
        // On failure the "Continue to sign in" button comes back, and the password just set works there.
        void setSession(session)
          .then(() => navigate('/', { replace: true }))
          .catch(() => setSigningIn(false));
      }
    } catch (err) {
      if (isDeadVerificationLink(getApiErrorCode(err))) {
        setStatus('failed');
        setMessage(authErrorMessage(err, 'This verification link is invalid or has expired.'));
      } else {
        // Keep the form so the user can retry (network, 422 validation, etc.).
        setFormError(authErrorMessage(err, 'Unable to verify email. Please try again.'));
      }
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
          {status === 'ready'
            ? 'Confirm your name and choose a password'
            : status === 'verified'
              ? 'Email verified'
              : token
                ? 'Could not verify email'
                : 'Open the link from your email'}
        </h2>
        {message ? (
          <p className="section-copy" role={status === 'failed' ? 'alert' : 'status'}>
            {signingIn ? 'Signing you in...' : message}
          </p>
        ) : null}
      </div>

      {status === 'ready' ? (
        <form className="stack" onSubmit={onConfirm}>
          <div className="field--full">
            <label htmlFor="full-name">Your name</label>
            <input
              id="full-name"
              className="input"
              type="text"
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
              autoComplete="name"
              maxLength={120}
              required
            />
          </div>
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

      {status === 'verified' && !signingIn ? (
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
