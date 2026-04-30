import { useEffect, useMemo, useState } from 'react';
import { FilePlus2, RefreshCw, Search, XCircle } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { cancelCreditNote, createCreditNote, listCreditNotes } from '../api/creditNotes';
import api, { getApiErrorMessage } from '../api/client';
import LedgerCombobox from '../components/LedgerCombobox';
import StatusToasts from '../components/StatusToasts';
import EmptyState from '../components/EmptyState';
import { invoiceCreditStatusMeta } from '../common/invoiceCreditStatus';
import type {
  CompanyProfile,
  CreditNote,
  CreditNoteCreate,
  CreditNoteType,
  Invoice,
  PaginatedInvoices,
  PaginatedLedgers,
  PaginatedProducts,
  Ledger,
  Product,
} from '../types/api';
import formatCurrency from '../utils/formatting';

type SelectedLineItem = {
  invoice: Invoice;
  item: Invoice['items'][number];
  productName: string;
  quantityKey: string;
};

const creditNoteTypeLabels: Record<CreditNoteType, string> = {
  return: 'Return',
  discount: 'Discount',
  adjustment: 'Adjustment',
};

const createCreditNoteTypeLabels: Record<'return' | 'discount', string> = {
  return: 'Return',
  discount: 'Discount',
};

function createQuantityKey(invoiceId: number, invoiceItemId: number) {
  return `${invoiceId}:${invoiceItemId}`;
}

function formatDate(value: string | null | undefined) {
  if (!value) return 'N/A';
  return new Date(value).toLocaleDateString();
}

function roundMoney(value: number) {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

export default function CreditNotesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryLedgerId = searchParams.get('ledger') || '';
  const queryInvoiceId = searchParams.get('invoice') || '';

  const [company, setCompany] = useState<CompanyProfile | null>(null);
  const [ledgers, setLedgers] = useState<Ledger[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [allInvoices, setAllInvoices] = useState<Invoice[]>([]);
  const [creditNotes, setCreditNotes] = useState<CreditNote[]>([]);

  const [selectedLedgerId, setSelectedLedgerId] = useState(queryLedgerId);
  const [selectedInvoiceIds, setSelectedInvoiceIds] = useState<number[]>([]);
  const [creditNoteType, setCreditNoteType] = useState<'return' | 'discount'>('return');
  const [reason, setReason] = useState('');
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [discountAmounts, setDiscountAmounts] = useState<Record<string, string>>({});

  const [loadingBootstrap, setLoadingBootstrap] = useState(true);
  const [loadingCreditNotes, setLoadingCreditNotes] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [cancellingId, setCancellingId] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [listPage, setListPage] = useState(1);
  const [listTotalPages, setListTotalPages] = useState(1);
  const [listTotal, setListTotal] = useState(0);
  const [refreshKey, setRefreshKey] = useState(0);
  const pageSize = 20;

  const currencyCode = company?.currency_code || 'INR';

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        setLoadingBootstrap(true);
        const [companyRes, ledgersRes, productsRes, invoicesRes] = await Promise.all([
          api.get<CompanyProfile>('/company/'),
          api.get<PaginatedLedgers>('/ledgers/', { params: { page_size: 500 } }),
          api.get<PaginatedProducts>('/products/', { params: { page_size: 500 } }),
          api.get<PaginatedInvoices>('/invoices/', { params: { page_size: 500, show_cancelled: false } }),
        ]);

        if (cancelled) return;

        setCompany(companyRes.data);
        setLedgers(ledgersRes.data.items);
        setProducts(productsRes.data.items);
        setAllInvoices(invoicesRes.data.items);

        if (!queryLedgerId && !queryInvoiceId && ledgersRes.data.items[0]) {
          setSelectedLedgerId(String(ledgersRes.data.items[0].id));
        }
      } catch (err) {
        if (!cancelled) {
          setError(getApiErrorMessage(err, 'Unable to load credit note workspace data'));
        }
      } finally {
        if (!cancelled) {
          setLoadingBootstrap(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [queryInvoiceId, queryLedgerId]);

  useEffect(() => {
    if (!queryInvoiceId) return;
    let cancelled = false;

    (async () => {
      try {
        const invoiceRes = await api.get<Invoice>(`/invoices/${Number(queryInvoiceId)}`);
        if (cancelled) return;

        if (invoiceRes.data.ledger_id) {
          setSelectedLedgerId(String(invoiceRes.data.ledger_id));
          setSelectedInvoiceIds([invoiceRes.data.id]);
        }
      } catch (err) {
        if (!cancelled) {
          setError(getApiErrorMessage(err, 'Unable to preload invoice for credit note creation'));
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [queryInvoiceId]);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        setLoadingCreditNotes(true);
        const response = await listCreditNotes({
          page: listPage,
          page_size: pageSize,
          search,
          status: statusFilter || undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
        });

        if (cancelled) return;

        setCreditNotes(response.data.items);
        setListTotal(response.data.total);
        setListTotalPages(response.data.total_pages);
      } catch (err) {
        if (!cancelled) {
          setError(getApiErrorMessage(err, 'Unable to load credit notes'));
        }
      } finally {
        if (!cancelled) {
          setLoadingCreditNotes(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [dateFrom, dateTo, listPage, refreshKey, search, statusFilter]);

  const filteredInvoices = useMemo(() => {
    const numericLedgerId = Number(selectedLedgerId);
    if (!numericLedgerId) return [];
    return allInvoices.filter((invoice) => invoice.ledger_id === numericLedgerId && invoice.status === 'active');
  }, [allInvoices, selectedLedgerId]);

  useEffect(() => {
    if (!selectedLedgerId) return;

    setSelectedInvoiceIds((current) => current.filter((invoiceId) =>
      filteredInvoices.some((invoice) => invoice.id === invoiceId)
    ));
    setQuantities((current) => {
      const allowedKeys = new Set(
        filteredInvoices.flatMap((invoice) => invoice.items.map((item) => createQuantityKey(invoice.id, item.id)))
      );
      return Object.fromEntries(Object.entries(current).filter(([key]) => allowedKeys.has(key)));
    });
    setDiscountAmounts((current) => {
      const allowedKeys = new Set(
        filteredInvoices.flatMap((invoice) => invoice.items.map((item) => createQuantityKey(invoice.id, item.id)))
      );
      return Object.fromEntries(Object.entries(current).filter(([key]) => allowedKeys.has(key)));
    });
  }, [filteredInvoices, selectedLedgerId]);

  useEffect(() => {
    if (!selectedLedgerId) return;
    const currentLedgerId = searchParams.get('ledger') || '';
    const currentInvoiceId = searchParams.get('invoice') || '';
    const nextInvoiceId = selectedInvoiceIds.length === 1 ? String(selectedInvoiceIds[0]) : '';

    if (currentLedgerId === selectedLedgerId && currentInvoiceId === nextInvoiceId) {
      return;
    }

    const nextParams = new URLSearchParams(searchParams);
    nextParams.set('ledger', selectedLedgerId);
    if (nextInvoiceId) {
      nextParams.set('invoice', nextInvoiceId);
    } else {
      nextParams.delete('invoice');
    }
    setSearchParams(nextParams, { replace: true });
  }, [searchParams, selectedInvoiceIds, selectedLedgerId, setSearchParams]);

  const selectedInvoiceMap = useMemo(() => new Set(selectedInvoiceIds), [selectedInvoiceIds]);

  const selectedLineItems = useMemo<SelectedLineItem[]>(() => {
    return filteredInvoices
      .filter((invoice) => selectedInvoiceMap.has(invoice.id))
      .flatMap((invoice) =>
        invoice.items.map((item) => {
          const matchedProduct = products.find((product) => product.id === item.product_id);
          return {
            invoice,
            item,
            productName: matchedProduct?.name || `Product #${item.product_id}`,
            quantityKey: createQuantityKey(invoice.id, item.id),
          };
        })
      );
  }, [filteredInvoices, products, selectedInvoiceMap]);

  const payloadItems = useMemo(() => {
    if (creditNoteType === 'discount') {
      return selectedLineItems
        .map((line) => ({
          invoice_id: line.invoice.id,
          invoice_item_id: line.item.id,
          discount_amount_inclusive: Number(discountAmounts[line.quantityKey] || 0),
        }))
        .filter((line) => Number.isFinite(line.discount_amount_inclusive) && line.discount_amount_inclusive > 0);
    }

    return selectedLineItems
      .map((line) => ({
        invoice_id: line.invoice.id,
        invoice_item_id: line.item.id,
        quantity: Number(quantities[line.quantityKey] || 0),
      }))
      .filter((line) => Number.isInteger(line.quantity) && line.quantity > 0);
  }, [creditNoteType, discountAmounts, quantities, selectedLineItems]);

  const previewTotal = useMemo(() => {
    if (creditNoteType === 'discount') {
      return selectedLineItems.reduce((sum, line) => {
        const discount = Number(discountAmounts[line.quantityKey] || 0);
        if (!Number.isFinite(discount) || discount <= 0) {
          return sum;
        }
        return sum + discount;
      }, 0);
    }

    return selectedLineItems.reduce((sum, line) => {
      const quantity = Number(quantities[line.quantityKey] || 0);
      if (!Number.isFinite(quantity) || quantity <= 0) {
        return sum;
      }
      const ratio = quantity / Math.max(line.item.quantity, 1);
      return sum + (line.item.line_total * ratio);
    }, 0);
  }, [creditNoteType, discountAmounts, quantities, selectedLineItems]);

  const discountPreviewSplit = useMemo(() => {
    if (creditNoteType !== 'discount') {
      return { taxable: 0, tax: 0 };
    }

    return selectedLineItems.reduce((acc, line) => {
      const discount = Number(discountAmounts[line.quantityKey] || 0);
      if (!Number.isFinite(discount) || discount <= 0) {
        return acc;
      }

      const gstRate = Number(line.item.gst_rate || 0);
      const taxable = gstRate > 0 ? roundMoney(discount / (1 + (gstRate / 100))) : roundMoney(discount);
      const tax = roundMoney(discount - taxable);

      return {
        taxable: roundMoney(acc.taxable + taxable),
        tax: roundMoney(acc.tax + tax),
      };
    }, { taxable: 0, tax: 0 });
  }, [creditNoteType, discountAmounts, selectedLineItems]);

  function handleLedgerChange(nextLedgerId: string) {
    setSelectedLedgerId(nextLedgerId);
    setSelectedInvoiceIds([]);
    setQuantities({});
    setDiscountAmounts({});
    setReason('');
  }

  function handleToggleInvoice(invoiceId: number) {
    setSelectedInvoiceIds((current) => {
      if (current.includes(invoiceId)) {
        setQuantities((existing) => {
          const next = { ...existing };
          Object.keys(next)
            .filter((key) => key.startsWith(`${invoiceId}:`))
            .forEach((key) => delete next[key]);
          return next;
        });
        setDiscountAmounts((existing) => {
          const next = { ...existing };
          Object.keys(next)
            .filter((key) => key.startsWith(`${invoiceId}:`))
            .forEach((key) => delete next[key]);
          return next;
        });
        return current.filter((value) => value !== invoiceId);
      }
      return [...current, invoiceId];
    });
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!selectedLedgerId) {
      setError('Select a ledger before creating a credit note.');
      return;
    }
    if (selectedInvoiceIds.length === 0) {
      setError('Select at least one invoice.');
      return;
    }
    if (payloadItems.length === 0) {
      setError(creditNoteType === 'discount' ? 'Enter at least one discount amount.' : 'Enter at least one credited quantity.');
      return;
    }

    const payload: CreditNoteCreate = {
      ledger_id: Number(selectedLedgerId),
      invoice_ids: selectedInvoiceIds,
      credit_note_type: creditNoteType,
      reason: reason.trim() || null,
      items: payloadItems,
    };

    try {
      setSubmitting(true);
      const response = await createCreditNote(payload);
      setSuccess(`Credit note ${response.data.credit_note_number} created.`);
      setReason('');
      setSelectedInvoiceIds([]);
      setQuantities({});
      setDiscountAmounts({});
      setRefreshKey((value) => value + 1);

      const [creditNotesRes, invoicesRes] = await Promise.all([
        listCreditNotes({ page: listPage, page_size: pageSize, search, status: statusFilter || undefined, date_from: dateFrom || undefined, date_to: dateTo || undefined }),
        api.get<PaginatedInvoices>('/invoices/', { params: { page_size: 500, show_cancelled: false } }),
      ]);

      setCreditNotes(creditNotesRes.data.items);
      setListTotal(creditNotesRes.data.total);
      setListTotalPages(creditNotesRes.data.total_pages);
      setAllInvoices(invoicesRes.data.items);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to create credit note'));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCancelCreditNote(creditNoteId: number) {
    try {
      setCancellingId(creditNoteId);
      await cancelCreditNote(creditNoteId);
      setSuccess('Credit note cancelled.');
      setRefreshKey((value) => value + 1);

      const [creditNotesRes, invoicesRes] = await Promise.all([
        listCreditNotes({ page: listPage, page_size: pageSize, search, status: statusFilter || undefined, date_from: dateFrom || undefined, date_to: dateTo || undefined }),
        api.get<PaginatedInvoices>('/invoices/', { params: { page_size: 500, show_cancelled: false } }),
      ]);

      setCreditNotes(creditNotesRes.data.items);
      setListTotal(creditNotesRes.data.total);
      setListTotalPages(creditNotesRes.data.total_pages);
      setAllInvoices(invoicesRes.data.items);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to cancel credit note'));
    } finally {
      setCancellingId(null);
    }
  }

  return (
    <>
      <StatusToasts
        error={error}
        success={success}
        onClearError={() => setError('')}
        onClearSuccess={() => setSuccess('')}
      />

      <section className="content-grid">
        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Credit notes</p>
              <h2 className="nav-panel__title">Ledger-first credit workflow</h2>
            </div>
            <div style={{ textAlign: 'right' }}>
              <p className="eyebrow">Preview total</p>
              <strong style={{ fontSize: '1.1rem' }}>{formatCurrency(previewTotal, currencyCode)}</strong>
            </div>
          </div>

          {loadingBootstrap ? <EmptyState message="Loading ledgers, invoices, and products..." /> : null}

          {!loadingBootstrap ? (
            <form className="stack" onSubmit={handleSubmit}>
              <div className="field-grid">
                <label>
                  <span>Ledger</span>
                  <LedgerCombobox
                    id="credit-note-ledger"
                    ledgers={ledgers}
                    value={selectedLedgerId}
                    onChange={handleLedgerChange}
                    required
                  />
                </label>
                <label>
                  <span>Type</span>
                  <select
                    className="select"
                    value={creditNoteType}
                    onChange={(event) => {
                      const nextType = event.target.value as 'return' | 'discount';
                      setCreditNoteType(nextType);
                      setQuantities({});
                      setDiscountAmounts({});
                    }}
                  >
                    {Object.entries(createCreditNoteTypeLabels).map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </select>
                </label>
              </div>

              <label>
                <span>Reason</span>
                <textarea
                  className="textarea"
                  rows={3}
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="Optional narrative for return or discount"
                />
              </label>

              <div className="stack" style={{ gap: '12px' }}>
                <div className="panel" style={{ padding: '16px' }}>
                  <div className="panel__header">
                    <div>
                      <p className="eyebrow">Step 1</p>
                      <h3 className="nav-panel__title" style={{ fontSize: '1rem' }}>Select invoice set</h3>
                    </div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>{filteredInvoices.length} active invoices for this ledger</span>
                  </div>

                  {filteredInvoices.length === 0 ? <EmptyState message="No active invoices found for the selected ledger." /> : null}

                  <div className="stack" style={{ gap: '10px' }}>
                    {filteredInvoices.map((invoice) => {
                      const creditStatus = invoiceCreditStatusMeta[invoice.credit_status];
                      const checked = selectedInvoiceMap.has(invoice.id);
                      return (
                        <label
                          key={invoice.id}
                          style={{
                            display: 'flex',
                            gap: '12px',
                            padding: '12px',
                            border: checked ? '1px solid var(--accent)' : '1px solid var(--border)',
                            borderRadius: '12px',
                            alignItems: 'flex-start',
                            cursor: 'pointer',
                          }}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => handleToggleInvoice(invoice.id)}
                            style={{ marginTop: '4px' }}
                          />
                          <div style={{ flex: 1 }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap' }}>
                              <div>
                                <strong>{invoice.invoice_number || `#${invoice.id}`}</strong>
                                <p style={{ margin: '4px 0 0', color: 'var(--text-muted)' }}>Date {formatDate(invoice.invoice_date)} • {invoice.items.length} items</p>
                              </div>
                              <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                                <span style={{ padding: '4px 10px', borderRadius: '999px', background: creditStatus.background, color: creditStatus.color, fontSize: '0.8rem', fontWeight: 600 }}>
                                  {creditStatus.label}
                                </span>
                                <span style={{ fontWeight: 600 }}>{formatCurrency(invoice.total_amount, invoice.company_currency_code || currencyCode)}</span>
                              </div>
                            </div>
                            <p style={{ margin: '8px 0 0', color: 'var(--text-muted)' }}>
                              {(invoice.items || []).slice(0, 3).map((item) => {
                                const matchedProduct = products.find((product) => product.id === item.product_id);
                                return `${matchedProduct?.name || `Product #${item.product_id}`} x${item.quantity}`;
                              }).join(', ')}
                              {(invoice.items || []).length > 3 ? ' +' : ''}
                            </p>
                          </div>
                        </label>
                      );
                    })}
                  </div>
                </div>

                <div className="panel" style={{ padding: '16px' }}>
                  <div className="panel__header">
                    <div>
                      <p className="eyebrow">Step 2</p>
                      <h3 className="nav-panel__title" style={{ fontSize: '1rem' }}>
                        {creditNoteType === 'discount' ? 'Enter discount amount (tax inclusive)' : 'Choose credited quantities'}
                      </h3>
                    </div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>{payloadItems.length} lines selected</span>
                  </div>

                  {creditNoteType === 'discount' ? (
                    <p style={{ margin: '0 0 8px', color: 'var(--text-muted)' }}>
                      Auto split: Taxable {formatCurrency(discountPreviewSplit.taxable, currencyCode)} + Tax {formatCurrency(discountPreviewSplit.tax, currencyCode)}
                    </p>
                  ) : null}

                  {selectedLineItems.length === 0 ? <EmptyState message="Pick one or more invoices to expose their line items." /> : null}

                  <div className="stack" style={{ gap: '10px' }}>
                    {selectedLineItems.map((line) => {
                      const discountAmount = Number(discountAmounts[line.quantityKey] || 0);
                      const gstRate = Number(line.item.gst_rate || 0);
                      const taxableSplit = gstRate > 0 ? roundMoney(discountAmount / (1 + (gstRate / 100))) : roundMoney(discountAmount);
                      const taxSplit = roundMoney(discountAmount - taxableSplit);

                      return (
                      <div
                        key={line.quantityKey}
                        style={{
                          display: 'grid',
                          gridTemplateColumns: 'minmax(0, 2fr) 120px 120px',
                          gap: '12px',
                          alignItems: 'center',
                          border: '1px solid var(--border)',
                          borderRadius: '12px',
                          padding: '12px',
                        }}
                      >
                        <div>
                          <strong>{line.productName}</strong>
                          <p style={{ margin: '4px 0 0', color: 'var(--text-muted)' }}>
                            Invoice {line.invoice.invoice_number || `#${line.invoice.id}`} • Qty {line.item.quantity} • GST {line.item.gst_rate}%
                          </p>
                        </div>
                        <div>
                          <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: '0.85rem' }}>Line total</p>
                          <strong>{formatCurrency(line.item.line_total, line.invoice.company_currency_code || currencyCode)}</strong>
                          {creditNoteType === 'discount' && discountAmount > 0 ? (
                            <p style={{ margin: '6px 0 0', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                              Split {formatCurrency(taxableSplit, line.invoice.company_currency_code || currencyCode)} + {formatCurrency(taxSplit, line.invoice.company_currency_code || currencyCode)}
                            </p>
                          ) : null}
                        </div>
                        <label>
                          <span style={{ display: 'block', marginBottom: '4px' }}>
                            {creditNoteType === 'discount' ? 'Discount (incl tax)' : 'Credit qty'}
                          </span>
                          <input
                            className="input"
                            type="number"
                            min={0}
                            max={creditNoteType === 'discount' ? undefined : line.item.quantity}
                            step={creditNoteType === 'discount' ? '0.01' : '1'}
                            value={creditNoteType === 'discount' ? (discountAmounts[line.quantityKey] || '') : (quantities[line.quantityKey] || '')}
                            onChange={(event) => {
                              if (creditNoteType === 'discount') {
                                setDiscountAmounts((current) => ({
                                  ...current,
                                  [line.quantityKey]: event.target.value,
                                }));
                                return;
                              }

                              setQuantities((current) => ({
                                ...current,
                                [line.quantityKey]: event.target.value,
                              }));
                            }}
                            placeholder="0"
                          />
                        </label>
                      </div>
                      );
                    })}
                  </div>
                </div>
              </div>

              <div className="button-row">
                <button type="submit" className="button button--primary" disabled={submitting || !selectedLedgerId || payloadItems.length === 0}>
                  <FilePlus2 size={16} />
                  {submitting ? 'Creating...' : 'Create Credit Note'}
                </button>
                <button
                  type="button"
                  className="button button--secondary"
                  onClick={() => {
                    setSelectedInvoiceIds([]);
                    setQuantities({});
                    setDiscountAmounts({});
                    setReason('');
                    setCreditNoteType('return');
                  }}
                >
                  Reset form
                </button>
              </div>
            </form>
          ) : null}
        </article>

        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Registry</p>
              <h2 className="nav-panel__title">Credit note feed</h2>
            </div>
            <div style={{ textAlign: 'right' }}>
              <p className="eyebrow">Listed total</p>
              <strong style={{ fontSize: '1.1rem' }}>{listTotal}</strong>
            </div>
          </div>

          <div className="field-grid">
            <label>
              <span>Search</span>
              <div style={{ position: 'relative' }}>
                <Search size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                <input
                  className="input"
                  style={{ paddingLeft: '36px' }}
                  value={search}
                  onChange={(event) => { setSearch(event.target.value); setListPage(1); }}
                  placeholder="Search credit note, ledger, or invoice number"
                />
              </div>
            </label>
            <label>
              <span>Status</span>
              <select
                className="select"
                value={statusFilter}
                onChange={(event) => { setStatusFilter(event.target.value); setListPage(1); }}
              >
                <option value="">All</option>
                <option value="active">Active</option>
                <option value="cancelled">Cancelled</option>
              </select>
            </label>
            <label>
              <span>From</span>
              <input className="input" type="date" value={dateFrom} onChange={(event) => { setDateFrom(event.target.value); setListPage(1); }} />
            </label>
            <label>
              <span>To</span>
              <input className="input" type="date" value={dateTo} onChange={(event) => { setDateTo(event.target.value); setListPage(1); }} />
            </label>
          </div>

          <div className="button-row">
            <button type="button" className="button button--ghost" onClick={() => {
              setSearch('');
              setStatusFilter('');
              setDateFrom('');
              setDateTo('');
              setListPage(1);
            }}>
              <XCircle size={16} />
              Clear filters
            </button>
            <button type="button" className="button button--secondary" onClick={() => setRefreshKey((value) => value + 1)}>
              <RefreshCw size={16} />
              Refresh
            </button>
          </div>

          {loadingCreditNotes ? <EmptyState message="Loading credit notes..." /> : null}
          {!loadingCreditNotes && creditNotes.length === 0 ? <EmptyState message="No credit notes match the current filters." /> : null}

          <div className="stack" style={{ gap: '12px' }}>
            {creditNotes.map((creditNote) => {
              const ledger = ledgers.find((entry) => entry.id === creditNote.ledger_id);
              return (
                <div key={creditNote.id} className="panel" style={{ padding: '16px' }}>
                  <div className="panel__header">
                    <div>
                      <p className="eyebrow">{creditNoteTypeLabels[creditNote.credit_note_type]}</p>
                      <h3 className="nav-panel__title" style={{ fontSize: '1rem' }}>{creditNote.credit_note_number}</h3>
                    </div>
                    <span style={{
                      padding: '4px 10px',
                      borderRadius: '999px',
                      background: creditNote.status === 'cancelled' ? '#fee2e2' : '#dcfce7',
                      color: creditNote.status === 'cancelled' ? '#b91c1c' : '#166534',
                      fontSize: '0.8rem',
                      fontWeight: 600,
                    }}>
                      {creditNote.status === 'cancelled' ? 'Cancelled' : 'Active'}
                    </span>
                  </div>

                  <p style={{ margin: '0 0 10px', color: 'var(--text-muted)' }}>
                    {ledger?.name || `Ledger #${creditNote.ledger_id}`} • Created {formatDate(creditNote.created_at)} • Invoices {creditNote.invoice_ids.join(', ')}
                  </p>

                  {creditNote.reason ? <p style={{ margin: '0 0 10px' }}>{creditNote.reason}</p> : null}

                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap', alignItems: 'center' }}>
                    <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', color: 'var(--text-muted)' }}>
                      <span>Taxable {formatCurrency(creditNote.taxable_amount, currencyCode)}</span>
                      <span>Tax {formatCurrency(creditNote.cgst_amount + creditNote.sgst_amount + creditNote.igst_amount, currencyCode)}</span>
                      <strong style={{ color: 'var(--text)' }}>Total {formatCurrency(creditNote.total_amount, currencyCode)}</strong>
                    </div>
                    {creditNote.status === 'active' ? (
                      <button
                        type="button"
                        className="button button--danger"
                        disabled={cancellingId === creditNote.id}
                        onClick={() => void handleCancelCreditNote(creditNote.id)}
                      >
                        {cancellingId === creditNote.id ? 'Cancelling...' : 'Cancel credit note'}
                      </button>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>

          {listTotalPages > 1 ? (
            <div className="button-row" style={{ justifyContent: 'center' }}>
              <button type="button" className="button button--ghost" disabled={listPage <= 1} onClick={() => setListPage((page) => page - 1)}>
                Previous
              </button>
              <span style={{ alignSelf: 'center', color: 'var(--text-muted)' }}>Page {listPage} of {listTotalPages}</span>
              <button type="button" className="button button--ghost" disabled={listPage >= listTotalPages} onClick={() => setListPage((page) => page + 1)}>
                Next
              </button>
            </div>
          ) : null}
        </article>
      </section>
    </>
  );
}