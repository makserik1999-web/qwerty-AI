import { Link } from 'react-router-dom'
import { Logo } from '../components/layout/Logo'
import { PRIVACY } from '../content/privacy'
import { useI18n } from '../lib/i18n'

/**
 * The privacy policy. Public: it is read before an account exists, and linked
 * from the sign-up form and the footer.
 *
 * Written in Kazakh and Russian. An English interface shows the Russian text
 * and says so, rather than an unchecked translation of a legal document.
 */
export function Privacy() {
  const { t, lang } = useI18n()
  const policy = PRIVACY[lang === 'kk' ? 'kk' : 'ru']

  return (
    <main className="legal" id="main">
      <div className="legal__inner">
        <header className="legal__head">
          <Logo />
          <Link to="/" className="text-sm">
            {t('privacy.back')}
          </Link>
        </header>
        <article className="legal__body">
          <h1 className="page__title">{policy.title}</h1>
          <p className="caption">{policy.updated}</p>
          {lang === 'en' ? <p className="text-sm text-secondary">{t('privacy.englishNote')}</p> : null}
          <p>{policy.intro}</p>
          {policy.sections.map((section) => (
            <section key={section.title} className="legal__section">
              <h2>{section.title}</h2>
              {section.paragraphs.map((paragraph) => (
                <p key={paragraph}>{paragraph}</p>
              ))}
              {section.items ? (
                <ul>
                  {section.items.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : null}
            </section>
          ))}
        </article>
      </div>
    </main>
  )
}
