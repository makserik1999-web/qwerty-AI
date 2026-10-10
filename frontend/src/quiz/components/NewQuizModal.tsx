/**
 * Starting a quiz: from a topic, written by the agent, or from nothing.
 *
 * Written from a topic is the default, because it is what saves the evening.
 * Either way the result is an ordinary quiz in the editor - nothing about a
 * written one is locked or special.
 */
import { useState } from 'react'
import {
  Button,
  Field,
  Input,
  Modal,
  SegmentedControl,
  Select,
  Skeleton,
  Stepper,
} from '../../components/ui'
import { useI18n } from '../../lib/i18n'
import { GRADES, SUBJECTS } from '../../lib/mockData'
import type { Lang, SubjectId } from '../../lib/types'
import { QuizError, createQuiz, draftQuestions } from '../api'
import { blankChoice } from '../edit'
import type { DraftInput, Quiz } from '../types'

type Mode = 'topic' | 'blank'

export function NewQuizModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: (quiz: Quiz) => void
}) {
  const { t, lang: uiLang } = useI18n()
  const [mode, setMode] = useState<Mode>('topic')
  const [topic, setTopic] = useState('')
  const [title, setTitle] = useState('')
  const [subject, setSubject] = useState<SubjectId>('physics')
  const [grade, setGrade] = useState(8)
  const [lang, setLang] = useState<Lang>(uiLang === 'ru' ? 'ru' : 'kk')
  const [count, setCount] = useState(8)
  const [mix, setMix] = useState<DraftInput['mix']>('mixed')
  const [difficulty, setDifficulty] = useState<DraftInput['difficulty']>('medium')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  function describe(failure: unknown): string {
    if (failure instanceof QuizError) {
      if (failure.status === 503) return t('quiz.new.errUnavailable')
      if (failure.status === 504) return t('quiz.new.errTimeout')
      if (failure.status === 429) return t('quiz.new.errLimit')
      if (failure.status === 0) return t('quiz.join.offline')
    }
    return t('quiz.new.errFailed')
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setError('')
    if (mode === 'topic' && !topic.trim()) {
      setError(t('quiz.new.topicNeeded'))
      return
    }
    setBusy(true)
    try {
      const questions =
        mode === 'topic'
          ? await draftQuestions({ subject, grade, topic: topic.trim(), lang, count, mix, difficulty })
          : [blankChoice()]
      const quiz = await createQuiz({
        title: (mode === 'topic' ? topic : title).trim() || t('quiz.new.untitled'),
        subject,
        grade,
        lang,
        topic: mode === 'topic' ? topic.trim() : '',
        questions,
      })
      onCreated(quiz)
    } catch (failure) {
      setError(describe(failure))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      title={t('quiz.new.title')}
      onClose={busy ? () => undefined : onClose}
      closeLabel={t('common.close')}
      wide
    >
      {busy && mode === 'topic' ? (
        <div className="stack stack-md" role="status" aria-live="polite">
          <p className="text-secondary">{t('quiz.new.writing', { n: count })}</p>
          <div className="ql-writing">
            {Array.from({ length: Math.min(count, 5) }, (_, i) => (
              <div key={i} className="ql-writing__card" style={{ '--i': i } as React.CSSProperties}>
                <span className={`ql-card__mark qz-tones-${i % 4}`} />
                <Skeleton height="14px" />
              </div>
            ))}
          </div>
          <p className="caption">{t('quiz.new.writingHint')}</p>
        </div>
      ) : (
        <form className="stack stack-md" onSubmit={submit}>
          <SegmentedControl
            label={t('quiz.new.title')}
            value={mode}
            onChange={setMode}
            options={[
              { value: 'topic', label: t('quiz.new.fromTopic') },
              { value: 'blank', label: t('quiz.new.blank') },
            ]}
          />

          {mode === 'topic' ? (
            <Field label={t('common.topic')} hint={t('quiz.new.topicHint')}>
              {(props) => (
                <Input
                  {...props}
                  value={topic}
                  autoFocus
                  maxLength={200}
                  placeholder={t('quiz.new.topicPlaceholder')}
                  onChange={(event) => setTopic(event.target.value)}
                />
              )}
            </Field>
          ) : (
            <Field label={t('quiz.new.name')}>
              {(props) => (
                <Input
                  {...props}
                  value={title}
                  autoFocus
                  maxLength={120}
                  placeholder={t('quiz.new.namePlaceholder')}
                  onChange={(event) => setTitle(event.target.value)}
                />
              )}
            </Field>
          )}

          <div className="row row-wrap" style={{ alignItems: 'flex-end' }}>
            <Field label={t('common.subject')} className="grow">
              {(props) => (
                <Select
                  {...props}
                  value={subject}
                  onChange={(event) => setSubject(event.target.value as SubjectId)}
                  options={SUBJECTS.map((item) => ({ value: item, label: t(`subject.${item}`) }))}
                />
              )}
            </Field>
            <Field label={t('common.grade')}>
              {(props) => (
                <Select
                  {...props}
                  value={String(grade)}
                  onChange={(event) => setGrade(Number(event.target.value))}
                  options={GRADES.map((item) => ({ value: String(item), label: String(item) }))}
                />
              )}
            </Field>
            <div className="field">
              <span className="field__label">{t('common.language')}</span>
              <SegmentedControl
                label={t('common.language')}
                value={lang}
                onChange={setLang}
                options={[
                  { value: 'kk', label: t('common.kazakh') },
                  { value: 'ru', label: t('common.russian') },
                ]}
              />
            </div>
          </div>

          {mode === 'topic' ? (
            <div className="row row-wrap" style={{ alignItems: 'flex-end' }}>
              <div className="field">
                <span className="field__label">{t('quiz.new.count')}</span>
                <Stepper
                  value={count}
                  min={3}
                  max={20}
                  onChange={setCount}
                  label={t('quiz.new.count')}
                  decreaseLabel="−1"
                  increaseLabel="+1"
                />
              </div>
              <div className="field">
                <span className="field__label">{t('quiz.new.mix')}</span>
                <SegmentedControl
                  label={t('quiz.new.mix')}
                  value={mix}
                  onChange={setMix}
                  options={[
                    { value: 'choice', label: t('quiz.new.mixChoice') },
                    { value: 'mixed', label: t('quiz.new.mixMixed') },
                    { value: 'short', label: t('quiz.new.mixShort') },
                  ]}
                />
              </div>
              <div className="field">
                <span className="field__label">{t('generate.difficulty')}</span>
                <SegmentedControl
                  label={t('generate.difficulty')}
                  value={difficulty}
                  onChange={setDifficulty}
                  options={[
                    { value: 'easy', label: t('generate.difficulty.easy') },
                    { value: 'medium', label: t('generate.difficulty.medium') },
                    { value: 'hard', label: t('generate.difficulty.hard') },
                  ]}
                />
              </div>
            </div>
          ) : null}

          {error ? (
            <p className="field__error" role="alert">
              {error}
            </p>
          ) : null}

          <div className="modal__footer">
            <Button onClick={onClose}>{t('common.cancel')}</Button>
            <Button type="submit" variant="primary" loading={busy}>
              {mode === 'topic' ? t('quiz.new.write') : t('quiz.new.create')}
            </Button>
          </div>
        </form>
      )}
    </Modal>
  )
}
