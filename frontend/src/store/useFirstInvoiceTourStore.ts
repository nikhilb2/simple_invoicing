import { create } from 'zustand';
import { saveFirstInvoiceTourStatus } from '../api/auth';
import type { ComposerFacts, FirstInvoiceTourStatus } from '../features/firstInvoiceTour/tourSteps';
import { useAuthStore } from './useAuthStore';

/** Keeps a running walkthrough alive through a page reload in this tab. Whose it is stops it following a sign-out. */
const RUNNING_KEY = 'first_invoice_tour_running_for';

function readRunningFor(): string | null {
  try {
    return sessionStorage.getItem(RUNNING_KEY);
  } catch {
    return null;
  }
}

function writeRunningFor(email: string | null): void {
  try {
    if (email) sessionStorage.setItem(RUNNING_KEY, email);
    else sessionStorage.removeItem(RUNNING_KEY);
  } catch {
    /* A reload then ends the walkthrough, which is not worth breaking anything over. */
  }
}

/** Saved to the account, so it holds on every device. A failed save only means being offered it once more. */
export function recordTourAnswer(status: FirstInvoiceTourStatus): void {
  const { setFirstInvoiceTourStatus } = useAuthStore.getState();
  setFirstInvoiceTourStatus(status);
  saveFirstInvoiceTourStatus(status)
    .then(setFirstInvoiceTourStatus)
    .catch(() => undefined);
}

type TourState = {
  phase: 'idle' | 'running' | 'done';
  owner: string | null;
  facts: ComposerFacts | null;
  start: () => void;
  /** Leaving part way counts as skipping. It can be started again from the dashboard. */
  exit: () => void;
  /** The invoice page calls this when a sales invoice is saved. Does nothing unless the walkthrough is running. */
  invoiceCreated: () => void;
  close: () => void;
  report: (facts: ComposerFacts | null) => void;
};

const runningFor = readRunningFor();

export const useFirstInvoiceTourStore = create<TourState>((set, get) => ({
  phase: runningFor ? 'running' : 'idle',
  owner: runningFor,
  facts: null,

  start: () => {
    const owner = useAuthStore.getState().userEmail;
    writeRunningFor(owner);
    set({ phase: 'running', owner });
  },

  exit: () => {
    writeRunningFor(null);
    set({ phase: 'idle', owner: null });
    recordTourAnswer('skipped');
  },

  invoiceCreated: () => {
    if (get().phase !== 'running') return;
    writeRunningFor(null);
    set({ phase: 'done' });
    recordTourAnswer('completed');
  },

  close: () => set({ phase: 'idle', owner: null }),

  report: (facts) => set({ facts }),
}));
