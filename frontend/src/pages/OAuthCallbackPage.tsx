import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { exchangeOAuthCode } from '../api/auth';
import { readUrlSecret } from '../lib/urlSecrets';
import { useAuth } from '../context/AuthContext';
import { callbackNextPath, OAUTH_FAILED_PATH } from '../utils/authFlow';
import AuthLayout from '../components/AuthLayout';

/**
 * Landing page for the provider round trip. The backend redirects here with a
 * single-use `code`; this trades it for the same token pair /auth/login
 * returns. `next` is validated like every other return path.
 */
export default function OAuthCallbackPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { setSession } = useAuth();
  // The code is single-use, and StrictMode runs effects twice in development:
  // the second exchange would fail and bounce a good sign-in back to /login.
  const started = useRef(false);
  // Read once and scrubbed from the URL, so replay never records it.
  const [code] = useState(() => readUrlSecret('code'));

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    if (!code) {
      navigate(OAUTH_FAILED_PATH, { replace: true });
      return;
    }

    const next = callbackNextPath(searchParams);
    exchangeOAuthCode(code)
      .then((tokens) => setSession(tokens))
      .then(() => navigate(next, { replace: true }))
      .catch(() => navigate(OAUTH_FAILED_PATH, { replace: true }));
  }, [code, searchParams, navigate, setSession]);

  return (
    <AuthLayout title="Signing in">
      <div>
        <p className="eyebrow">Sign in</p>
        <h2 className="page-title">Signing you in...</h2>
      </div>
    </AuthLayout>
  );
}
