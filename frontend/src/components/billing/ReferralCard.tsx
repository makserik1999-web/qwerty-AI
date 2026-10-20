import { useEffect, useState } from 'react'
import { getReferrals, type ReferralSummary } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { AnchorButton, Button, Card } from '../ui'

/** The teacher's invite link, a WhatsApp share, and what the link has earned. */
export function ReferralCard() {
  const { t } = useI18n()
  const [mine, setMine] = useState<ReferralSummary | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    getReferrals().then(setMine).catch(() => undefined)
  }, [])

  if (!mine) return null

  const message = `${t('ref.message')} ${mine.link}`

  async function copy() {
    try {
      await navigator.clipboard.writeText(mine!.link)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      /* the link is on screen to copy by hand */
    }
  }

  return (
    <Card as="section" elevation="raised" className="stack stack-md">
      <h2 className="card__title">{t('ref.title')}</h2>
      <p className="text-sm text-secondary">
        {t('ref.body', { bonus: mine.invitee_bonus_videos, cap: mine.cap })}
      </p>
      <code className="ref-card__link">{mine.link}</code>
      <div className="row row-wrap">
        <Button icon="copy" onClick={() => void copy()}>
          {copied ? t('ref.copied') : t('ref.copy')}
        </Button>
        <AnchorButton
          variant="primary"
          href={`https://wa.me/?text=${encodeURIComponent(message)}`}
          target="_blank"
          rel="noopener noreferrer"
        >
          {t('ref.whatsapp')}
        </AnchorButton>
      </div>
      <p className="caption">
        {t('ref.stats', { invited: mine.invited, paid: mine.paid, months: mine.months_this_year, cap: mine.cap })}
      </p>
    </Card>
  )
}
