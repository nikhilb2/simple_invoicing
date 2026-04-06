import { useState } from 'react';
import { useEscapeClose } from '../hooks/useEscapeClose';
import api, { getApiErrorMessage } from '../api/client';

type EmailType = 'invoice' | 'statement' | 'reminder';

type SendEmailModalProps = {
  type: EmailType;
  entityId: number;
  defaultTo: string;
  defaultSubject: string;
  onClose: () => void;
  onSuccess: (message: string) => void;
  onError: (message: string) => void;
  fromDate?: string;
  toDate?: string;
};

export default function SendEmailModal({
  type,
  entityId,
  defaultTo,
  defaultSubject,
  onClose,
  onSuccess,
  onError,
  fromDate,
  toDate,
}: SendEmailModalProps) {
  const [to, setTo] = useState(defaultTo);
  const [cc, setCc] = useState('');
  const [subject, setSubject] = useState(defaultSubject);
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);

  useEscapeClose(onClose);

  const getEndpoint = () => {
    switch (type) {
      case 'invoice':
        return `/email/invoice/${entityId}`;
      case 'statement':
        return `/email/ledger-statement/${entityId}`;
      case 'reminder':
        return `/email/payment-reminder/${entityId}`;
      default:
        throw new Error(`Unknown email type: ${type}`);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!to.trim()) {
      onError('Recipient email is required');
      return;
    }

    setSending(true);
    try {
      const payload: any = {
        to: to.trim(),
        cc: cc.trim() || undefined,
        subject: subject.trim(),
        message: message.trim() || undefined,
      };
      if (type === 'statement' && fromDate && toDate) {
        payload.from_date = fromDate;
        payload.to_date = toDate;
      }
      await api.post(getEndpoint(), payload);
      onSuccess('Email sent successfully');
      onClose();
    } catch (err) {
      onError(getApiErrorMessage(err, 'Failed to send email'));
    } finally {
      setSending(false);
    }
  };

  const getTitle = () => {
    switch (type) {
      case 'invoice':
        return 'Email Invoice';
      case 'statement':
        return 'Email Statement';
      case 'reminder':
        return 'Send Payment Reminder';
      default:
        return 'Send Email';
    }
  };

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="send-email-title">
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="panel__header">
          <div>
            <p className="eyebrow">Compose email</p>
            <h2 id="send-email-title" className="nav-panel__title">{getTitle()}</h2>
          </div>
          <button
            type="button"
            className="button button--ghost"
            onClick={onClose}
            title="Close modal"
            aria-label="Close modal"
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="stack">
          <div className="field-grid">
            <div className="field">
              <label htmlFor="email-to">To *</label>
              <input
                id="email-to"
                type="email"
                className="input"
                value={to}
                onChange={(e) => setTo(e.target.value)}
                required
                disabled={sending}
                placeholder="recipient@example.com"
              />
            </div>

            <div className="field">
              <label htmlFor="email-cc">CC</label>
              <input
                id="email-cc"
                type="email"
                className="input"
                value={cc}
                onChange={(e) => setCc(e.target.value)}
                disabled={sending}
                placeholder="cc@example.com"
              />
            </div>
          </div>

          <div className="field--full">
            <label htmlFor="email-subject">Subject</label>
            <input
              id="email-subject"
              type="text"
              className="input"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              disabled={sending}
              required
            />
          </div>

          <div className="field--full">
            <label htmlFor="email-message">Message</label>
            <textarea
              id="email-message"
              className="textarea"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              disabled={sending}
              placeholder="Optional custom message..."
            />
          </div>

          <div className="button-row">
            <button
              type="button"
              className="button button--secondary"
              onClick={onClose}
              disabled={sending}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="button button--primary"
              disabled={sending || !to.trim()}
            >
              {sending ? 'Sending...' : 'Send Email'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}