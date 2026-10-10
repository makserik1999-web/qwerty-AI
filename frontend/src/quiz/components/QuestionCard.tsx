/**
 * One question in the editor, edited where it stands.
 *
 * No edit mode and no dialog: the card IS the form. The answer marks are the
 * shapes the students will see, and pressing one is how the right answer is
 * chosen. Each wrong option has a line for why somebody would pick it - for
 * the teacher only, and what the results page quotes back when a third of
 * the class does.
 */
import { useLayoutEffect, useRef, useState } from 'react'
import { Badge, Icon, IconButton, Input, Menu, Skeleton } from '../../components/ui'
import type { MenuItem } from '../../components/ui'
import { useI18n } from '../../lib/i18n'
import { cx } from '../../lib/utils'
import { newId } from '../edit'
import { Glyph, letterOf } from '../glyphs'
import type { ProblemCode, QuizQuestion } from '../types'

export type CardAction = 'duplicate' | 'up' | 'down' | 'replace' | 'delete'

interface Props {
  question: QuizQuestion
  index: number
  total: number
  problems: ProblemCode[]
  busy: boolean
  flash: boolean
  dragging: boolean
  canDraft: boolean
  onChange: (question: QuizQuestion) => void
  onAction: (action: CardAction) => void
  onHandleDown: (event: React.PointerEvent<HTMLButtonElement>) => void
  onLeave: () => void
  cardRef: (element: HTMLElement | null) => void
}

/** A textarea that grows with what is typed into it. */
function GrowingText(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const ref = useRef<HTMLTextAreaElement>(null)
  useLayoutEffect(() => {
    const node = ref.current
    if (!node) return
    node.style.height = 'auto'
    node.style.height = `${node.scrollHeight + 2}px`
  }, [props.value])
  return <textarea ref={ref} rows={1} {...props} />
}

export function QuestionCard({
  question,
  index,
  total,
  problems,
  busy,
  flash,
  dragging,
  canDraft,
  onChange,
  onAction,
  onHandleDown,
  onLeave,
  cardRef,
}: Props) {
  const { t } = useI18n()
  const options = question.options ?? []
  const textId = `q-text-${question.id}`

  const set = (patch: Partial<QuizQuestion>) => onChange({ ...question, ...patch })

  const items: MenuItem[] = [
    { key: 'duplicate', label: t('quiz.edit.duplicate'), icon: 'copy', onSelect: () => onAction('duplicate') },
    ...(index > 0
      ? [{ key: 'up', label: t('quiz.edit.moveUp'), icon: 'arrowUp' as const, onSelect: () => onAction('up') }]
      : []),
    ...(index < total - 1
      ? [{ key: 'down', label: t('quiz.edit.moveDown'), icon: 'arrowDown' as const, onSelect: () => onAction('down') }]
      : []),
    ...(canDraft
      ? [{ key: 'replace', label: t('quiz.edit.replace'), icon: 'refresh' as const, onSelect: () => onAction('replace') }]
      : []),
    { key: 'delete', label: t('common.delete'), icon: 'trash', danger: true, onSelect: () => onAction('delete') },
  ]

  return (
    <li
      ref={cardRef}
      data-id={question.id}
      className={cx(
        'qe-card',
        problems.length > 0 && 'has-problem',
        dragging && 'is-dragging',
        flash && 'is-flash',
      )}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) onLeave()
      }}
    >
      <div className="qe-card__head">
        <button
          type="button"
          className="qe-handle"
          aria-label={t('quiz.edit.drag')}
          title={t('quiz.edit.drag')}
          onPointerDown={onHandleDown}
        >
          <svg width="14" height="18" viewBox="0 0 14 18" fill="currentColor" aria-hidden="true">
            {[3, 9, 15].map((y) => (
              <g key={y}>
                <circle cx="4" cy={y} r="1.6" />
                <circle cx="10" cy={y} r="1.6" />
              </g>
            ))}
          </svg>
        </button>
        <span className="qe-number">{index + 1}</span>
        <span className="qe-kind">
          {question.type === 'choice'
            ? options.length === 2
              ? t('quiz.edit.kindTwo')
              : t('quiz.edit.kindChoice')
            : t('quiz.edit.kindShort')}
        </span>
        <input
          className="qe-topic"
          value={question.topic}
          maxLength={80}
          placeholder={t('quiz.edit.topicPlaceholder')}
          aria-label={t('quiz.edit.topicLabel')}
          onChange={(event) => set({ topic: event.target.value })}
        />
        <span className="grow" />
        <Menu label={t('quiz.edit.actions', { n: index + 1 })} items={items} />
      </div>

      {busy ? (
        <div className="stack stack-sm" aria-busy="true">
          <Skeleton height="22px" width="80%" />
          <Skeleton height="40px" />
        </div>
      ) : (
        <>
          <label className="visually-hidden" htmlFor={textId}>
            {t('quiz.edit.textLabel', { n: index + 1 })}
          </label>
          <GrowingText
            id={textId}
            className="qe-text"
            value={question.text}
            maxLength={600}
            placeholder={t('quiz.edit.textPlaceholder')}
            onChange={(event) => set({ text: event.target.value })}
          />

          {question.type === 'choice' ? (
            <div
              className={cx(
                'qe-options',
                options.some((o) => o.text.length > 44) && 'qe-options--list',
              )}
            >
              {options.map((option, i) => {
                const correct = question.correct === option.id
                return (
                  <div key={option.id} className={cx('qe-option', correct && 'is-correct')}>
                    <div className="qe-option__row">
                      <button
                        type="button"
                        className={cx('qe-mark', `qz-tones-${i}`)}
                        aria-pressed={correct}
                        aria-label={t('quiz.edit.markRight', { letter: letterOf(i) })}
                        title={t('quiz.edit.markRight', { letter: letterOf(i) })}
                        onClick={() => set({ correct: option.id })}
                      >
                        <Glyph index={i} size={18} />
                        <span className="qe-mark__check" aria-hidden="true">
                          <Icon name="check" size={12} />
                        </span>
                      </button>
                      <GrowingText
                        className="qe-option__input"
                        value={option.text}
                        maxLength={200}
                        placeholder={t('quiz.edit.optionPlaceholder', { letter: letterOf(i) })}
                        aria-label={t('quiz.edit.optionLabel', { letter: letterOf(i) })}
                        onKeyDown={(event) => {
                          // One line per option: Enter is not a newline here.
                          if (event.key === 'Enter') event.preventDefault()
                        }}
                        onChange={(event) =>
                          set({
                            options: options.map((o) =>
                              o.id === option.id
                                ? { ...o, text: event.target.value.replace(/\n/g, ' ') }
                                : o,
                            ),
                          })
                        }
                      />
                      {options.length > 2 ? (
                        <IconButton
                          icon="close"
                          label={t('quiz.edit.removeOption', { letter: letterOf(i) })}
                          onClick={() =>
                            set({
                              options: options.filter((o) => o.id !== option.id),
                              correct: correct ? '' : question.correct,
                            })
                          }
                        />
                      ) : null}
                    </div>
                    {!correct ? (
                      <div className="qe-note">
                        <GrowingText
                          value={option.note}
                          maxLength={300}
                          placeholder={t('quiz.edit.notePlaceholder')}
                          aria-label={t('quiz.edit.noteLabel', { letter: letterOf(i) })}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter') event.preventDefault()
                          }}
                          onChange={(event) =>
                            set({
                              options: options.map((o) =>
                                o.id === option.id
                                  ? { ...o, note: event.target.value.replace(/\n/g, ' ') }
                                  : o,
                              ),
                            })
                          }
                        />
                      </div>
                    ) : null}
                  </div>
                )
              })}
              {options.length < 4 ? (
                <button
                  type="button"
                  className="qe-add-option"
                  onClick={() => set({ options: [...options, { id: newId('o'), text: '', note: '' }] })}
                >
                  <Icon name="plus" size={16} />
                  {t('quiz.edit.addOption')}
                </button>
              ) : null}
            </div>
          ) : (
            <div className="qe-short">
              <label>
                <span className="qe-label">{t('quiz.edit.answer')}</span>
                <Input
                  className="qe-answer"
                  value={question.answer ?? ''}
                  maxLength={60}
                  placeholder="600"
                  onChange={(event) => set({ answer: event.target.value })}
                />
              </label>
              <label>
                <span className="qe-label">{t('quiz.edit.unit')}</span>
                <Input
                  value={question.unit ?? ''}
                  maxLength={16}
                  placeholder={t('quiz.edit.unitPlaceholder')}
                  onChange={(event) => set({ unit: event.target.value })}
                />
              </label>
              <AcceptInput
                values={question.accept ?? []}
                onChange={(accept) => set({ accept })}
              />
            </div>
          )}

          <details className="qe-explain" open={Boolean(question.explanation) || undefined}>
            <summary>{t('quiz.edit.explanation')}</summary>
            <GrowingText
              className="textarea"
              value={question.explanation}
              maxLength={600}
              placeholder={t('quiz.edit.explanationPlaceholder')}
              aria-label={t('quiz.edit.explanation')}
              onChange={(event) => set({ explanation: event.target.value })}
            />
          </details>

          {problems.length ? (
            <div className="qe-problems">
              {problems.map((code) => (
                <Badge key={code} tone="warning">
                  {t(`quiz.problem.${code}`)}
                </Badge>
              ))}
            </div>
          ) : null}
        </>
      )}
    </li>
  )
}

/** Other ways to write the answer, as chips. Enter or comma adds one. */
function AcceptInput({ values, onChange }: { values: string[]; onChange: (values: string[]) => void }) {
  const { t } = useI18n()
  const [draft, setDraft] = useState('')

  function commit() {
    const value = draft.trim()
    if (value && !values.includes(value) && values.length < 8) onChange([...values, value])
    setDraft('')
  }

  return (
    <label>
      <span className="qe-label">{t('quiz.edit.accept')}</span>
      <span className="qe-accept">
        {values.map((value) => (
          <span key={value} className="qe-accept__tag">
            {value}
            <button
              type="button"
              aria-label={t('quiz.edit.removeAccept', { value })}
              onClick={(event) => {
                event.preventDefault()
                onChange(values.filter((v) => v !== value))
              }}
            >
              <Icon name="close" size={12} />
            </button>
          </span>
        ))}
        <input
          value={draft}
          maxLength={60}
          placeholder={values.length ? '' : t('quiz.edit.acceptPlaceholder')}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ',') {
              event.preventDefault()
              commit()
            } else if (event.key === 'Backspace' && !draft && values.length) {
              onChange(values.slice(0, -1))
            }
          }}
        />
      </span>
    </label>
  )
}
