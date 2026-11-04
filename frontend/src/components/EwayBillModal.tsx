import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useEscapeClose } from '../hooks/useEscapeClose';
import api, { getApiErrorDetails, getApiErrorMessage } from '../api/client';
import { useAuth } from '../context/AuthContext';
import ModalCloseButton from './ModalCloseButton';
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
  dispatch_state_code: string;
  buyer_gstin: string;
  buyer_trade_name: string;
  buyer_address_1: string;
  buyer_address_2: string;
  buyer_place: string;
  buyer_state_code: string;
  buyer_pincode: string;
  ship_to_state_code: string;
  supply_type: string;
  transaction_type: string;
  sub_supply_type: string;
  transport_mode: string;
  vehicle_number: string;
  distance_km: number | null;
  transporter_gstin: string;
  transporter_name: string;
  vehicle_type: string;
  transport_doc_no: string;
  transport_doc_date: string;
  save_transporter: boolean;
};

type EwayBillPreCheckResult = {
  valid: boolean;
  errors: EwayBillValidationError[];
  missing_fields: EwayBillValidationError[];
  form_data: EwayBillFormData;
  item_validation: EwayBillValidationError[];
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

// Values are the NIC subSupplyType codes the portal allows on a Tax Invoice.
const SUB_SUPPLY_EXPORT = '3';
const SUB_SUPPLY_TYPES = [
  { value: '1', label: 'Supply' },
  { value: SUB_SUPPLY_EXPORT, label: 'Export' },
  { value: '9', label: 'SKD/CKD/Lots' },
];

// NIC transactionType codes.
const TRANSACTION_TYPES = [
  { value: '1', label: 'Regular' },
  { value: '2', label: 'Bill To - Ship To' },
  { value: '3', label: 'Bill From - Dispatch From' },
  { value: '4', label: 'Combination of 2 and 3' },
];

const ROAD_MODE = '1';
const TRANSPORT_MODES = [
  { value: ROAD_MODE, label: '🚛 Road' },
  { value: '2', label: '🚂 Rail' },
  { value: '3', label: '✈️ Air' },
  { value: '4', label: '🚢 Ship' },
];

const VEHICLE_TYPES = [
  { value: 'R', label: 'Regular (R)' },
  { value: 'O', label: 'Over Dimensional (O)' },
];

// Pre-check notes that inform rather than ask for a fix.
const INFORMATIONAL_FIELDS = new Set(['buyer_gstin', 'ship_to_state_code']);

type FieldNotes = Record<string, { message: string; isError: boolean }>;

function notesFromPreCheck(result: EwayBillPreCheckResult): FieldNotes {
  const notes: FieldNotes = {};
  for (const note of result.missing_fields || []) {
    notes[note.field] = { message: note.message, isError: !INFORMATIONAL_FIELDS.has(note.field) };
  }
  for (const error of result.errors || []) {
    notes[error.field] = { message: error.message, isError: true };
  }
  return notes;
}

type FieldProps = {
  name: string;
  label: string;
  notes: FieldNotes;
  children: (describedBy: { id: string; 'aria-invalid'?: true; 'aria-describedby'?: string }) => ReactNode;
};

function Field({ name, label, notes, children }: FieldProps) {
  const id = `eway-${name}`;
  const note = notes[name];
  const noteId = `${id}-note`;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children({
        id,
        ...(note?.isError ? { 'aria-invalid': true as const } : {}),
        ...(note ? { 'aria-describedby': noteId } : {}),
      })}
      {note ? (
        <small id={noteId} className={note.isError ? 'field-error' : 'field-hint'} role={note.isError ? 'alert' : undefined}>
          {note.message}
        </small>
      ) : null}
    </div>
  );
}

type Props = {
  invoice: Invoice;
  onClose: () => void;
};

export default function EwayBillModal({ invoice, onClose }: Props) {
  // ── State ──
  const [step, setStep] = useState<'loading' | 'form' | 'error' | 'json-done'>('loading');
  const [loadError, setLoadError] = useState('');
  const [form, setForm] = useState<EwayBillFormData | null>(null);
  // What the invoice itself has wrong: no form input can fix these, so they block.
  const [invoiceErrors, setInvoiceErrors] = useState<EwayBillValidationError[]>([]);
  const [fieldNotes, setFieldNotes] = useState<FieldNotes>({});
  const [formErrors, setFormErrors] = useState<EwayBillValidationError[]>([]);
  const [generating, setGenerating] = useState(false);
  const [transporters, setTransporters] = useState<TransporterProfile[]>([]);
  const [selectedTransporterId, setSelectedTransporterId] = useState<number | null>(null);
  const [jsonPreview, setJsonPreview] = useState('');
  const [thresholdWarning, setThresholdWarning] = useState<string | null>(null);
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const { companyRole, userRole } = useAuth();
  const role = companyRole ?? userRole;
  const canSaveTransporter = role === 'admin' || role === 'manager';

  useEscapeClose(onClose);

  // ── Load precheck data on mount ──
  useEffect(() => {
    // Under StrictMode the effect runs twice on mount. The first run's answer must
    // not land after the form is showing, or it replaces what the user has typed.
    let cancelled = false;
    (async () => {
      try {
        const [preRes, transRes] = await Promise.all([
          api.get<EwayBillPreCheckResult>(`/invoices/${invoice.id}/eway-bill/precheck`),
          api.get<TransporterProfile[]>('/eway-bill/transporters').catch(() => null),
        ]);
        if (cancelled) return;
        const transporterList: TransporterProfile[] = transRes?.data ?? [];
        setTransporters(transporterList);
        const result = preRes.data;
        setForm(result.form_data);
        setInvoiceErrors(result.item_validation || []);
        setFieldNotes(notesFromPreCheck(result));
        setThresholdWarning(result.threshold_warning || null);

        // Auto-select default transporter
        const def = transporterList.find(t => t.is_default);
        if (def) {
          setSelectedTransporterId(def.id);
        }

        setStep('form');
      } catch (err) {
        if (cancelled) return;
        setLoadError(getApiErrorMessage(err, 'Could not load the E-Way Bill details for this invoice.'));
        setStep('error');
      }
    })();
    return () => { cancelled = true; };
  }, [invoice.id]);

  // ── Handlers ──
  const updateForm = (field: keyof EwayBillFormData, value: string | number | boolean | null) => {
    setForm(prev => prev ? { ...prev, [field]: value } : prev);
    // The user is dealing with it, so stop calling it wrong.
    setFieldNotes(prev => {
      if (!prev[field]) return prev;
      const rest = { ...prev };
      delete rest[field];
      return rest;
    });
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
      // The actual-state fields only apply to the transaction types that show them.
      const payload = {
        ...form,
        dispatch_state_code: showDispatchState(form) ? form.dispatch_state_code : form.seller_state_code,
        ship_to_state_code: showShipToState(form) ? form.ship_to_state_code : form.buyer_state_code,
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
      const { message, fieldErrors } = await getApiErrorDetails(err, 'Could not generate the E-Way Bill JSON. Please try again.');
      const fields = Object.keys(form);
      const known = fieldErrors.filter(e => fields.includes(e.field));
      const other = fieldErrors.filter(e => !fields.includes(e.field));
      if (known.length > 0) {
        setFieldNotes(prev => ({
          ...prev,
          ...Object.fromEntries(known.map(e => [e.field, { message: e.message, isError: true }])),
        }));
      }
      setFormErrors(fieldErrors.length > 0 ? [...known, ...other] : [{ field: '_general', message }]);
      requestAnimationFrame(() => {
        scrollAreaRef.current?.querySelector('[aria-invalid="true"]')?.scrollIntoView({ block: 'center' });
      });
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
          <p style={{ color: 'var(--muted)', marginBottom: '20px' }} role="alert">{loadError}</p>
          <button type="button" className="button button--ghost" onClick={onClose}>Close</button>
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
              <button type="button" className="button button--secondary" onClick={handleCopyJson}>Copy JSON</button>
              <button type="button" className="button button--primary" onClick={handleDownloadJson}>Download</button>
              <ModalCloseButton onClick={onClose} label="Close E-Way Bill" />
            </div>
          </div>
          <p style={{ color: 'var(--accent)', marginBottom: '16px', fontSize: '0.95rem' }}>
            ✅ E-Way Bill JSON generated. Upload this file on the GST E-Way Bill Portal, which runs its own checks on it.
          </p>
          <pre style={{
            background: 'rgb(var(--rgb-muted) / 0.08)',
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
  const errors = [...formErrors, ...invoiceErrors];
  const canGenerate = !generating && invoiceErrors.length === 0;
  const isRoad = form.transport_mode === ROAD_MODE;

  const textField = (name: keyof EwayBillFormData, label: string, options: { maxLength?: number; placeholder?: string; upper?: boolean; type?: string } = {}) => (
    <Field name={name} label={label} notes={fieldNotes}>
      {(described) => (
        <input
          {...described}
          name={name}
          className="input"
          type={options.type}
          value={String(form[name] ?? '')}
          maxLength={options.maxLength}
          placeholder={options.placeholder}
          onChange={e => updateForm(name, options.upper ? e.target.value.toUpperCase() : e.target.value)}
        />
      )}
    </Field>
  );

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="eway-bill-title">
      <div className="modal-panel" style={{ width: 'min(860px, 100%)' }}>
        <div className="panel__header">
          <div>
            <p className="eyebrow">Invoice #{invoice.invoice_number}</p>
            <h2 id="eway-bill-title" className="nav-panel__title">Generate E-Way Bill</h2>
          </div>
          <ModalCloseButton onClick={onClose} label="Close E-Way Bill form" />
        </div>

        {/* Threshold warning (guidance only — never blocks) */}
        {thresholdWarning && (
          <div style={{ background: 'rgb(var(--rgb-warning) / 0.08)', border: '1px solid rgb(var(--rgb-warning) / 0.25)', borderRadius: '16px', padding: '16px', marginBottom: '20px' }}>
            <p style={{ color: 'rgb(var(--rgb-warning))', fontWeight: 700, marginBottom: '4px', fontSize: '0.95rem' }}>⚠️ Threshold Notice</p>
            <p style={{ color: 'var(--muted)', fontSize: '0.9rem', margin: 0 }}>{thresholdWarning}</p>
          </div>
        )}

        {/* Validation errors */}
        {errors.length > 0 && (
          <div role="alert" style={{ background: 'rgb(var(--rgb-danger) / 0.1)', border: '1px solid rgb(var(--rgb-danger) / 0.3)', borderRadius: '16px', padding: '16px', marginBottom: '20px' }}>
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
            </div>
            <div className="field">
              <label htmlFor="eway-transporter-select">Select Transporter</label>
              <select
                id="eway-transporter-select"
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
        <div ref={scrollAreaRef} style={{ display: 'grid', gap: '16px', maxHeight: '55vh', overflowY: 'auto', paddingRight: '4px' }}>
          {/* ── Seller Details ── */}
          <div className="form-section">
            <h3 className="form-section__header" style={{ color: 'var(--accent)', fontWeight: 700, fontSize: '0.95rem' }}>
              🏢 Seller Details
            </h3>
            <div className="field-grid">
              {textField('seller_gstin', 'GSTIN', { upper: true, maxLength: 15 })}
              {textField('seller_trade_name', 'Trade Name')}
              {textField('seller_address_1', 'Address Line 1')}
              {textField('seller_address_2', 'Address Line 2')}
              {textField('seller_place', 'Place')}
              {textField('seller_state_code', 'State Code', { maxLength: 2 })}
              {textField('seller_pincode', 'PIN Code', { maxLength: 6 })}
              {showDispatchState(form) && textField('dispatch_state_code', 'Dispatch From State Code', { maxLength: 2 })}
            </div>
          </div>

          {/* ── Buyer Details ── */}
          <div className="form-section">
            <h3 className="form-section__header" style={{ color: 'var(--accent)', fontWeight: 700, fontSize: '0.95rem' }}>
              👤 Buyer Details
            </h3>
            <div className="field-grid">
              {textField('buyer_gstin', 'GSTIN', { upper: true, maxLength: 15, placeholder: 'Blank if unregistered' })}
              {textField('buyer_trade_name', 'Trade Name')}
              {textField('buyer_state_code', 'State Code', { maxLength: 2 })}
            </div>
            <h4 style={{ margin: '12px 0 4px', fontSize: '0.9rem', fontWeight: 600 }}>
              Delivery address
            </h4>
            <div className="field-grid">
              {textField('buyer_address_1', 'Address Line 1')}
              {textField('buyer_address_2', 'Address Line 2')}
              {textField('buyer_place', 'Place')}
              {textField('buyer_pincode', 'PIN Code', { maxLength: 6 })}
              {showShipToState(form) && textField('ship_to_state_code', 'Ship To State Code', { maxLength: 2 })}
            </div>
          </div>

          {/* ── Supply Details ── */}
          <div className="form-section">
            <h3 className="form-section__header" style={{ color: 'var(--accent)', fontWeight: 700, fontSize: '0.95rem' }}>
              📄 Supply Details
            </h3>
            <div className="field-grid">
              <Field name="transaction_type" label="Transaction Type" notes={fieldNotes}>
                {(described) => (
                  <select {...described} name="transaction_type" className="select" value={form.transaction_type} onChange={e => updateForm('transaction_type', e.target.value)}>
                    {TRANSACTION_TYPES.map(t => (
                      <option key={t.value} value={t.value}>{t.label}</option>
                    ))}
                  </select>
                )}
              </Field>
              <Field name="sub_supply_type" label="Sub-Supply Type" notes={fieldNotes}>
                {(described) => (
                  <select {...described} name="sub_supply_type" className="select" value={form.sub_supply_type} onChange={e => updateForm('sub_supply_type', e.target.value)}>
                    {SUB_SUPPLY_TYPES.map(s => (
                      <option key={s.value} value={s.value}>{s.label}</option>
                    ))}
                  </select>
                )}
              </Field>
            </div>
          </div>

          {/* ── Transport Details ── */}
          <div className="form-section">
            <h3 className="form-section__header" style={{ color: 'var(--accent)', fontWeight: 700, fontSize: '0.95rem' }}>
              🚛 Transport Details
            </h3>
            <div className="field-grid">
              <Field name="transport_mode" label="Transport Mode" notes={fieldNotes}>
                {(described) => (
                  <select {...described} name="transport_mode" className="select" value={form.transport_mode} onChange={e => updateForm('transport_mode', e.target.value)}>
                    {TRANSPORT_MODES.map(m => (
                      <option key={m.value} value={m.value}>{m.label}</option>
                    ))}
                  </select>
                )}
              </Field>
              <Field name="vehicle_type" label="Vehicle Type" notes={fieldNotes}>
                {(described) => (
                  <select {...described} name="vehicle_type" className="select" value={form.vehicle_type} onChange={e => updateForm('vehicle_type', e.target.value)}>
                    {VEHICLE_TYPES.map(v => (
                      <option key={v.value} value={v.value}>{v.label}</option>
                    ))}
                  </select>
                )}
              </Field>
              {textField('vehicle_number', 'Vehicle Number', { upper: true, placeholder: 'e.g., KA12AB1234' })}
              <Field name="distance_km" label="Distance (KM)" notes={fieldNotes}>
                {(described) => (
                  <input
                    {...described}
                    name="distance_km"
                    className="input"
                    type="number"
                    min={0}
                    max={4000}
                    step={1}
                    value={form.distance_km ?? ''}
                    onChange={e => updateForm('distance_km', e.target.value === '' ? null : Number(e.target.value))}
                    placeholder="Blank asks the portal to use the PIN codes"
                  />
                )}
              </Field>
              {!isRoad && textField('transport_doc_no', 'Transport Document Number', { maxLength: 15, placeholder: 'RR, airway bill or bill of lading no.' })}
              {!isRoad && textField('transport_doc_date', 'Transport Document Date', { type: 'date' })}
              {textField('transporter_name', 'Transporter Name', { placeholder: 'Transport company name' })}
              {textField('transporter_gstin', 'Transporter GSTIN', { upper: true, maxLength: 15, placeholder: isRoad ? 'Required if no vehicle number' : 'Optional' })}
            </div>
            {canSaveTransporter && (
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '8px', color: 'var(--muted)', fontSize: '0.9rem', cursor: 'pointer' }}>
                <input type="checkbox" checked={form.save_transporter} onChange={e => updateForm('save_transporter', e.target.checked)} />
                💾 Save as default transporter
              </label>
            )}
          </div>
        </div>

        {/* ── Action buttons ── */}
        <div className="button-row" style={{ marginTop: '20px', justifyContent: 'flex-end' }}>
          <button type="button" className="button button--ghost" onClick={onClose}>Cancel</button>
          <button
            type="button"
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

// NIC only separates the actual from-state on a Dispatch From movement, and the
// actual to-state on a Ship To movement or an export.
function showDispatchState(form: EwayBillFormData) {
  return form.transaction_type === '3' || form.transaction_type === '4';
}

function showShipToState(form: EwayBillFormData) {
  return form.transaction_type === '2' || form.transaction_type === '4' || form.sub_supply_type === SUB_SUPPLY_EXPORT;
}
