import ConfirmDialog from './ConfirmDialog';

type CurrencyChangeDialogProps = {
  fromCurrency: string;
  toCurrency: string;
  onConfirm: () => void;
  onCancel: () => void;
  confirmDisabled?: boolean;
};

/** Shown before a company that already has invoices switches currency. */
export default function CurrencyChangeDialog({
  fromCurrency,
  toCurrency,
  onConfirm,
  onCancel,
  confirmDisabled,
}: CurrencyChangeDialogProps) {
  return (
    <ConfirmDialog
      title={`Change currency to ${toCurrency}?`}
      message={`Invoices you have already created will stay in ${fromCurrency}. Only new invoices will use ${toCurrency}. Their amounts are not converted.`}
      confirmText={`Change to ${toCurrency}`}
      cancelText="Keep current currency"
      onConfirm={onConfirm}
      onCancel={onCancel}
      confirmDisabled={confirmDisabled}
    />
  );
}
