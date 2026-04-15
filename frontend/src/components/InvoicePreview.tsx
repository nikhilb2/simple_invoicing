import { useEffect, useRef, useState } from 'react';
import { useEscapeClose } from '../hooks/useEscapeClose';
import api, { getApiErrorMessage } from '../api/client';
import type { Invoice } from '../types/api';
import SendEmailModal from './SendEmailModal';

type InvoicePreviewProps = {
  invoice: Invoice;
  onClose: () => void;
  onError?: (message: string) => void;
};

export default function InvoicePreview({ invoice, onClose, onError }: InvoicePreviewProps) {
  const [showEmailModal, setShowEmailModal] = useState(false);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [loadingPdf, setLoadingPdf] = useState(true);
  const [pdfError, setPdfError] = useState('');
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  useEscapeClose(onClose);

  useEffect(() => {
    let isMounted = true;
    let objectUrlToRevoke: string | null = null;

    const loadPdf = async () => {
      setLoadingPdf(true);
      setPdfError('');
      setPdfUrl(null);

      try {
        const response = await api.get(`/invoices/${invoice.id}/pdf`, {
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

    loadPdf();

    return () => {
      isMounted = false;
      if (objectUrlToRevoke) {
        window.URL.revokeObjectURL(objectUrlToRevoke);
      }
    };
  }, [invoice.id]);

  const handleDownloadPdf = async () => {
    try {
      const response = await api.get(`/invoices/${invoice.id}/pdf`, {
        responseType: 'blob',
      });
      const url = window.URL.createObjectURL(response.data as Blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `invoice_${invoice.invoice_number || invoice.id}.pdf`;
      link.click();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      onError?.(getApiErrorMessage(err, 'Unable to download PDF'));
    }
  };

  const handlePrintPdf = () => {
    iframeRef.current?.contentWindow?.focus();
    iframeRef.current?.contentWindow?.print();
  };

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="invoice-preview-title">
      <div className="modal-panel modal-panel--invoice-preview">
        <div className="panel__header no-print">
          <div>
            <p className="eyebrow">Invoice preview</p>
            <h2 id="invoice-preview-title" className="nav-panel__title">PDF invoice {invoice.invoice_number || `#${invoice.id}`}</h2>
          </div>
          <div className="button-row">
            <button type="button" className="button button--secondary" onClick={handlePrintPdf} disabled={!pdfUrl || loadingPdf} title="Print invoice" aria-label="Print invoice">
              Print
            </button>
            <button
              type="button"
              className="button button--primary"
              title="Download invoice PDF"
              aria-label="Download invoice PDF"
              onClick={handleDownloadPdf}
            >
              Download PDF
            </button>
            <button
              type="button"
              className="button button--primary"
              onClick={() => setShowEmailModal(true)}
              title="Email invoice"
              aria-label="Email invoice"
            >
              Email Invoice
            </button>
            <button type="button" className="button button--ghost" onClick={onClose} title="Close invoice preview" aria-label="Close invoice preview">
              Close
            </button>
          </div>
        </div>

        <div className="invoice-pdf-viewer" aria-live="polite">
          {loadingPdf ? <p className="muted-text">Loading PDF preview...</p> : null}
          {!loadingPdf && pdfError ? <p className="error-text">{pdfError}</p> : null}
          {!loadingPdf && pdfUrl ? (
            <iframe
              ref={iframeRef}
              title={`Invoice ${invoice.invoice_number || invoice.id} PDF preview`}
              src={`${pdfUrl}#navpanes=0&toolbar=1&statusbar=0&messages=0`}
              className="invoice-pdf-viewer__frame"
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
          onSuccess={(message) => {
            setShowEmailModal(false);
            // Could show success toast here if needed
          }}
          onError={(message) => onError?.(message)}
        />
      )}
    </div>
  );
}
