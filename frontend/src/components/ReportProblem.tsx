import { useState } from 'react'
import { ApiError, reportProblem, type ReportKind } from '../lib/api'
import { useI18n } from '../lib/i18n'
import { Alert, Button, Modal, Textarea, useToast } from './ui'

/**
 * "Something is wrong here" - a wrong answer, a broken formula, a video that
 * says nothing. Goes to the team with what it is about; the pilot's main
 * source of what to fix.
 */
export function ReportProblem({ kind, refId = '' }: { kind: ReportKind; refId?: string }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function send() {
    if (!text.trim()) return
    setBusy(true)
    setError(null)
    try {
      await reportProblem({ kind, ref_id: refId, text: text.trim(), page: window.location.pathname })
      setOpen(false)
      setText('')
      toast(t('report.thanks'))
    } catch (failure) {
      setError(failure instanceof ApiError && failure.status === 429 ? t('report.limit') : t('report.failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <Button variant="ghost" size="sm" icon="alert" onClick={() => setOpen(true)}>
        {t('report.button')}
      </Button>
      <Modal
        open={open}
        title={t('report.title')}
        description={t('report.description')}
        onClose={() => (busy ? undefined : setOpen(false))}
        closeLabel={t('common.close')}
        footer={
          <>
            <Button variant="ghost" disabled={busy} onClick={() => setOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button variant="primary" loading={busy} disabled={!text.trim()} onClick={() => void send()}>
              {t('report.send')}
            </Button>
          </>
        }
      >
        <div className="stack stack-sm">
          <Textarea
            aria-label={t('report.title')}
            rows={5}
            maxLength={1500}
            value={text}
            placeholder={t('report.placeholder')}
            onChange={(event) => setText(event.target.value)}
          />
          {error ? <Alert tone="error">{error}</Alert> : null}
        </div>
      </Modal>
    </>
  )
}
