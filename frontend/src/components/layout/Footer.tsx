import { Link } from 'react-router-dom'
import { useI18n } from '../../lib/i18n'
import { CONTACT } from '../../lib/mockData'
import { Logo } from './Logo'

export function Footer() {
  const { t } = useI18n()
  return (
    <footer className="footer">
      <div className="container footer__inner">
        <div className="stack stack-sm footer__brand">
          <Logo />
          <p className="caption">{t('app.tagline')}</p>
        </div>

        <nav className="footer__col" aria-label={t('landing.footer.product')}>
          <h2 className="footer__heading">{t('landing.footer.product')}</h2>
          <a href="#how">{t('landing.nav.how')}</a>
          <a href="#examples">{t('landing.nav.examples')}</a>
          <Link to="/signup">{t('common.signUp')}</Link>
        </nav>

        <nav className="footer__col" aria-label={t('landing.footer.company')}>
          <h2 className="footer__heading">{t('landing.footer.company')}</h2>
          <a href="#team">{t('landing.nav.about')}</a>
          <a href={CONTACT.phoneHref}>{CONTACT.phone}</a>
          <a href={CONTACT.emailHref}>{CONTACT.email}</a>
        </nav>

        <nav className="footer__col" aria-label={t('landing.footer.legal')}>
          <h2 className="footer__heading">{t('landing.footer.legal')}</h2>
          <a href="#privacy">{t('landing.footer.privacy')}</a>
          <a href="#terms">{t('landing.footer.terms')}</a>
        </nav>
      </div>
      <div className="container footer__bottom">
        <p className="caption">© 2026 Anyq. {t('landing.footer.rights')}</p>
      </div>
    </footer>
  )
}
