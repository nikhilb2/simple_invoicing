import { create } from 'zustand';
import type { StockShortage } from '../features/invoices/stockShortage';

/** Where the Update stock dialog starts when it is opened from a stock error. */
export type StockUpdateStart = { productId: number; quantity: number };

type InvoiceComposerStore = {
  stockUpdateStart: StockUpdateStart | null;
  /** The product the last save ran short of, until stock is added or the form is cleared. */
  stockShortage: StockShortage | null;
  setStockShortage: (stockShortage: StockShortage | null) => void;
  selectedLedgerId: string;
  showLedgerCreateModal: boolean;
  showProductCreateModal: boolean;
  showStockUpdateModal: boolean;
  feedbackError: string;
  feedbackSuccess: string;
  setSelectedLedgerId: (selectedLedgerId: string) => void;
  openLedgerCreateModal: () => void;
  closeLedgerCreateModal: () => void;
  openProductCreateModal: () => void;
  closeProductCreateModal: () => void;
  openStockUpdateModal: (start?: StockUpdateStart) => void;
  closeStockUpdateModal: () => void;
  setFeedbackError: (feedbackError: string) => void;
  setFeedbackSuccess: (feedbackSuccess: string) => void;
  clearFeedback: () => void;
  clearFeedbackError: () => void;
  clearFeedbackSuccess: () => void;
};

export const useInvoiceComposerStore = create<InvoiceComposerStore>((set) => ({
  selectedLedgerId: '',
  showLedgerCreateModal: false,
  showProductCreateModal: false,
  showStockUpdateModal: false,
  stockUpdateStart: null,
  stockShortage: null,
  setStockShortage: (stockShortage) => set({ stockShortage }),
  feedbackError: '',
  feedbackSuccess: '',
  setSelectedLedgerId: (selectedLedgerId) => set({ selectedLedgerId }),
  openLedgerCreateModal: () => set({ showLedgerCreateModal: true }),
  closeLedgerCreateModal: () => set({ showLedgerCreateModal: false }),
  openProductCreateModal: () => set({ showProductCreateModal: true }),
  closeProductCreateModal: () => set({ showProductCreateModal: false }),
  openStockUpdateModal: (start) => set({ showStockUpdateModal: true, stockUpdateStart: start ?? null }),
  closeStockUpdateModal: () => set({ showStockUpdateModal: false, stockUpdateStart: null }),
  setFeedbackError: (feedbackError) => set({ feedbackError, feedbackSuccess: '' }),
  setFeedbackSuccess: (feedbackSuccess) => set({ feedbackSuccess, feedbackError: '' }),
  clearFeedback: () => set({ feedbackError: '', feedbackSuccess: '' }),
  clearFeedbackError: () => set({ feedbackError: '' }),
  clearFeedbackSuccess: () => set({ feedbackSuccess: '' }),
}));