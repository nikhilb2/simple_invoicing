import { useEffect, useRef } from 'react';
import { ArrowLeft } from 'lucide-react';
import { NavLink, useLocation } from 'react-router-dom';
import { SETTINGS_ROOT, visibleSettingsGroups } from '../../config/navigation';
import { useAuth } from '../../context/AuthContext';

/**
 * The frame every /settings/* page renders inside.
 *
 * Settings used to be seven links in the main rail, competing for attention
 * with the pages people open every day. They are one rail entry now, and this
 * is what sits behind it: a sub-navigation that only exists while you are in
 * settings, so the depth costs nothing anywhere else in the app.
 *
 * The sub-nav collapses to a horizontally scrolling strip of chips under 900px
 * rather than stacking — a vertical list of nine links above the content would
 * push the actual settings off a phone screen.
 */
export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const { isAdmin } = useAuth();
  const groups = visibleSettingsGroups(isAdmin);
  const location = useLocation();
  const onOverview = location.pathname === SETTINGS_ROOT;
  const navRef = useRef<HTMLElement>(null);

  // Once the sub-nav is a horizontal strip, the chip you are on is often past
  // the right edge — /settings/api-keys opened with the strip still showing
  // "All settings · Company · Marketplace" and no sign of where you were. Only
  // runs when the strip actually overflows, so the vertical layout is untouched.
  useEffect(() => {
    const nav = navRef.current;
    if (!nav || nav.scrollWidth <= nav.clientWidth) return;
    nav.querySelector('.settings-nav__link--active, .settings-nav__back--active')
      ?.scrollIntoView({ inline: 'center', block: 'nearest' });
  }, [location.pathname]);

  return (
    <div className="settings-shell">
      <aside className="settings-nav" aria-label="Settings navigation" ref={navRef}>
        <NavLink
          to={SETTINGS_ROOT}
          end
          className={`settings-nav__back${onOverview ? ' settings-nav__back--active' : ''}`}
        >
          <ArrowLeft size={15} aria-hidden="true" />
          <span>All settings</span>
        </NavLink>

        {groups.map((group) => (
          <div className="settings-nav__group" key={group.id} role="group" aria-labelledby={`settings-group-${group.id}`}>
            <p className="settings-nav__group-label" id={`settings-group-${group.id}`}>
              {group.label}
            </p>
            {group.items.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    `settings-nav__link${isActive ? ' settings-nav__link--active' : ''}`
                  }
                >
                  <Icon size={16} aria-hidden="true" />
                  <span>{item.label}</span>
                </NavLink>
              );
            })}
          </div>
        ))}
      </aside>

      <div className="settings-shell__content">{children}</div>
    </div>
  );
}
