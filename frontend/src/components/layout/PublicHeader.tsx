import { useI18n } from '../../lib/i18n'
import { LinkButton } from '../ui'
import { LanguageMenu } from './LanguageMenu'
import { Logo } from './Logo'
import { ThemeToggle } from './ThemeToggle'

/** Sticky header for the marketing page. */
export function PublicHeader() {
  const { t } = useI18n()
  return (
    <header className="public-header">
      <div className="container public-header__inner">
        <Logo />
        <nav className="public-header__nav" aria-label={t('common.menu')}>
          <a href="#how">{t('landing.nav.how')}</a>
          <a href="#examples">{t('landing.nav.examples')}</a>
          <a href="#team">{t('landing.nav.about')}</a>
        </nav>
        <div className="row row--actions">
          <LanguageMenu />
          <ThemeToggle />
          <span className="public-header__divider" aria-hidden="true" />
          <LinkButton
            to="/signin"
            variant="ghost"
            size="sm"
            className="public-header__signin"
          >
            {t('common.signIn')}
          </LinkButton>
          <LinkButton to="/signup" variant="primary" size="sm">
            {t('common.signUp')}
          </LinkButton>
        </div>
      </div>
    </header>
  )
}
