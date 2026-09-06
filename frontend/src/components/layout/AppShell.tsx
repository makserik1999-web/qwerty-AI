import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useI18n } from '../../lib/i18n'
import { useStore } from '../../lib/store'
import type { StringKey } from '../../lib/strings'
import { Avatar, Icon, type IconName } from '../ui'
import { LanguageMenu } from './LanguageMenu'
import { Logo } from './Logo'
import { ThemeToggle } from './ThemeToggle'

interface TabDef {
  to: string
  labelKey: StringKey
  icon: IconName
}

const STUDENT_TABS: TabDef[] = [
  { to: '/app/explain', labelKey: 'nav.explain', icon: 'sparkle' },
  { to: '/app/library', labelKey: 'nav.library', icon: 'book' },
  { to: '/app/settings', labelKey: 'nav.settings', icon: 'settings' },
]

const TEACHER_TABS: TabDef[] = [
  { to: '/app/explain', labelKey: 'nav.explain', icon: 'sparkle' },
  { to: '/app/generate', labelKey: 'nav.generate', icon: 'file' },
  { to: '/app/check', labelKey: 'nav.check', icon: 'clipboard' },
  { to: '/app/library', labelKey: 'nav.library', icon: 'book' },
  { to: '/app/billing', labelKey: 'nav.billing', icon: 'wallet' },
  { to: '/app/settings', labelKey: 'nav.settings', icon: 'settings' },
]

/**
 * Persistent chrome for every signed-in page: a sidebar on wide viewports that
 * becomes a bottom tab bar on narrow ones.
 */
export function AppShell() {
  const { t } = useI18n()
  const { user, signOut } = useStore()
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    function onPointerDown(event: PointerEvent) {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false)
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [menuOpen])

  if (!user) return null
  const tabs = user.role === 'teacher' ? TEACHER_TABS : STUDENT_TABS

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        {t('nav.explain')}
      </a>

      {/* A banner landmark: brand, primary navigation and the user menu. */}
      <header className="shell__sidebar">
        <div className="shell__brand">
          <Logo to="/app/explain" />
        </div>

        <nav className="shell__nav" aria-label={t('common.menu')}>
          <ul className="shell__nav-list">
            {tabs.map((tab) => (
              <li key={tab.to}>
                <NavLink
                  to={tab.to}
                  className={({ isActive }) =>
                    isActive ? 'shell__tab is-active' : 'shell__tab'
                  }
                >
                  <Icon name={tab.icon} size={20} />
                  <span>{t(tab.labelKey)}</span>
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        <div className="shell__controls">
          {/* Opens to the right: the sidebar sits against the left edge. */}
          <LanguageMenu side="top" align="start" />
          <ThemeToggle />
        </div>

        <div className="shell__user" ref={menuRef}>
          <button
            type="button"
            className="shell__user-button"
            aria-expanded={menuOpen}
            aria-haspopup="menu"
            onClick={() => setMenuOpen((open) => !open)}
          >
            <Avatar name={user.name} />
            <span className="shell__user-info">
              <span className="shell__user-name">{user.name}</span>
              <span className="shell__user-role">{t(`role.${user.role}`)}</span>
            </span>
            <Icon name="chevronDown" size={16} />
          </button>

          {menuOpen ? (
            <div className="shell__menu" role="menu">
              <button
                type="button"
                role="menuitem"
                className="shell__menu-item"
                onClick={() => {
                  setMenuOpen(false)
                  navigate('/app/settings')
                }}
              >
                <Icon name="settings" size={18} />
                {t('nav.settings')}
              </button>
              <button
                type="button"
                role="menuitem"
                className="shell__menu-item"
                onClick={() => {
                  setMenuOpen(false)
                  signOut()
                  navigate('/')
                }}
              >
                <Icon name="logOut" size={18} />
                {t('common.logOut')}
              </button>
            </div>
          ) : null}
        </div>
      </header>

      <main className="shell__main" id="main">
        <Outlet />
      </main>
    </div>
  )
}
