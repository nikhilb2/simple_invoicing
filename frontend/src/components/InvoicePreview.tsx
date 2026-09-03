import { useCallback, useEffect, useRef, useState } from 'react';
import { Download, Mail, Printer, Share2 } from 'lucide-react';
import { useEscapeClose } from '../hooks/useEscapeClose';
import api, { getApiErrorMessage } from '../api/client';
import { track } from '../lib/analytics';
import type { Invoice } from '../types/api';
import { formatInvoiceDateLabel } from '../utils/invoiceDueDate.ts';
import formatCurrency from '../utils/formatting';
import SendEmailModal from './SendEmailModal';
import ShareModal from './ShareModal';
import PreviewToolbar from './PreviewToolbar';
import CopiesStepper from './CopiesStepper';

type InvoicePreviewProps = {
  invoice: Invoice;
  onClose: () => void;
  onError?: (message: string) => void;
};

export default function InvoicePreview({ invoice, onClose, onError }: InvoicePreviewProps) {
  const [showEmailModal, setShowEmailModal] = useState(false);
  const [showShareModal, setShowShareModal] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [copies, setCopies] = useState(1);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [loadingPdf, setLoadingPdf] = useState(true);
  const [pdfError, setPdfError] = useState('');
  const [previewFailed, setPreviewFailed] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  // The email and share modals stacked on top close themselves on Escape;
  // without this guard the same keypress tears down the preview behind them.
  useEscapeClose(useCallback(() => {
    // Escape closes the open menu first, then the preview -- otherwise opening
    // the menu and hitting Escape would dismiss the whole dialog underneath it.
    if (menuOpen) { setMenuOpen(false); return; }
    if (!showEmailModal && !showShareModal) onClose();
  }, [menuOpen, showEmailModal, showShareModal, onClose]));

  useEffect(() => {
    let isMounted = true;
    let objectUrlToRevoke: string | null = null;

    const loadPdf = async () => {
      setLoadingPdf(true);
      setPdfError('');
      setPdfUrl(null);
      setPreviewFailed(false);

      try {
        const response = await api.get(`/invoices/${invoice.id}/pdf?copies=${copies}`, {
          responseType: 'blob',
        });
        const nextUrl = window.URL.createObjectURL(response.data as Blob);
        objectUrlToRevoke = nextUrl;

        if (!isMounted) {
          window.URL.revokeObjectURL(nextUrl);
          return;
        }
        setPdfUrl(nextUrl);
      } catch (err) {
        if (!isMounted) return;
        const message = getApiErrorMessage(err, 'Unable to load invoice PDF preview');
        setPdfError(message);
        onError?.(message);
      } finally {
        if (isMounted) {
          setLoadingPdf(false);
        }
      }
    };

    if (copies > 0) {
      loadPdf();
    }

    return () => {
      isMounted = false;
      if (objectUrlToRevoke) {
        window.URL.revokeObjectURL(objectUrlToRevoke);
      }
    };
  }, [invoice.id, copies]);

  const handleDownloadPdf = async () => {
    try {
      const response = await api.get(`/invoices/${invoice.id}/pdf?copies=${copies}`, {
        responseType: 'blob',
      });
      const url = window.URL.createObjectURL(response.data as Blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `invoice_${invoice.invoice_number || invoice.id}.pdf`;
      link.click();
      window.URL.revokeObjectURL(url);
      track('invoice_pdf_downloaded', {
        invoice_id: invoice.id,
        voucher_type: invoice.voucher_type,
        copies,
      });
    } catch (err) {
      onError?.(getApiErrorMessage(err, 'Unable to download PDF'));
    }
  };

  const handlePrintPdf = () => {
    iframeRef.current?.contentWindow?.focus();
    iframeRef.current?.contentWindow?.print();
  };

  const handleOpenInNewTab = () => {
    if (!pdfUrl) return;
    window.open(pdfUrl, '_blank', 'noopener,noreferrer');
  };

  const invoiceLabel = invoice.invoice_number || `#${invoice.id}`;
  // The backend reads voucher_type off the invoice, so one share button covers
  // both books — only the wording the customer reads has to change.
  const documentNoun = invoice.voucher_type === 'purchase' ? 'Purchase invoice' : 'Invoice';

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="invoice-preview-title">
      <div className="modal-panel modal-panel--invoice-preview">
        <PreviewToolbar
          eyebrow="Invoice preview"
          titleId="invoice-preview-title"
          title={`${documentNoun} ${invoice.invoice_number || `#${invoice.id}`}`}
          meta={
            <>
              {formatInvoiceDateLabel(invoice.invoice_date)}
              {invoice.due_date ? ` · Due ${formatInvoiceDateLabel(invoice.due_date)}` : ' · No due date'}
            </>
          }
          primary={{
            label: 'Share',
            icon: <Share2 size={16} aria-hidden="true" />,
            onClick: () => setShowShareModal(true),
            title: 'Share a link to this invoice',
          }}
          secondary={[
            {
              label: 'Print',
              icon: <Printer size={16} aria-hidden="true" />,
              onClick: handlePrintPdf,
              disabled: !pdfUrl || loadingPdf || previewFailed,
              title: 'Print invoice',
            },
            {
              label: 'Download',
              icon: <Download size={16} aria-hidden="true" />,
              onClick: handleDownloadPdf,
              title: 'Download invoice PDF',
            },
          ]}
          menuExtra={<CopiesStepper value={copies} onChange={setCopies} />}
          menu={[
            {
              label: 'Email invoice',
              icon: <Mail size={16} aria-hidden="true" />,
              onClick: () => setShowEmailModal(true),
            },
          ]}
          menuOpen={menuOpen}
          onMenuOpenChange={setMenuOpen}
          onClose={onClose}
          closeLabel="Close invoice preview"
        />

        <div className="invoice-pdf-viewer" aria-live="polite">
          {loadingPdf ? <p className="muted-text">Loading PDF preview...</p> : null}
          {!loadingPdf && pdfError ? <p className="error-text">{pdfError}</p> : null}
          {!loadingPdf && previewFailed && pdfUrl ? (
            <div style={{ display: 'grid', gap: '10px', justifyItems: 'center', textAlign: 'center', padding: '16px' }}>
              <p className="muted-text">PDF preview is unavailable in this browser.</p>
              <button
                type="button"
                className="button button--primary"
                onClick={handleOpenInNewTab}
                title="Open PDF in a new browser tab"
                aria-label="Open PDF in a new browser tab"
              >
                Open in New Tab
              </button>
            </div>
          ) : null}
          {!loadingPdf && pdfUrl && !previewFailed ? (
            <iframe
              ref={iframeRef}
              title={`Invoice ${invoice.invoice_number || invoice.id} PDF preview`}
              src={`${pdfUrl}#navpanes=0&toolbar=1&statusbar=0&messages=0`}
              className="invoice-pdf-viewer__frame"
              onError={() => {
                setPreviewFailed(true);
                onError?.('PDF preview failed. Open the PDF in a new tab.');
              }}
            />
          ) : null}
        </div>
      </div>

      {showEmailModal && (
        <SendEmailModal
          type="invoice"
          entityId={invoice.id}
          defaultTo={invoice.ledger?.email || ''}
          defaultSubject={`Invoice ${invoice.invoice_number || `#${invoice.id}`} from ${invoice.company_name || 'Company'}`}
          onClose={() => setShowEmailModal(false)}
          onSuccess={() => {
            setShowEmailModal(false);
            // Could show success toast here if needed
          }}
          onError={(message) => onError?.(message)}
        />
      )}

      {showShareModal && (
        <ShareModal
          resourceType="invoice"
          resourceId={invoice.id}
          label={`${documentNoun} ${invoiceLabel}`}
          messageLead={`${documentNoun} ${invoiceLabel}${invoice.company_name ? ` from ${invoice.company_name}` : ''} — ${formatCurrency(invoice.total_amount, invoice.company_currency_code || 'INR')}`}
          phone={invoice.ledger_phone}
          onClose={() => setShowShareModal(false)}
        />
      )}
    </div>
  );
}
