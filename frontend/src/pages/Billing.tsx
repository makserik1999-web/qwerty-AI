import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  Field,
  Icon,
  Input,
  Modal,
  SegmentedControl,
  Skeleton,
  Table,
  useToast,
} from '../components/ui'
import { useI18n } from '../lib/i18n'
import { PRICES, USAGE_BREAKDOWN, USAGE_SERIES } from '../lib/mockData'
import { useStore, type BalanceState } from '../lib/store'
import type { Transaction } from '../lib/types'
import { formatDate, formatDateTime, formatMoney, sleep } from '../lib/utils'

type Period = 'month' | 'quarter' | 'year'

const LOW_THRESHOLD = 1000

/**
 * Bar chart of spending over the selected period. The same numbers are also
 * exposed as a table for screen readers, so no information is colour-only.
 */
function UsageChart({ values, label }: { values: number[]; label: string }) {
  const max = Math.max(...values, 1)
  const gap = 6
  const width = 640
  const height = 180
  const barWidth = (width - gap * (values.length - 1)) / values.length

  return (
    <div className="chart">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="chart__svg"
        role="img"
        aria-label={label}
        preserveAspectRatio="none"
      >
        {values.map((value, index) => {
          const barHeight = Math.max(2, (value / max) * (height - 16))
          return (
            <rect
              key={index}
              className={value === 0 ? 'chart__bar chart__bar--empty' : 'chart__bar'}
              x={index * (barWidth + gap)}
              y={height - barHeight}
              width={barWidth}
              height={barHeight}
              rx={3}
            />
          )
        })}
      </svg>
    </div>
  )
}

export function Billing() {
  const { t, lang } = useI18n()
  const { toast } = useToast()
  const { balance, transactions, topUp, setBalanceState } = useStore()

  const [loading, setLoading] = useState(true)
  const [period, setPeriod] = useState<Period>('month')
  const [topUpOpen, setTopUpOpen] = useState(false)
  const [amount, setAmount] = useState('10000')
  const [openTx, setOpenTx] = useState<Transaction | null>(null)

  useEffect(() => {
    let active = true
    void sleep(600).then(() => {
      if (active) setLoading(false)
    })
    return () => {
      active = false
    }
  }, [])

  const series = USAGE_SERIES[period]
  const spent = useMemo(() => series.reduce((sum, value) => sum + value, 0), [series])

  const state: BalanceState =
    balance <= 0 ? 'zero' : balance < LOW_THRESHOLD ? 'low' : 'healthy'

  return (
    <div className="page">
      <header className="page__header">
        <div className="page__heading">
          <h1 className="page__title">{t('billing.title')}</h1>
          <p className="page__subtitle">{t('billing.subtitle')}</p>
        </div>
      </header>

      <div className="demo-bar">
        <Icon name="sliders" size={16} />
        <span>{t('billing.demoState')}</span>
        <SegmentedControl
          label={t('billing.demoState')}
          value={state}
          onChange={setBalanceState}
          options={[
            { value: 'healthy', label: t('billing.state.healthy') },
            { value: 'low', label: t('billing.state.low') },
            { value: 'zero', label: t('billing.state.zero') },
          ]}
        />
      </div>

      {loading ? (
        <Card elevation="raised" className="stack stack-md">
          <Skeleton width="30%" height="14px" />
          <Skeleton width="45%" height="40px" />
          <Skeleton height="120px" radius="md" />
        </Card>
      ) : (
        <>
          {/* Balance ------------------------------------------------------- */}
          <Card as="section" elevation="raised" className="balance">
            <div className="stack stack-sm">
              <p className="caption">{t('billing.balance')}</p>
              <p className="balance__value">{formatMoney(balance, lang)}</p>
              <div className="row row-wrap">
                <Badge
                  tone={
                    state === 'zero' ? 'error' : state === 'low' ? 'warning' : 'success'
                  }
                >
                  {t(`billing.state.${state}`)}
                </Badge>
                <span className="caption">
                  {t('billing.spentTotal')}: {formatMoney(-spent, lang)}
                </span>
              </div>
            </div>
            <Button variant="primary" icon="plus" onClick={() => setTopUpOpen(true)}>
              {t('billing.topUp')}
            </Button>
          </Card>

          {state !== 'healthy' ? (
            <Alert
              tone={state === 'zero' ? 'info' : 'warning'}
              title={state === 'zero' ? t('billing.zeroTitle') : t('billing.lowTitle')}
              action={
                <Button variant="primary" size="sm" onClick={() => setTopUpOpen(true)}>
                  {t('billing.topUp')}
                </Button>
              }
            >
              {state === 'zero' ? t('billing.zeroBody') : t('billing.lowBody')}
            </Alert>
          ) : null}

          {/* Usage --------------------------------------------------------- */}
          <Card as="section" elevation="flat" className="stack stack-md">
            <CardHeader
              title={t('billing.usage')}
              actions={
                <SegmentedControl
                  label={t('billing.period')}
                  value={period}
                  onChange={setPeriod}
                  options={[
                    { value: 'month', label: t('billing.period.month') },
                    { value: 'quarter', label: t('billing.period.quarter') },
                    { value: 'year', label: t('billing.period.year') },
                  ]}
                />
              }
            />

            <UsageChart
              values={series}
              label={t('billing.chartLabel', { period: t(`billing.period.${period}`) })}
            />

            <dl className="usage-summary">
              <div>
                <dt>{t('billing.explanations')}</dt>
                <dd>{USAGE_BREAKDOWN.explanations}</dd>
              </div>
              <div>
                <dt>{t('billing.assessments')}</dt>
                <dd>{USAGE_BREAKDOWN.assessments}</dd>
              </div>
              <div>
                <dt>{t('billing.gradings')}</dt>
                <dd>{USAGE_BREAKDOWN.gradings}</dd>
              </div>
              <div>
                <dt>{t('billing.spentTotal')}</dt>
                <dd>{formatMoney(-spent, lang)}</dd>
              </div>
            </dl>
          </Card>

          {/* Prices -------------------------------------------------------- */}
          <section className="stack stack-md">
            <h2 className="card__title">{t('billing.prices')}</h2>
            <Table caption={t('billing.prices')}>
              <tbody>
                <tr>
                  <th scope="row">{t('billing.price.explanation')}</th>
                  <td className="num">{formatMoney(PRICES.explanation, lang)}</td>
                </tr>
                <tr>
                  <th scope="row">{t('billing.price.assessment')}</th>
                  <td className="num">{formatMoney(PRICES.assessment, lang)}</td>
                </tr>
                <tr>
                  <th scope="row">{t('billing.price.grading')}</th>
                  <td className="num">{formatMoney(PRICES.grading, lang)}</td>
                </tr>
              </tbody>
            </Table>
          </section>

          {/* History ------------------------------------------------------- */}
          <section className="stack stack-md">
            <div className="row row-between row-wrap">
              <h2 className="card__title">{t('billing.history')}</h2>
              <Button
                icon="download"
                disabled={transactions.length === 0}
                onClick={() => toast(t('billing.exportHistory'))}
              >
                {t('billing.exportHistory')}
              </Button>
            </div>

            {transactions.length === 0 ? (
              <EmptyState
                icon="wallet"
                title={t('billing.historyEmptyTitle')}
                body={t('billing.historyEmptyBody')}
              />
            ) : (
              <Table caption={t('billing.history')}>
                <thead>
                  <tr>
                    <th scope="col">{t('common.date')}</th>
                    <th scope="col">{t('billing.col.action')}</th>
                    <th scope="col" className="num">
                      {t('billing.col.qty')}
                    </th>
                    <th scope="col" className="num">
                      {t('billing.col.amount')}
                    </th>
                    <th scope="col">
                      <span className="visually-hidden">{t('common.actions')}</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {transactions.map((transaction) => (
                    <tr key={transaction.id}>
                      <td>{formatDate(transaction.date, lang)}</td>
                      <th scope="row" className="table__rowhead">
                        {t(`billing.action.${transaction.action}`)}
                        <span className="caption"> · {transaction.detail}</span>
                      </th>
                      <td className="num">{transaction.quantity}</td>
                      <td
                        className={
                          transaction.amount > 0 ? 'num amount--in' : 'num amount--out'
                        }
                      >
                        {formatMoney(transaction.amount, lang)}
                      </td>
                      <td>
                        <Button size="sm" onClick={() => setOpenTx(transaction)}>
                          {t('common.open')}
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </section>
        </>
      )}

      {/* Top up ------------------------------------------------------------ */}
      <Modal
        open={topUpOpen}
        title={t('billing.topUpTitle')}
        closeLabel={t('common.close')}
        onClose={() => setTopUpOpen(false)}
        footer={
          <>
            <Button onClick={() => setTopUpOpen(false)}>{t('common.cancel')}</Button>
            <Button
              variant="primary"
              onClick={() => {
                const value = Number(amount)
                if (Number.isFinite(value) && value > 0) topUp(value)
                setTopUpOpen(false)
                toast(t('billing.topUpDone'))
              }}
            >
              {t('billing.topUp')}
            </Button>
          </>
        }
      >
        <Field label={t('billing.topUpAmount')} hint="₸">
          {(props) => (
            <Input
              {...props}
              type="number"
              min={1000}
              step={1000}
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
            />
          )}
        </Field>
      </Modal>

      {/* Transaction detail ------------------------------------------------ */}
      <Modal
        open={openTx !== null}
        title={t('billing.txTitle')}
        closeLabel={t('common.close')}
        onClose={() => setOpenTx(null)}
        footer={<Button onClick={() => setOpenTx(null)}>{t('common.close')}</Button>}
      >
        {openTx ? (
          <dl className="tx-detail">
            <div>
              <dt>{t('common.date')}</dt>
              <dd>{formatDateTime(openTx.date, lang)}</dd>
            </div>
            <div>
              <dt>{t('billing.col.action')}</dt>
              <dd>{t(`billing.action.${openTx.action}`)}</dd>
            </div>
            <div>
              <dt>{t('common.topic')}</dt>
              <dd>{openTx.detail}</dd>
            </div>
            <div>
              <dt>{t('billing.col.qty')}</dt>
              <dd>{openTx.quantity}</dd>
            </div>
            <div>
              <dt>{t('billing.col.amount')}</dt>
              <dd>{formatMoney(openTx.amount, lang)}</dd>
            </div>
          </dl>
        ) : null}
      </Modal>
    </div>
  )
}
