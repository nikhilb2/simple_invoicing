import { useCallback, useEffect, useRef, useState } from 'react';
import { Download, ExternalLink, Printer, Share2 } from 'lucide-react';
import { useEscapeClose } from '../hooks/useEscapeClose';
import api, { getApiErrorMessage } from '../api/client';
import ShareModal from './ShareModal';
import PreviewToolbar from './PreviewToolbar';

type CreditNotePreviewProps = {
  creditNoteId: number;
  creditNoteNumber?: string | null;
  /** A cancelled note can still be viewed and downloaded, but not shared. */
  canShare?: boolean;
  /** The customer's phone as stored — free text, and often absent. */
  ledgerPhone?: string | null;
  /** Named in the WhatsApp message so the customer knows who sent it. */
  companyName?: string | null;
  onClose: () => void;
  onError?: (message: string) => void;
};

export default function CreditNotePreview({
  creditNoteId,
  creditNoteNumber,
  canShare = true,
  ledgerPhone,
  companyName,
  onClose,
  onError,
}: CreditNotePreviewProps) {
  const [showShareModal, setShowShareModal] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [loadingPdf, setLoadingPdf] = useState(true);
  const [pdfError, setPdfError] = useState('');
  const [previewFailed, setPreviewFailed] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  // The share modal stacked on top closes itself on Escape; without this guard
  // the same keypress tears down the preview behind it as well.
  useEscapeClose(useCallback(() => {
    if (menuOpen) { setMenuOpen(false); return; }
    if (!showShareModal) onClose();
  }, [menuOpen, showShareModal, onClose]));

  useEffect(() => {
    let isMounted = true;
    let objectUrlToRevoke: string | null = null;

    const loadPdf = async () => {
      setLoadingPdf(true);
      setPdfError('');
      setPdfUrl(null);
      setPreviewFailed(false);

      try {
        const response = await api.get(`/credit-notes/${creditNoteId}/pdf`, {
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
        const message = getApiErrorMessage(err, 'Unable to load credit note PDF preview');
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
  }, [creditNoteId]);

  const handleDownloadPdf = async () => {
    try {
      const response = await api.get(`/credit-notes/${creditNoteId}/pdf`, {
        responseType: 'blob',
      });
      const url = window.URL.createObjectURL(response.data as Blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `credit_note_${(creditNoteNumber || String(creditNoteId)).replace(/\//g, '_')}.pdf`;
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

  const handleOpenInNewTab = () => {
    if (!pdfUrl) return;
    window.open(pdfUrl, '_blank', 'noopener,noreferrer');
  };

  const label = creditNoteNumber || `#${creditNoteId}`;

  const downloadAction = {
    label: 'Download',
    icon: <Download size={16} aria-hidden="true" />,
    onClick: handleDownloadPdf,
    title: 'Download credit note PDF',
  };

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="credit-note-preview-title">
      <div className="modal-panel modal-panel--invoice-preview">
        <PreviewToolbar
          eyebrow="Credit note preview"
          titleId="credit-note-preview-title"
          title={`Credit Note ${label}`}
          primary={canShare ? {
            label: 'Share',
            icon: <Share2 size={16} aria-hidden="true" />,
            onClick: () => setShowShareModal(true),
            title: 'Share a link to this credit note',
          } : downloadAction}
          secondary={[
            {
              label: 'Print',
              icon: <Printer size={16} aria-hidden="true" />,
              onClick: handlePrintPdf,
              disabled: !pdfUrl || loadingPdf || previewFailed,
              title: 'Print credit note',
            },
            ...(canShare ? [downloadAction] : []),
          ]}
          menu={[
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
          closeLabel="Close credit note preview"
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
              title={`Credit note ${label} PDF preview`}
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
          resourceType="credit_note"
          resourceId={creditNoteId}
          label={`Credit Note ${label}`}
          messageLead={`Credit Note ${label}${companyName ? ` from ${companyName}` : ''}`}
          phone={ledgerPhone}
          onClose={() => setShowShareModal(false)}
        />
      ) : null}
    </div>
  );
}
