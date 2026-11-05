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
          <p className="eyebrow">GST billing for your business</p>
          <h1 className="login-hero__title">Bills, stock and payments in one place.</h1>
          <p className="section-copy">
            Make GST invoices, send them to your customers, and always know what is in stock and who
            still owes you money.
          </p>

          <div className="login-hero__grid">
            <div className="login-metric">
              <p className="eyebrow">GST</p>
              <strong>GST-ready tax invoices</strong>
              <p className="muted-text">CGST and SGST, or IGST for sales to another state, worked out automatically.</p>
            </div>
            <div className="login-metric">
              <p className="eyebrow">Sharing</p>
              <strong>Send on WhatsApp or email</strong>
              <p className="muted-text">Get an invoice to your customer without printing or scanning it.</p>
            </div>
            <div className="login-metric">
              <p className="eyebrow">Stock</p>
              <strong>Track your stock</strong>
              <p className="muted-text">Every invoice updates your stock, so you can see what is left.</p>
            </div>
            <div className="login-metric">
              <p className="eyebrow">Payments</p>
              <strong>See who owes you</strong>
              <p className="muted-text">Track unpaid and overdue invoices, and remind customers on WhatsApp.</p>
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
