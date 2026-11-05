import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import { INVOICE_PATH, tourOffer } from '../features/firstInvoiceTour/tourSteps';
import { useReserveCardSpace } from './FirstInvoiceTourCoach';
import { useAuthStore } from '../store/useAuthStore';
import { recordTourAnswer, useFirstInvoiceTourStore } from '../store/useFirstInvoiceTourStore';
import type { DashboardMetrics } from '../types/api';

export function TourOfferCard({ onStart, onSkip, cardRef }: { onStart: () => void; onSkip: () => void; cardRef?: React.Ref<HTMLElement> }) {
  return (
    <section ref={cardRef} className="tour-coach tour-coach--offer" aria-labelledby="tour-offer-title" data-testid="tour-offer">
      <p className="eyebrow">New here?</p>
      <h2 className="tour-coach__title" id="tour-offer-title">Create your first invoice with us</h2>
      <p className="tour-coach__body">
        We’ll show you each step on the real page, including adding a customer and a product. It takes about 3 minutes.
      </p>
      <div className="tour-coach__actions">
        <button type="button" className="button button--primary button--small" onClick={onStart}>
          Show me how
        </button>
        <button type="button" className="button button--ghost button--small" onClick={onSkip}>
          Skip for now
        </button>
      </div>
    </section>
  );
}

/** Offered on the dashboard, without blocking it, until the user answers. */
export default function FirstInvoiceTourOffer({ metrics }: { metrics: DashboardMetrics | null }) {
  const status = useAuthStore((state) => state.firstInvoiceTourStatus);
  const companyRole = useAuthStore((state) => state.companyRole);
  const phase = useFirstInvoiceTourStore((state) => state.phase);
  const start = useFirstInvoiceTourStore((state) => state.start);
  const navigate = useNavigate();
  const offer = tourOffer(status, companyRole, metrics);
  const showing = offer === 'offer' && phase === 'idle';
  const cardRef = useRef<HTMLElement>(null);
  useReserveCardSpace(cardRef, showing);

  useEffect(() => {
    if (offer === 'not_needed') recordTourAnswer('not_needed');
  }, [offer]);

  if (!showing) return null;

  return createPortal(
    <TourOfferCard
      cardRef={cardRef}
      onStart={() => {
        start();
        navigate(INVOICE_PATH);
      }}
      onSkip={() => recordTourAnswer('skipped')}
    />,
    document.body,
  );
}
