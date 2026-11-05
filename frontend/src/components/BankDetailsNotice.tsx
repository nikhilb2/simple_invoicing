import { Link } from 'react-router-dom';

/** Tells the owner customers cannot see where to pay. Preview only; never in the PDF. */
export default function BankDetailsNotice() {
  return (
    <p className="muted-text" role="status" data-testid="bank-details-notice" style={{ margin: '0 0 8px', padding: '0 16px', fontSize: '0.85rem' }}>
      Your bank details are not on this invoice, so customers cannot see where to pay.{' '}
      <Link to="/cash-bank/accounts" style={{ color: 'var(--accent)', textDecoration: 'underline' }}>Add a bank account</Link>
    </p>
  );
}
