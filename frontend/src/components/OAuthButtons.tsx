import type { AuthProvider } from '../types/api';
import { oauthLoginUrl } from '../utils/authFlow';

type OAuthButtonsProps = {
  providers: AuthProvider[];
  next: string;
  /** Leads the "or" divider; the buttons sit above the email form. */
  label?: string;
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
          className="button button--ghost"
          href={oauthLoginUrl(provider.id, next)}
          data-testid={`oauth-${provider.id}`}
          style={{ textAlign: 'center', textDecoration: 'none' }}
        >
          {label} {provider.name}
        </a>
      ))}
      <p className="muted-text" style={{ textAlign: 'center', margin: 0 }}>or use your email</p>
    </div>
  );
}
