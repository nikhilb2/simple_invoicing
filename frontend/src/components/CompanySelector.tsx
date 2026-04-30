import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AnimatePresence, motion } from 'framer-motion';
import api, { getApiErrorMessage } from '../api/client';
import type {
  CompanyCreationCapOut,
  CompanyListItem,
  CompanyProfile,
  CompanyProfileUpdate,
  CompanySelectOut,
} from '../types/api';

export default function CompanySelector() {
  const queryClient = useQueryClient();
  const [companyDropdownOpen, setCompanyDropdownOpen] = useState(false);
  const [companySwitchingId, setCompanySwitchingId] = useState<number | null>(null);
  const [companyError, setCompanyError] = useState('');
  const [newCompanyModalOpen, setNewCompanyModalOpen] = useState(false);
  const [newCompanyName, setNewCompanyName] = useState('');
  const [newCompanySubmitting, setNewCompanySubmitting] = useState(false);
  const [newCompanyError, setNewCompanyError] = useState('');
  const companyDropdownRef = useRef<HTMLDivElement>(null);

  const companiesQuery = useQuery({
    queryKey: ['sidebar-companies'],
    queryFn: async () => {
      const [companiesRes, capabilityRes] = await Promise.all([
        api.get<CompanyListItem[]>('/company/companies'),
        api.get<CompanyCreationCapOut>('/company/companies/capability'),
      ]);

      return {
        companies: companiesRes.data,
        canCreateCompany: capabilityRes.data.can_create_company,
      };
    },
    refetchOnWindowFocus: 'always',
  });

  const companyList = companiesQuery.data?.companies ?? [];
  const canCreateCompany = companiesQuery.data?.canCreateCompany ?? false;
  const activeCompany = companyList.find((company) => company.is_active) ?? null;
  const queryError = companiesQuery.error
    ? getApiErrorMessage(companiesQuery.error, 'Failed to load companies')
    : '';
  const effectiveCompanyError = companyError || queryError;

  useEffect(() => {
    if (!companyDropdownOpen) return;
    const onClickOutside = (e: MouseEvent) => {
      if (companyDropdownRef.current && !companyDropdownRef.current.contains(e.target as Node)) {
        setCompanyDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, [companyDropdownOpen]);

  const handleCompanySwitch = async (companyId: number) => {
    if (companySwitchingId !== null) return;
    setCompanySwitchingId(companyId);
    setCompanyError('');
    try {
      const res = await api.post<CompanySelectOut>(`/company/select/${companyId}`);
      localStorage.setItem('active_company_id', String(res.data.active_company_id));
      window.location.reload();
    } catch (error) {
      setCompanyError(getApiErrorMessage(error, 'Failed to switch company'));
    } finally {
      setCompanySwitchingId(null);
    }
  };

  const handleCreateCompany = async () => {
    const trimmedName = newCompanyName.trim();
    if (!trimmedName) {
      setNewCompanyError('Company name is required.');
      return;
    }
    setNewCompanySubmitting(true);
    setNewCompanyError('');
    const payload: CompanyProfileUpdate = {
      name: trimmedName,
      address: '',
      gst: '',
      phone_number: '',
      currency_code: 'USD',
      email: '',
      website: '',
      bank_name: '',
      branch_name: '',
      account_name: '',
      account_number: '',
      ifsc_code: '',
    };

    try {
      const createRes = await api.post<CompanyProfile>('/company/companies', payload);
      await handleCompanySwitch(createRes.data.id);
    } catch (error) {
      setNewCompanyError(getApiErrorMessage(error, 'Failed to create company'));
    } finally {
      setNewCompanySubmitting(false);
    }
  };

  return (
    <>
      <p className="sidebar__group-label" style={{ marginBottom: '6px' }}>Company</p>
      <div ref={companyDropdownRef} style={{ position: 'relative', marginBottom: '12px' }}>
        <button
          className="button button--ghost"
          style={{ width: '100%', textAlign: 'left', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
          onClick={() => setCompanyDropdownOpen((v) => !v)}
          aria-haspopup="listbox"
          aria-expanded={companyDropdownOpen}
        >
          <span>{activeCompany?.name?.trim() || 'Select company'}</span>
          <span style={{ fontSize: '0.75rem', opacity: 0.6 }}>▾</span>
        </button>
        {companyDropdownOpen && (
          <div
            role="listbox"
            style={{
              position: 'absolute',
              left: 0,
              right: 0,
              top: 'calc(100% + 4px)',
              background: 'var(--bg-card-strong)',
              border: '1px solid var(--line-strong)',
              borderRadius: '0.5rem',
              boxShadow: '0 4px 24px rgba(0,0,0,0.45)',
              zIndex: 100,
              overflow: 'hidden',
              color: 'var(--text)',
            }}
          >
            {companiesQuery.isLoading && (
              <p style={{ padding: '0.5rem 0.75rem', fontSize: '0.85rem', opacity: 0.7 }}>Loading companies...</p>
            )}
            {!companiesQuery.isLoading && companyList.length === 0 && (
              <p style={{ padding: '0.5rem 0.75rem', fontSize: '0.85rem', opacity: 0.6 }}>No companies found</p>
            )}
            {companyList.map((company) => (
              <button
                key={company.id}
                role="option"
                aria-selected={company.is_active}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  width: '100%',
                  textAlign: 'left',
                  padding: '0.5rem 0.75rem',
                  background: 'none',
                  border: 'none',
                  cursor: companySwitchingId === null ? 'pointer' : 'wait',
                  fontWeight: company.is_active ? 700 : 400,
                  fontSize: '0.875rem',
                  color: 'inherit',
                }}
                disabled={companySwitchingId !== null}
                onClick={() => {
                  void handleCompanySwitch(company.id);
                  setCompanyDropdownOpen(false);
                }}
              >
                <span style={{ width: '1rem' }}>{company.is_active ? '✓' : ''}</span>
                {company.name || `Company #${company.id}`}
              </button>
            ))}
            {canCreateCompany && (
              <>
                <hr style={{ margin: '0.25rem 0', border: 'none', borderTop: '1px solid var(--line)' }} />
                <button
                  style={{
                    display: 'block',
                    width: '100%',
                    textAlign: 'left',
                    padding: '0.5rem 0.75rem',
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    fontSize: '0.875rem',
                    color: 'inherit',
                    fontWeight: 500,
                  }}
                  onClick={() => {
                    setCompanyDropdownOpen(false);
                    setNewCompanyName('');
                    setNewCompanyError('');
                    setNewCompanyModalOpen(true);
                  }}
                >
                  + New Company
                </button>
              </>
            )}
          </div>
        )}
      </div>
      {effectiveCompanyError && (
        <p style={{ marginTop: '-6px', marginBottom: '8px', color: 'var(--error, #ef4444)', fontSize: '0.8rem' }}>
          {effectiveCompanyError}
        </p>
      )}

      <AnimatePresence>
        {newCompanyModalOpen && (
          <motion.div
            className="modal-overlay"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={(e) => { if (e.target === e.currentTarget) setNewCompanyModalOpen(false); }}
          >
            <motion.div
              className="modal-panel"
              role="dialog"
              aria-modal="true"
              aria-label="Create new company"
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              transition={{ duration: 0.2 }}
              style={{ maxWidth: '28rem' }}
            >
              <h2 style={{ marginBottom: '1.25rem', fontSize: '1.125rem', fontWeight: 700 }}>New Company</h2>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                <label style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', fontSize: '0.875rem', fontWeight: 500 }}>
                  Company name
                  <input
                    className="input"
                    value={newCompanyName}
                    onChange={(e) => setNewCompanyName(e.target.value)}
                    autoFocus
                  />
                </label>
                <p style={{ margin: 0, fontSize: '0.8rem', opacity: 0.7 }}>
                  This creates a blank company profile. You can complete GST, address, and bank details on the Company page.
                </p>
                {newCompanyError && <p style={{ margin: 0, color: 'var(--error, #ef4444)', fontSize: '0.85rem' }}>{newCompanyError}</p>}
                <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end', marginTop: '0.5rem' }}>
                  <button type="button" className="button button--ghost" onClick={() => setNewCompanyModalOpen(false)}>
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="button"
                    disabled={newCompanySubmitting}
                    onClick={() => { void handleCreateCompany(); }}
                  >
                    {newCompanySubmitting ? 'Creating…' : 'Create Company'}
                  </button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}