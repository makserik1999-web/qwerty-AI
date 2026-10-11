/**
 * Referrals in the admin panel: who invited whom, whether it paid off, and
 * the hints of abuse - an invitee on the inviter's own device, many accounts
 * from one browser. Hints, not proof: a school's computer room is one network.
 */
import { useEffect, useState } from 'react'
import { Alert, Badge, Table } from '../components/ui'
import { ApiError } from '../lib/api'

interface Pair {
  inviter: string
  invitee: string
  joined: string | null
  paid: boolean
  rewarded_months: number
  capped: boolean
  same_device: boolean
  same_network: boolean
}

interface Crowd {
  kind: 'device' | 'network'
  fingerprint: string
  accounts: string[]
}

export function ReferralsSection() {
  const [data, setData] = useState<{ pairs: Pair[]; crowded: Crowd[] } | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    fetch('/api/admin/referrals', { credentials: 'include', headers: { Accept: 'application/json' } })
      .then(async (response) => {
        if (!response.ok) throw new ApiError(response.status, '')
        setData(await response.json())
      })
      .catch(() => setError('Не удалось загрузить рефералы.'))
  }, [])

  if (error) return <Alert tone="error">{error}</Alert>
  if (!data) return <p className="caption">Загрузка…</p>

  return (
    <div className="admin__stack">
      <h3 className="admin__subhead">Кто кого пригласил</h3>
      {data.pairs.length ? (
        <Table caption="Приглашения">
          <thead>
            <tr>
              <th>Пригласил</th>
              <th>Приглашённый</th>
              <th>Регистрация</th>
              <th>Оплата</th>
              <th>Подозрения</th>
            </tr>
          </thead>
          <tbody>
            {data.pairs.map((p) => (
              <tr key={`${p.inviter}-${p.invitee}`}>
                <td>{p.inviter}</td>
                <td>{p.invitee}</td>
                <td>{p.joined ? new Date(p.joined).toLocaleDateString('ru-RU') : '—'}</td>
                <td>
                  {p.paid ? (
                    <Badge tone="success">{p.capped ? 'оплатил, лимит наград' : `+${p.rewarded_months} мес.`}</Badge>
                  ) : (
                    '—'
                  )}
                </td>
                <td className="admin__roles">
                  {p.same_device ? <Badge tone="error">то же устройство</Badge> : null}
                  {p.same_network ? <Badge tone="warning">та же сеть</Badge> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      ) : (
        <p className="caption">Приглашений пока нет.</p>
      )}

      <h3 className="admin__subhead">Много аккаунтов с одного устройства или сети</h3>
      {data.crowded.length ? (
        <ul className="admin__events">
          {data.crowded.map((g) => (
            <li key={`${g.kind}-${g.fingerprint}`}>
              <Badge tone={g.kind === 'device' ? 'error' : 'warning'}>
                {g.kind === 'device' ? 'устройство' : 'сеть'} {g.fingerprint}
              </Badge>{' '}
              {g.accounts.length} аккаунтов: {g.accounts.join(', ')}
            </li>
          ))}
        </ul>
      ) : (
        <p className="caption">Ничего подозрительного.</p>
      )}
    </div>
  )
}
