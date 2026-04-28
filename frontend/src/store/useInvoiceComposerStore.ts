import { create } from 'zustand';

type InvoiceComposerStore = {
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
  openStockUpdateModal: () => void;
  closeStockUpdateModal: () => void;
  setFeedbackError: (feedbackError: string) => void;
  setFeedbackSuccess: (feedbackSuccess: string) => void;
  clearFeedback: () => void;
};

export const useInvoiceComposerStore = create<InvoiceComposerStore>((set) => ({
  selectedLedgerId: '',
  showLedgerCreateModal: false,
  showProductCreateModal: false,
  showStockUpdateModal: false,
  feedbackError: '',
  feedbackSuccess: '',
  setSelectedLedgerId: (selectedLedgerId) => set({ selectedLedgerId }),
  openLedgerCreateModal: () => set({ showLedgerCreateModal: true }),
  closeLedgerCreateModal: () => set({ showLedgerCreateModal: false }),
  openProductCreateModal: () => set({ showProductCreateModal: true }),
  closeProductCreateModal: () => set({ showProductCreateModal: false }),
  openStockUpdateModal: () => set({ showStockUpdateModal: true }),
  closeStockUpdateModal: () => set({ showStockUpdateModal: false }),
  setFeedbackError: (feedbackError) => set({ feedbackError, feedbackSuccess: '' }),
  setFeedbackSuccess: (feedbackSuccess) => set({ feedbackSuccess, feedbackError: '' }),
  clearFeedback: () => set({ feedbackError: '', feedbackSuccess: '' }),
}));