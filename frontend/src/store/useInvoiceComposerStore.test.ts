import { beforeEach, describe, expect, it } from 'vitest';
import { useInvoiceComposerStore } from './useInvoiceComposerStore';

describe('useInvoiceComposerStore feedback', () => {
  beforeEach(() => useInvoiceComposerStore.getState().clearFeedback());

  it('clearFeedbackError leaves success untouched', () => {
    useInvoiceComposerStore.setState({ feedbackError: 'bad', feedbackSuccess: 'good' });
    useInvoiceComposerStore.getState().clearFeedbackError();
    expect(useInvoiceComposerStore.getState().feedbackError).toBe('');
    expect(useInvoiceComposerStore.getState().feedbackSuccess).toBe('good');
  });

  it('clearFeedbackSuccess leaves error untouched', () => {
    useInvoiceComposerStore.setState({ feedbackError: 'bad', feedbackSuccess: 'good' });
    useInvoiceComposerStore.getState().clearFeedbackSuccess();
    expect(useInvoiceComposerStore.getState().feedbackSuccess).toBe('');
    expect(useInvoiceComposerStore.getState().feedbackError).toBe('bad');
  });
});
