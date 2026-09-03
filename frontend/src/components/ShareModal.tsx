import { useCallback, useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Copy, MessageCircle, Trash2 } from 'lucide-react';
import ModalCloseButton from './ModalCloseButton';
import ConfirmDialog from './ConfirmDialog';
import { useEscapeClose } from '../hooks/useEscapeClose';
import { getApiErrorMessage } from '../api/client';
import { ensureShareLink, revokeShareLink } from '../features/share/api';
import { shareQueryKeys } from '../features/share/queryKeys';
import { track } from '../lib/analytics';
import type { ShareResourceType } from '../types/api';
import { buildWhatsAppUrl, toWhatsAppNumber } from '../utils/phone';

type ShareModalProps = {
  resourceType: ShareResourceType;
  /** Invoice id, *ledger* id for a statement, or payment id. */
  resourceId: number;
  /** Names the document in the dialog header, e.g. "Invoice INV-0042". */
  label: string;
  /**
   * The line sent above the URL on WhatsApp, written by the calling surface
   * because only it knows what the document is called and what it is worth —
   * e.g. "Invoice INV-0042 from Acme Traders — ₹12,500.00".
   */
  messageLead: string;
  /** Statement period. Ignored for every other resource type. */
  fromDate?: string;
  toDate?: string;
  /** The customer's phone as stored: free text, possibly unusable. */
  phone?: string | null;
  onClose: () => void;
};

/** "2 hours ago" for the last-opened line. Intl does the pluralising. */
function formatRelativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) {
    return 'recently';
  }

  const seconds = Math.round((then - Date.now()) / 1000);
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ['second', 60],
    ['minute', 60],
    ['hour', 24],
    ['day', 30],
    ['month', 12],
    ['year', Number.POSITIVE_INFINITY],
  ];

  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
  let value = seconds;
  for (const [unit, step] of units) {
    if (Math.abs(value) < step) {
      return formatter.format(Math.round(value), unit);
    }
    value /= step;
  }
  return formatter.format(Math.round(value), 'year');
}

function describeViews(viewCount: number, lastViewedAt: string | null): string {
  if (viewCount <= 0) {
    return 'Not opened yet';
  }

  const opened = viewCount === 1 ? 'Opened once' : `Opened ${viewCount} times`;
  return lastViewedAt ? `${opened} · last ${formatRelativeTime(lastViewedAt)}` : opened;
}

/**
 * Copies without the async clipboard API, which needs a secure context: an
 * instance reached over plain http on the shop LAN has no `navigator.clipboard`
 * at all, and the copy button is the whole point of this dialog.
 */
function copyViaSelection(text: string): boolean {
  const field = document.createElement('textarea');
  field.value = text;
  field.setAttribute('readonly', '');
  field.style.position = 'fixed';
  field.style.opacity = '0';
  document.body.appendChild(field);
  field.select();
  try {
    return document.execCommand('copy');
  } catch {
    return false;
  } finally {
    document.body.removeChild(field);
  }
}

export default function ShareModal({
  resourceType,
  resourceId,
  label,
  messageLead,
  fromDate,
  toDate,
  phone,
  onClose,
}: ShareModalProps) {
  const queryClient = useQueryClient();
  // Set the moment a link is revoked, and only cleared by "Create a new link".
  // Without it the idempotent create would fire again on the next render and
  // silently hand back a live link the user just asked us to destroy.
  const [revoked, setRevoked] = useState(false);
  const [confirmingRevoke, setConfirmingRevoke] = useState(false);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState('');
  const trackedLinkIds = useRef<Set<number>>(new Set());

  const queryKey = shareQueryKeys.link(resourceType, resourceId, fromDate, toDate);

  // The confirm dialog stacked on top closes itself on Escape; without this
  // guard the same keypress tears down the share dialog behind it as well.
  useEscapeClose(useCallback(() => {
    if (!confirmingRevoke) onClose();
  }, [confirmingRevoke, onClose]));

  const linkQuery = useQuery({
    queryKey,
    queryFn: () => ensureShareLink({ resourceType, resourceId, fromDate, toDate }),
    enabled: !revoked,
    // The open count is the reason to reopen this dialog, so it is never served
    // stale, and a revoked link must not survive in the cache behind it.
    staleTime: 0,
    gcTime: 0,
    retry: false,
  });

  const link = revoked ? undefined : linkQuery.data;

  const revokeMutation = useMutation({
    mutationFn: (id: number) => revokeShareLink(id),
    onSuccess: (_result, id) => {
      track('share_link_revoked', {
        share_link_id: id,
        resource_type: resourceType,
        resource_id: resourceId,
      });
      setConfirmingRevoke(false);
      setRevoked(true);
      // removeQueries, not invalidateQueries: invalidating would immediately
      // re-run the create-or-fetch POST and mint a replacement nobody asked for.
      queryClient.removeQueries({ queryKey });
    },
  });

  useEffect(() => {
    if (!link || trackedLinkIds.current.has(link.id)) {
      return;
    }
    trackedLinkIds.current.add(link.id);
    track('share_link_created', {
      share_link_id: link.id,
      resource_type: link.resource_type,
      resource_id: link.resource_id,
      view_count: link.view_count,
    });
  }, [link]);

  useEffect(() => {
    if (!copied) {
      return;
    }
    const timer = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const whatsAppNumber = toWhatsAppNumber(phone);
  const message = link ? `${messageLead}\n${link.url}` : '';

  const handleCopy = async () => {
    if (!link) return;
    setCopyError('');

    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(link.url);
        setCopied(true);
        return;
      }
    } catch {
      // Permission denied or an insecure context — fall through to the
      // selection-based copy rather than leaving the user with nothing.
    }

    if (copyViaSelection(link.url)) {
      setCopied(true);
    } else {
      setCopyError('Could not copy automatically — select the link and copy it.');
    }
  };

  const handleWhatsApp = () => {
    if (!link) return;
    track('share_link_whatsapp_opened', {
      share_link_id: link.id,
      resource_type: link.resource_type,
      resource_id: link.resource_id,
      // Whether we could address the chat, not the number itself.
      has_recipient_number: whatsAppNumber !== null,
    });
    window.open(buildWhatsAppUrl(whatsAppNumber, message), '_blank', 'noopener,noreferrer');
  };

  const loadError = linkQuery.error
    ? getApiErrorMessage(linkQuery.error, 'Unable to create a share link')
    : '';
  const revokeError = revokeMutation.error
    ? getApiErrorMessage(revokeMutation.error, 'Unable to revoke this link')
    : '';

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="share-modal-title">
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="panel__header">
          <div>
            <p className="eyebrow">Share a public link</p>
            <h2 id="share-modal-title" className="nav-panel__title">{label}</h2>
          </div>
          <ModalCloseButton onClick={onClose} label="Close share link" />
        </div>

        <div className="stack">
          <p className="muted-text" style={{ margin: 0 }}>
            Anyone with this link can view {resourceType === 'ledger_statement' ? 'the statement' : 'the document'} —
            no sign-in needed. Revoke it here when you want it to stop working.
          </p>

          {linkQuery.isPending && !revoked ? (
            <p className="muted-text" aria-live="polite">Creating the link…</p>
          ) : null}

          {loadError ? (
            <div className="stack" aria-live="polite">
              <p className="error-text share-link__error">{loadError}</p>
              <div className="button-row">
                <button type="button" className="button button--secondary" onClick={() => void linkQuery.refetch()}>
                  Try again
                </button>
              </div>
            </div>
          ) : null}

          {revoked ? (
            <div className="share-link__revoked" aria-live="polite">
              <p className="share-link__revoked-title">This link has been revoked.</p>
              <p className="muted-text" style={{ margin: 0 }}>
                The old URL no longer opens anything, including for anyone you already sent it to.
                Creating a new link issues a different URL — the old one stays dead.
              </p>
              <div className="button-row">
                <button
                  type="button"
                  className="button button--primary"
                  onClick={() => {
                    revokeMutation.reset();
                    setRevoked(false);
                  }}
                  title="Create a new share link"
                  aria-label="Create a new share link"
                >
                  Create a new link
                </button>
              </div>
            </div>
          ) : null}

          {link ? (
            <>
              <div className="field--full">
                <label htmlFor="share-link-url">Public link</label>
                <div className="share-link__row">
                  <input
                    id="share-link-url"
                    type="text"
                    className="input share-link__url"
                    value={link.url}
                    readOnly
                    onFocus={(e) => e.currentTarget.select()}
                  />
                  <button
                    type="button"
                    className="button button--secondary"
                    onClick={() => void handleCopy()}
                    title="Copy link"
                    aria-label="Copy share link"
                  >
                    {copied ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}
                    {copied ? 'Copied' : 'Copy'}
                  </button>
                </div>
                <p className="field-hint" aria-live="polite">
                  {copyError || describeViews(link.view_count, link.last_viewed_at)}
                </p>
              </div>

              {whatsAppNumber === null ? (
                <p className="field-hint" style={{ margin: 0 }}>
                  {phone
                    ? 'No usable phone number on this account, so WhatsApp will ask you to pick the contact.'
                    : 'No phone number on this account, so WhatsApp will ask you to pick the contact.'}
                </p>
              ) : null}

              {revokeError ? <p className="error-text share-link__error">{revokeError}</p> : null}

              <div className="button-row">
                <button
                  type="button"
                  className="button button--danger"
                  onClick={() => setConfirmingRevoke(true)}
                  disabled={revokeMutation.isPending}
                  title="Revoke this link"
                  aria-label="Revoke share link"
                >
                  <Trash2 size={16} aria-hidden="true" />
                  {revokeMutation.isPending ? 'Revoking…' : 'Revoke'}
                </button>
                <button
                  type="button"
                  className="button button--primary"
                  onClick={handleWhatsApp}
                  title="Send this link on WhatsApp"
                  aria-label="Send on WhatsApp"
                >
                  <MessageCircle size={16} aria-hidden="true" />
                  Send on WhatsApp
                </button>
              </div>
            </>
          ) : null}
        </div>
      </div>

      {confirmingRevoke && link ? (
        <ConfirmDialog
          title="Revoke this link?"
          message="Anyone you already sent this link to will stop being able to open it. This cannot be undone — you can create a new link afterwards, but it will have a different URL."
          confirmText="Revoke link"
          danger
          onConfirm={() => revokeMutation.mutate(link.id)}
          onCancel={() => setConfirmingRevoke(false)}
        />
      ) : null}
    </div>
  );
}
