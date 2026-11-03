import { MessageCircle, Phone } from 'lucide-react';
import { buildWhatsAppUrl, toWhatsAppNumber } from '../utils/phone';

type LedgerCardPhoneChipsProps = {
  phone: string | null | undefined;
};

/**
 * The phone chip(s) for a ledger card on the ledgers list, matching the
 * detail page behaviour in LedgerPhoneLinks: a tel: link for the number,
 * plus a WhatsApp chip only when the number can be confidently addressed
 * on wa.me. A value with no digits stays a plain, non-link chip, so cards
 * without a usable number look exactly as they did before.
 */
export default function LedgerCardPhoneChips({ phone }: LedgerCardPhoneChipsProps) {
  const displayPhone = phone?.trim();
  if (!displayPhone) return null;

  const digits = displayPhone.replace(/\D/g, '');
  if (!digits) {
    return (
      <span className="ledger-chip">
        <Phone size={13} aria-hidden="true" />
        {displayPhone}
      </span>
    );
  }

  const dialNumber = `${displayPhone.startsWith('+') ? '+' : ''}${digits}`;
  const whatsappNumber = toWhatsAppNumber(displayPhone);

  return (
    <>
      <a
        className="ledger-chip"
        href={`tel:${dialNumber}`}
        title={`Call ${displayPhone}`}
        aria-label={`Call ${displayPhone}`}
      >
        <Phone size={13} aria-hidden="true" />
        {displayPhone}
      </a>
      {whatsappNumber ? (
        <a
          className="ledger-chip ledger-chip--whatsapp"
          href={buildWhatsAppUrl(whatsappNumber, '')}
          target="_blank"
          rel="noopener noreferrer"
          title={`WhatsApp ${displayPhone}`}
          aria-label={`WhatsApp ${displayPhone}`}
        >
          <MessageCircle size={13} aria-hidden="true" />
          WhatsApp
        </a>
      ) : null}
    </>
  );
}
