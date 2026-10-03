/**
 * Results as a spreadsheet, made in the browser.
 *
 * Semicolons and a byte-order mark, because that is what opens correctly in
 * Excel on a Kazakh or Russian Windows - where the decimal separator is a
 * comma, a comma-separated file lands in one column, and without the BOM the
 * Cyrillic arrives as mojibake.
 */
import type { Translate } from '../lib/i18n'
import type { Results } from './types'

function cell(value: string | number | null | undefined): string {
  const text = value === null || value === undefined ? '' : String(value)
  // Quoted when it has to be; a leading = + - @ is defused so a name cannot
  // become a formula when the file is opened.
  const safe = /^[=+\-@]/.test(text) ? `'${text}` : text
  return /[";\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe
}

export function resultsCsv(results: Results, t: Translate): string {
  const questions = results.questions
  const header = [
    t('quiz.results.rank'),
    t('quiz.results.name'),
    t('quiz.results.score'),
    t('quiz.results.correct'),
    '%',
    t('quiz.results.timeSec'),
    ...questions.map((q) => `${q.index + 1}. ${q.text.slice(0, 40)}`),
  ]
  const rows = results.players.map((person) => [
    person.rank,
    person.name,
    person.score,
    `${person.correct}/${person.total}`,
    person.percent,
    person.durationSec === null ? '' : Math.round(person.durationSec),
    ...person.answers.map((a) =>
      a.correct === null ? '' : `${a.correct ? '✓' : '✗'} ${a.skipped ? '' : a.value}`.trim(),
    ),
  ])
  return [header, ...rows].map((row) => row.map(cell).join(';')).join('\r\n')
}

export function downloadCsv(results: Results, t: Translate): void {
  const blob = new Blob(['﻿' + resultsCsv(results, t)], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  const stamp = (results.session.startsAt ?? results.session.createdAt).slice(0, 10)
  const safeTitle = results.session.title.replace(/[\\/:*?"<>|]+/g, ' ').trim().slice(0, 60) || 'quiz'
  link.href = url
  link.download = `${safeTitle} ${stamp}.csv`
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
