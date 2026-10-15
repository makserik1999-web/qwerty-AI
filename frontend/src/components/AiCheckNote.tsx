import type { ReportKind } from '../lib/api'
import { useI18n } from '../lib/i18n'
import { ReportProblem } from './ReportProblem'
import { Icon } from './ui'

/**
 * "AI wrote this - check it before the lesson."
 *
 * Under every paper, plan and quiz the model wrote. A model states a wrong
 * answer as confidently as a right one, and the teacher is the one who puts
 * it in front of a class; the page says so where the document is, not in a
 * policy nobody reads. Hidden when printing: it is for the teacher, not the
 * students.
 */
export function AiCheckNote({ report }: { report?: { kind: ReportKind; refId?: string } }) {
  const { t } = useI18n()
  return (
    <div className="ai-check" role="note">
      <Icon name="alert" size={16} />
      <span className="ai-check__text">{t('ai.checkNote')}</span>
      {report ? <ReportProblem kind={report.kind} refId={report.refId} /> : null}
    </div>
  )
}
