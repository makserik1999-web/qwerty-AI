import { useI18n } from '../lib/i18n'
import type { Explanation } from '../lib/types'
import { formatDate } from '../lib/utils'
import { AnimationPlayer } from './anim/AnimationPlayer'
import { SCENE_TITLES } from './anim/scenes'
import { MarkdownMessage } from './MarkdownMessage'
import { VideoPlayer } from './player/VideoPlayer'
import { Alert, Badge } from './ui'

interface ExplanationViewProps {
  explanation: Explanation
  /** Rendered under the animation, e.g. a save button. */
  actions?: React.ReactNode
  /** Shown when the animation could not be produced. */
  partialAction?: React.ReactNode
  /** Offered on a semantic cache hit, which answered a different wording. */
  askAgainAction?: React.ReactNode
  headingLevel?: 2 | 3
  /** Freshly generated results start playing; saved ones wait for the user. */
  autoPlay?: boolean
}

/** Explanation text plus its animation. Shared by Explain and Library. */
export function ExplanationView({
  explanation,
  actions,
  partialAction,
  askAgainAction,
  headingLevel = 2,
  autoPlay = false,
}: ExplanationViewProps) {
  const { t, lang } = useI18n()
  const Heading = `h${headingLevel}` as 'h2' | 'h3'
  const StepHeading = `h${(headingLevel + 1) as 3 | 4}` as 'h3' | 'h4'

  const hasVideo = Boolean(explanation.videoUrl)
  const hasScene = Boolean(explanation.scene)

  return (
    <article className="explanation">
      <header className="explanation__head">
        <Heading className="explanation__question">{explanation.question}</Heading>
        <div className="row row-wrap">
          <Badge tone="info">{t(`subject.${explanation.subject}`)}</Badge>
          <Badge tone="neutral">
            {explanation.lang === 'kk' ? t('common.kazakh') : t('common.russian')}
          </Badge>
          {explanation.fromCache ? (
            <Badge tone="success" title={t('explain.fromLibraryHint')}>
              {t('explain.fromLibrary')}
            </Badge>
          ) : null}
          <span className="caption">{formatDate(explanation.createdAt, lang)}</span>
        </div>
      </header>

      {/* A semantic hit answered a question somebody else asked, in different
          words. Saying which one is not a detail: without it the reader gets a
          confident answer to something they did not ask and has no way to tell.
          Shown for semantic matches only - an exact hit answered this wording. */}
      {explanation.cacheMatch === 'semantic' && explanation.matchedQuestion ? (
        <Alert tone="info" action={askAgainAction}>
          {t('explain.matchedQuestion', { question: explanation.matchedQuestion })}
        </Alert>
      ) : null}

      {explanation.status === 'partial' ? (
        <Alert tone="warning" title={t('explain.partialTitle')} action={partialAction}>
          {t('explain.partialBody')}
        </Alert>
      ) : (
        <>
          {hasVideo ? (
            <VideoPlayer
              src={explanation.videoUrl as string}
              title={explanation.question}
              autoPlay={autoPlay}
            />
          ) : hasScene ? (
            <AnimationPlayer
              scene={explanation.scene!}
              duration={explanation.duration ?? 0}
              title={`${explanation.question} — ${SCENE_TITLES[explanation.scene!]}`}
              autoPlay={autoPlay}
            />
          ) : null}
          {actions ? <div className="row row-wrap">{actions}</div> : null}
        </>
      )}

      {explanation.status === 'partial' && actions ? (
        <div className="row row-wrap">{actions}</div>
      ) : null}

      {/* A real answer is markdown with formulas in it; the seeded library
          entries are the older block shape. */}
      {explanation.markdown ? (
        <MarkdownMessage content={explanation.markdown} />
      ) : (
        <div className="prose">
          {(explanation.blocks ?? []).map((block, index) => {
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
      )}
    </article>
  )
}