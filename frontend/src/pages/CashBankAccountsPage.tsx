import CompanyAccountsCard from '../components/CompanyAccountsCard';
import { useAuth } from '../context/AuthContext';

export default function CashBankAccountsPage() {
  const { isAdmin } = useAuth();

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Accounting</p>
          <h1 className="page-title">Cash &amp; Bank Accounts</h1>
          <p className="section-copy">Add and manage cash and bank accounts used for receipts and payments.</p>
        </div>
      </section>

      <section>
        <CompanyAccountsCard isAdmin={isAdmin} />
      </section>
    </div>
  );
}
