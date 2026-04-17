import { useEffect, useRef, useState } from 'react';
import { useEscapeClose } from '../hooks/useEscapeClose';
import api, { getApiErrorMessage } from '../api/client';

type PaymentReceiptPreviewProps = {
  paymentId: number;
  paymentNumber?: string | null;
  onClose: () => void;
  onError?: (message: string) => void;
};

export default function PaymentReceiptPreview({
  paymentId,
  paymentNumber,
  onClose,
  onError,
}: PaymentReceiptPreviewProps) {
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
        const response = await api.get(`/payments/${paymentId}/pdf`, {
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
        const message = getApiErrorMessage(err, 'Unable to load receipt PDF preview');
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
  }, [paymentId]);

  const handleDownloadPdf = async () => {
    try {
      const response = await api.get(`/payments/${paymentId}/pdf`, {
        responseType: 'blob',
      });
      const url = window.URL.createObjectURL(response.data as Blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `receipt_${paymentNumber || paymentId}.pdf`;
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

  const label = paymentNumber || `#${paymentId}`;

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="receipt-preview-title">
      <div className="modal-panel modal-panel--invoice-preview">
        <div className="panel__header no-print">
          <div>
            <p className="eyebrow">Receipt preview</p>
            <h2 id="receipt-preview-title" className="nav-panel__title">PDF receipt {label}</h2>
          </div>
          <div className="button-row">
            <button
              type="button"
              className="button button--secondary"
              onClick={handlePrintPdf}
              disabled={!pdfUrl || loadingPdf}
              title="Print receipt"
              aria-label="Print receipt"
            >
              Print
            </button>
            <button
              type="button"
              className="button button--primary"
              title="Download receipt PDF"
              aria-label="Download receipt PDF"
              onClick={handleDownloadPdf}
            >
              Download PDF
            </button>
            <button
              type="button"
              className="button button--ghost"
              onClick={onClose}
              title="Close receipt preview"
              aria-label="Close receipt preview"
            >
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
              title={`Receipt ${label} PDF preview`}
              src={`${pdfUrl}#navpanes=0&toolbar=1&statusbar=0&messages=0`}
              className="invoice-pdf-viewer__frame"
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}
