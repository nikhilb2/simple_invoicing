import { useEffect } from 'react';
import { motion } from 'framer-motion';
import GitHubStarButton from './GitHubStarButton';

type AuthLayoutProps = {
  /** Browser tab title, without the app name. */
  title: string;
  children: React.ReactNode;
};

/** The two-column frame shared by the login, sign-up and password recovery pages. */
export default function AuthLayout({ title, children }: AuthLayoutProps) {
  useEffect(() => {
    document.title = `${title} | Simple Invoicing`;
  }, [title]);

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

        <motion.div
          initial={{ opacity: 0, scale: 0.98 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.08, duration: 0.28 }}
          className="login-card stack"
        >
          {children}
          <GitHubStarButton className="login-card__github" />
        </motion.div>
      </motion.div>
    </div>
  );
}
