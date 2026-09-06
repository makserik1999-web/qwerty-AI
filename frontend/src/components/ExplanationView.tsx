import { useI18n } from '../lib/i18n'
import type { Explanation } from '../lib/types'
import { formatDate } from '../lib/utils'
import { AnimationPlayer } from './anim/AnimationPlayer'
import { SCENE_TITLES } from './anim/scenes'
import { Alert, Badge } from './ui'

interface ExplanationViewProps {
  explanation: Explanation
  /** Rendered under the animation, e.g. a save button. */
  actions?: React.ReactNode
  /** Shown when the animation could not be produced. */
  partialAction?: React.ReactNode
  headingLevel?: 2 | 3
  /** Freshly generated results start playing; saved ones wait for the user. */
  autoPlay?: boolean
}

/** Explanation text plus its animation. Shared by Explain and Library. */
export function ExplanationView({
  explanation,
  actions,
  partialAction,
  headingLevel = 2,
  autoPlay = false,
}: ExplanationViewProps) {
  const { t, lang } = useI18n()
  const Heading = `h${headingLevel}` as 'h2' | 'h3'
  const StepHeading = `h${(headingLevel + 1) as 3 | 4}` as 'h3' | 'h4'

  return (
    <article className="explanation">
      <header className="explanation__head">
        <Heading className="explanation__question">{explanation.question}</Heading>
        <div className="row row-wrap">
          <Badge tone="info">{t(`subject.${explanation.subject}`)}</Badge>
          <Badge tone="neutral">
            {explanation.lang === 'kk' ? t('common.kazakh') : t('common.russian')}
          </Badge>
          <span className="caption">{formatDate(explanation.createdAt, lang)}</span>
        </div>
      </header>

      {explanation.status === 'partial' ? (
        <Alert tone="warning" title={t('explain.partialTitle')} action={partialAction}>
          {t('explain.partialBody')}
        </Alert>
      ) : (
        <>
          <AnimationPlayer
            scene={explanation.scene}
            duration={explanation.duration}
            title={`${explanation.question} — ${SCENE_TITLES[explanation.scene]}`}
            autoPlay={autoPlay}
          />
          {actions ? <div className="row row-wrap">{actions}</div> : null}
        </>
      )}

      {explanation.status === 'partial' && actions ? (
        <div className="row row-wrap">{actions}</div>
      ) : null}

      <div className="prose">
        {explanation.blocks.map((block, index) => {
          if (block.kind === 'formula') {
            return (
              <p key={index} className="prose__formula mono">
                {block.text}
              </p>
            )
          }
          if (block.kind === 'step') {
            return (
              <section key={index} className="prose__step">
                <StepHeading className="prose__step-title">{block.title}</StepHeading>
                <p>{block.text}</p>
              </section>
            )
          }
          return <p key={index}>{block.text}</p>
        })}
      </div>
    </article>
  )
}
