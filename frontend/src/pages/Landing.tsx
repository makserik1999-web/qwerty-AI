import { AnimationPlayer, ScenePreview } from '../components/anim/AnimationPlayer'
import { SCENE_TITLES } from '../components/anim/scenes'
import { CompareSlider } from '../components/CompareSlider'
import { Footer } from '../components/layout/Footer'
import { PublicHeader } from '../components/layout/PublicHeader'
import { AnchorButton, Avatar, Badge, Card, Icon, LinkButton } from '../components/ui'
import { useInView } from '../lib/hooks'
import { useI18n } from '../lib/i18n'
import { CONTACT, LANDING_EXAMPLES, TEAM } from '../lib/mockData'
import type { StringKey } from '../lib/strings'
import { cx } from '../lib/utils'

const STEPS: Array<{
  key: string
  titleKey: StringKey
  bodyKey: StringKey
  icon: 'lightbulb' | 'book' | 'sparkle'
}> = [
  {
    key: 'ask',
    titleKey: 'landing.how.step1.title',
    bodyKey: 'landing.how.step1.body',
    icon: 'lightbulb',
  },
  {
    key: 'explain',
    titleKey: 'landing.how.step2.title',
    bodyKey: 'landing.how.step2.body',
    icon: 'book',
  },
  {
    key: 'animate',
    titleKey: 'landing.how.step3.title',
    bodyKey: 'landing.how.step3.body',
    icon: 'sparkle',
  },
]

function HowStep({
  index,
  titleKey,
  bodyKey,
  icon,
}: {
  index: number
  titleKey: StringKey
  bodyKey: StringKey
  icon: 'lightbulb' | 'book' | 'sparkle'
}) {
  const { t } = useI18n()
  const { ref, inView } = useInView<HTMLLIElement>()

  return (
    <li
      ref={ref}
      className={cx('how__step', inView && 'is-visible')}
      style={{ transitionDelay: `${index * 120}ms` }}
    >
      <span className="how__marker" aria-hidden="true">
        <Icon name={icon} size={22} />
      </span>
      <span className="how__index caption">{index + 1}</span>
      <h3 className="how__title">{t(titleKey)}</h3>
      <p className="text-secondary text-sm">{t(bodyKey)}</p>
    </li>
  )
}

export function Landing() {
  const { t, lang } = useI18n()

  return (
    <div className="landing">
      <PublicHeader />

      <main id="main">
        {/* Hero ------------------------------------------------------------ */}
        <section className="section hero">
          <div className="container hero__inner">
            <div className="hero__copy">
              <p className="eyebrow">{t('app.tagline')}</p>
              <h1>{t('landing.hero.title')}</h1>
              <p className="text-lg text-secondary measure">
                {t('landing.hero.subtitle')}
              </p>
              <div className="row row-wrap">
                <LinkButton
                  to="/signup"
                  variant="primary"
                  size="lg"
                  iconAfter="arrowRight"
                >
                  {t('landing.hero.cta')}
                </LinkButton>
                <AnchorButton href="#examples" variant="secondary" size="lg">
                  {t('landing.hero.secondary')}
                </AnchorButton>
              </div>
            </div>

            <div className="hero__media">
              <AnimationPlayer
                scene="pythagoras"
                duration={42}
                title={SCENE_TITLES.pythagoras}
                autoPlay
              />
              <p className="caption">{t('landing.hero.caption')}</p>
            </div>
          </div>
        </section>

        {/* Compare slider -------------------------------------------------- */}
        <section className="section section--surface" id="compare">
          <div className="container stack stack-lg">
            <header className="section__head">
              <h2>{t('landing.compare.title')}</h2>
              <p className="text-secondary measure">{t('landing.compare.subtitle')}</p>
            </header>
            <CompareSlider
              scene="pythagoras"
              sceneTitle={SCENE_TITLES.pythagoras}
              textTitle={t('landing.compare.textTitle')}
              textBody={t('landing.compare.textBody')}
            />
          </div>
        </section>

        {/* How it works ---------------------------------------------------- */}
        <section className="section" id="how">
          <div className="container stack stack-lg">
            <header className="section__head">
              <h2>{t('landing.how.title')}</h2>
            </header>
            <ol className="how">
              {STEPS.map((step, index) => (
                <HowStep
                  key={step.key}
                  index={index}
                  titleKey={step.titleKey}
                  bodyKey={step.bodyKey}
                  icon={step.icon}
                />
              ))}
            </ol>
          </div>
        </section>

        {/* Examples -------------------------------------------------------- */}
        <section className="section section--surface" id="examples">
          <div className="container stack stack-lg">
            <header className="section__head">
              <h2>{t('landing.examples.title')}</h2>
              <p className="text-secondary measure">{t('landing.examples.subtitle')}</p>
            </header>
            <ul className="example-grid">
              {LANDING_EXAMPLES.map((example) => (
                <li key={example.scene}>
                  <Card elevation="raised" plain className="example-card">
                    <ScenePreview
                      scene={example.scene}
                      title={SCENE_TITLES[example.scene]}
                    />
                    <div className="example-card__body">
                      <Badge tone="info">{t(`subject.${example.subject}`)}</Badge>
                      <h3 className="card__title mono example-card__title">
                        {SCENE_TITLES[example.scene]}
                      </h3>
                      <p className="caption">{t('landing.examples.play')}</p>
                    </div>
                  </Card>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* Why Kazakh ------------------------------------------------------ */}
        <section className="section" id="why">
          <div className="container why">
            <div className="stack stack-md">
              <h2>{t('landing.why.title')}</h2>
              <p className="text-secondary">{t('landing.why.body1')}</p>
              <p className="text-secondary">{t('landing.why.body2')}</p>
            </div>
            <dl className="why__stats">
              {[
                { label: 'landing.why.stat1', value: 'landing.why.stat1v' },
                { label: 'landing.why.stat2', value: 'landing.why.stat2v' },
                { label: 'landing.why.stat3', value: 'landing.why.stat3v' },
              ].map((stat) => (
                <div key={stat.label} className="why__stat">
                  <dt className="caption">{t(stat.label as StringKey)}</dt>
                  <dd className="why__stat-value">{t(stat.value as StringKey)}</dd>
                </div>
              ))}
            </dl>
          </div>
        </section>

        {/* Team ------------------------------------------------------------ */}
        <section className="section section--surface" id="team">
          <div className="container stack stack-lg">
            <header className="section__head">
              <h2>{t('landing.team.title')}</h2>
              <p className="text-secondary">{t('landing.team.subtitle')}</p>
            </header>
            <ul className="team-grid">
              {TEAM.map((person) => (
                <li key={person.name}>
                  <Card elevation="raised" className="team-card">
                    <Avatar name={person.name} size="lg" />
                    <div className="stack stack-sm">
                      <div className="row team-card__head">
                        <h3 className="card__title">{person.name}</h3>
                        <Badge tone="accent">{person.title}</Badge>
                      </div>
                      <p className="text-secondary text-sm">
                        {lang === 'kk'
                          ? person.roleKk
                          : lang === 'ru'
                            ? person.roleRu
                            : person.roleEn}
                      </p>
                    </div>
                  </Card>
                </li>
              ))}
            </ul>

            <Card elevation="flat" className="contact">
              <div className="stack stack-sm">
                <h3 className="card__title">{t('landing.contact.title')}</h3>
                <p className="text-secondary text-sm">{t('landing.contact.body')}</p>
              </div>
              <ul className="contact__list">
                <li>
                  <a className="contact__link" href={CONTACT.phoneHref}>
                    <Icon name="phone" size={18} />
                    <span className="stack">
                      <span className="caption">{t('landing.contact.phone')}</span>
                      <span className="contact__value">{CONTACT.phone}</span>
                    </span>
                  </a>
                </li>
                <li>
                  <a className="contact__link" href={CONTACT.emailHref}>
                    <Icon name="mail" size={18} />
                    <span className="stack">
                      <span className="caption">{t('landing.contact.email')}</span>
                      <span className="contact__value">{CONTACT.email}</span>
                    </span>
                  </a>
                </li>
              </ul>
            </Card>
          </div>
        </section>

        {/* Closing CTA ------------------------------------------------------ */}
        <section className="section">
          <div className="container">
            <Card elevation="floating" className="cta">
              <div className="stack stack-sm">
                <h2>{t('landing.cta.title')}</h2>
                <p className="text-secondary">{t('landing.cta.body')}</p>
              </div>
              <LinkButton to="/signup" variant="primary" size="lg" iconAfter="arrowRight">
                {t('common.signUp')}
              </LinkButton>
            </Card>
          </div>
        </section>
      </main>

      <Footer />
    </div>
  )
}
