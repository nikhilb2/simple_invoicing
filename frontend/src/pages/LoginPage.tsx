import { FormEvent, useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { getApiErrorMessage } from '../api/client';
import { useAuth } from '../context/AuthContext';
import StatusToasts from '../components/StatusToasts';

export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  async function onSubmit(event: FormEvent) {
    event.preventDefault();

    try {
      setSubmitting(true);
      setError('');
      await login(email, password);
      navigate('/');
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to sign in'));
    } finally {
      setSubmitting(false);
    }
  }

  useEffect(() => {
    document.title = 'Login | Simple Invoicing';
  }, []);

  return (
    <div className="login-page">
      <motion.div
        className="login-shell"
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: 'easeOut' }}
      >
        <section className="login-hero">
          <p className="eyebrow">Simple control surface</p>
          <h1 className="login-hero__title">Run inventory and invoicing without spreadsheet drag.</h1>
          <p className="section-copy">
            The frontend now centers the live workflows the backend already supports: product intake,
            stock adjustment, and invoice creation with inventory deduction.
          </p>

          <div className="login-hero__grid">
            <div className="login-metric">
              <p className="eyebrow">Products</p>
              <strong>Catalog intake</strong>
              <p className="muted-text">Create SKUs with pricing and optional description.</p>
            </div>
            <div className="login-metric">
              <p className="eyebrow">Inventory</p>
              <strong>Live stock moves</strong>
              <p className="muted-text">Apply positive or negative adjustments against existing product rows.</p>
            </div>
            <div className="login-metric">
              <p className="eyebrow">Invoices</p>
              <strong>Order composer</strong>
              <p className="muted-text">Assemble multi-line invoices and let the API guard stock levels.</p>
            </div>
            <div className="login-metric">
              <p className="eyebrow">Access</p>
              <strong>JWT session flow</strong>
              <p className="muted-text">Bearer token storage with protected routes and recovery on refresh.</p>
            </div>
          </div>
        </section>

        <motion.form
          onSubmit={onSubmit}
          initial={{ opacity: 0, scale: 0.98 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.08, duration: 0.28 }}
          className="login-card stack"
        >
          <div>
            <p className="eyebrow">Sign in</p>
            <h2 className="page-title">Access the workspace</h2>
            <p className="section-copy">Use a valid operator account to load the protected screens.</p>
          </div>

          <div className="field--full">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              className="input"
              placeholder="admin@simple.dev"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="email"
            />
          </div>

          <div className="field--full">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              className="input"
              placeholder="Enter password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
            />
          </div>

          <StatusToasts error={error} onClearError={() => setError('')} onClearSuccess={() => { }} />

          <button className="button button--primary" disabled={submitting} title="Open dashboard" aria-label="Open dashboard">
            {submitting ? 'Signing in...' : 'Open dashboard'}
          </button>
        </motion.form>
      </motion.div>
    </div>
  );
}
