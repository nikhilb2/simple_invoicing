import { useCallback, useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Copy, Trash2 } from 'lucide-react';
import ModalCloseButton from './ModalCloseButton';
import ConfirmDialog from './ConfirmDialog';
import { useEscapeClose } from '../hooks/useEscapeClose';
import { getApiErrorMessage } from '../api/client';
import { listShareLinks, revokeShareLink } from '../features/share/api';
import { shareQueryKeys } from '../features/share/queryKeys';
import { describeShareLinkPeriod, describeViews } from '../features/share/describe';
import type { ShareLink } from '../types/api';
import { copyTextToClipboard } from '../utils/clipboard';
import { formatDate } from '../utils/formatting';

type PublicLinksDialogProps = {
  ledgerId: number;
  ledgerName: string;
  onClose: () => void;
};

/**
 * Every live public statement link for one ledger, including the dated
 * reminder links and the open-ended "Always current" one. Opening this
 * dialog only lists links — it never creates one, unlike the share dialog,
 * whose open call is a create-or-fetch POST.
 */
export default function PublicLinksDialog({ ledgerId, ledgerName, onClose }: PublicLinksDialogProps) {
  const queryClient = useQueryClient();
  const [confirmingRevoke, setConfirmingRevoke] = useState<ShareLink | null>(null);
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [copyError, setCopyError] = useState('');

  useEscapeClose(useCallback(() => {
    if (!confirmingRevoke) onClose();
  }, [confirmingRevoke, onClose]));

  const listKey = shareQueryKeys.list('ledger_statement', ledgerId);
  const linksQuery = useQuery({
    queryKey: listKey,
    queryFn: () => listShareLinks('ledger_statement', ledgerId),
    staleTime: 0,
    retry: false,
  });

  const revokeMutation = useMutation({
    mutationFn: (id: number) => revokeShareLink(id),
    onSuccess: () => {
      setConfirmingRevoke(null);
      // Invalidate the list only. Invalidating the `link` keys would run the
      // share dialog's create-or-fetch POST again and mint a replacement.
      void queryClient.invalidateQueries({ queryKey: listKey });
    },
  });

  useEffect(() => {
    if (copiedId === null) {
      return;
    }
    const timer = window.setTimeout(() => setCopiedId(null), 2000);
    return () => window.clearTimeout(timer);
  }, [copiedId]);

  const handleCopy = async (link: ShareLink) => {
    setCopyError('');
    if (await copyTextToClipboard(link.url)) {
      setCopiedId(link.id);
    } else {
      setCopyError('Could not copy automatically — select the link and copy it.');
    }
  };

  const links = linksQuery.data ?? [];
  const loadError = linksQuery.error
    ? getApiErrorMessage(linksQuery.error, 'Unable to load public links')
    : '';
  const revokeError = revokeMutation.error
    ? getApiErrorMessage(revokeMutation.error, 'Unable to revoke this link')
    : '';

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="public-links-title">
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="panel__header">
          <div>
            <p className="eyebrow">Public links</p>
            <h2 id="public-links-title" className="nav-panel__title">{ledgerName}</h2>
          </div>
          <ModalCloseButton onClick={onClose} label="Close public links" />
        </div>

        <div className="stack">
          <p className="muted-text" style={{ margin: 0 }}>
            Anyone with one of these links can view the statement — no sign-in needed.
            Revoking a link stops it opening, including for customers holding an old reminder email.
          </p>

          {linksQuery.isPending ? (
            <p className="muted-text" aria-live="polite">Loading links…</p>
          ) : null}

          {loadError ? (
            <div className="stack" aria-live="polite">
              <p className="error-text share-link__error">{loadError}</p>
              <div className="button-row">
                <button type="button" className="button button--secondary" onClick={() => void linksQuery.refetch()}>
                  Try again
                </button>
              </div>
            </div>
          ) : null}

          {!linksQuery.isPending && !loadError && links.length === 0 ? (
            <p className="muted-text" aria-live="polite">No live public links for this ledger.</p>
          ) : null}

          {links.map((link) => {
            return (
              <div className="stack" key={link.id}>
                <p style={{ margin: 0 }}>
                  <strong>{describeShareLinkPeriod(link)}</strong>
                </p>
                <p className="field-hint" style={{ margin: 0 }}>
                  {describeViews(link.view_count, link.last_viewed_at)} · Created {formatDate(link.created_at)}
                </p>
                <div className="share-link__row">
                  <input
                    type="text"
                    className="input share-link__url"
                    value={link.url}
                    readOnly
                    onFocus={(e) => e.currentTarget.select()}
                    aria-label={`Public link for ${describeShareLinkPeriod(link)}`}
                  />
                  <button
                    type="button"
                    className="button button--secondary"
                    onClick={() => void handleCopy(link)}
                    title="Copy link"
                    aria-label="Copy public link"
                  >
                    {copiedId === link.id ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}
                    {copiedId === link.id ? 'Copied' : 'Copy'}
                  </button>
                  <button
                    type="button"
                    className="button button--danger"
                    onClick={() => setConfirmingRevoke(link)}
                    disabled={revokeMutation.isPending}
                    title="Revoke this link"
                    aria-label="Revoke public link"
                  >
                    <Trash2 size={16} aria-hidden="true" />
                    {revokeMutation.isPending ? 'Revoking…' : 'Revoke'}
                  </button>
                </div>
              </div>
            );
          })}

          {copyError ? <p className="error-text share-link__error">{copyError}</p> : null}
          {revokeError ? <p className="error-text share-link__error">{revokeError}</p> : null}
        </div>
      </div>

      {confirmingRevoke ? (
        <ConfirmDialog
          title="Revoke this link?"
          message={
            'Anyone holding this link, including customers with an old reminder email, will no longer be able to open it.' +
            (!confirmingRevoke.from_date && !confirmingRevoke.to_date
              ? ' The next reminder will create a new link.'
              : '')
          }
          confirmText="Revoke link"
          danger
          confirmDisabled={revokeMutation.isPending}
          onConfirm={() => revokeMutation.mutate(confirmingRevoke.id)}
          onCancel={() => setConfirmingRevoke(null)}
        />
      ) : null}
    </div>
  );
}
