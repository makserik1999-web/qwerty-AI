/**
 * The video library in the admin panel. The topic cache fills it on its own;
 * this is where someone watches what it filed and decides: on the showcase,
 * rejected (never served again), or deleted. Title and topic can be corrected
 * - the classifier will sometimes file a video under the wrong one.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { VideoPlayer } from '../components/player/VideoPlayer'
import { Alert, Badge, Button, Card, Input, SegmentedControl, Select } from '../components/ui'
import * as adminApi from '../lib/admin'
import type { AdminVideo, Topic } from '../lib/admin'

const FILTERS = [
  { value: 'cached', label: 'На проверке' },
  { value: 'public', label: 'В витрине' },
  { value: 'rejected', label: 'Отклонённые' },
]

const STATUS_LABEL: Record<string, string> = { cached: 'на проверке', public: 'в витрине', rejected: 'отклонено' }

export function VideosSection() {
  const [status, setStatus] = useState('cached')
  const [silent, setSilent] = useState(false)
  const [items, setItems] = useState<AdminVideo[] | null>(null)
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [topics, setTopics] = useState<Topic[]>([])
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const found = await adminApi.listVideos(status, silent)
      setItems(found.items)
      setCounts(found.counts)
    } catch {
      setError('Не удалось загрузить библиотеку.')
    }
  }, [status, silent])

  useEffect(() => {
    setItems(null)
    void load()
  }, [load])

  useEffect(() => {
    adminApi.listTopics().then((found) => setTopics(found.items)).catch(() => undefined)
  }, [])

  return (
    <div className="admin__stack">
      <div className="admin__toolbar">
        <SegmentedControl
          label="Статус"
          value={status}
          onChange={setStatus}
          options={FILTERS.map((f) => ({ ...f, label: `${f.label} (${counts[f.value] ?? 0})` }))}
        />
        <label className="row">
          <input type="checkbox" checked={silent} onChange={(e) => setSilent(e.target.checked)} />
          <span className="text-sm">Только без звука</span>
        </label>
      </div>
      {error ? <Alert tone="error">{error}</Alert> : null}
      {!items ? <p className="caption">Загрузка…</p> : null}
      {items && !items.length ? <p className="caption">Пусто.</p> : null}
      <div className="admin__videos">
        {(items ?? []).map((video) => (
          <VideoCard key={video.id} video={video} topics={topics} onChanged={load} />
        ))}
      </div>
    </div>
  )
}

function VideoCard({ video, topics, onChanged }: { video: AdminVideo; topics: Topic[]; onChanged: () => void }) {
  const [title, setTitle] = useState(video.title)
  const [topicId, setTopicId] = useState(video.topic_id)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const options = useMemo(
    () =>
      topics
        .filter((t) => t.subject === video.subject)
        .map((t) => ({ value: t.id, label: `${t.grade} кл. — ${t.ru}` })),
    [topics, video.subject],
  )

  async function run(action: () => Promise<unknown>, done: string) {
    setBusy(true)
    setMessage(null)
    try {
      await action()
      setMessage(done)
      onChanged()
    } catch {
      setMessage('Ошибка')
    } finally {
      setBusy(false)
    }
  }

  const changed = title !== video.title || topicId !== video.topic_id

  return (
    <Card as="article" className="admin__stack admin__video">
      <VideoPlayer src={video.video_url} title={video.title} />
      <div className="admin__roles">
        <Badge tone={video.status === 'public' ? 'success' : video.status === 'rejected' ? 'error' : 'info'}>
          {STATUS_LABEL[video.status]}
        </Badge>
        <Badge tone="neutral">{video.lang}</Badge>
        {video.has_audio === false ? <Badge tone="warning">без звука</Badge> : null}
        <span className="caption">
          👍 {video.rating_up} · 👎 {video.rating_down} · показов {video.served}
          {video.duration ? ` · ${Math.round(video.duration)} с` : ''}
        </span>
      </div>
      <label className="field">
        <span className="field__label">Название</span>
        <Input value={title} onChange={(e) => setTitle(e.target.value)} />
      </label>
      <label className="field">
        <span className="field__label">Тема</span>
        <Select value={topicId} onChange={(e) => setTopicId(e.target.value)} options={options} />
      </label>
      <div className="row row-wrap">
        {changed ? (
          <Button
            loading={busy}
            onClick={() => void run(() => adminApi.editVideo(video.id, { title, topic_id: topicId }), 'Сохранено')}
          >
            Сохранить
          </Button>
        ) : null}
        {video.status !== 'public' ? (
          <Button variant="primary" loading={busy} onClick={() => void run(() => adminApi.videoAction(video.id, 'publish'), 'В витрине')}>
            В витрину
          </Button>
        ) : null}
        {video.status !== 'rejected' ? (
          <Button loading={busy} onClick={() => void run(() => adminApi.videoAction(video.id, 'reject'), 'Отклонено')}>
            Отклонить
          </Button>
        ) : null}
        <Button variant="quietDanger" loading={busy} onClick={() => void run(() => adminApi.videoAction(video.id, 'delete'), 'Удалено')}>
          Удалить
        </Button>
      </div>
      {message ? <p className="caption">{message}</p> : null}
    </Card>
  )
}
