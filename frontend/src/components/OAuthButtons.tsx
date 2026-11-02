import type { AuthProvider } from '../types/api';
import { oauthLoginUrl } from '../utils/authFlow';

type OAuthButtonsProps = {
  providers: AuthProvider[];
  next: string;
  /** Leads the "or" divider; the buttons sit above the email form. */
  label?: string;
};

// Keyed by provider id. Google's rules don't allow changing the colours of its "G" or
// drawing a different one: https://developers.google.com/identity/branding-guidelines
const PROVIDER_LOGOS: Record<string, string> = {
  google: '/google-g.svg',
};

/** One "Continue with …" button per enabled provider, then an "or" divider. */
export default function OAuthButtons({ providers, next, label = 'Continue with' }: OAuthButtonsProps) {
  if (providers.length === 0) {
    return null;
  }

  return (
    <div className="stack">
      {providers.map((provider) => (
        // A plain link: the browser must leave the SPA for the provider.
        <a
          key={provider.id}
          className={`button button--ghost oauth-button oauth-button--${provider.id}`}
          href={oauthLoginUrl(provider.id, next)}
          data-testid={`oauth-${provider.id}`}
          style={{ textAlign: 'center', textDecoration: 'none' }}
        >
          {PROVIDER_LOGOS[provider.id] ? (
            // Decorative: the label beside it already names the provider.
            <span className="oauth-button__logo">
              <img src={PROVIDER_LOGOS[provider.id]} alt="" width="18" height="18" />
            </span>
          ) : null}
          <span>{label} {provider.name}</span>
        </a>
      ))}
      <p className="muted-text" style={{ textAlign: 'center', margin: 0 }}>or use your email</p>
    </div>
  );
}
