import { LogOut, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { Link, NavLink } from 'react-router-dom';
import SidebarFYSwitcher from './SidebarFYSwitcher';
import { visibleNavGroups } from '../config/navigation';
import { useAuth } from '../context/AuthContext';
import { useSidebarStore } from '../store/useSidebarStore';

interface SidebarProps {
  isOpen?: boolean;
  onClose?: () => void;
}

export default function Sidebar({ isOpen = false, onClose }: SidebarProps) {
  const { isAdmin, userEmail, logout } = useAuth();
  const { collapsed, toggleCollapsed } = useSidebarStore();
  const groups = visibleNavGroups(isAdmin);

  // Escape-to-close lives in Layout, which owns the drawer state.

  return (
    <aside
      className={`sidebar${isOpen ? ' sidebar--open' : ''}`}
      {...(isOpen ? { role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Navigation drawer' } : {})}
    >
      <div className="sidebar__header">
        <button
          className="sidebar__close"
          onClick={onClose}
          aria-label="Close navigation"
        >
          ✕
        </button>
        <Link to="/" className="sidebar__brand" onClick={() => onClose?.()}>
          <span>⚡</span>
          <div>
            <span className="sidebar__brand-name">Simple Invoicing</span>
            <span className="sidebar__brand-tagline">Stock &amp; billing</span>
          </div>
        </Link>
        <button
          className="sidebar__collapse"
          onClick={toggleCollapsed}
          aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'}
          aria-expanded={!collapsed}
          aria-controls="sidebar-nav"
        >
          {collapsed ? <PanelLeftOpen size={18} aria-hidden="true" /> : <PanelLeftClose size={18} aria-hidden="true" />}
        </button>
      </div>

      <nav className="sidebar__nav" id="sidebar-nav" aria-label="Sidebar navigation">
        {groups.map((group) => (
          <div
            className="sidebar__group"
            key={group.id}
            role="group"
            {...(group.label ? { 'aria-labelledby': `nav-group-${group.id}` } : {})}
          >
            {group.label && (
              <p className="sidebar__group-label" id={`nav-group-${group.id}`}>
                {group.label}
              </p>
            )}
            {group.items.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    `sidebar__link${isActive ? ' sidebar__link--active' : ''}`
                  }
                  onClick={() => onClose?.()}
                  // Tooltip stands in for the label once the rail collapses.
                  title={item.label}
                >
                  <Icon size={18} aria-hidden="true" />
                  <span className="sidebar__link-label">{item.label}</span>
                </NavLink>
              );
            })}
          </div>
        ))}
      </nav>

      <SidebarFYSwitcher />

      <div className="sidebar__footer">
        <div className="sidebar__user">
          <div className="sidebar__user-avatar">
            {userEmail ? userEmail[0].toUpperCase() : 'U'}
          </div>
          <div className="sidebar__user-meta">
            <span className="sidebar__user-email">{userEmail ?? 'Active user'}</span>
            <span className="sidebar__user-role">{isAdmin ? 'Admin' : 'User'}</span>
          </div>
        </div>
        <button className="button button--ghost sidebar__logout" onClick={logout} title="Logout">
          <LogOut size={16} aria-hidden="true" />
          <span className="sidebar__link-label">Logout</span>
        </button>
      </div>
    </aside>
  );
}
