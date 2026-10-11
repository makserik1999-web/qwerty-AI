/**
 * Running the service: generation tasks, the system's health, and metrics.
 *
 * Tasks and the system page are for any staff role - "my video never came"
 * starts here. Metrics include money and are the admin's; the server refuses
 * them to support whatever this page shows.
 */
import { useCallback, useEffect, useState } from 'react'
import { Alert, Badge, Button, Card, SegmentedControl, Table } from '../components/ui'
import * as adminApi from '../lib/admin'
import type { AdminJob, Metrics, SystemState } from '../lib/admin'
import { ApiError } from '../lib/api'

const KIND_LABEL: Record<string, string> = {
  video: 'видео',
  assessment: 'БЖБ/ТЖБ',
  lesson_plan: 'план урока',
  quiz_draft: 'квиз (ИИ)',
}

const STATUS_LABEL: Record<AdminJob['status'], string> = {
  queued: 'в очереди',
  running: 'идёт',
  done: 'готово',
  failed: 'ошибка',
}

const STATUS_TONE: Record<AdminJob['status'], 'info' | 'accent' | 'success' | 'error'> = {
  queued: 'info',
  running: 'accent',
  done: 'success',
  failed: 'error',
}

// What the error types mean, for the ones the backend names itself. The
// agent's own are exception class names and are shown as they are.
const ERROR_LABEL: Record<string, string> = {
  timeout: 'превышено время',
  agent_lost: 'агент отключился',
  agent_unavailable: 'агент недоступен',
  delivery: 'не дошло до агента',
  backend_restart: 'перезапуск сервера',
  bad_output: 'негодный ответ модели',
  agent_error: 'ошибка агента',
  internal: 'внутренняя ошибка',
  cancelled: 'отменено',
}

const WARNING_LABEL: Record<string, string> = {
  agent_offline: 'Агент не подключён — новые видео и документы не делаются.',
  heartbeat_stale: 'Агент давно не присылал статус — возможно, завис.',
  disk_low: 'Мало места на диске: меньше 10%.',
  queue_old: 'Запрос ждёт в очереди больше 15 минут.',
  failures_many: 'Много ошибок за сутки — посмотрите «Задачи».',
  database: 'База данных не отвечает.',
}

function when(iso: string | null): string {
  if (!iso) return '—'
  const date = new Date(iso)
  return Number.isNaN(date.getTime())
    ? '—'
    : date.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function ago(iso: string | null): string {
  if (!iso) return '—'
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000))
  if (seconds < 90) return `${seconds} с назад`
  if (seconds < 5400) return `${Math.round(seconds / 60)} мин назад`
  return `${Math.round(seconds / 3600)} ч назад`
}

function span(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—'
  if (seconds < 120) return `${Math.round(seconds)} с`
  if (seconds < 7200) return `${Math.round(seconds / 60)} мин`
  if (seconds < 172800) return `${Math.round(seconds / 3600)} ч`
  return `${Math.round(seconds / 86400)} дн`
}

function bytes(value: number | null | undefined): string {
  if (!value && value !== 0) return '—'
  const gb = value / 1024 ** 3
  return gb >= 1 ? `${gb.toFixed(1)} ГБ` : `${Math.round(value / 1024 ** 2)} МБ`
}

const tenge = (amount: number) => `${amount.toLocaleString('ru-RU')} ₸`

function failureText(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return 'Этот раздел только для роли admin.'
    if (error.reason === 'plan_required' || error.reason === 'plan_exhausted')
      return 'У учителя нет доступных видео или планов по тарифу.'
    if (error.reason === 'chat_gone') return 'Учитель удалил этот чат.'
    if (error.reason === 'owner_unavailable') return 'Аккаунт удалён, заблокирован или не учитель.'
    if (error.reason === 'agent_unavailable') return 'Агент не подключён.'
    if (error.reason === 'not_restartable') return 'Эту задачу уже перезапустили или её нельзя перезапустить.'
    if (error.detail) return error.detail
  }
  return fallback
}

/* Tasks ---------------------------------------------------------------------- */

const STATUS_FILTERS = [
  { value: 'open', label: 'Очередь' },
  { value: 'failed', label: 'Ошибки' },
  { value: 'done', label: 'Готовые' },
  { value: '', label: 'Все' },
]

const KIND_FILTERS = [
  { value: '', label: 'Всё' },
  { value: 'video', label: 'Видео' },
  { value: 'lesson_plan', label: 'Планы' },
  { value: 'assessment', label: 'БЖБ/ТЖБ' },
  { value: 'quiz_draft', label: 'Квизы' },
]

export function JobsSection() {
  const [status, setStatus] = useState('failed')
  const [kind, setKind] = useState('')
  const [silent, setSilent] = useState(false)
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Awaited<ReturnType<typeof adminApi.listJobs>> | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState<{ tone: 'success' | 'error'; text: string } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setData(await adminApi.listJobs({ status: silent ? '' : status, kind: silent ? 'video' : kind, silent, page }))
      setError('')
    } catch (e) {
      setError(failureText(e, 'Не удалось загрузить задачи.'))
    }
  }, [status, kind, silent, page])

  useEffect(() => {
    void load()
    // The queue moves on its own; the page follows it while it is open.
    const timer = window.setInterval(() => void load(), 15000)
    return () => window.clearInterval(timer)
  }, [load])

  async function restart(job: AdminJob) {
    const reason = window.prompt('Причина перезапуска (попадёт в журнал):', 'повтор после ошибки')
    if (reason === null) return
    setBusy(job.id)
    setNotice(null)
    try {
      await adminApi.restartJob(job.id, reason)
      setNotice({ tone: 'success', text: 'Перезапущено. Результат придёт учителю в тот же чат или в список планов.' })
      await load()
    } catch (e) {
      setNotice({ tone: 'error', text: failureText(e, 'Не удалось перезапустить.') })
    } finally {
      setBusy(null)
    }
  }

  const counts = data?.counts
  const pages = data ? Math.max(1, Math.ceil(data.total / 50)) : 1

  return (
    <div className="admin__stack">
      {counts ? (
        <div className="admin__cards">
          <Figure label="В очереди" value={counts.queued} />
          <Figure label="Выполняется" value={counts.running} />
          <Figure label="Ошибок за сутки" value={counts.failed_24h} bad={counts.failed_24h > 0} />
          <Figure label="Без звука за сутки" value={counts.silent_24h} bad={counts.silent_24h > 0} />
        </div>
      ) : null}

      <div className="admin__toolbar">
        {!silent ? (
          <>
            <SegmentedControl
              label="Статус"
              value={status}
              options={STATUS_FILTERS}
              onChange={(v) => {
                setStatus(v)
                setPage(1)
              }}
            />
            <SegmentedControl
              label="Тип"
              value={kind}
              options={KIND_FILTERS}
              onChange={(v) => {
                setKind(v)
                setPage(1)
              }}
            />
          </>
        ) : null}
        <label className="row">
          <input
            type="checkbox"
            checked={silent}
            onChange={(e) => {
              setSilent(e.target.checked)
              setPage(1)
            }}
          />
          <span className="text-sm">Только видео без звука (озвучка была заказана)</span>
        </label>
      </div>

      {notice ? <Alert tone={notice.tone}>{notice.text}</Alert> : null}
      {error ? <Alert tone="error">{error}</Alert> : null}
      {!data && !error ? <p className="caption">Загрузка…</p> : null}

      {data && !data.items.length ? <p className="caption">Пусто.</p> : null}
      {data && data.items.length ? (
        <Table caption="Задачи генерации">
          <thead>
            <tr>
              <th>Когда</th>
              <th>Что</th>
              <th>Учитель</th>
              <th>Статус</th>
              <th className="num">Время</th>
              <th>Подробности</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.items.map((job) => (
              <tr key={job.id}>
                <td>{when(job.created_at)}</td>
                <td>
                  {KIND_LABEL[job.kind] ?? job.kind}
                  {job.summary ? <div className="caption admin__clip">{job.summary}</div> : null}
                </td>
                <td>{job.email || (job.user_id === 'deleted' ? 'аккаунт удалён' : job.user_id)}</td>
                <td>
                  <Badge tone={STATUS_TONE[job.status]}>{STATUS_LABEL[job.status]}</Badge>
                  {job.error_type ? (
                    <div className="caption">{ERROR_LABEL[job.error_type] ?? job.error_type}</div>
                  ) : null}
                </td>
                <td className="num">{span(job.render_sec)}</td>
                <td>
                  <div className="admin__roles admin__wrap">
                    {job.kind === 'video' && job.status === 'done' ? (
                      job.video ? (
                        job.has_audio === false && job.narration ? (
                          <Badge tone="warning">без звука</Badge>
                        ) : (
                          <Badge tone="neutral">{job.duration ? `${Math.round(job.duration)} с` : 'видео'}</Badge>
                        )
                      ) : (
                        <Badge tone="neutral">только текст</Badge>
                      )
                    ) : null}
                    {job.effort ? <Badge tone="neutral">{job.effort}</Badge> : null}
                    {job.tts_chars ? <Badge tone="neutral">{job.tts_chars} симв.</Badge> : null}
                    {job.restart_of ? <Badge tone="info">повтор</Badge> : null}
                    {job.restarted_as ? <Badge tone="info">перезапущена</Badge> : null}
                  </div>
                </td>
                <td>
                  {job.restartable ? (
                    <Button size="sm" variant="secondary" loading={busy === job.id} onClick={() => void restart(job)}>
                      Перезапустить
                    </Button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      ) : null}

      {data && pages > 1 ? (
        <div className="admin__toolbar">
          <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            Назад
          </Button>
          <span className="caption">
            {page} / {pages}
          </span>
          <Button size="sm" variant="ghost" disabled={page >= pages} onClick={() => setPage(page + 1)}>
            Дальше
          </Button>
        </div>
      ) : null}
    </div>
  )
}

function Figure({ label, value, bad = false }: { label: string; value: string | number; bad?: boolean }) {
  return (
    <Card className="admin__figure">
      <span className="caption">{label}</span>
      <span className={bad ? 'admin__figure-value admin__bad' : 'admin__figure-value'}>
        {typeof value === 'number' ? value.toLocaleString('ru-RU') : value}
      </span>
    </Card>
  )
}

/* System --------------------------------------------------------------------- */

export function SystemSection() {
  const [state, setState] = useState<SystemState | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      setState(await adminApi.getSystem())
      setError('')
    } catch (e) {
      setError(failureText(e, 'Не удалось получить состояние системы.'))
    }
  }, [])

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), 10000)
    return () => window.clearInterval(timer)
  }, [load])

  if (error) return <Alert tone="error">{error}</Alert>
  if (!state) return <p className="caption">Загрузка…</p>

  const beat = state.agent.heartbeat
  const freeShare = state.disk.free_share

  return (
    <div className="admin__stack">
      {state.warnings.length ? (
        state.warnings.map((w) => (
          <Alert key={w} tone="warning">
            {WARNING_LABEL[w] ?? w}
          </Alert>
        ))
      ) : (
        <Alert tone="success">Всё в порядке.</Alert>
      )}

      <div className="admin__cards">
        <Card className="admin__figure">
          <span className="caption">Агент</span>
          <span className="admin__figure-value">
            {state.agent.connected ? <Badge tone="success">на связи</Badge> : <Badge tone="error">не подключён</Badge>}
          </span>
          <span className="caption">
            {state.agent.connected ? `с ${when(state.agent.connected_at)}` : `последний раз ${ago(state.agent.last_seen)}`}
          </span>
        </Card>
        <Card className="admin__figure">
          <span className="caption">Пульс агента</span>
          <span className="admin__figure-value">{beat ? ago(beat.at) : '—'}</span>
          <span className="caption">
            {beat
              ? `${beat.busy ? 'рендерит' : 'свободен'} · ждут: ${beat.queue ?? 0} · работает ${span(beat.uptime_sec)}`
              : 'агент старой версии или ещё не прислал'}
          </span>
        </Card>
        <Figure label="Видео в работе" value={state.queue.videos} />
        <Figure label="Документы в работе" value={state.queue.documents} />
        <Figure label="Самый старый запрос" value={span(state.queue.oldest_sec)} bad={state.queue.oldest_sec > 900} />
        <Figure label="Экспорты в очереди" value={state.queue.exports} />
        <Card className="admin__figure">
          <span className="caption">Диск (видео)</span>
          <span className={freeShare !== null && freeShare < 0.1 ? 'admin__figure-value admin__bad' : 'admin__figure-value'}>
            {bytes(state.disk.free)}
          </span>
          <span className="caption">
            свободно из {bytes(state.disk.total)}
            {freeShare !== null ? ` · ${Math.round(freeShare * 100)}%` : ''}
          </span>
        </Card>
        <Card className="admin__figure">
          <span className="caption">База данных</span>
          <span className="admin__figure-value">
            {state.database.ok ? <Badge tone="success">работает</Badge> : <Badge tone="error">не отвечает</Badge>}
          </span>
          <span className="caption">
            {state.database.storage_bytes !== undefined ? `на диске ${bytes(state.database.storage_bytes)}` : ''}
          </span>
        </Card>
        <Figure label="Сервер работает" value={span(state.backend.uptime_sec)} />
      </div>
    </div>
  )
}

/* Metrics -------------------------------------------------------------------- */

const DAY_OPTIONS = [
  { value: '7', label: '7 дней' },
  { value: '30', label: '30 дней' },
  { value: '90', label: '90 дней' },
]

export function MetricsSection() {
  const [days, setDays] = useState('30')
  const [data, setData] = useState<Metrics | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setData(null)
    adminApi
      .getMetrics(Number(days))
      .then((found) => {
        if (!cancelled) setData(found)
      })
      .catch((e) => {
        if (!cancelled) setError(failureText(e, 'Не удалось загрузить метрики.'))
      })
    return () => {
      cancelled = true
    }
  }, [days])

  if (error) return <Alert tone="error">{error}</Alert>
  if (!data) return <p className="caption">Загрузка…</p>

  const f = data.funnel
  const steps: Array<[string, number]> = [
    ['Зарегистрировались', f.registered],
    ['Подтвердили телефон', f.phone_confirmed],
    ['Начали сынақ', f.trial_started],
    ['Что-то сделали на сынақ', f.trial_used],
    ['Израсходовали сынақ', f.trial_spent],
    ['Оплатили', f.paid],
  ]
  const azureShare = data.azure.limit ? data.azure.chars / data.azure.limit : 0
  const projectedShare = data.azure.limit ? data.azure.projected / data.azure.limit : 0
  const renders = [...data.renders].reverse()

  return (
    <div className="admin__stack">
      <div className="admin__toolbar">
        <SegmentedControl label="Период" value={days} options={DAY_OPTIONS} onChange={setDays} />
        <span className="caption">Воронка — учителя, зарегистрированные за период. Дни — по UTC+{data.utc_offset_hours}.</span>
      </div>

      <div className="admin__cards">
        <Figure label="Активных учителей за день" value={data.active_teachers.day} />
        <Figure label="за неделю" value={data.active_teachers.week} />
        <Figure label="за 30 дней" value={data.active_teachers.month} />
        <Card className="admin__figure">
          <span className="caption">Azure TTS, {data.azure.month}</span>
          <span className={projectedShare > 1 ? 'admin__figure-value admin__bad' : 'admin__figure-value'}>
            {Math.round(azureShare * 100)}%
          </span>
          <span className="caption">
            {data.azure.chars.toLocaleString('ru-RU')} из {data.azure.limit.toLocaleString('ru-RU')} симв. · к концу месяца ≈{' '}
            {Math.round(projectedShare * 100)}%
          </span>
        </Card>
      </div>

      <Table caption="Воронка">
        <thead>
          <tr>
            <th>Шаг</th>
            <th className="num">Учителей</th>
            <th className="num">От регистраций</th>
          </tr>
        </thead>
        <tbody>
          {steps.map(([label, value]) => (
            <tr key={label}>
              <td>{label}</td>
              <td className="num">{value}</td>
              <td className="num">{f.registered ? `${Math.round((value / f.registered) * 100)}%` : '—'}</td>
            </tr>
          ))}
        </tbody>
      </Table>

      <Table caption="Выручка по месяцам (подтверждённые платежи, за вычетом возвратов)">
        <thead>
          <tr>
            <th>Месяц</th>
            <th className="num">Сумма</th>
          </tr>
        </thead>
        <tbody>
          {data.revenue.length ? (
            data.revenue.map((row) => (
              <tr key={row.month}>
                <td>{row.month}</td>
                <td className="num">{tenge(row.amount)}</td>
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={2}>Платежей пока нет.</td>
            </tr>
          )}
        </tbody>
      </Table>

      <Table caption="Рендеры видео по дням">
        <thead>
          <tr>
            <th>Дата</th>
            <th className="num">Видео</th>
            <th className="num">Ошибки</th>
            <th className="num">Без звука</th>
            <th className="num">Среднее время</th>
          </tr>
        </thead>
        <tbody>
          {renders.length ? (
            renders.map((day) => (
              <tr key={day.date}>
                <td>{day.date}</td>
                <td className="num">{day.videos}</td>
                <td className="num">{day.failed ? <span className="admin__bad">{day.failed}</span> : 0}</td>
                <td className="num">{day.silent ? <span className="admin__bad">{day.silent}</span> : 0}</td>
                <td className="num">{span(day.avg_render_sec)}</td>
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={5}>Рендеров за период нет.</td>
            </tr>
          )}
        </tbody>
      </Table>

      {data.failures.length ? (
        <Table caption="Ошибки по типам">
          <thead>
            <tr>
              <th>Тип</th>
              <th className="num">Сколько</th>
            </tr>
          </thead>
          <tbody>
            {data.failures.map((row) => (
              <tr key={row.error_type}>
                <td>{ERROR_LABEL[row.error_type] ?? row.error_type}</td>
                <td className="num">{row.count}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      ) : null}
    </div>
  )
}
