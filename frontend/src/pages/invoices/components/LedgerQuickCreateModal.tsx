import { useState, type FormEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import api, { getApiErrorMessage } from '../../../api/client';
import type { LedgerCreate } from '../../../types/api';
import { useEscapeClose } from '../../../hooks/useEscapeClose';
import { invoiceQueryKeys } from '../../../features/invoices/queryKeys';
import { useInvoiceComposerStore } from '../../../store/useInvoiceComposerStore';
import {
  applyOpeningBalanceSide,
  openingBalanceMagnitude,
  parseOpeningBalanceInput,
  type OpeningBalanceSide,
} from '../../../utils/openingBalance';

function createInitialLedgerForm(): LedgerCreate {
  return {
    name: '',
    address: '',
    gst: '',
    opening_balance: null,
    phone_number: '',
    email: '',
    website: '',
    bank_name: '',
    branch_name: '',
    account_name: '',
    account_number: '',
    ifsc_code: '',
  };
}

export default function LedgerQuickCreateModal() {
  const queryClient = useQueryClient();
  const showLedgerCreateModal = useInvoiceComposerStore((state) => state.showLedgerCreateModal);
  const closeLedgerCreateModal = useInvoiceComposerStore((state) => state.closeLedgerCreateModal);
  const setSelectedLedgerId = useInvoiceComposerStore((state) => state.setSelectedLedgerId);
  const setFeedbackError = useInvoiceComposerStore((state) => state.setFeedbackError);
  const setFeedbackSuccess = useInvoiceComposerStore((state) => state.setFeedbackSuccess);
  const [ledgerForm, setLedgerForm] = useState<LedgerCreate>(createInitialLedgerForm());
  const [ledgerOpeningBalanceSide, setLedgerOpeningBalanceSide] = useState<OpeningBalanceSide>('debit');
  const [ledgerSubmitting, setLedgerSubmitting] = useState(false);

  useEscapeClose(() => {
    if (showLedgerCreateModal) {
      closeLedgerCreateModal();
    }
  });

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    try {
      setLedgerSubmitting(true);
      setFeedbackError('');

      const payload: LedgerCreate = {
        name: ledgerForm.name.trim(),
        address: ledgerForm.address.trim(),
        gst: ledgerForm.gst.trim().toUpperCase(),
        opening_balance: ledgerForm.opening_balance,
        phone_number: ledgerForm.phone_number.trim(),
        email: ledgerForm.email.trim(),
        website: ledgerForm.website.trim(),
        bank_name: ledgerForm.bank_name.trim(),
        branch_name: ledgerForm.branch_name.trim(),
        account_name: ledgerForm.account_name.trim(),
        account_number: ledgerForm.account_number.trim(),
        ifsc_code: ledgerForm.ifsc_code.trim().toUpperCase(),
      };

      const response = await api.post<{ id: number }>('/ledgers/', payload);
      setSelectedLedgerId(String(response.data.id));
      setLedgerForm(createInitialLedgerForm());
      setLedgerOpeningBalanceSide('debit');
      closeLedgerCreateModal();
      setFeedbackSuccess('Ledger added and selected for this invoice.');
      await queryClient.invalidateQueries({ queryKey: invoiceQueryKeys.all });
    } catch (err) {
      setFeedbackError(getApiErrorMessage(err, 'Unable to create ledger'));
    } finally {
      setLedgerSubmitting(false);
    }
  }

  if (!showLedgerCreateModal) {
    return null;
  }

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="ledger-modal-title">
      <div className="modal-panel">
        <div className="panel__header">
          <div>
            <p className="eyebrow">Quick add</p>
            <h2 id="ledger-modal-title" className="nav-panel__title">Create ledger</h2>
          </div>
        </div>

        <form className="stack" onSubmit={handleSubmit}>
          <div className="field">
            <label htmlFor="modal-ledger-name">Name</label>
            <input
              id="modal-ledger-name"
              className="input"
              value={ledgerForm.name}
              onChange={(event) => setLedgerForm((current) => ({ ...current, name: event.target.value }))}
              placeholder="Acme Studio"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="modal-ledger-gst">GST</label>
            <input
              id="modal-ledger-gst"
              className="input"
              value={ledgerForm.gst}
              onChange={(event) => setLedgerForm((current) => ({ ...current, gst: event.target.value }))}
              placeholder="27ABCDE1234F1Z5"
              pattern="^$|[0-9]{2}[A-Za-z]{5}[0-9]{4}[A-Za-z][A-Za-z0-9]Z[A-Za-z0-9]$"
              title="Enter a valid 15-character GSTIN (e.g. 27ABCDE1234F1Z5), or leave blank"
              maxLength={15}
            />
            <small className="field-hint">Optional. If entered, format must be 27ABCDE1234F1Z5.</small>
          </div>
          <div className="field">
            <label htmlFor="modal-ledger-phone">Phone number</label>
            <input
              id="modal-ledger-phone"
              className="input"
              value={ledgerForm.phone_number}
              onChange={(event) => setLedgerForm((current) => ({ ...current, phone_number: event.target.value }))}
              placeholder="+91 9876543210"
              required
            />
          </div>
          <div className="field field--full">
            <label htmlFor="modal-ledger-opening-balance">Opening balance</label>
            <div className="opening-balance-group">
              <div className="opening-balance-group__amount">
                <input
                  id="modal-ledger-opening-balance"
                  className="input"
                  type="number"
                  step="0.01"
                  min="0"
                  value={openingBalanceMagnitude(ledgerForm.opening_balance) ?? ''}
                  onChange={(event) =>
                    setLedgerForm((current) => ({
                      ...current,
                      opening_balance: parseOpeningBalanceInput(event.target.value, ledgerOpeningBalanceSide),
                    }))
                  }
                  placeholder="0.00"
                />
              </div>
              <div className="opening-balance-group__type">
                <label htmlFor="modal-ledger-opening-balance-side">Type</label>
                <select
                  id="modal-ledger-opening-balance-side"
                  className="select"
                  value={ledgerOpeningBalanceSide}
                  onChange={(event) => {
                    const nextSide = event.target.value as OpeningBalanceSide;
                    setLedgerOpeningBalanceSide(nextSide);
                    setLedgerForm((current) => ({
                      ...current,
                      opening_balance: applyOpeningBalanceSide(current.opening_balance, nextSide),
                    }));
                  }}
                >
                  <option value="debit">Debit</option>
                  <option value="credit">Credit</option>
                </select>
              </div>
            </div>
            <small className="field-hint">Enter the amount only. Choose debit or credit separately. Leave blank for none.</small>
          </div>
          <div className="field">
            <label htmlFor="modal-ledger-email">Email</label>
            <input
              id="modal-ledger-email"
              className="input"
              value={ledgerForm.email}
              onChange={(event) => setLedgerForm((current) => ({ ...current, email: event.target.value }))}
              placeholder="accounts@acme.com"
            />
          </div>
          <div className="field">
            <label htmlFor="modal-ledger-website">Website</label>
            <input
              id="modal-ledger-website"
              className="input"
              value={ledgerForm.website}
              onChange={(event) => setLedgerForm((current) => ({ ...current, website: event.target.value }))}
              placeholder="https://acme.com"
            />
          </div>
          <div className="field">
            <label htmlFor="modal-ledger-address">Address</label>
            <textarea
              id="modal-ledger-address"
              className="textarea"
              value={ledgerForm.address}
              onChange={(event) => setLedgerForm((current) => ({ ...current, address: event.target.value }))}
              placeholder="221B Baker Street, London"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="modal-ledger-bank-name">Bank name</label>
            <input
              id="modal-ledger-bank-name"
              className="input"
              value={ledgerForm.bank_name}
              onChange={(event) => setLedgerForm((current) => ({ ...current, bank_name: event.target.value }))}
              placeholder="HDFC Bank"
            />
          </div>
          <div className="field">
            <label htmlFor="modal-ledger-branch-name">Branch</label>
            <input
              id="modal-ledger-branch-name"
              className="input"
              value={ledgerForm.branch_name}
              onChange={(event) => setLedgerForm((current) => ({ ...current, branch_name: event.target.value }))}
              placeholder="Bandra West"
            />
          </div>
          <div className="field">
            <label htmlFor="modal-ledger-account-name">Account holder</label>
            <input
              id="modal-ledger-account-name"
              className="input"
              value={ledgerForm.account_name}
              onChange={(event) => setLedgerForm((current) => ({ ...current, account_name: event.target.value }))}
              placeholder="Acme Traders"
            />
          </div>
          <div className="field">
            <label htmlFor="modal-ledger-account-number">Account number</label>
            <input
              id="modal-ledger-account-number"
              className="input"
              value={ledgerForm.account_number}
              onChange={(event) => setLedgerForm((current) => ({ ...current, account_number: event.target.value }))}
              placeholder="123456789012"
            />
          </div>
          <div className="field">
            <label htmlFor="modal-ledger-ifsc">IFSC</label>
            <input
              id="modal-ledger-ifsc"
              className="input"
              value={ledgerForm.ifsc_code}
              onChange={(event) => setLedgerForm((current) => ({ ...current, ifsc_code: event.target.value }))}
              placeholder="HDFC0001234"
            />
          </div>

          <div className="button-row">
            <button type="button" className="button button--ghost" onClick={closeLedgerCreateModal} title="Cancel ledger creation" aria-label="Cancel ledger creation">
              Cancel
            </button>
            <button className="button button--primary" disabled={ledgerSubmitting} title="Save ledger" aria-label="Save ledger">
              {ledgerSubmitting ? 'Saving ledger...' : 'Save ledger'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
