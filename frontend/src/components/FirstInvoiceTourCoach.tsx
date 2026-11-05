import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  AWAY_GUIDE,
  guideFor,
  INVOICE_PATH,
  pickTarget,
  TOUR_STEPS,
  type FieldState,
  type Guide,
  type GuideTarget,
} from '../features/firstInvoiceTour/tourSteps';
import { useAuthStore } from '../store/useAuthStore';
import { useFirstInvoiceTourStore } from '../store/useFirstInvoiceTourStore';

type Box = { top: number; left: number; width: number; height: number };

const RING_GAP = 4;
const PANEL_MARGIN = 16;

function visibleElement(selector: string): HTMLElement | null {
  const element = document.querySelector<HTMLElement>(selector);
  if (!element) return null;
  const { width, height } = element.getBoundingClientRect();
  return width > 0 && height > 0 ? element : null;
}

function readField(selector: string): FieldState {
  const element = visibleElement(selector);
  if (!element) return { visible: false, value: '', focused: false };
  return {
    visible: true,
    value: (element as HTMLInputElement).value ?? '',
    focused: document.activeElement === element,
  };
}

function sameBox(a: Box | null, b: Box | null): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  return a.top === b.top && a.left === b.left && a.width === b.width && a.height === b.height;
}

/**
 * Follows the guide's target every frame. Dialogs open, forms scroll inside them,
 * and rows grow as they are filled in; one measurement of one element a frame is
 * simpler than watching for each of those, and stops as soon as the guide does.
 */
function useTarget(guide: Guide | null): { target: GuideTarget | null; box: Box | null } {
  const [state, setState] = useState<{ target: GuideTarget | null; box: Box | null }>({ target: null, box: null });
  const current = useRef(state);

  useEffect(() => {
    const publish = (target: GuideTarget | null, box: Box | null) => {
      if (current.current.target === target && sameBox(current.current.box, box)) return;
      current.current = { target, box };
      setState(current.current);
    };

    if (!guide) {
      publish(null, null);
      return undefined;
    }

    let frame = 0;
    const tick = () => {
      const target = pickTarget(guide, readField);
      const element = target ? visibleElement(target.selector) : null;
      if (element) {
        const rect = element.getBoundingClientRect();
        publish(target, { top: rect.top, left: rect.left, width: rect.width, height: rect.height });
      } else {
        publish(null, null);
      }
      frame = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(frame);
  }, [guide]);

  return state;
}

/**
 * Makes room for the floating card, so pages and dialogs can always scroll what
 * they hold clear of it. On a phone it would otherwise sit on a form's Save button.
 */
export function useReserveCardSpace(cardRef: React.RefObject<HTMLElement>, visible: boolean): void {
  useLayoutEffect(() => {
    const root = document.documentElement;
    if (!visible) return;
    root.setAttribute('data-tour-card', '');
    root.style.setProperty('--tour-card-height', `${cardRef.current?.getBoundingClientRect().height ?? 0}px`);
  });
  useLayoutEffect(() => {
    if (!visible) return undefined;
    const root = document.documentElement;
    return () => {
      root.removeAttribute('data-tour-card');
      root.style.removeProperty('--tour-card-height');
    };
  }, [visible]);
}

export type CoachCardProps = {
  step: number;
  title: string;
  body: string;
  done?: boolean;
  placeOnTop?: boolean;
  onExit?: () => void;
  onFinish?: () => void;
  onBackToInvoice?: () => void;
  cardRef?: React.Ref<HTMLElement>;
};

export function CoachCard({ step, title, body, done, placeOnTop, onExit, onFinish, onBackToInvoice, cardRef }: CoachCardProps) {
  return (
    <section
      ref={cardRef}
      className={`tour-coach${placeOnTop ? ' tour-coach--top' : ''}`}
      aria-label="First invoice walkthrough"
      data-testid="tour-coach"
    >
      <div className="tour-coach__progress" aria-hidden="true">
        {Array.from({ length: TOUR_STEPS }, (_, index) => (
          <span key={index} className={index < step || done ? 'tour-coach__dot tour-coach__dot--on' : 'tour-coach__dot'} />
        ))}
      </div>
      <p className="eyebrow">{done ? 'All done' : `Step ${step} of ${TOUR_STEPS}`}</p>
      <div aria-live="polite">
        <h2 className="tour-coach__title">{title}</h2>
        <p className="tour-coach__body">{body}</p>
      </div>
      <div className="tour-coach__actions">
        {onBackToInvoice ? (
          <button type="button" className="button button--primary button--small" onClick={onBackToInvoice}>
            Back to the invoice
          </button>
        ) : null}
        {onFinish ? (
          <button type="button" className="button button--primary button--small" onClick={onFinish}>
            Finish
          </button>
        ) : null}
        {onExit ? (
          <button type="button" className="button button--ghost button--small" onClick={onExit}>
            Exit walkthrough
          </button>
        ) : null}
      </div>
    </section>
  );
}

/**
 * Guides the first invoice from a card that sits beside the real page.
 *
 * Nothing is dimmed or blocked: people are typing into real forms, dialogs and
 * dropdowns, and a step only moves on when the customer, product or invoice has
 * actually been saved. That is why this is not built on a tour library, whose
 * overlays are made for clicking Next through a page.
 */
export default function FirstInvoiceTourCoach() {
  const phase = useFirstInvoiceTourStore((state) => state.phase);
  const owner = useFirstInvoiceTourStore((state) => state.owner);
  const facts = useFirstInvoiceTourStore((state) => state.facts);
  const exit = useFirstInvoiceTourStore((state) => state.exit);
  const close = useFirstInvoiceTourStore((state) => state.close);
  const userEmail = useAuthStore((state) => state.userEmail);
  const { pathname } = useLocation();
  const navigate = useNavigate();

  const mine = owner === userEmail;
  const onInvoicePage = pathname === INVOICE_PATH;
  const guide = phase === 'running' && mine ? (onInvoicePage ? guideFor(facts) : AWAY_GUIDE) : null;
  const { target, box } = useTarget(guide);

  // Bring a target into view once, when it changes. After that the page is theirs to scroll.
  const selector = target?.selector ?? null;
  useEffect(() => {
    if (!selector) return;
    const element = visibleElement(selector);
    if (!element) return;
    const { top, bottom } = element.getBoundingClientRect();
    if (top >= 0 && bottom <= window.innerHeight) return;
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    element.scrollIntoView({ block: 'center', behavior: reduceMotion ? 'auto' : 'smooth' });
  }, [selector]);

  const cardRef = useRef<HTMLElement>(null);
  const finished = phase === 'done' && mine;
  useReserveCardSpace(cardRef, finished || guide !== null);

  // Moves to the top of the screen rather than sit on the very thing it points at.
  const [placeOnTop, setPlaceOnTop] = useState(false);
  useLayoutEffect(() => {
    const card = cardRef.current;
    if (!card || !box) {
      setPlaceOnTop(false);
      return;
    }
    const { width, height } = card.getBoundingClientRect();
    const zoneTop = window.innerHeight - height - PANEL_MARGIN * 2;
    const zoneLeft = window.innerWidth - width - PANEL_MARGIN * 2;
    setPlaceOnTop(box.top + box.height > zoneTop && box.left + box.width > zoneLeft);
  }, [box]);

  if (finished) {
    return createPortal(
      <CoachCard
        cardRef={cardRef}
        step={TOUR_STEPS}
        done
        title="Your first invoice is ready"
        body="Use Share, Email or Download at the top of the preview to send it to your customer. You’ll find it under Invoices from now on."
        onFinish={close}
      />,
      document.body,
    );
  }

  if (!guide) return null;

  return createPortal(
    <>
      {box ? (
        <div
          className="tour-ring"
          aria-hidden="true"
          data-testid="tour-ring"
          style={{
            top: box.top - RING_GAP,
            left: box.left - RING_GAP,
            width: box.width + RING_GAP * 2,
            height: box.height + RING_GAP * 2,
          }}
        />
      ) : null}
      <CoachCard
        cardRef={cardRef}
        step={guide.step}
        title={target?.title ?? guide.title}
        body={target?.body ?? guide.body}
        placeOnTop={placeOnTop}
        onExit={exit}
        onBackToInvoice={onInvoicePage ? undefined : () => navigate(INVOICE_PATH)}
      />
    </>,
    document.body,
  );
}
