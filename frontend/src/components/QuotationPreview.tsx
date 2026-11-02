import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { Download, ExternalLink, Printer, Share2 } from 'lucide-react';
import { useEscapeClose } from '../hooks/useEscapeClose';
import api, { getApiErrorMessage } from '../api/client';
import ShareModal from './ShareModal';
import PreviewToolbar, { type PreviewAction } from './PreviewToolbar';
import type { Quotation } from '../types/api';
import { QUOTATION_DOCUMENT_LABELS, allowedQuotationActions } from '../utils/quotationStatus';

type QuotationPreviewProps = {
  quotation: Quotation;
  /** Status changes and the like, behind the "…" menu. The page owns what they do. */
  menuActions?: PreviewAction[];
  meta?: ReactNode;
  onClose: () => void;
  onError?: (message: string) => void;
};

export default function QuotationPreview({ quotation, menuActions = [], meta, onClose, onError }: QuotationPreviewProps) {
  const [showShareModal, setShowShareModal] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [loadingPdf, setLoadingPdf] = useState(true);
  const [pdfError, setPdfError] = useState('');
  const [previewFailed, setPreviewFailed] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  const label = QUOTATION_DOCUMENT_LABELS[quotation.document_type];
  const title = `${label} ${quotation.quotation_number}`;
  const canShare = allowedQuotationActions(quotation).includes('share');

  useEscapeClose(useCallback(() => {
    if (menuOpen) { setMenuOpen(false); return; }
    if (!showShareModal) onClose();
  }, [menuOpen, showShareModal, onClose]));

  useEffect(() => {
    let isMounted = true;
    let objectUrlToRevoke: string | null = null;

    (async () => {
      setLoadingPdf(true);
      setPdfError('');
      setPdfUrl(null);
      setPreviewFailed(false);
      try {
        const response = await api.get(`/quotations/${quotation.id}/pdf`, { responseType: 'blob' });
        const nextUrl = window.URL.createObjectURL(response.data as Blob);
        objectUrlToRevoke = nextUrl;
        if (!isMounted) {
          window.URL.revokeObjectURL(nextUrl);
          return;
        }
        setPdfUrl(nextUrl);
      } catch (err) {
        if (!isMounted) return;
        const message = getApiErrorMessage(err, 'Unable to load PDF preview');
        setPdfError(message);
        onError?.(message);
      } finally {
        if (isMounted) setLoadingPdf(false);
      }
    })();

    return () => {
      isMounted = false;
      if (objectUrlToRevoke) window.URL.revokeObjectURL(objectUrlToRevoke);
    };
    // The status is in the key: the PDF prints a mark when it is cancelled or expired.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quotation.id, quotation.status]);

  const handleDownload = async () => {
    try {
      const response = await api.get(`/quotations/${quotation.id}/pdf`, { responseType: 'blob' });
      const url = window.URL.createObjectURL(response.data as Blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${quotation.document_type}_${quotation.quotation_number.replace(/\//g, '_')}.pdf`;
      link.click();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      onError?.(getApiErrorMessage(err, 'Unable to download PDF'));
    }
  };

  const handleOpenInNewTab = () => {
    if (pdfUrl) window.open(pdfUrl, '_blank', 'noopener,noreferrer');
  };

  const downloadAction: PreviewAction = {
    label: 'Download',
    icon: <Download size={16} aria-hidden="true" />,
    onClick: handleDownload,
    title: `Download ${label.toLowerCase()} PDF`,
  };

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="quotation-preview-title">
      <div className="modal-panel modal-panel--invoice-preview">
        <PreviewToolbar
          eyebrow={`${label} preview`}
          titleId="quotation-preview-title"
          title={title}
          meta={meta}
          primary={canShare ? {
            label: 'Share',
            icon: <Share2 size={16} aria-hidden="true" />,
            onClick: () => setShowShareModal(true),
            title: `Share a link to this ${label.toLowerCase()}`,
          } : downloadAction}
          secondary={[
            {
              label: 'Print',
              icon: <Printer size={16} aria-hidden="true" />,
              onClick: () => {
                iframeRef.current?.contentWindow?.focus();
                iframeRef.current?.contentWindow?.print();
              },
              disabled: !pdfUrl || loadingPdf || previewFailed,
              title: `Print ${label.toLowerCase()}`,
            },
            ...(canShare ? [downloadAction] : []),
          ]}
          menu={[
            ...menuActions,
            {
              label: 'Open in new tab',
              icon: <ExternalLink size={16} aria-hidden="true" />,
              onClick: handleOpenInNewTab,
              disabled: !pdfUrl,
            },
          ]}
          menuOpen={menuOpen}
          onMenuOpenChange={setMenuOpen}
          onClose={onClose}
          closeLabel={`Close ${label.toLowerCase()} preview`}
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
              title={`${title} PDF preview`}
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

      {showShareModal ? (
        <ShareModal
          resourceType="quotation"
          resourceId={quotation.id}
          label={title}
          messageLead={`${title}${quotation.company_name ? ` from ${quotation.company_name}` : ''}`}
          phone={quotation.ledger_phone}
          onClose={() => setShowShareModal(false)}
        />
      ) : null}
    </div>
  );
}
