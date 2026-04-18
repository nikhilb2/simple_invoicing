import { FormEvent, useState } from 'react';
import api, { getApiErrorMessage } from '../api/client';
import StatusToasts from '../components/StatusToasts';
import type { ChangePasswordRequest, ChangePasswordResponse } from '../types/api';

const MIN_PASSWORD_LENGTH = 8;

export default function ChangePasswordPage() {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState<string>();
  const [error, setError] = useState<string>();

  const checks = {
    length: newPassword.length >= MIN_PASSWORD_LENGTH,
    lower: /[a-z]/.test(newPassword),
    upper: /[A-Z]/.test(newPassword),
    numberOrSymbol: /[0-9\W_]/.test(newPassword),
  };

  const completedChecks = Object.values(checks).filter(Boolean).length;
  const strengthLabels = ['Very weak', 'Weak', 'Fair', 'Strong', 'Very strong'];
  const strengthClassByScore = [
    'change-password-strength__fill--very-weak',
    'change-password-strength__fill--weak',
    'change-password-strength__fill--fair',
    'change-password-strength__fill--strong',
    'change-password-strength__fill--very-strong',
  ];
  const strengthClass = strengthClassByScore[completedChecks];
  const strengthLabel = newPassword ? strengthLabels[completedChecks] : 'Not set';

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!currentPassword || !newPassword || !confirmPassword) {
      setError('All password fields are required');
      setSuccess(undefined);
      return;
    }

    if (newPassword.length < MIN_PASSWORD_LENGTH) {
      setError(`New password must be at least ${MIN_PASSWORD_LENGTH} characters long`);
      setSuccess(undefined);
      return;
    }

    if (newPassword !== confirmPassword) {
      setError('New password and confirm password must match');
      setSuccess(undefined);
      return;
    }

    if (currentPassword === newPassword) {
      setError('New password must be different from current password');
      setSuccess(undefined);
      return;
    }

    const payload: ChangePasswordRequest = {
      current_password: currentPassword,
      new_password: newPassword,
    };

    try {
      setSubmitting(true);
      setError(undefined);
      const response = await api.post<ChangePasswordResponse>('/auth/change-password', payload);
      setSuccess(response.data.detail || 'Password updated successfully');
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to update password'));
      setSuccess(undefined);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Settings</p>
          <h1 className="page-title">Change password</h1>
          <p className="section-copy">Keep your account secure with a stronger password and quick inline validation before saving.</p>
        </div>
      </section>

      <StatusToasts
        success={success}
        error={error}
        onClearSuccess={() => setSuccess(undefined)}
        onClearError={() => setError(undefined)}
      />

      <section className="content-grid">
        <article className="section-card change-password-card">
          <form className="stack" onSubmit={handleSubmit}>
            <div className="change-password-card__header">
              <div>
                <p className="change-password-card__eyebrow">Account security</p>
                <h2 className="change-password-card__title">Update your password</h2>
              </div>
              <span className="change-password-card__badge">Recommended every 90 days</span>
            </div>

            <div className="field-grid">
              <div className="field field--full">
                <label htmlFor="current-password">Current password</label>
                <div className="change-password-input-wrap">
                  <input
                    className="input"
                    id="current-password"
                    type={showCurrentPassword ? 'text' : 'password'}
                    value={currentPassword}
                    onChange={(event) => setCurrentPassword(event.target.value)}
                    autoComplete="current-password"
                    required
                  />
                  <button
                    className="button button--ghost button--small change-password-input-wrap__toggle"
                    type="button"
                    onClick={() => setShowCurrentPassword((value) => !value)}
                    aria-label={showCurrentPassword ? 'Hide current password' : 'Show current password'}
                  >
                    {showCurrentPassword ? 'Hide' : 'Show'}
                  </button>
                </div>
              </div>

              <div className="field field--full">
                <label htmlFor="new-password">New password</label>
                <div className="change-password-input-wrap">
                  <input
                    className="input"
                    id="new-password"
                    type={showNewPassword ? 'text' : 'password'}
                    value={newPassword}
                    onChange={(event) => setNewPassword(event.target.value)}
                    autoComplete="new-password"
                    minLength={MIN_PASSWORD_LENGTH}
                    required
                  />
                  <button
                    className="button button--ghost button--small change-password-input-wrap__toggle"
                    type="button"
                    onClick={() => setShowNewPassword((value) => !value)}
                    aria-label={showNewPassword ? 'Hide new password' : 'Show new password'}
                  >
                    {showNewPassword ? 'Hide' : 'Show'}
                  </button>
                </div>
                <div className="change-password-strength" aria-live="polite">
                  <div className="change-password-strength__bar" role="progressbar" aria-valuemin={0} aria-valuemax={4} aria-valuenow={completedChecks}>
                    <span className={`change-password-strength__fill ${strengthClass}`} style={{ width: `${(completedChecks / 4) * 100}%` }} />
                  </div>
                  <span className="change-password-strength__label">Strength: {strengthLabel}</span>
                </div>
                <small className="field-hint">Minimum {MIN_PASSWORD_LENGTH} characters.</small>
              </div>

              <div className="field field--full">
                <label htmlFor="confirm-password">Confirm new password</label>
                <div className="change-password-input-wrap">
                  <input
                    className="input"
                    id="confirm-password"
                    type={showConfirmPassword ? 'text' : 'password'}
                    value={confirmPassword}
                    onChange={(event) => setConfirmPassword(event.target.value)}
                    autoComplete="new-password"
                    minLength={MIN_PASSWORD_LENGTH}
                    required
                  />
                  <button
                    className="button button--ghost button--small change-password-input-wrap__toggle"
                    type="button"
                    onClick={() => setShowConfirmPassword((value) => !value)}
                    aria-label={showConfirmPassword ? 'Hide confirmation password' : 'Show confirmation password'}
                  >
                    {showConfirmPassword ? 'Hide' : 'Show'}
                  </button>
                </div>
              </div>
            </div>

            <div className="form-action-bar">
              <p className="form-action-bar__meta">After updating, use the new password on your next login.</p>
              <button className="button button--primary" type="submit" disabled={submitting}>
                {submitting ? 'Updating password...' : 'Update password'}
              </button>
            </div>
          </form>
        </article>

        <aside className="panel change-password-guide">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Password guide</p>
              <h3 className="change-password-guide__title">Security checklist</h3>
            </div>
          </div>

          <ul className="change-password-guide__list">
            <li className={checks.length ? 'is-pass' : ''}>At least {MIN_PASSWORD_LENGTH} characters</li>
            <li className={checks.lower ? 'is-pass' : ''}>Contains a lowercase letter</li>
            <li className={checks.upper ? 'is-pass' : ''}>Contains an uppercase letter</li>
            <li className={checks.numberOrSymbol ? 'is-pass' : ''}>Contains a number or symbol</li>
            <li className={newPassword && newPassword === confirmPassword ? 'is-pass' : ''}>Confirmation matches new password</li>
          </ul>

          <div className="change-password-guide__tip">
            <strong>Tip</strong>
            <p>A passphrase with 3+ uncommon words and separators is easier to remember and harder to guess.</p>
          </div>
        </aside>
      </section>
    </div>
  );
}
