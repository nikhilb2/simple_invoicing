import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { Boxes, Lock, Plus, Trash2 } from 'lucide-react';
import api, { getApiErrorMessage } from '../../api/client';
import { track } from '../../lib/analytics';
import type { CompanyAccount, CompanyProfile, Invoice, InvoiceCreate, Ledger, LedgerAddress, Payment, PaymentCreate, Product } from '../../types/api';
import InvoicePreview from '../../components/InvoicePreview';
import ScanBar, { type ScanOutcome, type ScanResolution } from '../../components/ScanBar';
import StatusToasts from '../../components/StatusToasts';
import ProductCombobox from '../../components/ProductCombobox';
import LedgerCombobox from '../../components/LedgerCombobox';
import formatCurrency from '../../utils/formatting';
import { formatInvoiceTaxBreakdown, isInterstateSupply } from '../../utils/invoiceTax';
import { createDueDateFormState, formatInvoiceDateLabel, resolveDueDate, type DueDateMode } from '../../utils/invoiceDueDate.ts';
import { readInvoiceComposerPrefs, updateInvoiceComposerPrefs } from '../../utils/invoiceComposerPrefs.ts';
import { useFY } from '../../context/FYContext';
import { useShortcuts } from '../../context/ShortcutsContext';
import { fetchInvoiceById, fetchInvoiceComposerData, fetchLedgerAddresses } from '../../features/invoices/api';
import { invoiceQueryKeys } from '../../features/invoices/queryKeys';
import { useInvoiceComposerStore } from '../../store/useInvoiceComposerStore';
import LedgerQuickCreateModal from './components/LedgerQuickCreateModal';
import ProductQuickCreateModal from './components/ProductQuickCreateModal';
import SerialChips from './components/SerialChips';
import SerialPickerModal from './components/SerialPickerModal';
import StockUpdateModal from './components/StockUpdateModal';
import ReceiptModal from '../../components/ReceiptModal';
import { createItem, type InvoiceFormItem } from './types';

export default function InvoicesPage() {
  const { activeFY } = useFY();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedLedgerId = useInvoiceComposerStore((state) => state.selectedLedgerId);
  const setSelectedLedgerId = useInvoiceComposerStore((state) => state.setSelectedLedgerId);
  const openLedgerCreateModal = useInvoiceComposerStore((state) => state.openLedgerCreateModal);
  const openProductCreateModal = useInvoiceComposerStore((state) => state.openProductCreateModal);
  const openStockUpdateModal = useInvoiceComposerStore((state) => state.openStockUpdateModal);
  const feedbackError = useInvoiceComposerStore((state) => state.feedbackError);
  const feedbackSuccess = useInvoiceComposerStore((state) => state.feedbackSuccess);
  const clearFeedback = useInvoiceComposerStore((state) => state.clearFeedback);
  /* Settings the user picks the same way on most invoices are restored here.
     Read in an initializer rather than an effect so a remembered choice is
     already applied on first paint instead of flipping in after it. */
  const [initialPrefs] = useState(readInvoiceComposerPrefs);
  const [products, setProducts] = useState<Product[]>([]);
  const [ledgers, setLedgers] = useState<Ledger[]>([]);
  const [company, setCompany] = useState<CompanyProfile | null>(null);
  const [companyAccounts, setCompanyAccounts] = useState<CompanyAccount[]>([]);
  const [voucherType, setVoucherType] = useState<'sales' | 'purchase' | 'payment' | 'receipt'>('sales');
  const [showReceiptModal, setShowReceiptModal] = useState(false);
  const [taxInclusive, setTaxInclusive] = useState(initialPrefs.taxInclusive);
  const [applyRoundOff, setApplyRoundOff] = useState(initialPrefs.applyRoundOff);
  const [invoiceDiscountType, setInvoiceDiscountType] = useState<'percentage' | 'net'>(initialPrefs.invoiceDiscountType);
  const [invoiceDiscountValue, setInvoiceDiscountValue] = useState('');
  const [supplierInvoiceNumber, setSupplierInvoiceNumber] = useState('');
  const [referenceNotes, setReferenceNotes] = useState('');
  const [paymentMode, setPaymentMode] = useState('cash');
  const [paymentReference, setPaymentReference] = useState('');
  const [selectedPaymentAccountId, setSelectedPaymentAccountId] = useState('');
  const [paymentAmount, setPaymentAmount] = useState('');
  const [invoiceDate, setInvoiceDate] = useState(new Date().toISOString().slice(0, 10));
  const [dueDateMode, setDueDateMode] = useState<DueDateMode>(initialPrefs.dueDateMode);
  const [dueDate, setDueDate] = useState('');
  const [dueDateDays, setDueDateDays] = useState(initialPrefs.dueDateDays);
  const [items, setItems] = useState<InvoiceFormItem[]>([createItem(1)]);
  const [nextItemId, setNextItemId] = useState(2);
  const [flashItemId, setFlashItemId] = useState<number | null>(null);
  const [pickerItemId, setPickerItemId] = useState<number | null>(null);
  /** Tracked lines a submit attempt found empty, so the block is stated where
   *  the fix is rather than in a toast at the top of the page. */
  const [serialBlockIds, setSerialBlockIds] = useState<number[]>([]);
  const [scanTargetItemId, setScanTargetItemId] = useState<number | null>(null);
  const [editingInvoiceId, setEditingInvoiceId] = useState<number | null>(null);
  /** Everything that is not needed to write an ordinary invoice lives behind
   *  this. It opens itself when a value inside it is actually in use — editing
   *  an invoice that carries a discount must not hide the discount. */
  const [showAdvanced, setShowAdvanced] = useState(initialPrefs.showAdvanced);
  // Shipping address state (sales invoices only)
  const [ledgerAddresses, setLedgerAddresses] = useState<LedgerAddress[]>([]);
  const [shippingSameAsBilling, setShippingSameAsBilling] = useState(true);
  const [selectedShippingAddressId, setSelectedShippingAddressId] = useState<number | null>(null);
  const [newShippingLabel, setNewShippingLabel] = useState('');
  const [newShippingAddress, setNewShippingAddress] = useState('');
  const showCancelled = false;
  const [previewInvoice, setPreviewInvoice] = useState<Invoice | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const invoicePage = 1;
  const [invoiceTotal, setInvoiceTotal] = useState(0);
  const invoiceSearch = '';
  const invoicePageSize = 20;
  const financialYearId = activeFY?.id;
  const { registerAction } = useShortcuts();

  /* A scanner fires codes faster than React repaints, and each one has to see
     the lines the one before it produced — otherwise the second handset of a
     burst opens a second line for a product that already has one. These refs
     are the synchronous copy the scan handlers read; every render re-syncs them
     so an edit made with the mouse is never lost. */
  const itemsRef = useRef(items);
  const nextItemIdRef = useRef(nextItemId);
  const scanTargetRef = useRef<number | null>(scanTargetItemId);
  const scanInputRef = useRef<HTMLInputElement>(null);
  const flashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    itemsRef.current = items;
    nextItemIdRef.current = nextItemId;
  });

  const composerQuery = useQuery({
    queryKey: invoiceQueryKeys.composer(invoicePage, invoicePageSize, invoiceSearch, showCancelled, financialYearId),
    queryFn: () =>
      fetchInvoiceComposerData({
        page: invoicePage,
        pageSize: invoicePageSize,
        search: invoiceSearch,
        showCancelled,
        financialYearId,
      }),
  });

  async function loadInvoicePageData() {
    const res = await composerQuery.refetch();
    if (res.error) {
      throw res.error;
    }
  }

  async function refreshInvoicesAfterMutation() {
    await queryClient.invalidateQueries({
      queryKey: invoiceQueryKeys.all,
      refetchType: 'none',
    });
    await loadInvoicePageData();
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get<CompanyAccount[]>('/company-accounts/');
        if (cancelled) return;
        setCompanyAccounts(res.data);
      } catch {
        // Keep payment voucher flow usable even when accounts fail to load.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  /* A real handler, registered where the box lives — note that create_invoice
     and save_invoice are declared in shortcutDefaults with no handler anywhere,
     so those two combos do nothing today. */
  useEffect(() => registerAction('focus_scan', () => scanInputRef.current?.focus()), [registerAction]);

  useEffect(() => () => {
    if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
  }, []);

  useEffect(() => {
    if (!composerQuery.data) {
      return;
    }

    setProducts(composerQuery.data.products);
    setLedgers(composerQuery.data.ledgers);
    setInvoiceTotal(composerQuery.data.invoiceTotal);
    setCompany(composerQuery.data.company);
    if (!selectedLedgerId) {
      setSelectedLedgerId(String(composerQuery.data.ledgers[0]?.id ?? ''));
    }
    setItems((current) =>
      current.map((item, index) => {
        const defaultProduct = composerQuery.data.products[index] ?? composerQuery.data.products[0];
        return {
          ...item,
          productId: item.productId || String(defaultProduct?.id ?? ''),
          unit_price: item.unit_price || String(defaultProduct?.price ?? ''),
          // Filled by the composer, so a scan may still take this line over.
          autoFilled: item.productId ? item.autoFilled : true,
        };
      })
    );
  }, [composerQuery.data, selectedLedgerId, setSelectedLedgerId]);

  // Fetch ledger addresses when ledger selection changes (for shipping address UI)
  useEffect(() => {
    if (!selectedLedgerId) {
      setLedgerAddresses([]);
      return;
    }
    let cancelled = false;
    fetchLedgerAddresses(Number(selectedLedgerId))
      .then((addrs) => { if (!cancelled) setLedgerAddresses(addrs); })
      .catch(() => { if (!cancelled) setLedgerAddresses([]); });
    return () => { cancelled = true; };
  }, [selectedLedgerId]);

  // Reset shipping selection when ledger changes
  useEffect(() => {
    setShippingSameAsBilling(true);
    setSelectedShippingAddressId(null);
    setNewShippingLabel('');
    setNewShippingAddress('');
  }, [selectedLedgerId]);

  // Handle ?edit=<id> query param — triggered from invoice feed or any other page
  useEffect(() => {
    const editId = searchParams.get('edit');
    if (!editId || editingInvoiceId) return;
    fetchInvoiceById(Number(editId))
      .then(startEditingInvoice)
      .catch(() => setError('Unable to load invoice for editing.'));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  // Handle ?duplicate=<id> query param — pre-fill create form from existing invoice
  useEffect(() => {
    const duplicateId = searchParams.get('duplicate');
    if (!duplicateId || editingInvoiceId) return;
    fetchInvoiceById(Number(duplicateId))
      .then(startDuplicatingInvoice)
      .catch(() => setError('Unable to load invoice for duplication.'));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  useEffect(() => {
    if (!composerQuery.error) {
      return;
    }
    setError(getApiErrorMessage(composerQuery.error, 'Unable to load invoice data'));
  }, [composerQuery.error]);

  const totalAmount = items.reduce((sum, item) => {
    const product = products.find((entry) => entry.id === Number(item.productId));
    /* A tracked line is worth exactly as many units as it has serials — there
       is no state in which the two can disagree. */
    const quantity = product?.track_serials ? item.serials.length : Number(item.quantity);
    const unitPrice = item.unit_price ? Number(item.unit_price) : (product?.price || 0);
    const gstRate = product?.gst_rate || 0;

    if (!product || Number.isNaN(quantity)) {
      return sum;
    }

    let lineTotal: number;
    let taxableAmount: number;
    if (taxInclusive) {
      lineTotal = unitPrice * quantity;
      taxableAmount = lineTotal / (1 + gstRate / 100);
    } else {
      taxableAmount = unitPrice * quantity;
      lineTotal = taxableAmount + taxableAmount * gstRate / 100;
    }

    // Apply item-level discount
    if (item.discount_type && item.discount_value && Number(item.discount_value) > 0) {
      const discVal = Number(item.discount_value);
      let discAmount = 0;
      if (item.discount_type === 'percentage') {
        discAmount = taxableAmount * discVal / 100;
      } else {
        discAmount = Math.min(discVal, taxableAmount);
      }
      const discountedTaxable = taxableAmount - discAmount;
      if (taxInclusive) {
        lineTotal = discountedTaxable * (1 + gstRate / 100);
      } else {
        lineTotal = discountedTaxable + discountedTaxable * gstRate / 100;
      }
    }

    return sum + lineTotal;
  }, 0);

  // Apply invoice-level discount
  let invoiceDiscountAmount = 0;
  if (invoiceDiscountType && invoiceDiscountValue && Number(invoiceDiscountValue) > 0) {
    const discVal = Number(invoiceDiscountValue);
    if (invoiceDiscountType === 'percentage') {
      invoiceDiscountAmount = totalAmount * discVal / 100;
    } else {
      invoiceDiscountAmount = Math.min(discVal, totalAmount);
    }
  }
  const afterDiscountTotal = totalAmount - invoiceDiscountAmount;

  const roundedTotalAmount = Math.round(afterDiscountTotal);
  const roundOffPreviewAmount = applyRoundOff ? roundedTotalAmount - afterDiscountTotal : 0;
  const projectedTotalAmount = applyRoundOff ? roundedTotalAmount : afterDiscountTotal;

  const activeCurrencyCode = company?.currency_code || 'USD';
  const selectedLedger = ledgers.find((entry) => entry.id === Number(selectedLedgerId));
  const composerInterstateSupply = isInterstateSupply(company?.gst, selectedLedger?.gst);
  const resolvedDueDate = resolveDueDate({
    mode: dueDateMode,
    invoiceDate,
    exactDate: dueDate,
    daysFromInvoice: dueDateDays,
  });

  /* Which advanced settings this invoice actually uses. It names them on the
     closed row, so the disclosure is worth reading before opening it. */
  const advancedInUse = [
    dueDateMode !== 'none' ? 'due date' : '',
    supplierInvoiceNumber.trim() || referenceNotes.trim() ? 'reference' : '',
    voucherType === 'sales' && !shippingSameAsBilling ? 'shipping address' : '',
    Number(invoiceDiscountValue) > 0 ? 'discount' : '',
    applyRoundOff ? 'round off' : '',
  ].filter(Boolean);
  const advancedSummary = advancedInUse.length > 0
    ? `In use: ${advancedInUse.join(' · ')}`
    : 'Due date, reference, shipping address, discount, round off';

  /* Never hide a setting that is in use: an invoice opened for editing can
     carry any of these, and a closed disclosure would put them out of sight
     while they still affect the total. */
  const advancedCount = advancedInUse.length;
  useEffect(() => {
    if (advancedCount > 0) setShowAdvanced(true);
  }, [advancedCount]);

  function addItem() {
    const defaultProduct = products[0];
    setItems((current) => [...current, createItem(nextItemId, String(defaultProduct?.id ?? ''), String(defaultProduct?.price ?? ''))]);
    setNextItemId((current) => current + 1);
  }

  function removeItem(id: number) {
    setItems((current) => (current.length === 1 ? current : current.filter((item) => item.id !== id)));
  }

  function updateItem(id: number, key: 'productId' | 'quantity' | 'unit_price' | 'description' | 'discount_type' | 'discount_value', value: string) {
    setItems((current) => current.map((item) => (item.id === id ? { ...item, [key]: value, autoFilled: false } : item)));
  }

  // ---------------------------------------------------------------------------
  // Scanning
  // ---------------------------------------------------------------------------

  function findProduct(productId: number) {
    return products.find((product) => product.id === productId);
  }

  function isTrackedLine(item: InvoiceFormItem) {
    return Boolean(findProduct(Number(item.productId))?.track_serials);
  }

  function lineQuantity(item: InvoiceFormItem) {
    return isTrackedLine(item) ? item.serials.length : Number(item.quantity);
  }

  /** Writes to the ref first so the next queued scan reads the new lines. */
  function commitItems(next: InvoiceFormItem[]) {
    itemsRef.current = next;
    setItems(next);
  }

  function takeItemId() {
    const id = nextItemIdRef.current;
    nextItemIdRef.current = id + 1;
    setNextItemId(id + 1);
    return id;
  }

  function setScanTarget(itemId: number) {
    scanTargetRef.current = itemId;
    setScanTargetItemId(itemId);
  }

  function clearSerialBlock(itemId: number) {
    setSerialBlockIds((current) => current.filter((entry) => entry !== itemId));
  }

  /* The line the scan landed on lights up, because the operator is looking at
     the handset in their hand, not at the screen. Dropping the attribute for a
     frame is what lets the same line flash twice in a row — an animation does
     not restart while its selector keeps matching. */
  function flashLine(itemId: number) {
    if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
    setFlashItemId(null);
    window.requestAnimationFrame(() => setFlashItemId(itemId));
    flashTimerRef.current = setTimeout(() => setFlashItemId(null), 1200);
  }

  /* A serial can name a product that is not in the composer's catalogue page —
     it loads 500 products, a long catalogue has more. Adopting it keeps the
     combobox label, the tax rate and the line total correct. */
  function adoptProduct(product: Product) {
    setProducts((current) => (current.some((entry) => entry.id === product.id) ? current : [...current, product]));
  }

  function findLineWithSerial(serialNumber: string) {
    const wanted = serialNumber.trim().toUpperCase();
    return itemsRef.current.findIndex((item) => item.serials.some((entry) => entry.trim().toUpperCase() === wanted));
  }

  /**
   * The line a scanned product belongs on: an existing line for it, else the
   * composer's own seeded line if nobody has touched it, else a new one. Taking
   * the seeded line over is what stops a five-phone invoice starting with a
   * stray line of whatever product happened to be first in the catalogue.
   */
  function lineForProduct(product: Product): { item: InvoiceFormItem; index: number; created: boolean } {
    const current = itemsRef.current;
    const existingIndex = current.findIndex((item) => Number(item.productId) === product.id);
    if (existingIndex >= 0) {
      return { item: current[existingIndex], index: existingIndex, created: false };
    }

    const spareIndex = current.findIndex((item) => item.autoFilled && item.serials.length === 0);
    if (spareIndex >= 0) {
      const spare: InvoiceFormItem = {
        ...current[spareIndex],
        productId: String(product.id),
        unit_price: String(product.price),
        quantity: '1',
        serials: [],
        autoFilled: false,
      };
      const next = [...current];
      next[spareIndex] = spare;
      commitItems(next);
      return { item: spare, index: spareIndex, created: true };
    }

    const fresh: InvoiceFormItem = {
      ...createItem(takeItemId(), String(product.id), String(product.price)),
      autoFilled: false,
    };
    commitItems([...current, fresh]);
    return { item: fresh, index: current.length, created: true };
  }

  function serialTail(serialNumber: string) {
    return serialNumber.length > 4 ? `…${serialNumber.slice(-4)}` : serialNumber;
  }

  function attachSerial(item: InvoiceFormItem, index: number, product: Product, serialNumber: string): ScanOutcome {
    const serials = [...item.serials, serialNumber];
    commitItems(itemsRef.current.map((entry) => (entry.id === item.id ? { ...entry, serials, autoFilled: false } : entry)));
    setScanTarget(item.id);
    clearSerialBlock(item.id);
    flashLine(item.id);
    return {
      status: 'ok',
      message: `${product.name} · ${serialTail(serialNumber)} → Line ${index + 1} (qty ${serials.length})`,
    };
  }

  function addProductUnit(product: Product): ScanOutcome {
    const { item, index, created } = lineForProduct(product);
    const quantity = created ? item.quantity : String(Number(item.quantity || '0') + 1);
    commitItems(itemsRef.current.map((entry) => (entry.id === item.id ? { ...entry, quantity, autoFilled: false } : entry)));
    flashLine(item.id);
    return { status: 'ok', message: `${product.name} → Line ${index + 1} (qty ${quantity})` };
  }

  /** Purchase mode registers into a line, so it needs one: the last tracked
   *  line a scan touched, or the only tracked line there is. */
  function resolveScanTarget() {
    const tracked = itemsRef.current
      .map((item, index) => ({ item, index }))
      .filter((entry) => isTrackedLine(entry.item));
    return tracked.find((entry) => entry.item.id === scanTargetRef.current) ?? tracked[tracked.length - 1] ?? null;
  }

  function handleScanResolution(resolution: ScanResolution): ScanOutcome {
    const purchase = voucherType === 'purchase';

    if (resolution.kind === 'product') {
      adoptProduct(resolution.product);
      if (!resolution.product.track_serials) {
        track('serial_scan', { mode: purchase ? 'purchase' : 'sales', kind: 'product' });
        return addProductUnit(resolution.product);
      }
      // A tracked product's own barcode cannot add a unit — a unit is a serial.
      const { item, index } = lineForProduct(resolution.product);
      setScanTarget(item.id);
      flashLine(item.id);
      return { status: 'info', message: `Line ${index + 1} · ${resolution.product.name} — scan each serial now.` };
    }

    if (resolution.kind === 'serial') {
      const serial = resolution.serial;
      const onLine = findLineWithSerial(serial.serial_number);
      if (onLine >= 0) {
        flashLine(itemsRef.current[onLine].id);
        return { status: 'info', message: `Already added to line ${onLine + 1}.` };
      }

      if (purchase) {
        track('serial_scan_failed', { mode: 'purchase', reason: 'already_registered' });
        const arrival = serial.purchase_invoice
          ? ` on ${serial.purchase_invoice.invoice_number ?? `#${serial.purchase_invoice.id}`}`
          : '';
        return { status: 'error', message: `Already registered to ${serial.product.name}${arrival}.` };
      }

      if (serial.status === 'sold') {
        track('serial_scan_failed', { mode: 'sales', reason: 'sold' });
        const ref = serial.sales_invoice;
        if (!ref) {
          return { status: 'error', message: 'This serial has already been sold.' };
        }
        const label = ref.invoice_number ?? `#${ref.id}`;
        return {
          status: 'error',
          message: `Already sold on ${label} (${formatInvoiceDateLabel(ref.invoice_date)})`,
          link: { to: `/invoices-view?search=${encodeURIComponent(label)}`, label: 'Open invoice' },
        };
      }

      adoptProduct(serial.product);
      const product = findProduct(serial.product_id) ?? serial.product;
      const { item, index } = lineForProduct(product);
      track('serial_scan', { mode: 'sales', kind: 'serial' });
      return attachSerial(item, index, product, serial.serial_number);
    }

    if (!purchase) {
      track('serial_scan_failed', { mode: 'sales', reason: 'unknown_code' });
      return { status: 'error', message: resolution.detail };
    }

    // Purchase: a code nobody has registered is exactly what should be arriving.
    const onLine = findLineWithSerial(resolution.code);
    if (onLine >= 0) {
      flashLine(itemsRef.current[onLine].id);
      return { status: 'info', message: `Already added to line ${onLine + 1}.` };
    }

    const target = resolveScanTarget();
    if (!target) {
      track('serial_scan_failed', { mode: 'purchase', reason: 'no_target_line' });
      /* Nothing to register into, so the caret goes where the fix is. The scan
         bar leaves it alone from here — it only reclaims focus when nothing
         else holds it. */
      const firstItem = itemsRef.current[0];
      if (firstItem) {
        document.getElementById(`invoice-product-${firstItem.id}`)?.focus();
      }
      return { status: 'error', message: 'Add a serial-tracked product line first — or scan its product barcode.' };
    }

    const product = findProduct(Number(target.item.productId));
    if (!product) {
      return { status: 'error', message: `Choose a product on line ${target.index + 1} first.` };
    }

    track('serial_scan', { mode: 'purchase', kind: 'registered' });
    return attachSerial(target.item, target.index, product, resolution.code);
  }

  function setLineSerials(itemId: number, serials: string[]) {
    commitItems(itemsRef.current.map((item) => (item.id === itemId ? { ...item, serials, autoFilled: false } : item)));
    if (serials.length > 0) {
      setScanTarget(itemId);
      clearSerialBlock(itemId);
    }
  }

  function resetInvoiceForm() {
    /* The next invoice starts from the user's standing preferences, not from
       hard defaults — otherwise every remembered setting would be lost the
       moment an invoice is created. Read fresh rather than reusing the value
       from mount, since they may have changed during the session. */
    const prefs = readInvoiceComposerPrefs();
    setShowAdvanced(prefs.showAdvanced);
    setEditingInvoiceId(null);
    setSupplierInvoiceNumber('');
    setReferenceNotes('');
    setTaxInclusive(prefs.taxInclusive);
    setApplyRoundOff(prefs.applyRoundOff);
    setInvoiceDiscountType(prefs.invoiceDiscountType);
    // Per-invoice, never remembered: a carried-over discount would silently
    // reduce the next invoice's total.
    setInvoiceDiscountValue('');
    setPaymentMode('cash');
    setPaymentReference('');
    setSelectedPaymentAccountId('');
    setPaymentAmount('');
    const defaultProduct = products[0];
    itemsRef.current = [createItem(1, String(defaultProduct?.id ?? ''), String(defaultProduct?.price ?? ''))];
    setItems(itemsRef.current);
    setNextItemId(2);
    setSerialBlockIds([]);
    setScanTargetItemId(null);
    scanTargetRef.current = null;
    setPickerItemId(null);
    setInvoiceDate(new Date().toISOString().slice(0, 10));
    setDueDateMode(prefs.dueDateMode);
    setDueDate('');
    setDueDateDays(prefs.dueDateDays);
    setShippingSameAsBilling(true);
    setSelectedShippingAddressId(null);
    setNewShippingLabel('');
    setNewShippingAddress('');
  }

  function startEditingInvoice(invoice: Invoice) {
    if (!invoice.ledger_id) {
      setError('This invoice is missing its ledger and cannot be edited.');
      return;
    }

    if (!invoice.items || invoice.items.length === 0) {
      setError('This invoice has no line items and cannot be edited.');
      return;
    }

    setError('');
    setSuccess('');
    setEditingInvoiceId(invoice.id);
    setVoucherType(invoice.voucher_type);
    setSupplierInvoiceNumber(invoice.supplier_invoice_number ?? '');
    setReferenceNotes(invoice.voucher_type === 'sales' ? (invoice.reference_notes ?? '') : '');
    setTaxInclusive(invoice.tax_inclusive ?? false);
    setApplyRoundOff(invoice.apply_round_off ?? false);
    setInvoiceDiscountType((invoice.discount_type as 'percentage' | 'net') || 'percentage');
    setInvoiceDiscountValue(invoice.discount_value != null ? String(invoice.discount_value) : '');
    setSelectedLedgerId(String(invoice.ledger_id));
    setInvoiceDate(invoice.invoice_date ? invoice.invoice_date.slice(0, 10) : new Date().toISOString().slice(0, 10));
    const dueDateState = createDueDateFormState(invoice.due_date);
    setDueDateMode(dueDateState.mode);
    setDueDate(dueDateState.exactDate);
    setDueDateDays(dueDateState.daysFromInvoice);

    const nextItems = invoice.items.map((line, index) => ({
      id: index + 1,
      productId: String(line.product_id),
      quantity: String(line.quantity),
      unit_price: String(line.unit_price),
      description: line.description ?? '',
      discount_type: (line.discount_type || '') as '' | 'percentage' | 'net',
      discount_value: line.discount_value != null ? String(line.discount_value) : '',
      serials: line.serial_numbers ?? [],
      autoFilled: false,
    }));

    itemsRef.current = nextItems;
    setItems(nextItems);
    setNextItemId(nextItems.length + 1);
    // Restore shipping address state from the invoice being edited
    if (invoice.shipping_address) {
      setShippingSameAsBilling(false);
      // We only have the snapshot; pre-fill the new-address fields so the user can see what was used
      setSelectedShippingAddressId(null);
      setNewShippingLabel(invoice.shipping_address_label ?? '');
      setNewShippingAddress(invoice.shipping_address);
    } else {
      setShippingSameAsBilling(true);
      setSelectedShippingAddressId(null);
      setNewShippingLabel('');
      setNewShippingAddress('');
    }
  }

  function startDuplicatingInvoice(invoice: Invoice) {
    if (!invoice.ledger_id) {
      setError('This invoice is missing its ledger and cannot be duplicated.');
      return;
    }

    if (!invoice.items || invoice.items.length === 0) {
      setError('This invoice has no line items and cannot be duplicated.');
      return;
    }

    setError('');
    setSuccess('Invoice data loaded. Review and click Create Invoice to save.');
    setEditingInvoiceId(null);
    setVoucherType(invoice.voucher_type);
    setSupplierInvoiceNumber(invoice.supplier_invoice_number ?? '');
    setReferenceNotes(invoice.voucher_type === 'sales' ? (invoice.reference_notes ?? '') : '');
    setTaxInclusive(invoice.tax_inclusive ?? false);
    setApplyRoundOff(invoice.apply_round_off ?? false);
    setInvoiceDiscountType((invoice.discount_type as 'percentage' | 'net') || 'percentage');
    setInvoiceDiscountValue(invoice.discount_value != null ? String(invoice.discount_value) : '');
    setSelectedLedgerId(String(invoice.ledger_id));
    setInvoiceDate(new Date().toISOString().slice(0, 10));
    setDueDateMode('none');
    setDueDate('');
    setDueDateDays('');

    const nextItems = invoice.items.map((line, index) => ({
      id: index + 1,
      productId: String(line.product_id),
      quantity: String(line.quantity),
      unit_price: String(line.unit_price),
      description: line.description ?? '',
      discount_type: (line.discount_type || '') as '' | 'percentage' | 'net',
      discount_value: line.discount_value != null ? String(line.discount_value) : '',
      /* Serials are physical units, and the copy is not those units. The
         duplicate arrives with none, and cannot be saved until they are
         scanned off the handsets actually going out. */
      serials: [],
      autoFilled: false,
    }));

    itemsRef.current = nextItems;
    setItems(nextItems);
    setNextItemId(nextItems.length + 1);
    // Restore shipping address state from the invoice being duplicated
    if (invoice.shipping_address) {
      setShippingSameAsBilling(false);
      setSelectedShippingAddressId(null);
      setNewShippingLabel(invoice.shipping_address_label ?? '');
      setNewShippingAddress(invoice.shipping_address);
    } else {
      setShippingSameAsBilling(true);
      setSelectedShippingAddressId(null);
      setNewShippingLabel('');
      setNewShippingAddress('');
    }

    // Clear the duplicate query param so a refresh doesn't re-trigger
    if (searchParams.has('duplicate')) {
      setSearchParams((prev) => { prev.delete('duplicate'); return prev; }, { replace: true });
    }
  }

  async function handleSubmitInvoice(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (voucherType === 'receipt') {
      if (!selectedLedgerId) {
        setError('Please select a ledger to record a receipt against.');
        return;
      }
      setShowReceiptModal(true);
      return;
    }

    if (voucherType === 'payment') {
      try {
        setSubmitting(true);
        setError('');
        setSuccess('');

        const payload: PaymentCreate = {
          ledger_id: Number(selectedLedgerId),
          voucher_type: 'payment',
          amount: Number(paymentAmount),
          account_id: selectedPaymentAccountId ? Number(selectedPaymentAccountId) : null,
          date: invoiceDate ? new Date(invoiceDate).toISOString() : undefined,
          mode: paymentMode || undefined,
          reference: paymentReference.trim() || undefined,
        };

        await api.post<Payment>('/payments/', payload);
        track('payment_voucher_created', {
          amount: Number(paymentAmount),
          mode: paymentMode || null,
          has_account: Boolean(selectedPaymentAccountId),
          source: 'invoices_page',
        });
        setSuccess('Payment voucher created successfully.');
        resetInvoiceForm();
      } catch (err) {
        setError(getApiErrorMessage(err, 'Unable to create payment voucher'));
      } finally {
        setSubmitting(false);
      }
      return;
    }

    /* A tracked line with no serials is not an incomplete form, it is an
       invoice for units nobody has identified. The block is stated on the line
       itself — a toast at the top of a six-line invoice does not say which. */
    const missingSerials = items.filter((item) => isTrackedLine(item) && item.serials.length === 0);
    if (missingSerials.length > 0) {
      setSerialBlockIds(missingSerials.map((item) => item.id));
      flashLine(missingSerials[0].id);
      scanInputRef.current?.focus();
      return;
    }

    try {
      setSubmitting(true);
      setError('');
      setSuccess('');

      const payload: InvoiceCreate = {
        ledger_id: Number(selectedLedgerId),
        voucher_type: voucherType,
        invoice_date: invoiceDate,
        due_date: resolvedDueDate ?? invoiceDate,
        supplier_invoice_number: voucherType === 'purchase' ? (supplierInvoiceNumber.trim() || null) : null,
        reference_notes: voucherType === 'sales' ? (referenceNotes.trim() || null) : null,
        tax_inclusive: taxInclusive,
        apply_round_off: applyRoundOff,
        discount_type: invoiceDiscountType || null,
        discount_value: invoiceDiscountValue ? Number(invoiceDiscountValue) : null,
        ...(voucherType === 'sales' ? {
          shipping_address_same_as_billing: shippingSameAsBilling,
          shipping_address_id: (!shippingSameAsBilling && selectedShippingAddressId !== null) ? selectedShippingAddressId : null,
          new_shipping_address: (!shippingSameAsBilling && selectedShippingAddressId === null && newShippingAddress.trim())
            ? { label: newShippingLabel.trim() || 'Shipping', address: newShippingAddress.trim() }
            : null,
        } : {}),
        items: items.map((item) => ({
          product_id: Number(item.productId),
          quantity: lineQuantity(item),
          unit_price: item.unit_price ? Number(item.unit_price) : undefined,
          description: item.description || undefined,
          discount_type: item.discount_type || null,
          discount_value: item.discount_value ? Number(item.discount_value) : null,
          serial_numbers: item.serials.length > 0 ? item.serials : undefined,
        })),
      };

      if (editingInvoiceId) {
        const res = await api.put<Invoice>(`/invoices/${editingInvoiceId}`, payload);
        track('invoice_updated', {
          invoice_id: res.data.id,
          voucher_type: voucherType,
          line_item_count: payload.items.length,
          total_amount: res.data.total_amount,
          tax_inclusive: taxInclusive,
        });
        setSuccess('Invoice updated successfully. Inventory has been recalculated.');
        setPreviewInvoice(res.data);
        if (searchParams.has('edit')) {
          setSearchParams((prev) => { prev.delete('edit'); return prev; }, { replace: true });
        }
      } else {
        const res = await api.post<Invoice>('/invoices/', payload);
        // The app's core conversion event — everything else on this page is a
        // step towards getting a document out the door.
        track('invoice_created', {
          invoice_id: res.data.id,
          voucher_type: voucherType,
          line_item_count: payload.items.length,
          total_amount: res.data.total_amount,
          total_tax_amount: res.data.total_tax_amount,
          tax_inclusive: taxInclusive,
          has_invoice_discount: Boolean(payload.discount_value),
          serial_line_count: payload.items.filter((line) => (line.serial_numbers?.length ?? 0) > 0).length,
          outside_active_fy: Boolean(res.data.warnings?.includes('invoice_date_outside_fy')),
          source: 'invoices_page',
        });
        const baseMsg =
          voucherType === 'sales'
            ? 'Sales invoice created. Inventory has been reduced.'
            : 'Purchase invoice created. Inventory has been increased.';
        const warningNote =
          res.data.warnings?.includes('invoice_date_outside_fy') && activeFY
            ? ` ⚠️ Date is outside the active financial year (${activeFY.label}).`
            : '';
        setSuccess(baseMsg + warningNote);
        setPreviewInvoice(res.data);
      }

      resetInvoiceForm();
      await refreshInvoicesAfterMutation();
    } catch (err) {
      setError(getApiErrorMessage(err, editingInvoiceId ? 'Unable to update invoice' : 'Unable to create invoice'));
    } finally {
      setSubmitting(false);
    }
  }

  const trackedEntries = items
    .map((item, index) => ({ item, index }))
    .filter((entry) => isTrackedLine(entry.item));
  const scanTargetEntry =
    trackedEntries.find((entry) => entry.item.id === scanTargetItemId) ?? trackedEntries[trackedEntries.length - 1] ?? null;
  const hasTrackedProducts = products.some((product) => product.track_serials);
  const pickerItem = pickerItemId !== null ? items.find((item) => item.id === pickerItemId) ?? null : null;
  const pickerProduct = pickerItem ? findProduct(Number(pickerItem.productId)) : undefined;

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Invoices</p>
          <h1 className="page-title">Invoice composer</h1>
          <p className="section-copy">Build multi-line invoices against live product pricing and submit directly to the API.</p>
        </div>
        <div className="status-chip">{invoiceTotal} invoices listed</div>
      </section>

      <StatusToasts
        error={error || feedbackError}
        success={success || feedbackSuccess}
        onClearError={() => {
          setError('');
          clearFeedback();
        }}
        onClearSuccess={() => {
          setSuccess('');
          clearFeedback();
        }}
      />

      <section className="content-grid content-grid--single">
        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Create invoice</p>
              <h2 className="nav-panel__title">{editingInvoiceId ? `Editing invoice #${editingInvoiceId}` : 'Order entry'}</h2>
            </div>
            <div className="button-row" style={{ justifyContent: 'flex-end' }}>
              <div className="status-chip">Projected total {formatCurrency(projectedTotalAmount, activeCurrencyCode)}</div>
              <Link className="button button--secondary" to="/invoices-view">Open invoice view</Link>
            </div>
          </div>

          <div className="summary-box">
            <p className="eyebrow">Billing company</p>
            <p className="summary-box__value" style={{ fontSize: '1.25rem' }}>
              {company?.name?.trim() ? company.name : 'Company not configured'}
            </p>
            <p className="muted-text">
              {company?.gst ? `GST: ${company.gst} · ` : ''}
              {company?.phone_number ? `Phone: ${company.phone_number}` : 'Set details in Company page'}
            </p>
            <p className="muted-text">Currency: {activeCurrencyCode}</p>
            {(company?.email || company?.website) ? (
              <p className="muted-text">
                {company?.email ? `Email: ${company.email}` : ''}
                {company?.email && company?.website ? ' · ' : ''}
                {company?.website ? `Web: ${company.website}` : ''}
              </p>
            ) : null}
            <p className="muted-text">{company?.address || ''}</p>
            {company?.bank_name || company?.account_number ? (
              <p className="muted-text">
                Bank: {company?.bank_name || 'N/A'}
                {company?.branch_name ? ` (${company.branch_name})` : ''} · A/C: {company?.account_number || 'N/A'}
                {company?.ifsc_code ? ` · IFSC: ${company.ifsc_code}` : ''}
              </p>
            ) : null}
          </div>

          <form className="stack" onSubmit={handleSubmitInvoice}>
            <div className="field-grid">
              <div className="field">
                <label htmlFor="invoice-voucher-type">Voucher type</label>
                <select
                  id="invoice-voucher-type"
                  className="select"
                  value={voucherType}
                  onChange={(event) => setVoucherType(event.target.value as 'sales' | 'purchase' | 'payment' | 'receipt')}
                >
                  <option value="sales">Sales</option>
                  <option value="purchase">Purchase</option>
                  <option value="payment">Payment</option>
                  <option value="receipt">Receipt</option>
                </select>
              </div>

              <div className="field">
                <div className="field__label-row">
                  <label htmlFor="invoice-ledger">Ledger</label>
                  <button type="button" className="link-button" onClick={openLedgerCreateModal}>
                    <Plus size={13} />
                    New ledger
                  </button>
                </div>
                <LedgerCombobox
                  id="invoice-ledger"
                  ledgers={ledgers}
                  value={selectedLedgerId}
                  onChange={setSelectedLedgerId}
                  required
                />
              </div>

              <div className="field">
                <label htmlFor="invoice-date">Invoice date</label>
                <input
                  id="invoice-date"
                  className="input"
                  type="date"
                  value={invoiceDate}
                  onChange={(event) => setInvoiceDate(event.target.value)}
                  required
                />
                {activeFY !== null &&
                  invoiceDate !== '' &&
                  (invoiceDate < activeFY.start_date || invoiceDate > activeFY.end_date) ? (
                  <p className="field-warning">
                    ⚠️ This date is outside the active financial year ({activeFY.label}). The invoice will still be created.
                  </p>
                ) : null}
              </div>
            </div>

            <label className="form-advanced-toggle">
              <input
                type="checkbox"
                checked={showAdvanced}
                onChange={(event) => {
                  setShowAdvanced(event.target.checked);
                  updateInvoiceComposerPrefs({ showAdvanced: event.target.checked });
                }}
              />
              <span className="form-advanced-toggle__label">Advanced options</span>
              <span className="form-advanced-toggle__hint">{advancedSummary}</span>
            </label>

            {showAdvanced ? (
              <div className="field-grid">
              {voucherType !== 'payment' && voucherType !== 'receipt' ? (
                <>
                  <div className="field">
                    <label htmlFor="invoice-due-mode">Due date</label>
                    <select
                      id="invoice-due-mode"
                      className="select"
                      value={dueDateMode}
                      onChange={(event) => {
                        const mode = event.target.value as DueDateMode;
                        setDueDateMode(mode);
                        updateInvoiceComposerPrefs({ dueDateMode: mode });
                      }}
                    >
                      <option value="none">No due date</option>
                      <option value="exact">Choose exact date</option>
                      <option value="days">Set days from invoice date</option>
                    </select>
                  </div>

                  {dueDateMode === 'exact' ? (
                    <div className="field">
                      <label htmlFor="invoice-due-date">Exact due date</label>
                      <input
                        id="invoice-due-date"
                        className="input"
                        type="date"
                        value={dueDate}
                        min={invoiceDate || undefined}
                        onChange={(event) => setDueDate(event.target.value)}
                      />
                    </div>
                  ) : null}

                  {dueDateMode === 'days' ? (
                    <div className="field">
                      <label htmlFor="invoice-due-days">Days from invoice date</label>
                      <input
                        id="invoice-due-days"
                        className="input"
                        type="number"
                        min="0"
                        step="1"
                        value={dueDateDays}
                        onChange={(event) => {
                          setDueDateDays(event.target.value);
                          updateInvoiceComposerPrefs({ dueDateDays: event.target.value });
                        }}
                        placeholder="0"
                      />
                    </div>
                  ) : null}

                  {dueDateMode !== 'none' ? (
                    <div className="field" style={{ gridColumn: '1 / -1' }}>
                      <p className="muted-text" style={{ margin: 0 }}>
                        {resolvedDueDate
                          ? `Resolved due date: ${formatInvoiceDateLabel(resolvedDueDate)}`
                          : 'Select a valid due date or enter the number of days from the invoice date.'}
                      </p>
                    </div>
                  ) : null}
                </>
              ) : null}

              {voucherType === 'purchase' ? (
                <div className="field">
                  <label htmlFor="invoice-supplier-ref">Supplier Invoice #</label>
                  <input
                    id="invoice-supplier-ref"
                    className="input"
                    type="text"
                    value={supplierInvoiceNumber}
                    onChange={(event) => setSupplierInvoiceNumber(event.target.value)}
                    placeholder="Supplier's invoice number"
                  />
                </div>
              ) : null}

              {voucherType === 'sales' ? (
                <div className="field">
                  <label htmlFor="invoice-reference-notes">Reference Notes</label>
                  <input
                    id="invoice-reference-notes"
                    className="input"
                    type="text"
                    value={referenceNotes}
                    onChange={(event) => setReferenceNotes(event.target.value)}
                    placeholder="PO number or customer reference"
                  />
                  <p className="muted-text" style={{ marginBottom: 0 }}>
                    Optional: include PO number or any customer-provided reference.
                  </p>
                </div>
              ) : null}

              {voucherType === 'sales' ? (
                <div className="field" style={{ gridColumn: '1 / -1' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
                    <input
                      id="invoice-shipping-same"
                      type="checkbox"
                      checked={shippingSameAsBilling}
                      onChange={(e) => {
                        setShippingSameAsBilling(e.target.checked);
                        if (e.target.checked) {
                          setSelectedShippingAddressId(null);
                          setNewShippingLabel('');
                          setNewShippingAddress('');
                        }
                      }}
                    />
                    <label htmlFor="invoice-shipping-same" style={{ marginBottom: 0, cursor: 'pointer' }}>
                      Shipping address same as billing address
                    </label>
                  </div>

                  {!shippingSameAsBilling ? (
                    <div className="stack" style={{ gap: '8px', paddingLeft: '0' }}>
                      {ledgerAddresses.length > 0 ? (
                        <div className="field" style={{ marginBottom: 0 }}>
                          <label htmlFor="invoice-shipping-select">Saved addresses</label>
                          <select
                            id="invoice-shipping-select"
                            className="select"
                            value={selectedShippingAddressId ?? ''}
                            onChange={(e) => {
                              const val = e.target.value;
                              if (val === '') {
                                setSelectedShippingAddressId(null);
                              } else if (val === '__new__') {
                                setSelectedShippingAddressId(null);
                                setNewShippingLabel('');
                                setNewShippingAddress('');
                              } else {
                                const id = Number(val);
                                setSelectedShippingAddressId(id);
                                const found = ledgerAddresses.find((a) => a.id === id);
                                if (found) {
                                  setNewShippingLabel(found.label);
                                  setNewShippingAddress(found.address);
                                }
                              }
                            }}
                          >
                            <option value="">-- Select saved address --</option>
                            {ledgerAddresses.map((addr) => (
                              <option key={addr.id} value={addr.id}>
                                {addr.label} — {addr.address.slice(0, 50)}{addr.address.length > 50 ? '…' : ''}
                              </option>
                            ))}
                            <option value="__new__">+ Enter new address</option>
                          </select>
                        </div>
                      ) : null}

                      {(selectedShippingAddressId === null) ? (
                        <>
                          <div className="field" style={{ marginBottom: 0 }}>
                            <label htmlFor="invoice-shipping-label">Address label</label>
                            <input
                              id="invoice-shipping-label"
                              className="input"
                              type="text"
                              value={newShippingLabel}
                              onChange={(e) => setNewShippingLabel(e.target.value)}
                              placeholder="e.g. Warehouse, Site A"
                            />
                          </div>
                          <div className="field" style={{ marginBottom: 0 }}>
                            <label htmlFor="invoice-shipping-address">Shipping address</label>
                            <textarea
                              id="invoice-shipping-address"
                              className="input"
                              rows={3}
                              value={newShippingAddress}
                              onChange={(e) => setNewShippingAddress(e.target.value)}
                              placeholder="Full shipping / delivery address"
                            />
                            <p className="muted-text" style={{ marginBottom: 0 }}>
                              This address will be saved to the ledger for future use.
                            </p>
                          </div>
                        </>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              ) : null}

              </div>
            ) : null}

            {showAdvanced && voucherType !== 'payment' && voucherType !== 'receipt' ? (
              <div className="stack" style={{ gap: '8px' }}>
                <div className="field" style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: 0 }}>
                  <input
                    id="invoice-apply-round-off"
                    type="checkbox"
                    checked={applyRoundOff}
                    onChange={(event) => {
                      setApplyRoundOff(event.target.checked);
                      updateInvoiceComposerPrefs({ applyRoundOff: event.target.checked });
                    }}
                  />
                  <label htmlFor="invoice-apply-round-off" style={{ marginBottom: 0, cursor: 'pointer' }}>Apply round off</label>
                </div>
                {applyRoundOff ? (
                  <p className="muted-text" style={{ marginTop: 0 }}>
                    Round off: {formatCurrency(roundOffPreviewAmount, activeCurrencyCode)} · Adjusted total: {formatCurrency(projectedTotalAmount, activeCurrencyCode)}
                  </p>
                ) : null}

                {/* Invoice-level discount */}
                <div className="field" style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: 0, flexWrap: 'wrap' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <input
                      id="invoice-discount-percentage"
                      type="radio"
                      name="inv-disc-type"
                      value="percentage"
                      checked={invoiceDiscountType === 'percentage'}
                      onChange={() => {
                        setInvoiceDiscountType('percentage');
                        updateInvoiceComposerPrefs({ invoiceDiscountType: 'percentage' });
                      }}
                    />
                    <label htmlFor="invoice-discount-percentage" style={{ marginBottom: 0, cursor: 'pointer', fontSize: '13px' }}>%</label>
                    <input
                      id="invoice-discount-net"
                      type="radio"
                      name="inv-disc-type"
                      value="net"
                      checked={invoiceDiscountType === 'net'}
                      onChange={() => {
                        setInvoiceDiscountType('net');
                        updateInvoiceComposerPrefs({ invoiceDiscountType: 'net' });
                      }}
                    />
                    <label htmlFor="invoice-discount-net" style={{ marginBottom: 0, cursor: 'pointer', fontSize: '13px' }}>Flat</label>
                  </div>
                  <label htmlFor="invoice-discount-value" style={{ marginBottom: 0, cursor: 'pointer', fontSize: '13px' }}>
                    Invoice discount:
                  </label>
                  <input
                    id="invoice-discount-value"
                    className="input"
                    type="number"
                    step="0.01"
                    min="0"
                    value={invoiceDiscountValue}
                    onChange={(e) => setInvoiceDiscountValue(e.target.value)}
                    placeholder={invoiceDiscountType === 'percentage' ? 'e.g. 5%' : 'e.g. 100.00'}
                    style={{ width: '120px' }}
                  />
                </div>
                {invoiceDiscountValue && Number(invoiceDiscountValue) > 0 ? (
                  <p className="muted-text" style={{ marginTop: 0 }}>
                    Discount: {formatCurrency(invoiceDiscountAmount, activeCurrencyCode)} · After discount: {formatCurrency(afterDiscountTotal, activeCurrencyCode)}
                  </p>
                ) : null}
              </div>
            ) : null}

            {voucherType === 'payment' ? (
              <div className="field-grid">
                <div className="field">
                  <label htmlFor="payment-account">Account</label>
                  <select
                    id="payment-account"
                    className="select"
                    value={selectedPaymentAccountId}
                    onChange={(event) => setSelectedPaymentAccountId(event.target.value)}
                  >
                    <option value="">Unallocated</option>
                    {companyAccounts.map((account) => (
                      <option key={account.id} value={account.id}>
                        {account.display_name} ({account.account_type})
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="payment-mode">Payment mode</label>
                  <select
                    id="payment-mode"
                    className="select"
                    value={paymentMode}
                    onChange={(event) => setPaymentMode(event.target.value)}
                  >
                    <option value="cash">Cash</option>
                    <option value="cheque">Cheque</option>
                    <option value="upi">UPI</option>
                    <option value="other">Other</option>
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="payment-reference">Reference #</label>
                  <input
                    id="payment-reference"
                    className="input"
                    type="text"
                    value={paymentReference}
                    onChange={(event) => setPaymentReference(event.target.value)}
                    placeholder="Cheque no. or UPI transaction ID"
                  />
                </div>
                <div className="field">
                  <label htmlFor="payment-amount">Amount</label>
                  <input
                    id="payment-amount"
                    className="input"
                    type="number"
                    step="0.01"
                    min="0.01"
                    value={paymentAmount}
                    onChange={(event) => setPaymentAmount(event.target.value)}
                    placeholder="0.00"
                    required
                  />
                </div>
              </div>
            ) : null}

            {voucherType !== 'payment' && voucherType !== 'receipt' ? (
              <div className="stack">
                <div className="line-items__header">
                  <p className="eyebrow" style={{ margin: 0 }}>Line items</p>
                  <div className="line-items__tools">
                    <label className="inline-check" htmlFor="invoice-tax-inclusive">
                      <input
                        id="invoice-tax-inclusive"
                        type="checkbox"
                        checked={taxInclusive}
                        onChange={(event) => {
                          setTaxInclusive(event.target.checked);
                          updateInvoiceComposerPrefs({ taxInclusive: event.target.checked });
                        }}
                      />
                      Prices include GST
                    </label>
                    <button type="button" className="link-button" onClick={openProductCreateModal}>
                      <Plus size={13} />
                      New product
                    </button>
                    <button type="button" className="link-button" onClick={openStockUpdateModal}>
                      <Boxes size={13} />
                      Update stock
                    </button>
                  </div>
                </div>
                {hasTrackedProducts ? (
                  <ScanBar
                    mode={voucherType === 'purchase' ? 'purchase' : 'sales'}
                    onResolve={handleScanResolution}
                    target={
                      scanTargetEntry
                        ? {
                            lineNumber: scanTargetEntry.index + 1,
                            productName: findProduct(Number(scanTargetEntry.item.productId))?.name ?? 'this line',
                          }
                        : null
                    }
                    inputRef={scanInputRef}
                  />
                ) : null}
                {items.map((item, index) => {
                  const selectedProduct = products.find((product) => product.id === Number(item.productId));
                  const selectedUnit = selectedProduct?.unit || 'Pieces';
                  const allowDecimalQuantity = Boolean(selectedProduct?.allow_decimal);
                  const tracked = Boolean(selectedProduct?.track_serials);
                  const quantityValue = tracked ? String(item.serials.length) : item.quantity;
                  const unitPrice = item.unit_price ? Number(item.unit_price) : (selectedProduct?.price || 0);
                  const gstRate = selectedProduct?.gst_rate || 0;
                  let lineTotal: number;
                  let taxAmount: number;
                  if (taxInclusive) {
                    lineTotal = unitPrice * Number(quantityValue || 0);
                    taxAmount = lineTotal - lineTotal / (1 + gstRate / 100);
                  } else {
                    const taxableAmount = unitPrice * Number(quantityValue || 0);
                    taxAmount = taxableAmount * gstRate / 100;
                    lineTotal = taxableAmount + taxAmount;
                  }

                  return (
                    <div
                      key={item.id}
                      className="line-item line-item--discount"
                      data-flash={flashItemId === item.id ? 'on' : undefined}
                    >
                      <div className="field">
                        <label htmlFor={`invoice-product-${item.id}`}>Line {index + 1}</label>
                        <ProductCombobox
                          id={`invoice-product-${item.id}`}
                          products={products}
                          value={item.productId}
                          onChange={(productId, newProduct) => {
                            updateItem(item.id, 'productId', productId);
                            updateItem(item.id, 'unit_price', String(newProduct.price));
                          }}
                          required
                        />
                      </div>

                      <div className="field">
                        <label htmlFor={`invoice-quantity-${item.id}`}>
                          Qty ({selectedUnit})
                          {tracked ? <Lock size={11} className="field__lock" aria-hidden="true" /> : null}
                        </label>
                        <input
                          id={`invoice-quantity-${item.id}`}
                          className="input"
                          type="number"
                          min={allowDecimalQuantity ? '0.001' : '1'}
                          step={allowDecimalQuantity ? '0.001' : '1'}
                          value={quantityValue}
                          disabled={tracked}
                          title={tracked ? 'Quantity follows the serial numbers' : undefined}
                          onChange={(event) => updateItem(item.id, 'quantity', event.target.value)}
                          required
                        />
                      </div>

                      <div className="field">
                        <label htmlFor={`invoice-price-${item.id}`}>{taxInclusive ? 'Amount (incl. GST)' : 'Price'}</label>
                        <input
                          id={`invoice-price-${item.id}`}
                          className="input"
                          type="number"
                          step="0.01"
                          min="0"
                          value={item.unit_price}
                          onChange={(event) => updateItem(item.id, 'unit_price', event.target.value)}
                          placeholder={selectedProduct ? String(selectedProduct.price) : '0.00'}
                        />
                      </div>

                      <div className="field line-item__discount">
                        <label htmlFor={`item-disc-value-${item.id}`}>Discount</label>
                        <div className="line-item__discount-modes">
                          <input
                            id={`item-disc-pct-${item.id}`}
                            type="radio"
                            name={`item-disc-type-${item.id}`}
                            value="percentage"
                            checked={item.discount_type === 'percentage'}
                            onChange={() => updateItem(item.id, 'discount_type', 'percentage')}
                          />
                          <label htmlFor={`item-disc-pct-${item.id}`}>%</label>
                          <input
                            id={`item-disc-net-${item.id}`}
                            type="radio"
                            name={`item-disc-type-${item.id}`}
                            value="net"
                            checked={item.discount_type === 'net'}
                            onChange={() => updateItem(item.id, 'discount_type', 'net')}
                          />
                          <label htmlFor={`item-disc-net-${item.id}`}>Flat</label>
                        </div>
                        <input
                          id={`item-disc-value-${item.id}`}
                          className="input"
                          type="number"
                          step="0.01"
                          min="0"
                          value={item.discount_value}
                          onChange={(event) => updateItem(item.id, 'discount_value', event.target.value)}
                          placeholder="0"
                        />
                      </div>

                      <div className="line-item__price">
                        <span className="line-item__label">Line total</span>
                        <div className="line-item__price-value">
                          <span>{formatCurrency(lineTotal, activeCurrencyCode)}</span>
                          <span className="table-subtext">
                            {formatInvoiceTaxBreakdown({
                              gstRate,
                              taxAmount,
                              currencyCode: activeCurrencyCode,
                              interstateSupply: composerInterstateSupply,
                            })}
                          </span>
                        </div>
                      </div>

                      <button
                        type="button"
                        className="button button--danger button--icon"
                        onClick={() => removeItem(item.id)}
                        title={`Remove line item ${index + 1}`}
                        aria-label={`Remove line item ${index + 1}`}
                      >
                        <Trash2 size={15} />
                      </button>
                      {tracked ? (
                        <div className="field field--full serial-line">
                          <SerialChips
                            value={item.serials}
                            onChange={(next) => setLineSerials(item.id, next)}
                            productId={Number(item.productId) || null}
                            mode={voucherType === 'purchase' ? 'purchase' : 'sales'}
                            idPrefix={`invoice-line-${item.id}`}
                            onPickFromStock={voucherType === 'sales' ? () => setPickerItemId(item.id) : undefined}
                          />
                          {item.serials.length === 0 ? (
                            <p
                              className={`serial-line__message${serialBlockIds.includes(item.id) ? ' serial-line__message--blocking' : ''}`}
                              role={serialBlockIds.includes(item.id) ? 'alert' : undefined}
                            >
                              This product is serial tracked — scan or add at least one serial before saving.
                            </p>
                          ) : null}
                        </div>
                      ) : null}
                      <div className="field field--full">
                        <label htmlFor={`invoice-description-${item.id}`}>Description (optional)</label>
                        {/* One row, resizable: an optional note used to open at two rows and
                            take up more of the line item than the fields that price it. */}
                        <textarea
                          id={`invoice-description-${item.id}`}
                          className="input"
                          rows={1}
                          value={item.description}
                          onChange={(event) => updateItem(item.id, 'description', event.target.value)}
                          placeholder={tracked ? 'Condition, box number, or item notes' : 'Serial number, batch code, or item notes'}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : null}

            <div className="button-row">
              {voucherType !== 'payment' && voucherType !== 'receipt' ? (
                <button type="button" className="button button--ghost" onClick={addItem} disabled={products.length === 0} title="Add line item" aria-label="Add line item">
                  Add line item
                </button>
              ) : null}
              {editingInvoiceId ? (
                <button type="button" className="button button--secondary" onClick={resetInvoiceForm} title="Cancel invoice edit" aria-label="Cancel invoice edit">
                  Cancel edit
                </button>
              ) : null}
              {voucherType === 'payment' ? (
                <button className="button button--primary" disabled={submitting || !selectedLedgerId || !paymentAmount} title="Create payment voucher" aria-label="Create payment voucher">
                  {submitting ? 'Creating payment...' : 'Create payment voucher'}
                </button>
              ) : voucherType === 'receipt' ? (
                <button className="button button--primary" disabled={!selectedLedgerId} title="Record receipt" aria-label="Record receipt">
                  Record receipt
                </button>
              ) : (
                <button className="button button--primary" disabled={submitting || products.length === 0 || !selectedLedgerId} title={editingInvoiceId ? 'Update invoice' : 'Create invoice'} aria-label={editingInvoiceId ? 'Update invoice' : 'Create invoice'}>
                  {submitting ? (editingInvoiceId ? 'Updating invoice...' : 'Creating invoice...') : editingInvoiceId ? 'Update invoice' : 'Create invoice'}
                </button>
              )}
            </div>
          </form>
        </article>

      </section>

      <LedgerQuickCreateModal />

      {previewInvoice ? (
        <InvoicePreview
          invoice={previewInvoice}
          onClose={() => setPreviewInvoice(null)}
          onError={(msg) => setError(msg)}
        />
      ) : null}

      <ProductQuickCreateModal />

      <StockUpdateModal />

      {pickerItem && pickerProduct ? (
        <SerialPickerModal
          productId={pickerProduct.id}
          productName={pickerProduct.name}
          selected={pickerItem.serials}
          onCancel={() => setPickerItemId(null)}
          onConfirm={(serials) => {
            setLineSerials(pickerItem.id, serials);
            setPickerItemId(null);
          }}
        />
      ) : null}

      {showReceiptModal && selectedLedgerId ? (
        <ReceiptModal
          ledgerId={Number(selectedLedgerId)}
          ledgerName={selectedLedger?.name || `Ledger #${selectedLedgerId}`}
          currencyCode={activeCurrencyCode}
          onClose={() => setShowReceiptModal(false)}
          onSuccess={(message) => {
            setSuccess(message);
            setShowReceiptModal(false);
            resetInvoiceForm();
            refreshInvoicesAfterMutation();
          }}
          onError={(message) => setError(message)}
        />
      ) : null}
    </div>
  );
}
