import { useCallback, useState } from 'react';
import { Download, ExternalLink, Mail, Printer, Share2 } from 'lucide-react';
import api, { getApiErrorMessage } from '../api/client';
import type { CompanyProfile, Ledger, LedgerStatement } from '../types/api';
import formatCurrency from '../utils/formatting';
import SendEmailModal from './SendEmailModal';
import ShareModal from './ShareModal';
import PreviewToolbar from './PreviewToolbar';
import PdfPreview, { usePdfPreview } from './PdfPreview';
import { useEscapeClose } from '../hooks/useEscapeClose';

type StatementPreviewProps = {
  ledger: Ledger;
  statement: LedgerStatement;
  /** No longer drawn on the statement itself — the PDF carries its own header.
   *  Still the name the email subject and the share message are written in. */
  company: CompanyProfile | null;
  currencyCode: string;
  onClose: () => void;
  onError?: (message: string) => void;
};

export default function StatementPreview({ ledger, statement, company, currencyCode, onClose, onError }: StatementPreviewProps) {
  const [showEmailModal, setShowEmailModal] = useState(false);
  const [showShareModal, setShowShareModal] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  // The email and share modals stacked on top close themselves on Escape;
  // without this guard the same keypress tears down the preview behind them.
  useEscapeClose(useCallback(() => {
    // Escape closes the open menu first, then the preview -- otherwise opening
    // the menu and hitting Escape would dismiss the whole dialog underneath it.
    if (menuOpen) { setMenuOpen(false); return; }
    if (!showEmailModal && !showShareModal) onClose();
  }, [menuOpen, showEmailModal, showShareModal, onClose]));

  // The statement is a view over a period, so the dates are part of what is
  // being previewed: change them on the page behind the modal and this refetches.
  const preview = usePdfPreview({
    path: `/ledgers/${ledger.id}/statement/pdf`,
    params: { from_date: statement.from_date, to_date: statement.to_date },
    errorMessage: 'Unable to load statement PDF preview',
    onError,
  });

  const handleDownloadPdf = async () => {
    try {
      const response = await api.get(`/ledgers/${ledger.id}/statement/pdf`, {
        params: { from_date: statement.from_date, to_date: statement.to_date },
        responseType: 'blob',
      });
      const url = window.URL.createObjectURL(response.data as Blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `statement_${ledger.name.replace(/\s+/g, '_').slice(0, 30)}_${statement.from_date}_${statement.to_date}.pdf`;
      link.click();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      onError?.(getApiErrorMessage(err, 'Unable to download PDF'));
    }
  };

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="statement-preview-title">
      <div className="modal-panel modal-panel--invoice-preview">
        <PreviewToolbar
          eyebrow="Statement preview"
          titleId="statement-preview-title"
          title={ledger.name}
          meta={`${statement.from_date} to ${statement.to_date}`}
          primary={{
            label: 'Share',
            icon: <Share2 size={16} aria-hidden="true" />,
            onClick: () => setShowShareModal(true),
            title: 'Share a link to this statement',
          }}
          secondary={[
            {
              // Same reasoning as the invoice preview: the send action belongs
              // in the row, not behind an overflow menu nobody opens.
              label: 'Email',
              icon: <Mail size={16} aria-hidden="true" />,
              onClick: () => setShowEmailModal(true),
              title: 'Email statement',
            },
            {
              label: 'Print',
              icon: <Printer size={16} aria-hidden="true" />,
              onClick: preview.print,
              disabled: !preview.canPrint,
              title: 'Print statement',
            },
            {
              label: 'Download',
              icon: <Download size={16} aria-hidden="true" />,
              onClick: handleDownloadPdf,
              title: 'Download statement PDF',
            },
          ]}
          menu={[
            {
              // Always offered, not just once the frame has given up: on iOS
              // Safari a PDF in an iframe simply will not scroll, and the frame
              // fires no error, so the fallback card never appears there.
              label: 'Open in new tab',
              icon: <ExternalLink size={16} aria-hidden="true" />,
              onClick: preview.openInNewTab,
              disabled: !preview.pdfUrl,
            },
          ]}
          menuOpen={menuOpen}
          onMenuOpenChange={setMenuOpen}
          onClose={onClose}
          closeLabel="Close statement preview"
        />

        <PdfPreview preview={preview} title={`Statement for ${ledger.name} PDF preview`} />
      </div>

      {showEmailModal && (
        <SendEmailModal
          type="statement"
          entityId={ledger.id}
          defaultTo={ledger.email || ''}
          defaultSubject={`Account Statement from ${company?.name || 'Company'}`}
          fromDate={statement.from_date}
          toDate={statement.to_date}
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
          resourceType="ledger_statement"
          /* The ledger id, not a statement id — a statement is a view over a
             period, and the period is what scopes the link. */
          resourceId={ledger.id}
          fromDate={statement.from_date}
          toDate={statement.to_date}
          label={`Statement — ${statement.from_date} to ${statement.to_date}`}
          messageLead={`Account statement${company?.name ? ` from ${company.name}` : ''} (${statement.from_date} to ${statement.to_date}) — closing balance ${formatCurrency(statement.closing_balance, currencyCode)}`}
          phone={ledger.phone_number}
          onClose={() => setShowShareModal(false)}
        />
      )}
    </div>
  );
}
