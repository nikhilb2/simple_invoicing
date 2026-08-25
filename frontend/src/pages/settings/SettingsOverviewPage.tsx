import { ChevronRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import { visibleSettingsGroups } from '../../config/navigation';
import { useAuth } from '../../context/AuthContext';

/**
 * The /settings landing page.
 *
 * The sub-nav beside it lists the same destinations, so this exists for the
 * one thing a list of labels cannot do: say what each page is for. "SMTP" and
 * "API keys" are only obvious to someone who already knows where to go.
 */
export default function SettingsOverviewPage() {
  const { isAdmin, userEmail } = useAuth();
  const groups = visibleSettingsGroups(isAdmin);

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Settings</p>
          <h1 className="page-title">Settings</h1>
          <p className="section-copy">
            Everything you configure once and then forget about — signed in as {userEmail ?? 'this account'}
            {isAdmin ? ' with admin access' : ''}.
          </p>
        </div>
      </section>

      {groups.map((group) => (
        <section className="settings-overview__group" key={group.id}>
          <h2 className="nav-panel__title">{group.label}</h2>
          <div className="settings-overview__grid">
            {group.items.map((item) => {
              const Icon = item.icon;
              return (
                <Link to={item.to} key={item.to} className="settings-card">
                  <span className="settings-card__icon" aria-hidden="true">
                    <Icon size={18} />
                  </span>
                  <span className="settings-card__body">
                    <span className="settings-card__title">{item.label}</span>
                    <span className="settings-card__copy">{item.description}</span>
                  </span>
                  <ChevronRight size={16} className="settings-card__chevron" aria-hidden="true" />
                </Link>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
