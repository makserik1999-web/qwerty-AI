import { useRef, useState } from 'react'
import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  Field,
  Icon,
  IconButton,
  Input,
  ProgressBar,
  Table,
  useToast,
} from '../components/ui'
import { useI18n } from '../lib/i18n'
import { buildSubmissions, useStore } from '../lib/store'
import type { Submission, UploadFile, UploadStatus } from '../lib/types'
import { cx, formatDateTime, sleep, uid } from '../lib/utils'

const DEMO_FILES = [
  { name: 'aisulu-sor3.pdf', sizeKb: 820 },
  { name: 'dinmukhammed-sor3.pdf', sizeKb: 910 },
  { name: 'madina-sor3.jpg', sizeKb: 1480 },
  { name: 'erasyl-sor3.pdf', sizeKb: 760 },
]

const STATUS_TONE: Record<UploadStatus, 'neutral' | 'info' | 'success' | 'error'> = {
  queued: 'neutral',
  uploading: 'info',
  processing: 'info',
  done: 'success',
  failed: 'error',
}

export function Check() {
  const { t, lang } = useI18n()
  const { toast } = useToast()
  const { submissions, setSubmissions, charge } = useStore()

  const [files, setFiles] = useState<UploadFile[]>([])
  const [dragging, setDragging] = useState(false)
  const [processing, setProcessing] = useState(false)
  const [selected, setSelected] = useState<Submission | null>(null)
  const [overrideValue, setOverrideValue] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  function addFiles(incoming: Array<{ name: string; sizeKb: number }>) {
    setFiles((prev) => [
      ...prev,
      ...incoming.map((file) => ({
        id: uid('file'),
        name: file.name,
        sizeKb: file.sizeKb,
        status: 'queued' as UploadStatus,
        progress: 0,
      })),
    ])
  }

  function onDrop(event: React.DragEvent) {
    event.preventDefault()
    setDragging(false)
    const dropped = Array.from(event.dataTransfer.files).map((file) => ({
      name: file.name,
      sizeKb: Math.max(1, Math.round(file.size / 1024)),
    }))
    addFiles(dropped.length > 0 ? dropped : DEMO_FILES)
  }

  function onPick(event: React.ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(event.target.files ?? []).map((file) => ({
      name: file.name,
      sizeKb: Math.max(1, Math.round(file.size / 1024)),
    }))
    if (picked.length > 0) addFiles(picked)
    event.target.value = ''
  }

  function patchFile(id: string, patch: Partial<UploadFile>) {
    setFiles((prev) =>
      prev.map((file) => (file.id === id ? { ...file, ...patch } : file)),
    )
  }

  async function process() {
    setProcessing(true)
    const pool = buildSubmissions(lang)
    const queue = files.filter((file) => file.status === 'queued')
    const graded: Submission[] = []

    for (let index = 0; index < queue.length; index += 1) {
      const file = queue[index]
      patchFile(file.id, { status: 'uploading', progress: 0 })
      for (const step of [35, 70, 100]) {
        await sleep(220)
        patchFile(file.id, { progress: step })
      }
      patchFile(file.id, { status: 'processing' })
      await sleep(700)

      // One file in every batch is deliberately unreadable, so the per-file
      // failure state is reachable in the prototype.
      const fails = index === 2
      if (fails) {
        patchFile(file.id, { status: 'failed', error: t('check.fileFailed') })
        continue
      }

      patchFile(file.id, { status: 'done', progress: 100 })
      const template = pool[index % pool.length]
      graded.push({
        ...template,
        id: uid('sub'),
        fileName: file.name,
        student: template.student,
        gradedAt: new Date().toISOString(),
      })
    }

    setSubmissions((prev) => [...graded, ...prev])
    if (graded.length > 0) charge('grading', graded.length, t('check.title'))
    setProcessing(false)
    toast(t('check.processed', { n: graded.length }))
  }

  function applyOverride() {
    if (!selected) return
    const next = Math.max(0, Math.min(selected.max, Number(overrideValue)))
    if (Number.isNaN(next)) return
    const updated: Submission = { ...selected, score: next, status: 'overridden' }
    setSubmissions((prev) =>
      prev.map((item) => (item.id === selected.id ? updated : item)),
    )
    setSelected(updated)
    toast(t('check.overrideSaved'))
  }

  const queued = files.filter((file) => file.status === 'queued').length

  return (
    <div className="page">
      <header className="page__header">
        <div className="page__heading">
          <h1 className="page__title">{t('check.title')}</h1>
          <p className="page__subtitle">{t('check.subtitle')}</p>
        </div>
        <Button
          icon="download"
          disabled={submissions.length === 0}
          onClick={() => toast(t('check.exportResults'))}
        >
          {t('check.exportResults')}
        </Button>
      </header>

      {/* Upload ------------------------------------------------------------- */}
      <section className="stack stack-md">
        <h2 className="visually-hidden">{t('check.dropTitle')}</h2>
        <div
          className={cx('dropzone', dragging && 'is-dragging')}
          onDragOver={(event) => {
            event.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <span className="dropzone__icon">
            <Icon name="upload" size={24} />
          </span>
          <p className="dropzone__title">{t('check.dropTitle')}</p>
          <p className="text-sm text-secondary">{t('check.dropBody')}</p>
          <div className="row row--actions">
            <Button icon="file" onClick={() => inputRef.current?.click()}>
              {t('check.browse')}
            </Button>
            <Button variant="ghost" onClick={() => addFiles(DEMO_FILES)}>
              {t('check.uploadDemo')}
            </Button>
          </div>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept=".pdf,.jpg,.jpeg,.png"
            className="visually-hidden"
            onChange={onPick}
            aria-label={t('check.browse')}
          />
        </div>

        {files.length > 0 ? (
          <Card elevation="flat" className="stack stack-md">
            <CardHeader
              level={3}
              title={t('check.queue')}
              actions={
                <Button
                  variant="primary"
                  icon="clipboard"
                  loading={processing}
                  disabled={queued === 0}
                  onClick={() => void process()}
                >
                  {t('check.process')}
                </Button>
              }
            />

            <ul className="file-list" aria-live="polite">
              {files.map((file) => (
                <li key={file.id} className="file-list__item">
                  <Icon name="file" size={18} />
                  <div className="file-list__body">
                    <span className="file-list__name">{file.name}</span>
                    <span className="caption">{file.sizeKb} KB</span>
                    {file.status === 'uploading' ? (
                      <ProgressBar value={file.progress} label={file.name} />
                    ) : null}
                    {file.error ? (
                      <span className="file-list__error">{file.error}</span>
                    ) : null}
                  </div>
                  <Badge tone={STATUS_TONE[file.status]}>
                    {t(`check.status.${file.status}`)}
                  </Badge>
                  {file.status === 'queued' ? (
                    <IconButton
                      icon="close"
                      label={t('check.removeFile', { name: file.name })}
                      onClick={() =>
                        setFiles((prev) => prev.filter((item) => item.id !== file.id))
                      }
                    />
                  ) : null}
                </li>
              ))}
            </ul>
          </Card>
        ) : null}
      </section>

      {/* Results ------------------------------------------------------------ */}
      {/* The detail column only claims space once a result is open. */}
      <section className={cx('check__results', selected && 'has-detail')}>
        <div className="stack stack-md">
          <h2 className="card__title">{t('check.results')}</h2>

          {files.length === 0 && submissions.length === 0 ? (
            <EmptyState
              icon="clipboard"
              title={t('check.emptyTitle')}
              body={t('check.emptyBody')}
            />
          ) : submissions.length === 0 ? (
            <EmptyState
              icon="search"
              title={t('check.noResultsTitle')}
              body={t('check.noResultsBody')}
            />
          ) : (
            <Table caption={t('check.results')}>
              <thead>
                <tr>
                  <th scope="col">{t('check.col.student')}</th>
                  <th scope="col" className="num">
                    {t('check.col.score')}
                  </th>
                  <th scope="col">{t('common.date')}</th>
                  <th scope="col">{t('common.status')}</th>
                  <th scope="col">
                    <span className="visually-hidden">{t('common.actions')}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {submissions.map((submission) => (
                  <tr
                    key={submission.id}
                    className={cx(
                      'is-clickable',
                      selected?.id === submission.id && 'is-selected',
                    )}
                  >
                    <th scope="row" className="table__rowhead">
                      {submission.student}
                    </th>
                    <td className="num">
                      {submission.score} / {submission.max}
                    </td>
                    <td>{formatDateTime(submission.gradedAt, lang)}</td>
                    <td>
                      <Badge
                        tone={submission.status === 'overridden' ? 'accent' : 'success'}
                      >
                        {submission.status === 'overridden'
                          ? t('check.overridden')
                          : t('check.status.done')}
                      </Badge>
                    </td>
                    <td>
                      <Button
                        size="sm"
                        onClick={() => {
                          setSelected(submission)
                          setOverrideValue(String(submission.score))
                        }}
                      >
                        {t('common.open')}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </div>

        {/* Detail panel ----------------------------------------------------- */}
        {selected ? (
          <Card as="section" elevation="raised" className="detail-panel">
            <div className="row row-between">
              <h3 className="card__title">
                {t('check.detailFor', { student: selected.student })}
              </h3>
              <IconButton
                icon="close"
                label={t('common.close')}
                onClick={() => setSelected(null)}
              />
            </div>

            <p className="detail-panel__score">
              {selected.score}
              <span className="detail-panel__max"> / {selected.max}</span>
            </p>
            <p className="caption">{selected.fileName}</p>

            <h4 className="detail-panel__subtitle">{t('check.breakdown')}</h4>
            <ul className="breakdown">
              {selected.breakdown.map((row) => (
                <li key={row.number} className="breakdown__item">
                  <div className="row row-between">
                    <span className="breakdown__q">
                      {t('check.question', { n: row.number })}
                    </span>
                    <Badge tone={row.awarded === row.max ? 'success' : 'warning'}>
                      {row.awarded} / {row.max}
                    </Badge>
                  </div>
                  <p className="text-sm text-secondary">{row.note}</p>
                </li>
              ))}
            </ul>

            <div className="detail-panel__override">
              <Field label={t('check.overrideLabel')}>
                {(props) => (
                  <Input
                    {...props}
                    type="number"
                    min={0}
                    max={selected.max}
                    value={overrideValue}
                    onChange={(event) => setOverrideValue(event.target.value)}
                  />
                )}
              </Field>
              <Button variant="primary" icon="check" onClick={applyOverride}>
                {t('check.overrideSave')}
              </Button>
            </div>

            {selected.status === 'overridden' ? (
              <Alert tone="info" live>
                {t('check.overridden')}
              </Alert>
            ) : null}
          </Card>
        ) : null}
      </section>
    </div>
  )
}
