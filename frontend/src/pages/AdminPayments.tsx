/**
 * Payments in the admin panel. Check Kaspi for the code and the amount, then
 * confirm - that switches the plan on - or reject with a reason the teacher
 * will see. Refunds are recorded here too. Admin only.
 */
import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Alert, Badge, Button, Input, SegmentedControl, Table } from '../components/ui'
import * as adminApi from '../lib/admin'
import type { AdminPayment } from '../lib/admin'
import { ApiError } from '../lib/api'

const STATUS_LABEL: Record<string, string> = {
  submitted: 'на проверке',
  awaiting: 'ждёт оплаты',
  confirmed: 'подтверждён',
  rejected: 'отклонён',
  refunded: 'возврат',
  expired: 'истёк',
  cancelled: 'отменён',
}

const FILTERS = [
  { value: 'submitted', label: 'На проверке' },
  { value: 'awaiting', label: 'Ждут оплаты' },
  { value: 'confirmed', label: 'Подтверждённые' },
  { value: '', label: 'Все' },
]

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : '—'
}

export function PaymentsSection() {
  const [params] = useSearchParams()
  // ?code=AK-... - where the Telegram message about a payment points.
  const [code, setCode] = useState(() => params.get('code') ?? '')
  const [status, setStatus] = useState('submitted')
  const [items, setItems] = useState<AdminPayment[] | null>(null)
  const [revenue, setRevenue] = useState<Array<{ month: string; amount: number }>>([])
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<{ tone: 'success' | 'error'; text: string } | null>(null)

  const load = useCallback(async () => {
    try {
      const found = await adminApi.listPayments(status, code.trim())
      setItems(found.items)
      setRevenue(found.revenue)
    } catch (failure) {
      setMessage({ tone: 'error', text: failure instanceof ApiError ? failure.detail || `Ошибка ${failure.status}` : 'Ошибка' })
    }
  }, [status, code])

  useEffect(() => {
    // Typing a code settles for a moment before it becomes a request.
    const timer = window.setTimeout(() => {
      setItems(null)
      void load()
    }, 250)
    return () => window.clearTimeout(timer)
  }, [load])

  async function act(id: string, label: string, action: () => Promise<unknown>) {
    setBusy(id)
    setMessage(null)
    try {
      await action()
      setMessage({ tone: 'success', text: label })
      setReason('')
      await load()
    } catch (failure) {
      const text =
        failure instanceof ApiError && failure.reason === 'reason_required'
          ? 'Укажите причину — её увидит учитель и журнал.'
          : failure instanceof ApiError
            ? failure.detail || `Ошибка ${failure.status}`
            : 'Ошибка'
      setMessage({ tone: 'error', text })
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="admin__stack">
      {revenue.length ? (
        <p className="caption">
          Выручка по месяцам:{' '}
          {revenue.map((r) => `${r.month} — ${r.amount.toLocaleString('ru-RU')} ₸`).join(' · ')}
        </p>
      ) : null}
      <div className="admin__toolbar">
        <label className="field">
          <span className="field__label">Код из комментария Kaspi</span>
          <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="AK-7KQ3M" />
        </label>
        {code.trim() ? null : (
          <SegmentedControl label="Статус" value={status} options={FILTERS} onChange={setStatus} />
        )}
        <label className="field admin__grow">
          <span className="field__label">Причина (для отклонения и возврата обязательна)</span>
          <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Например: перевод не найден" />
        </label>
      </div>
      {message ? <Alert tone={message.tone}>{message.text}</Alert> : null}
      {!items ? (
        <p className="caption">Загрузка…</p>
      ) : !items.length ? (
        <p className="caption">Платежей нет.</p>
      ) : (
        <Table caption="Платежи">
          <thead>
            <tr>
              <th>Код</th>
              <th>Аккаунт</th>
              <th>Тариф</th>
              <th className="num">Сумма</th>
              <th>Создан</th>
              <th>«Оплатил»</th>
              <th>Статус</th>
              <th>Действия</th>
            </tr>
          </thead>
          <tbody>
            {items.map((p) => (
              <tr key={p.id}>
                <td className="admin__code">{p.code}</td>
                <td>{p.email || p.user_id}</td>
                <td>{p.title}</td>
                <td className="num">{p.amount.toLocaleString('ru-RU')} ₸</td>
                <td>{when(p.created_at)}</td>
                <td>{when(p.submitted_at)}</td>
                <td>
                  <Badge tone={p.status === 'confirmed' ? 'success' : p.status === 'submitted' ? 'info' : 'neutral'}>
                    {STATUS_LABEL[p.status] ?? p.status}
                  </Badge>
                  {p.decided_by ? <div className="caption">{p.decided_by}</div> : null}
                  {p.reason ? <div className="caption">{p.reason}</div> : null}
                </td>
                <td>
                  <div className="admin__roles">
                    {p.status === 'submitted' || p.status === 'awaiting' ? (
                      <>
                        <Button
                          size="sm"
                          variant="primary"
                          loading={busy === p.id}
                          onClick={() => {
                            // The code and the sum, said back once: confirming the
                            // wrong row gives somebody a plan they did not pay for.
                            const amount = `${p.amount.toLocaleString('ru-RU')} ₸`
                            if (!window.confirm(`Подтвердить ${p.code} на ${amount} (${p.title})?\nПеревод с этим кодом пришёл в Kaspi?`)) return
                            void act(p.id, `Подтверждён ${p.code}: тариф включён`, () => adminApi.confirmPayment(p.id, reason))
                          }}
                        >
                          Подтвердить
                        </Button>
                        <Button
                          size="sm"
                          variant="quietDanger"
                          disabled={busy === p.id}
                          onClick={() => void act(p.id, `Отклонён ${p.code}`, () => adminApi.rejectPayment(p.id, reason))}
                        >
                          Отклонить
                        </Button>
                      </>
                    ) : null}
                    {p.status === 'confirmed' ? (
                      <Button
                        size="sm"
                        variant="quietDanger"
                        loading={busy === p.id}
                        onClick={() => void act(p.id, `Возврат ${p.code} записан`, () => adminApi.refundPayment(p.id, reason, true))}
                      >
                        Возврат
                      </Button>
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </div>
  )
}
