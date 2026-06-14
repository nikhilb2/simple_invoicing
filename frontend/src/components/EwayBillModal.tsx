import { useEffect, useState } from 'react';
import { useEscapeClose } from '../hooks/useEscapeClose';
import api, { getApiErrorMessage } from '../api/client';
import type { Invoice } from '../types/api';

// ── Types matching the backend schemas ──

type EwayBillValidationError = {
  field: string;
  message: string;
};

type EwayBillFormData = {
  seller_gstin: string;
  seller_trade_name: string;
  seller_address_1: string;
  seller_address_2: string;
  seller_place: string;
  seller_state_code: string;
  seller_pincode: string;
  buyer_gstin: string;
  buyer_trade_name: string;
  buyer_address_1: string;
  buyer_address_2: string;
  buyer_place: string;
  buyer_state_code: string;
  buyer_pincode: string;
  supply_type: string;
  transaction_type: string;
  sub_supply_type: string;
  sub_supply_desc: string;
  transport_mode: string;
  vehicle_number: string;
  distance_km: number | null;
  transporter_gstin: string;
  transporter_name: string;
  vehicle_type: string;
  save_transporter: boolean;
};

type EwayBillPreCheckResult = {
  valid: boolean;
  errors: EwayBillValidationError[];
  missing_fields: EwayBillValidationError[];
  form_data: EwayBillFormData;
  item_validation: EwayBillValidationError[];
  eway_enabled: boolean;
  threshold_warning: string | null;
  eway_local_threshold: number;
  eway_interstate_threshold: number;
};

type TransporterProfile = {
  id: number;
  company_id: number;
  transporter_name: string;
  transporter_gstin: string | null;
  transport_mode: string;
  vehicle_type: string;
  is_default: boolean;
};

// ── Constants ──

// Values are the NIC subSupplyType codes the portal expects.
const SUB_SUPPLY_TYPES = [
  { value: '1', label: 'Supply' },
  { value: '2', label: 'Import' },
  { value: '3', label: 'Export' },
  { value: '4', label: 'Job Work' },
  { value: '5', label: 'For Own Use' },
  { value: '7', label: 'Sales Return' },
  { value: '12', label: 'Exhibition or Fairs' },
  { value: '10', label: 'Line Sales' },
  { value: '8', label: 'Others' },
];
const SUB_SUPPLY_OTHERS_CODE = '8';

// NIC transactionType codes.
const TRANSACTION_TYPES = [
  { value: '1', label: 'Regular' },
  { value: '2', label: 'Bill To - Ship To' },
  { value: '3', label: 'Bill From - Dispatch From' },
  { value: '4', label: 'Combination of 2 and 3' },
];

const TRANSPORT_MODES = [
  { value: '1', label: '🚛 Road' },
  { value: '2', label: '🚂 Rail' },
  { value: '3', label: '✈️ Air' },
  { value: '4', label: '🚢 Ship' },
];

const VEHICLE_TYPES = [
  { value: 'R', label: 'Regular (R)' },
  { value: 'O', label: 'Over Dimensional (O)' },
];

type Props = {
  invoice: Invoice;
  onClose: () => void;
  onError: (msg: string) => void;
};

export default function EwayBillModal({ invoice, onClose, onError }: Props) {
  // ── State ──
  const [step, setStep] = useState<'loading' | 'form' | 'error' | 'json-done'>('loading');
  const [form, setForm] = useState<EwayBillFormData | null>(null);
  const [itemErrors, setItemErrors] = useState<EwayBillValidationError[]>([]);
  const [formErrors, setFormErrors] = useState<EwayBillValidationError[]>([]);
  const [generating, setGenerating] = useState(false);
  const [transporters, setTransporters] = useState<TransporterProfile[]>([]);
  const [selectedTransporterId, setSelectedTransporterId] = useState<number | null>(null);
  const [subSupplyIsOthers, setSubSupplyIsOthers] = useState(false);
  const [showTransporterManager, setShowTransporterManager] = useState(false);
  const [jsonPreview, setJsonPreview] = useState('');
  const [thresholdWarning, setThresholdWarning] = useState<string | null>(null);
  const [ewayEnabled, setEwayEnabled] = useState(true);

  useEscapeClose(onClose);

  // ── Load precheck data on mount ──
  useEffect(() => {
    (async () => {
      try {
        const [preRes, transRes] = await Promise.all([
          api.get<EwayBillPreCheckResult>(`/invoices/${invoice.id}/eway-bill/precheck`),
          api.get<TransporterProfile[]>('/eway-bill/transporters').catch(() => null),
        ]);
        const transporterList: TransporterProfile[] = transRes?.data ?? [];
        setTransporters(transporterList);
        const result = preRes.data;
        setForm(result.form_data);
        setItemErrors([...(result.errors || []), ...(result.item_validation || [])]);
        setSubSupplyIsOthers(result.form_data.sub_supply_type === SUB_SUPPLY_OTHERS_CODE);
        setThresholdWarning(result.threshold_warning || null);
        setEwayEnabled(result.eway_enabled !== false);

        // Auto-select default transporter
        const def = transporterList.find(t => t.is_default);
        if (def) {
          setSelectedTransporterId(def.id);
        }

        setStep('form');
      } catch (err) {
        const msg = getApiErrorMessage(err, 'Failed to load E-Way Bill data');
        onError(msg);
        setStep('error');
      }
    })();
  }, [invoice.id]);

  // ── Handlers ──
  const updateForm = (field: string, value: string | number | boolean) => {
    setForm(prev => prev ? { ...prev, [field]: value } : prev);
  };

  const handleTransporterSelect = (id: string) => {
    if (!id) {
      setSelectedTransporterId(null);
      return;
    }
    const numId = parseInt(id, 10);
    const tp = transporters.find(t => t.id === numId);
    if (tp) {
      setSelectedTransporterId(numId);
      updateForm('transporter_name', tp.transporter_name);
      updateForm('transporter_gstin', tp.transporter_gstin || '');
      updateForm('transport_mode', tp.transport_mode);
      updateForm('vehicle_type', tp.vehicle_type);
    }
  };

  const handleGenerate = async () => {
    if (!form) return;
    setGenerating(true);
    setFormErrors([]);

    try {
      const formData: EwayBillFormData = {
        ...form,
        sub_supply_type: form.sub_supply_type,
      };
      // Cast number fields properly
      const payload = {
        ...formData,
        distance_km: formData.distance_km ? Number(formData.distance_km) : null,
        save_transporter: formData.save_transporter,
      };

      const res = await api.post(`/invoices/${invoice.id}/eway-bill/generate`, payload, {
        responseType: 'blob',
      });

      // Download the JSON file
      const blob = res.data as Blob;
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `EWB_${invoice.invoice_number || invoice.id}.json`;
      link.click();
      window.URL.revokeObjectURL(url);

      // Also show preview
      const text = await blob.text();
      const pretty = JSON.stringify(JSON.parse(text), null, 2);
      setJsonPreview(pretty);
      setStep('json-done');
    } catch (err) {
      const msg = getApiErrorMessage(err, 'Failed to generate E-Way Bill JSON');
      setFormErrors([{ field: '_general', message: msg }]);
    } finally {
      setGenerating(false);
    }
  };

  const handleCopyJson = () => {
    navigator.clipboard.writeText(jsonPreview);
  };

  const handleDownloadJson = () => {
    // Already downloaded on generate, but this re-downloads
    const blob = new Blob([jsonPreview], { type: 'application/json' });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `EWB_${invoice.invoice_number || invoice.id}.json`;
    link.click();
    window.URL.revokeObjectURL(url);
  };

  // ── Loading state ──
  if (step === 'loading') {
    return (
      <div className="modal-overlay" role="dialog" aria-modal="true">
        <div className="modal-panel" style={{ textAlign: 'center', padding: '40px' }}>
          <p style={{ fontSize: '1.1rem', color: 'var(--muted)' }}>Checking invoice data for E-Way Bill...</p>
        </div>
      </div>
    );
  }

  // ── Error state ──
  if (step === 'error' || !form) {
    return (
      <div className="modal-overlay" role="dialog" aria-modal="true">
        <div className="modal-panel" style={{ textAlign: 'center', padding: '40px' }}>
          <h2 style={{ color: 'var(--danger)', marginBottom: '12px' }}>Cannot Generate E-Way Bill</h2>
          <p style={{ color: 'var(--muted)', marginBottom: '20px' }}>
            This invoice doesn't meet the requirements for E-Way Bill generation.
          </p>
          <button className="button button--ghost" onClick={onClose}>Close</button>
        </div>
      </div>
    );
  }

  // ── JSON done state ──
  if (step === 'json-done') {
    return (
      <div className="modal-overlay" role="dialog" aria-modal="true">
        <div className="modal-panel" style={{ width: 'min(720px, 100%)' }}>
          <div className="panel__header">
            <div>
              <p className="eyebrow">E-Way Bill Generated</p>
              <h2 className="nav-panel__title">EWB_{invoice.invoice_number || invoice.id}.json</h2>
            </div>
            <div className="button-row">
              <button className="button button--secondary" onClick={handleCopyJson}>Copy JSON</button>
              <button className="button button--primary" onClick={handleDownloadJson}>Download</button>
              <button className="button button--ghost" onClick={onClose}>Close</button>
            </div>
          </div>
          <p style={{ color: 'var(--accent)', marginBottom: '16px', fontSize: '0.95rem' }}>
            ✅ E-Way Bill JSON generated successfully. Upload this file on the GST E-Way Bill Portal.
          </p>
          <pre style={{
            background: 'rgba(6,12,22,0.6)',
            padding: '16px',
            borderRadius: '12px',
            fontSize: '0.8rem',
            overflow: 'auto',
            maxHeight: '60vh',
            border: '1px solid var(--line)',
            color: 'var(--muted)',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}>{jsonPreview}</pre>
        </div>
      </div>
    );
  }

  // ── Form state ──
  const errors = [...formErrors, ...itemErrors];
  const canGenerate = !generating && itemErrors.length === 0 && ewayEnabled;

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="eway-bill-title">
      <div className="modal-panel" style={{ width: 'min(860px, 100%)' }}>
        <div className="panel__header">
          <div>
            <p className="eyebrow">Invoice #{invoice.invoice_number}</p>
            <h2 id="eway-bill-title" className="nav-panel__title">Generate E-Way Bill</h2>
          </div>
          <button className="button button--ghost" onClick={onClose}>Close</button>
        </div>

        {/* E-Way Bill disabled notice */}
        {!ewayEnabled && (
          <div style={{ background: 'rgba(255,139,139,0.1)', border: '1px solid rgba(255,139,139,0.3)', borderRadius: '16px', padding: '16px', marginBottom: '20px' }}>
            <p style={{ color: 'var(--danger)', fontWeight: 700, margin: 0 }}>⚠️ E-Way Bill generation is disabled in Company Settings. Enable it under Company → E-Way Bill Configuration.</p>
          </div>
        )}

        {/* Threshold warning (guidance only — never blocks) */}
        {thresholdWarning && (
          <div style={{ background: 'rgba(255,193,7,0.08)', border: '1px solid rgba(255,193,7,0.25)', borderRadius: '16px', padding: '16px', marginBottom: '20px' }}>
            <p style={{ color: '#e0a800', fontWeight: 700, marginBottom: '4px', fontSize: '0.95rem' }}>⚠️ Threshold Notice</p>
            <p style={{ color: 'var(--muted)', fontSize: '0.9rem', margin: 0 }}>{thresholdWarning}</p>
          </div>
        )}

        {/* Validation errors */}
        {errors.length > 0 && (
          <div style={{ background: 'rgba(255,139,139,0.1)', border: '1px solid rgba(255,139,139,0.3)', borderRadius: '16px', padding: '16px', marginBottom: '20px' }}>
            <p style={{ color: 'var(--danger)', fontWeight: 700, marginBottom: '8px' }}>⚠️ Issues to fix</p>
            <ul style={{ margin: 0, paddingLeft: '20px', color: 'var(--muted)', fontSize: '0.9rem' }}>
              {errors.map((e, i) => <li key={i}>{e.message}</li>)}
            </ul>
          </div>
        )}

        {/* Transporter selector */}
        {transporters.length > 0 && (
          <div className="form-section" style={{ marginBottom: '16px' }}>
            <div className="form-section__header">
              <h3 style={{ fontSize: '0.95rem', fontWeight: 700, color: 'var(--accent)' }}>Saved Transporter</h3>
              <button className="button button--small button--ghost" onClick={() => setShowTransporterManager(!showTransporterManager)}>
                {showTransporterManager ? 'Hide' : 'Manage'}
              </button>
            </div>
            <div className="field">
              <label>Select Transporter</label>
              <select
                className="select"
                value={selectedTransporterId || ''}
                onChange={e => handleTransporterSelect(e.target.value)}
              >
                <option value="">— Select —</option>
                {transporters.map(tp => (
                  <option key={tp.id} value={tp.id}>
                    {tp.transporter_name}{tp.is_default ? ' ⭐' : ''}
                  </option>
                ))}
              </select>
            </div>
          </div>
        )}

        {/* Scrollable form area */}
        <div style={{ display: 'grid', gap: '16px', maxHeight: '55vh', overflowY: 'auto', paddingRight: '4px' }}>
          {/* ── Seller Details ── */}
          <div className="form-section">
            <h3 className="form-section__header" style={{ color: 'var(--accent)', fontWeight: 700, fontSize: '0.95rem' }}>
              🏢 Seller Details
            </h3>
            <div className="field-grid">
              <div className="field">
                <label>GSTIN</label>
                <input className="input" value={form.seller_gstin} onChange={e => updateForm('seller_gstin', e.target.value)} />
              </div>
              <div className="field">
                <label>Trade Name</label>
                <input className="input" value={form.seller_trade_name} onChange={e => updateForm('seller_trade_name', e.target.value)} />
              </div>
              <div className="field">
                <label>Address Line 1</label>
                <input className="input" value={form.seller_address_1} onChange={e => updateForm('seller_address_1', e.target.value)} />
              </div>
              <div className="field">
                <label>Address Line 2</label>
                <input className="input" value={form.seller_address_2} onChange={e => updateForm('seller_address_2', e.target.value)} />
              </div>
              <div className="field">
                <label>Place</label>
                <input className="input" value={form.seller_place} onChange={e => updateForm('seller_place', e.target.value)} />
              </div>
              <div className="field">
                <label>State Code</label>
                <input className="input" value={form.seller_state_code} onChange={e => updateForm('seller_state_code', e.target.value)} maxLength={2} />
              </div>
              <div className="field">
                <label>Pincode</label>
                <input className="input" value={form.seller_pincode} onChange={e => updateForm('seller_pincode', e.target.value)} maxLength={6} />
              </div>
            </div>
          </div>

          {/* ── Buyer Details ── */}
          <div className="form-section">
            <h3 className="form-section__header" style={{ color: 'var(--accent)', fontWeight: 700, fontSize: '0.95rem' }}>
              👤 Buyer Details
            </h3>
            <div className="field-grid">
              <div className="field">
                <label>GSTIN</label>
                <input className="input" value={form.buyer_gstin} onChange={e => updateForm('buyer_gstin', e.target.value)} />
              </div>
              <div className="field">
                <label>Trade Name</label>
                <input className="input" value={form.buyer_trade_name} onChange={e => updateForm('buyer_trade_name', e.target.value)} />
              </div>
              <div className="field">
                <label>Address Line 1</label>
                <input className="input" value={form.buyer_address_1} onChange={e => updateForm('buyer_address_1', e.target.value)} />
              </div>
              <div className="field">
                <label>Address Line 2</label>
                <input className="input" value={form.buyer_address_2} onChange={e => updateForm('buyer_address_2', e.target.value)} />
              </div>
              <div className="field">
                <label>Place</label>
                <input className="input" value={form.buyer_place} onChange={e => updateForm('buyer_place', e.target.value)} />
              </div>
              <div className="field">
                <label>State Code</label>
                <input className="input" value={form.buyer_state_code} onChange={e => updateForm('buyer_state_code', e.target.value)} maxLength={2} />
              </div>
              <div className="field">
                <label>Pincode</label>
                <input className="input" value={form.buyer_pincode} onChange={e => updateForm('buyer_pincode', e.target.value)} maxLength={6} />
              </div>
            </div>
          </div>

          {/* ── Supply Details ── */}
          <div className="form-section">
            <h3 className="form-section__header" style={{ color: 'var(--accent)', fontWeight: 700, fontSize: '0.95rem' }}>
              📄 Supply Details
            </h3>
            <div className="field-grid">
              <div className="field">
                <label>Supply Type</label>
                <select className="select" value={form.supply_type} onChange={e => updateForm('supply_type', e.target.value)}>
                  <option value="O">Outward</option>
                  <option value="I">Inward</option>
                </select>
              </div>
              <div className="field">
                <label>Transaction Type</label>
                <select className="select" value={form.transaction_type} onChange={e => updateForm('transaction_type', e.target.value)}>
                  {TRANSACTION_TYPES.map(t => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label>Sub-Supply Type</label>
                <select className="select" value={form.sub_supply_type} onChange={e => {
                  updateForm('sub_supply_type', e.target.value);
                  setSubSupplyIsOthers(e.target.value === SUB_SUPPLY_OTHERS_CODE);
                }}>
                  {SUB_SUPPLY_TYPES.map(s => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </select>
              </div>
              {subSupplyIsOthers && (
                <div className="field field--full">
                  <label>Sub-Supply Description</label>
                  <input className="input" value={form.sub_supply_desc} onChange={e => updateForm('sub_supply_desc', e.target.value)} placeholder="Describe the supply type" />
                </div>
              )}
            </div>
          </div>

          {/* ── Transport Details ── */}
          <div className="form-section">
            <h3 className="form-section__header" style={{ color: 'var(--accent)', fontWeight: 700, fontSize: '0.95rem' }}>
              🚛 Transport Details
            </h3>
            <div className="field-grid">
              <div className="field">
                <label>Transport Mode</label>
                <select className="select" value={form.transport_mode} onChange={e => updateForm('transport_mode', e.target.value)}>
                  {TRANSPORT_MODES.map(m => (
                    <option key={m.value} value={m.value}>{m.label}</option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label>Vehicle Type</label>
                <select className="select" value={form.vehicle_type} onChange={e => updateForm('vehicle_type', e.target.value)}>
                  {VEHICLE_TYPES.map(v => (
                    <option key={v.value} value={v.value}>{v.label}</option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label>Vehicle Number</label>
                <input className="input" value={form.vehicle_number} onChange={e => updateForm('vehicle_number', e.target.value.toUpperCase())} placeholder="e.g., HR55AB1234" />
              </div>
              <div className="field">
                <label>Distance (KM)</label>
                <input className="input" type="number" min={0} value={form.distance_km ?? ''} onChange={e => { const v = e.target.value; updateForm('distance_km', v ? Number(v) : 0); }} placeholder="e.g., 200" />
              </div>
              <div className="field">
                <label>Transporter Name</label>
                <input className="input" value={form.transporter_name} onChange={e => updateForm('transporter_name', e.target.value)} placeholder="Transport company name" />
              </div>
              <div className="field">
                <label>Transporter GSTIN</label>
                <input className="input" value={form.transporter_gstin} onChange={e => updateForm('transporter_gstin', e.target.value)} placeholder="Optional" />
              </div>
            </div>
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '8px', color: 'var(--muted)', fontSize: '0.9rem', cursor: 'pointer' }}>
              <input type="checkbox" checked={form.save_transporter} onChange={e => updateForm('save_transporter', e.target.checked)} />
              💾 Save as default transporter
            </label>
          </div>
        </div>

        {/* ── Action buttons ── */}
        <div className="button-row" style={{ marginTop: '20px', justifyContent: 'flex-end' }}>
          <button className="button button--ghost" onClick={onClose}>Cancel</button>
          <button
            className="button button--primary"
            onClick={handleGenerate}
            disabled={!canGenerate}
          >
            {generating ? 'Generating...' : 'Generate JSON'}
          </button>
        </div>
      </div>
    </div>
  );
}
