import { useEffect, useRef, useState } from 'react';
import api, { getApiErrorMessage } from '../api/client';
import type {
  CompanyAccount,
  CompanyAccountCreate,
  CompanyAccountType,
  CompanyAccountUpdate,
} from '../types/api';

type AccountDraft = {
  account_type: CompanyAccountType;
  display_name: string;
  bank_name: string;
  branch_name: string;
  account_name: string;
  account_number: string;
  ifsc_code: string;
  opening_balance: string;
  is_active: boolean;
};

function toDraft(account: CompanyAccount): AccountDraft {
  return {
    account_type: account.account_type,
    display_name: account.display_name,
    bank_name: account.bank_name || '',
    branch_name: account.branch_name || '',
    account_name: account.account_name || '',
    account_number: account.account_number || '',
    ifsc_code: account.ifsc_code || '',
    opening_balance: String(account.opening_balance ?? 0),
    is_active: account.is_active,
  };
}

const EMPTY_CREATE_DRAFT: AccountDraft = {
  account_type: 'bank',
  display_name: '',
  bank_name: '',
  branch_name: '',
  account_name: '',
  account_number: '',
  ifsc_code: '',
  opening_balance: '0',
  is_active: true,
};

export default function CompanyAccountsCard({ isAdmin }: { isAdmin: boolean }) {
  const [accounts, setAccounts] = useState<CompanyAccount[]>([]);
  const [drafts, setDrafts] = useState<Record<number, AccountDraft>>({});
  const [loading, setLoading] = useState(true);
  const [createDraft, setCreateDraft] = useState<AccountDraft>(EMPTY_CREATE_DRAFT);
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState<Record<number, boolean>>({});
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const saveInFlightRef = useRef<Record<number, boolean>>({});

  async function loadAccounts() {
    try {
      setLoading(true);
      setError('');
      const res = await api.get<CompanyAccount[]>('/company-accounts/', {
        params: { include_inactive: true },
      });
      setAccounts(res.data);
      const nextDrafts: Record<number, AccountDraft> = {};
      for (const account of res.data) {
        nextDrafts[account.id] = toDraft(account);
      }
      setDrafts(nextDrafts);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to load company accounts'));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadAccounts();
  }, []);

  function patchDraft(id: number, patch: Partial<AccountDraft>) {
    setDrafts((current) => ({
      ...current,
      [id]: { ...current[id], ...patch },
    }));
  }

  async function handleCreateAccount() {
    if (!createDraft.display_name.trim()) {
      setError('Account display name is required');
      return;
    }

    const payload: CompanyAccountCreate = {
      account_type: createDraft.account_type,
      display_name: createDraft.display_name.trim(),
      bank_name: createDraft.bank_name.trim() || undefined,
      branch_name: createDraft.branch_name.trim() || undefined,
      account_name: createDraft.account_name.trim() || undefined,
      account_number: createDraft.account_number.trim() || undefined,
      ifsc_code: createDraft.ifsc_code.trim().toUpperCase() || undefined,
      opening_balance: Number(createDraft.opening_balance || '0') || 0,
      is_active: createDraft.is_active,
    };

    try {
      setCreating(true);
      setError('');
      setSuccess('');
      const res = await api.post<CompanyAccount>('/company-accounts/', payload);
      const created = res.data;
      setAccounts((current) => [...current, created].sort((a, b) => a.display_name.localeCompare(b.display_name)));
      setDrafts((current) => ({ ...current, [created.id]: toDraft(created) }));
      setCreateDraft(EMPTY_CREATE_DRAFT);
      setSuccess('Account added successfully.');
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to create account'));
    } finally {
      setCreating(false);
    }
  }

  async function handleSaveAccount(accountId: number) {
    if (saveInFlightRef.current[accountId]) return;
    const draft = drafts[accountId];
    if (!draft) return;
    if (!draft.display_name.trim()) {
      setError('Account display name is required');
      return;
    }

    const payload: CompanyAccountUpdate = {
      account_type: draft.account_type,
      display_name: draft.display_name.trim(),
      bank_name: draft.bank_name.trim(),
      branch_name: draft.branch_name.trim(),
      account_name: draft.account_name.trim(),
      account_number: draft.account_number.trim(),
      ifsc_code: draft.ifsc_code.trim().toUpperCase(),
      opening_balance: Number(draft.opening_balance || '0') || 0,
      is_active: draft.is_active,
    };

    try {
      saveInFlightRef.current[accountId] = true;
      setSaving((current) => ({ ...current, [accountId]: true }));
      setError('');
      const res = await api.put<CompanyAccount>(`/company-accounts/${accountId}`, payload);
      setAccounts((current) => current.map((account) => (account.id === accountId ? res.data : account)));
      setDrafts((current) => ({ ...current, [accountId]: toDraft(res.data) }));
      setSuccess('Account updated.');
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to save account changes'));
    } finally {
      saveInFlightRef.current[accountId] = false;
      setSaving((current) => ({ ...current, [accountId]: false }));
    }
  }

  async function handleToggleAccountStatus(accountId: number) {
    const account = accounts.find((entry) => entry.id === accountId);
    if (!account) return;

    try {
      setSaving((current) => ({ ...current, [accountId]: true }));
      setError('');
      if (account.is_active) {
        await api.delete(`/company-accounts/${accountId}`);
      } else {
        await api.put<CompanyAccount>(`/company-accounts/${accountId}`, { is_active: true });
      }
      await loadAccounts();
      setSuccess(account.is_active ? 'Account deactivated.' : 'Account activated.');
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to update account status'));
    } finally {
      setSaving((current) => ({ ...current, [accountId]: false }));
    }
  }

  if (loading) {
    return <article className="panel stack"><div className="empty-state">Loading accounts...</div></article>;
  }

  return (
    <article className="panel stack">
      <div className="panel__header">
        <div>
          <p className="eyebrow">Cash and bank</p>
          <h2 className="nav-panel__title">Account master</h2>
        </div>
      </div>

      {error ? <div className="empty-state" style={{ color: 'var(--color-danger, #b91c1c)' }}>{error}</div> : null}
      {success ? <div className="empty-state" style={{ color: 'var(--color-success, #166534)' }}>{success}</div> : null}

      {isAdmin ? (
        <div className="panel" style={{ padding: '16px' }}>
          <p style={{ marginTop: 0, marginBottom: '8px', fontWeight: 600 }}>Add account</p>
          <div className="field-grid">
            <div className="field">
              <label htmlFor="new-account-type">Type</label>
              <select
                id="new-account-type"
                className="select"
                value={createDraft.account_type}
                onChange={(event) => setCreateDraft((current) => ({ ...current, account_type: event.target.value as CompanyAccountType }))}
              >
                <option value="bank">Bank</option>
                <option value="cash">Cash</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="new-account-display">Display name</label>
              <input
                id="new-account-display"
                className="input"
                value={createDraft.display_name}
                onChange={(event) => setCreateDraft((current) => ({ ...current, display_name: event.target.value }))}
                placeholder="Main HDFC Account"
              />
            </div>
            <div className="field">
              <label htmlFor="new-account-opening">Opening balance</label>
              <input
                id="new-account-opening"
                className="input"
                type="number"
                step="0.01"
                value={createDraft.opening_balance}
                onChange={(event) => setCreateDraft((current) => ({ ...current, opening_balance: event.target.value }))}
              />
            </div>
            <div className="field">
              <label htmlFor="new-account-bank">Bank name</label>
              <input
                id="new-account-bank"
                className="input"
                value={createDraft.bank_name}
                onChange={(event) => setCreateDraft((current) => ({ ...current, bank_name: event.target.value }))}
                placeholder="HDFC Bank"
              />
            </div>
            <div className="field">
              <label htmlFor="new-account-accno">Account number</label>
              <input
                id="new-account-accno"
                className="input"
                value={createDraft.account_number}
                onChange={(event) => setCreateDraft((current) => ({ ...current, account_number: event.target.value }))}
                placeholder="1234567890"
              />
            </div>
            <div className="field">
              <label htmlFor="new-account-ifsc">IFSC</label>
              <input
                id="new-account-ifsc"
                className="input"
                value={createDraft.ifsc_code}
                onChange={(event) => setCreateDraft((current) => ({ ...current, ifsc_code: event.target.value }))}
                placeholder="HDFC0001234"
              />
            </div>
          </div>
          <div className="button-row" style={{ marginTop: '12px' }}>
            <button type="button" className="button button--primary" disabled={creating} onClick={() => void handleCreateAccount()}>
              {creating ? 'Adding...' : 'Add account'}
            </button>
          </div>
        </div>
      ) : null}

      <div className="stack" style={{ gap: '16px' }}>
        {accounts.length === 0 ? <div className="empty-state">No accounts added yet.</div> : null}
        {accounts.map((account) => {
          const draft = drafts[account.id];
          if (!draft) return null;
          return (
            <div key={account.id} className="panel" style={{ padding: '16px' }}>
              <div className="field-grid">
                <div className="field">
                  <label htmlFor={`account-type-${account.id}`}>Type</label>
                  <select
                    id={`account-type-${account.id}`}
                    className="select"
                    value={draft.account_type}
                    onChange={(event) => patchDraft(account.id, { account_type: event.target.value as CompanyAccountType })}
                    disabled={!isAdmin}
                  >
                    <option value="bank">Bank</option>
                    <option value="cash">Cash</option>
                  </select>
                </div>
                <div className="field">
                  <label htmlFor={`account-display-${account.id}`}>Display name</label>
                  <input
                    id={`account-display-${account.id}`}
                    className="input"
                    value={draft.display_name}
                    onChange={(event) => patchDraft(account.id, { display_name: event.target.value })}
                    disabled={!isAdmin}
                  />
                </div>
                <div className="field">
                  <label htmlFor={`account-opening-${account.id}`}>Opening balance</label>
                  <input
                    id={`account-opening-${account.id}`}
                    className="input"
                    type="number"
                    step="0.01"
                    value={draft.opening_balance}
                    onChange={(event) => patchDraft(account.id, { opening_balance: event.target.value })}
                    disabled={!isAdmin}
                  />
                </div>
                <div className="field">
                  <label htmlFor={`account-bank-${account.id}`}>Bank name</label>
                  <input
                    id={`account-bank-${account.id}`}
                    className="input"
                    value={draft.bank_name}
                    onChange={(event) => patchDraft(account.id, { bank_name: event.target.value })}
                    disabled={!isAdmin}
                  />
                </div>
                <div className="field">
                  <label htmlFor={`account-accno-${account.id}`}>Account number</label>
                  <input
                    id={`account-accno-${account.id}`}
                    className="input"
                    value={draft.account_number}
                    onChange={(event) => patchDraft(account.id, { account_number: event.target.value })}
                    disabled={!isAdmin}
                  />
                </div>
                <div className="field">
                  <label htmlFor={`account-ifsc-${account.id}`}>IFSC</label>
                  <input
                    id={`account-ifsc-${account.id}`}
                    className="input"
                    value={draft.ifsc_code}
                    onChange={(event) => patchDraft(account.id, { ifsc_code: event.target.value })}
                    disabled={!isAdmin}
                  />
                </div>
              </div>

              <div className="button-row" style={{ marginTop: '12px' }}>
                <span className="status-chip" style={{ opacity: account.is_active ? 1 : 0.7 }}>
                  {account.is_active ? 'Active' : 'Inactive'}
                </span>
                {isAdmin ? (
                  <button
                    type="button"
                    className="button button--secondary"
                    onClick={() => void handleSaveAccount(account.id)}
                    disabled={saving[account.id]}
                  >
                    {saving[account.id] ? 'Saving...' : 'Save changes'}
                  </button>
                ) : null}
                {isAdmin ? (
                  <button
                    type="button"
                    className="button button--ghost"
                    onClick={() => void handleToggleAccountStatus(account.id)}
                    disabled={saving[account.id]}
                  >
                    {account.is_active ? 'Deactivate' : 'Activate'}
                  </button>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </article>
  );
}
