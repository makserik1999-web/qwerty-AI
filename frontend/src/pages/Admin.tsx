/**
 * The admin panel: statistics, users, the audit log.
 *
 * In Russian only, and outside the kk/ru/en dictionary on purpose: it is used
 * by the two or three people who run the service, not by teachers.
 *
 * Loaded as its own chunk, so ordinary accounts never download it. That is
 * tidiness, not protection - the protection is on the server, where every
 * /api/admin request checks the staff role and answers 404 to anyone else.
 */
import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { Logo } from '../components/layout/Logo'
import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
  LinkButton,
  Modal,
  SearchInput,
  SegmentedControl,
  Spinner,
  Table,
  Tabs,
} from '../components/ui'
import * as adminApi from '../lib/admin'
import type {
  AdminUser,
  AdminUserDetail,
  AuditEntry,
  CacheStats,
  Stats,
  Usage,
  UsageEntry,
} from '../lib/admin'
import { ApiError } from '../lib/api'
import { useStore } from '../lib/store'
import type { StaffRole } from '../lib/types'
import '../styles/admin.css'
import { PaymentsSection } from './AdminPayments'
import { ReferralsSection } from './AdminReferrals'
import { VideosSection } from './AdminVideos'
import { PLAN_LABEL, PlansSection, UserPlanPanel } from './AdminPlans'

type Section = 'stats' | 'users' | 'videos' | 'referrals' | 'payments' | 'plans' | 'audit'

const PAGE = 50

const ROLE_LABEL: Record<string, string> = { teacher: 'учитель', student: 'ученик' }
const STAFF_LABEL: Record<StaffRole, string> = { admin: 'admin', support: 'support' }

const KIND_LABEL: Record<UsageEntry['kind'], string> = {
  explanation: 'объяснение',
  assessment: 'БЖБ / ТЖБ',
  lesson_plan: 'поурочный план',
  quiz_draft: 'квиз (ИИ)',
}

const ACTION_LABEL: Record<string, string> = {
  'staff.grant': 'выдал роль',
  'staff.revoke': 'снял роль',
}

function formatPhone(phone: string | null): string {
  if (!phone) return '—'
  return phone.length === 11
    ? `+7 ${phone.slice(1, 4)} ${phone.slice(4, 7)} ${phone.slice(7, 9)} ${phone.slice(9)}`
    : phone
}

function formatDate(iso: string | null, withTime = true): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    ...(withTime ? { hour: '2-digit', minute: '2-digit' } : {}),
  })
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 0) return 'Сервер не отвечает. Проверьте соединение.'
    if (error.status === 403) return 'Этот раздел только для роли admin.'
    return error.detail || `Ошибка ${error.status}`
  }
  return 'Что-то пошло не так.'
}

export function Admin() {
  const { user } = useStore()
  const [section, setSection] = useState<Section>('stats')

  // Not staff: the same thing as an address that does not exist.
  if (!user?.staffRole) return <Navigate to="/" replace />
  const isAdmin = user.staffRole === 'admin'

  const sections: Array<{ value: Section; label: string }> = [
    { value: 'stats', label: 'Статистика' },
    { value: 'users', label: 'Пользователи' },
    { value: 'videos', label: 'Библиотека' },
    { value: 'referrals', label: 'Рефералы' },
    ...(isAdmin
      ? [
          { value: 'payments' as const, label: 'Платежи' },
          { value: 'plans' as const, label: 'Тарифы' },
          { value: 'audit' as const, label: 'Журнал' },
        ]
      : []),
  ]

  return (
    <div className="admin">
      <header className="admin__bar">
        <Logo to="/app/explain" />
        <span className="admin__title">Админка</span>
        <Badge tone={isAdmin ? 'accent' : 'info'}>{STAFF_LABEL[user.staffRole]}</Badge>
        <span className="admin__spacer" />
        <LinkButton to="/app/explain" variant="ghost" size="sm" icon="chevronLeft">
          В приложение
        </LinkButton>
      </header>

      <main className="page admin__page">
        <Tabs label="Разделы админки" value={section} items={sections} onChange={setSection}>
          {section === 'stats' ? <StatsSection isAdmin={isAdmin} /> : null}
          {section === 'users' ? <UsersSection isAdmin={isAdmin} /> : null}
          {section === 'videos' ? <VideosSection /> : null}
          {section === 'referrals' ? <ReferralsSection /> : null}
          {section === 'payments' && isAdmin ? <PaymentsSection /> : null}
          {section === 'plans' && isAdmin ? <PlansSection /> : null}
          {section === 'audit' && isAdmin ? <AuditSection /> : null}
        </Tabs>
      </main>
    </div>
  )
}

/* Statistics ----------------------------------------------------------------- */

const DAY_OPTIONS = [
  { value: '7', label: '7 дней' },
  { value: '14', label: '14 дней' },
  { value: '30', label: '30 дней' },
]

function StatsSection({ isAdmin }: { isAdmin: boolean }) {
  const [days, setDays] = useState('14')
  const [stats, setStats] = useState<Stats | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setError('')
    adminApi
      .getStats(Number(days))
      .then((found) => {
        if (!cancelled) setStats(found)
      })
      .catch((e) => {
        if (!cancelled) setError(errorText(e))
      })
    return () => {
      cancelled = true
    }
  }, [days])

  if (error) return <Alert tone="error">{error}</Alert>
  if (!stats) return <Loading />

  const rows = [...stats.days].reverse()
  const sum = (key: keyof Usage | 'signups') =>
    stats.days.reduce((total, day) => total + day[key], 0)

  return (
    <div className="admin__stack">
      <div className="admin__cards">
        <Figure label="Аккаунтов" value={stats.totals.users} />
        <Figure label="Учителей" value={stats.totals.teachers} />
        <Figure label={`Регистраций за ${days} дн.`} value={sum('signups')} />
        <Figure label={`Видео за ${days} дн.`} value={sum('videos')} />
        <Card className="admin__figure">
          <span className="caption">Агент</span>
          <span className="admin__figure-value">
            {stats.agent.connected ? (
              <Badge tone="success">на связи</Badge>
            ) : (
              <Badge tone="error">не подключён</Badge>
            )}
          </span>
          <span className="caption">в очереди: {stats.agent.queue}</span>
        </Card>
      </div>

      <div className="admin__toolbar">
        <SegmentedControl label="Период" value={days} options={DAY_OPTIONS} onChange={setDays} />
        <span className="caption">
          {stats.usage_logged_since
            ? `Генерации считаются с ${formatDate(stats.usage_logged_since, false)}. Дни — по UTC+${stats.utc_offset_hours}.`
            : 'Генераций пока не было: счётчик заработал с этого обновления.'}
        </span>
      </div>

      <Table caption="Статистика по дням">
        <thead>
          <tr>
            <th>Дата</th>
            <th className="num">Регистрации</th>
            <th className="num">Объяснения</th>
            <th className="num">из них видео</th>
            <th className="num">Из библиотеки</th>
            <th className="num">Ошибки</th>
            <th className="num">БЖБ/ТЖБ</th>
            <th className="num">Планы</th>
            <th className="num">Квизы ИИ</th>
            <th className="num">Квизы</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((day) => (
            <tr key={day.date}>
              <td>{formatDate(`${day.date}T12:00:00Z`, false)}</td>
              <td className="num">{day.signups}</td>
              <td className="num">{day.explanations}</td>
              <td className="num">{day.videos}</td>
              <td className="num">{day.from_library}</td>
              <td className="num">{day.failed ? <span className="admin__bad">{day.failed}</span> : 0}</td>
              <td className="num">{day.assessments}</td>
              <td className="num">{day.lesson_plans}</td>
              <td className="num">{day.quiz_drafts}</td>
              <td className="num">{day.quizzes}</td>
            </tr>
          ))}
        </tbody>
      </Table>

      {isAdmin ? <CacheSection /> : null}
    </div>
  )
}

function Figure({ label, value }: { label: string; value: number }) {
  return (
    <Card className="admin__figure">
      <span className="caption">{label}</span>
      <span className="admin__figure-value">{value.toLocaleString('ru-RU')}</span>
    </Card>
  )
}

function CacheSection() {
  const [cache, setCache] = useState<CacheStats | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    adminApi.getCacheStats().then(setCache).catch((e) => setError(errorText(e)))
  }, [])

  if (error) return <Alert tone="error">{error}</Alert>
  if (!cache) return <Loading />

  return (
    <Card as="section" className="admin__stack">
      <CardHeader
        title="Кэш ответов"
        subtitle={`Записей: ${cache.entries_total} · вопросов: ${cache.questions_seen} · повторялись: ${cache.questions_repeated}`}
        level={3}
      />
      {cache.top_questions.length ? (
        <Table caption="Самые частые вопросы">
          <thead>
            <tr>
              <th>Вопрос</th>
              <th className="num">Раз</th>
            </tr>
          </thead>
          <tbody>
            {cache.top_questions.map((q) => (
              <tr key={q.question}>
                <td>{q.question}</td>
                <td className="num">{q.hits}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      ) : (
        <p className="caption">Вопросов пока нет.</p>
      )}
    </Card>
  )
}

/* Users ---------------------------------------------------------------------- */

function UsersSection({ isAdmin }: { isAdmin: boolean }) {
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState('')
  const [skip, setSkip] = useState(0)
  const [page, setPage] = useState<{ total: number; items: AdminUser[] } | null>(null)
  const [error, setError] = useState('')
  const [openId, setOpenId] = useState<string | null>(null)

  // Typing settles for a moment before it becomes a request.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(query.trim())
      setSkip(0)
    }, 300)
    return () => window.clearTimeout(timer)
  }, [query])

  useEffect(() => {
    let cancelled = false
    setError('')
    adminApi
      .listUsers(search, skip, PAGE)
      .then((found) => {
        if (!cancelled) setPage(found)
      })
      .catch((e) => {
        if (!cancelled) setError(errorText(e))
      })
    return () => {
      cancelled = true
    }
  }, [search, skip])

  return (
    <div className="admin__stack">
      <div className="admin__toolbar">
        <SearchInput
          id="admin-user-search"
          label="Поиск пользователей"
          placeholder="Почта, имя, телефон или id"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className="admin__search"
        />
        {page ? <span className="caption">Найдено: {page.total}</span> : null}
      </div>

      {error ? <Alert tone="error">{error}</Alert> : null}
      {!page && !error ? <Loading /> : null}

      {page ? (
        <Table caption="Пользователи">
          <thead>
            <tr>
              <th>Почта</th>
              <th>Имя</th>
              <th>Телефон</th>
              <th>Роль</th>
              <th>Тариф</th>
              <th>Создан</th>
              <th className="num">Видео</th>
              <th className="num">Из библ.</th>
              <th className="num">БЖБ</th>
              <th className="num">Планы</th>
              <th className="num">Квизы</th>
            </tr>
          </thead>
          <tbody>
            {page.items.map((row) => (
              <tr key={row.id}>
                <td>
                  <button type="button" className="admin__link" onClick={() => setOpenId(row.id)}>
                    {row.email || row.username}
                  </button>
                  {row.email && !row.email_verified ? (
                    <span className="caption"> · не подтверждена</span>
                  ) : null}
                </td>
                <td>{row.name}</td>
                <td>{row.phone_verified ? formatPhone(row.phone) : '—'}</td>
                <td>
                  <span className="admin__roles">
                    {ROLE_LABEL[row.role] ?? row.role}
                    {row.staff_role ? <Badge tone="accent">{row.staff_role}</Badge> : null}
                  </span>
                </td>
                <td>
                  <span className="admin__roles">
                    {PLAN_LABEL[row.plan] ?? row.plan}
                    {row.blocked ? <Badge tone="error">блок</Badge> : null}
                  </span>
                </td>
                <td>{formatDate(row.created_at, false)}</td>
                <td className="num">{row.usage.videos}</td>
                <td className="num">{row.usage.from_library}</td>
                <td className="num">{row.usage.assessments}</td>
                <td className="num">{row.usage.lesson_plans}</td>
                <td className="num">{row.usage.quizzes}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      ) : null}

      {page && page.total > PAGE ? (
        <div className="admin__pager">
          <Button size="sm" disabled={skip === 0} onClick={() => setSkip(Math.max(0, skip - PAGE))}>
            Назад
          </Button>
          <span className="caption">
            {skip + 1}–{Math.min(skip + PAGE, page.total)} из {page.total}
          </span>
          <Button size="sm" disabled={skip + PAGE >= page.total} onClick={() => setSkip(skip + PAGE)}>
            Дальше
          </Button>
        </div>
      ) : null}

      <UserModal id={openId} isAdmin={isAdmin} onClose={() => setOpenId(null)} />
    </div>
  )
}

function UserModal({
  id,
  isAdmin,
  onClose,
}: {
  id: string | null
  isAdmin: boolean
  onClose: () => void
}) {
  const [detail, setDetail] = useState<AdminUserDetail | null>(null)
  const [error, setError] = useState('')
  // Bumped after an action, to read the account again.
  const [version, setVersion] = useState(0)

  useEffect(() => {
    if (!id) return
    let cancelled = false
    setError('')
    adminApi
      .getUser(id)
      .then((found) => {
        if (!cancelled) setDetail(found)
      })
      .catch((e) => {
        if (!cancelled) setError(errorText(e))
      })
    return () => {
      cancelled = true
    }
  }, [id, version])

  useEffect(() => {
    setDetail(null)
  }, [id])

  return (
    <Modal
      open={Boolean(id)}
      title={detail ? detail.email || detail.username : 'Пользователь'}
      onClose={onClose}
      closeLabel="Закрыть"
      wide
    >
      {error ? <Alert tone="error">{error}</Alert> : null}
      {!detail && !error ? <Loading /> : null}
      {detail ? (
        <div className="admin__stack">
          <dl className="admin__facts">
            <dt>Имя</dt>
            <dd>{detail.name}</dd>
            <dt>Роль</dt>
            <dd>
              {ROLE_LABEL[detail.role] ?? detail.role}
              {detail.staff_role ? ` · ${detail.staff_role}` : ''}
            </dd>
            <dt>Почта</dt>
            <dd>
              {detail.email || '—'}
              {detail.email ? (detail.email_verified ? ' · подтверждена' : ' · не подтверждена') : ''}
            </dd>
            <dt>Телефон</dt>
            <dd>
              {formatPhone(detail.phone)}
              {detail.phone ? (detail.phone_verified ? ' · подтверждён' : ' · не подтверждён') : ''}
            </dd>
            <dt>Вход через Google</dt>
            <dd>{detail.google ? 'да' : 'нет'}</dd>
            <dt>Логин</dt>
            <dd>{detail.username}</dd>
            <dt>id</dt>
            <dd className="admin__mono">{detail.id}</dd>
            <dt>Создан</dt>
            <dd>{formatDate(detail.created_at)}</dd>
            <dt>Последний вход</dt>
            <dd>{formatDate(detail.last_sign_in)}</dd>
            <dt>Видео за сутки</dt>
            <dd>
              {detail.quota.used_day} из {detail.quota.limit_day} (за час {detail.quota.used_hour} из{' '}
              {detail.quota.limit_hour})
            </dd>
          </dl>

          <div className="admin__cards">
            <Figure label="Объяснений" value={detail.usage.explanations} />
            <Figure label="из них видео" value={detail.usage.videos} />
            <Figure label="Из библиотеки" value={detail.usage.from_library} />
            <Figure label="Ошибок" value={detail.usage.failed} />
            <Figure label="БЖБ/ТЖБ" value={detail.usage.assessments} />
            <Figure label="Планов" value={detail.usage.lesson_plans} />
            <Figure label="Квизов ИИ" value={detail.usage.quiz_drafts} />
            <Figure label="Квизов" value={detail.usage.quizzes} />
          </div>

          <UserPlanPanel detail={detail} isAdmin={isAdmin} onChanged={() => setVersion((v) => v + 1)} />

          <section className="admin__stack">
            <h3 className="admin__subhead">Последние действия</h3>
            {detail.recent.length ? (
              <ul className="admin__events">
                {detail.recent.map((entry, index) => (
                  <li key={`${entry.at}-${index}`}>
                    <span className="caption">{formatDate(entry.at)}</span>{' '}
                    {KIND_LABEL[entry.kind] ?? entry.kind}
                    {entry.kind === 'explanation' ? describeExplanation(entry) : ''}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="caption">Ничего пока не делал.</p>
            )}
          </section>
        </div>
      ) : null}
    </Modal>
  )
}

function describeExplanation(entry: UsageEntry): string {
  if (entry.cached) return ' — из библиотеки'
  if (!entry.ok) return ' — ошибка'
  return entry.video ? ' — с видео' : ' — текстом'
}

/* Audit ---------------------------------------------------------------------- */

function AuditSection() {
  const [items, setItems] = useState<AuditEntry[] | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    adminApi
      .getAudit()
      .then((found) => setItems(found.items))
      .catch((e) => setError(errorText(e)))
  }, [])

  if (error) return <Alert tone="error">{error}</Alert>
  if (!items) return <Loading />
  if (!items.length) return <p className="caption">Записей пока нет.</p>

  return (
    <Table caption="Журнал действий сотрудников">
      <thead>
        <tr>
          <th>Когда</th>
          <th>Кто</th>
          <th>Действие</th>
          <th>Кому</th>
          <th>Подробности</th>
          <th>Причина</th>
        </tr>
      </thead>
      <tbody>
        {items.map((entry) => (
          <tr key={entry.id}>
            <td>{formatDate(entry.at)}</td>
            <td>{entry.actor.kind === 'server' ? 'команда на сервере' : entry.actor.email}</td>
            <td>{ACTION_LABEL[entry.action] ?? entry.action}</td>
            <td>{entry.target.email || '—'}</td>
            <td className="admin__mono">{describeDetails(entry.details)}</td>
            <td>{entry.reason || '—'}</td>
          </tr>
        ))}
      </tbody>
    </Table>
  )
}

function describeDetails(details: Record<string, unknown>): string {
  const parts = Object.entries(details)
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .map(([key, value]) => `${key}: ${String(value)}`)
  return parts.length ? parts.join(', ') : '—'
}

function Loading() {
  return (
    <div className="admin__loading" role="status">
      <Spinner />
      <span className="caption">Загрузка…</span>
    </div>
  )
}
