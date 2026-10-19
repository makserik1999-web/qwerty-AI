import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useI18n } from '../../lib/i18n'
import { useStore } from '../../lib/store'
import type { StringKey } from '../../lib/strings'
import { Avatar, Icon, type IconName } from '../ui'
import { LanguageMenu } from './LanguageMenu'
import { Logo } from './Logo'
import { ThemeToggle } from './ThemeToggle'
import { ConsentGate } from '../auth/ConsentGate'
import { VerifyGate } from '../auth/VerifyGate'
import { VerifyBanner } from './VerifyBanner'

interface TabDef {
  to: string
  labelKey: StringKey
  icon: IconName
  /** A shorter label for the phone's tab bar, where "Сабақ жоспары" does not fit. */
  shortKey?: StringKey
}

/* A phone's tab bar holds this many; the rest move into the menu behind the
   avatar. Eight tabs and an avatar across 375 pixels was labels wrapping onto
   two lines and the last tab cut off at the edge. */
const BAR_TABS = 4

const STUDENT_TABS: TabDef[] = [
  { to: '/app/explain', labelKey: 'nav.explain', icon: 'sparkle' },
  { to: '/app/showcase', labelKey: 'nav.showcase', icon: 'video' },
  { to: '/app/library', labelKey: 'nav.library', icon: 'book' },
  // Leaves the shell: joining a quiz is the phone screen, full-bleed.
  { to: '/join', labelKey: 'nav.joinQuiz', icon: 'listCheck' },
  { to: '/app/settings', labelKey: 'nav.settings', icon: 'settings' },
]

const TEACHER_TABS: TabDef[] = [
  { to: '/app/explain', labelKey: 'nav.explain', icon: 'sparkle' },
  { to: '/app/generate', labelKey: 'nav.generate', icon: 'file' },
  { to: '/app/plan', labelKey: 'nav.plan', icon: 'clipboard', shortKey: 'nav.plan.short' },
  { to: '/app/quizzes', labelKey: 'nav.quizzes', icon: 'listCheck' },
  { to: '/app/showcase', labelKey: 'nav.showcase', icon: 'video' },
  { to: '/app/library', labelKey: 'nav.library', icon: 'book' },
  { to: '/app/billing', labelKey: 'nav.billing', icon: 'wallet' },
  { to: '/app/settings', labelKey: 'nav.settings', icon: 'settings' },
]

/**
 * Persistent chrome for every signed-in page: a sidebar on wide viewports that
 * becomes a bottom tab bar on narrow ones. On the bar, the first BAR_TABS tabs
 * stay and the rest are in the menu ("Тағы").
 */
export function AppShell() {
  const { t } = useI18n()
  const { user, signOut } = useStore()
  const navigate = useNavigate()
  const location = useLocation()
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
  // Nothing of the app until the address is confirmed, when that is required.
  if (user.verifyNeeded) return <VerifyGate />
  const tabs = user.role === 'teacher' ? TEACHER_TABS : STUDENT_TABS
  // Settings is in the menu already; the others are there only on a phone.
  const moved = tabs.slice(BAR_TABS).filter((tab) => tab.to !== '/app/settings')
  const onMovedTab = tabs.slice(BAR_TABS).some((tab) => location.pathname.startsWith(tab.to))

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
            {tabs.map((tab, index) => (
              <li key={tab.to} className={index >= BAR_TABS ? 'shell__nav-moved' : undefined}>
                <NavLink
                  to={tab.to}
                  className={({ isActive }) =>
                    ['shell__tab', isActive && 'is-active', tab.shortKey && 'has-short']
                      .filter(Boolean)
                      .join(' ')
                  }
                >
                  <Icon name={tab.icon} size={20} />
                  <span className="shell__tab-label">{t(tab.labelKey)}</span>
                  {tab.shortKey ? <span className="shell__tab-short">{t(tab.shortKey)}</span> : null}
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
            className={onMovedTab ? 'shell__user-button is-active' : 'shell__user-button'}
            aria-expanded={menuOpen}
            aria-haspopup="menu"
            onClick={() => setMenuOpen((open) => !open)}
          >
            <Avatar name={user.name} />
            <span className="shell__user-info">
              <span className="shell__user-name">{user.name}</span>
              <span className="shell__user-role">{t(`role.${user.role}`)}</span>
            </span>
            {/* Under the avatar on the phone's tab bar, where the tabs that
                did not fit are. */}
            <span className="shell__more-label">{t('nav.more')}</span>
            <Icon name="chevronDown" size={16} />
          </button>

          {menuOpen ? (
            <div className="shell__menu" role="menu">
              {moved.map((tab) => (
                <button
                  key={tab.to}
                  type="button"
                  role="menuitem"
                  className="shell__menu-item shell__menu-item--moved"
                  onClick={() => {
                    setMenuOpen(false)
                    navigate(tab.to)
                  }}
                >
                  <Icon name={tab.icon} size={18} />
                  {t(tab.labelKey)}
                </button>
              ))}
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
              {/* Shown to staff only. Showing it is all this decides: the
                  server refuses every admin request from anyone else. */}
              {user.staffRole ? (
                <button
                  type="button"
                  role="menuitem"
                  className="shell__menu-item"
                  onClick={() => {
                    setMenuOpen(false)
                    navigate('/admin')
                  }}
                >
                  <Icon name="sliders" size={18} />
                  {t('nav.admin')}
                </button>
              ) : null}
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
        <VerifyBanner />
        <ConsentGate />
        <Outlet />
      </main>
    </div>
  )
}
