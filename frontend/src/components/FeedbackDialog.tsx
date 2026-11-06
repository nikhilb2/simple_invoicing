import ConfirmDialog from './ConfirmDialog';

const ISSUES_URL = 'https://github.com/nikhilb2/simple-invoicing-free-gst-billing-software/issues';

export default function FeedbackDialog({ onClose }: { onClose: () => void }) {
  const openIssues = () => {
    window.open(ISSUES_URL, '_blank', 'noopener,noreferrer');
    onClose();
  };

  return (
    <ConfirmDialog
      title="Request a feature or report a bug"
      message={'We track these on GitHub. Please open a new issue there: click "New issue" and tell us what you need or what went wrong. You will need a free GitHub account.'}
      confirmText="Go to GitHub issues"
      cancelText="Not now"
      onConfirm={openIssues}
      onCancel={onClose}
    />
  );
}
