import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ScenePreview } from '../components/anim/AnimationPlayer'
import { SCENE_TITLES } from '../components/anim/scenes'
import { ExplanationView } from '../components/ExplanationView'
import {
  Alert,
  Badge,
  Button,
  Card,
  Chip,
  ChipGroup,
  EmptyState,
  Field,
  Icon,
  Input,
  Menu,
  Modal,
  SearchInput,
  SegmentedControl,
  Select,
  Skeleton,
  useToast,
} from '../components/ui'
import { useI18n } from '../lib/i18n'
import { SUBJECTS } from '../lib/mockData'
import { useStore } from '../lib/store'
import type { Explanation, SubjectId } from '../lib/types'
import { formatDate } from '../lib/utils'

type SortKey = 'new' | 'old' | 'az'
type LangFilter = 'all' | 'kk' | 'ru'

export function Library() {
  const { t, lang } = useI18n()
  const { toast } = useToast()
  const navigate = useNavigate()
  const { library, libraryLoading, removeFromLibrary, renameExplanation, reloadLibrary } =
    useStore()

  const [failure, setFailure] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [subjects, setSubjects] = useState<SubjectId[]>([])
  const [langFilter, setLangFilter] = useState<LangFilter>('all')
  const [sort, setSort] = useState<SortKey>('new')

  const [opened, setOpened] = useState<Explanation | null>(null)
  const [renaming, setRenaming] = useState<Explanation | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [deleting, setDeleting] = useState<Explanation | null>(null)

  /* Read on arrival. The skeleton grid covers the request rather than a
     timer, so it lasts as long as the request does. */
  useEffect(() => {
    void reloadLibrary().catch(() => setFailure(t('library.loadFailed')))
  }, [reloadLibrary, t])

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const result = library.filter((item) => {
      const matchesQuery = !needle || item.question.toLowerCase().includes(needle)
      const matchesSubject = subjects.length === 0 || subjects.includes(item.subject)
      const matchesLang = langFilter === 'all' || item.lang === langFilter
      return matchesQuery && matchesSubject && matchesLang
    })
    return result.sort((a, b) => {
      if (sort === 'az') return a.question.localeCompare(b.question, lang)
      const diff = new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
      return sort === 'new' ? diff : -diff
    })
  }, [library, query, subjects, langFilter, sort, lang])

  function toggleSubject(subject: SubjectId) {
    setSubjects((prev) =>
      prev.includes(subject)
        ? prev.filter((item) => item !== subject)
        : [...prev, subject],
    )
  }

  function clearFilters() {
    setQuery('')
    setSubjects([])
    setLangFilter('all')
  }

  const filtersActive = query.trim() !== '' || subjects.length > 0 || langFilter !== 'all'

  return (
    <div className="page">
      <header className="page__header">
        <div className="page__heading">
          <h1 className="page__title">{t('library.title')}</h1>
          <p className="page__subtitle">{t('library.count', { n: filtered.length })}</p>
        </div>
        <Button variant="primary" icon="plus" onClick={() => navigate('/app/explain')}>
          {t('explain.newChat')}
        </Button>
      </header>


      {failure ? <Alert tone="error">{failure}</Alert> : null}

      {/* Filter bar --------------------------------------------------------- */}
      <Card as="section" elevation="flat" className="filters">
        <h2 className="visually-hidden">{t('common.search')}</h2>
        <SearchInput
          id="library-search"
          label={t('library.searchPlaceholder')}
          placeholder={t('library.searchPlaceholder')}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className="filters__search"
        />

        <ChipGroup label={t('common.subject')}>
          {SUBJECTS.map((subject) => (
            <Chip
              key={subject}
              selected={subjects.includes(subject)}
              onClick={() => toggleSubject(subject)}
            >
              {t(`subject.${subject}`)}
            </Chip>
          ))}
        </ChipGroup>

        <div className="filters__controls">
          <SegmentedControl
            label={t('common.language')}
            value={langFilter}
            onChange={setLangFilter}
            options={[
              { value: 'all', label: t('common.all') },
              { value: 'kk', label: t('common.kazakh') },
              { value: 'ru', label: t('common.russian') },
            ]}
          />
          <Field label={t('library.sortLabel')} className="filters__sort">
            {(props) => (
              <Select
                {...props}
                value={sort}
                onChange={(event) => setSort(event.target.value as SortKey)}
                options={[
                  { value: 'new', label: t('library.sort.new') },
                  { value: 'old', label: t('library.sort.old') },
                  { value: 'az', label: t('library.sort.az') },
                ]}
              />
            )}
          </Field>
        </div>
      </Card>

      {/* Grid --------------------------------------------------------------- */}
      <section aria-busy={libraryLoading} aria-live="polite">
        <h2 className="visually-hidden">{t('library.title')}</h2>

        {libraryLoading ? (
          <ul className="card-grid">
            {Array.from({ length: 6 }, (_, index) => (
              <li key={index}>
                <Card elevation="flat" plain>
                  <Skeleton height="180px" radius="md" />
                  <div className="stack stack-sm library-card__body">
                    <Skeleton width="40%" height="18px" radius="full" />
                    <Skeleton height="16px" />
                    <Skeleton width="70%" height="16px" />
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        ) : library.length === 0 ? (
          <EmptyState
            icon="book"
            title={t('library.emptyTitle')}
            body={t('library.emptyBody')}
            level={3}
            action={
              <Button variant="primary" onClick={() => navigate('/app/explain')}>
                {t('library.emptyCta')}
              </Button>
            }
          />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon="search"
            title={t('library.noResultsTitle')}
            body={t('library.noResultsBody')}
            level={3}
            action={
              filtersActive ? (
                <Button onClick={clearFilters}>{t('library.clearFilters')}</Button>
              ) : undefined
            }
          />
        ) : (
          <ul className="card-grid">
            {filtered.map((item) => (
              <li key={item.id}>
                <Card elevation="raised" plain className="library-card">
                  <button
                    type="button"
                    className="library-card__thumb"
                    onClick={() => setOpened(item)}
                  >
                    <span className="visually-hidden">
                      {t('common.open')}: {item.question}
                    </span>
                    {/* Saved answers from Explain are rendered video, not one
                        of the seven built-in scenes, and there is no thumbnail
                        for them until the library itself becomes real in Ф5. */}
                    {item.scene ? (
                      <ScenePreview scene={item.scene} title={SCENE_TITLES[item.scene]} />
                    ) : (
                      <span className="library-card__poster" aria-hidden="true">
                        <Icon name="play" size={22} />
                      </span>
                    )}
                  </button>

                  <div className="library-card__body">
                    <div className="row row-between">
                      <Badge tone="info">{t(`subject.${item.subject}`)}</Badge>
                      <Menu
                        label={t('library.cardMenu', { title: item.question })}
                        items={[
                          {
                            key: 'open',
                            label: t('common.open'),
                            icon: 'arrowRight',
                            onSelect: () => setOpened(item),
                          },
                          {
                            key: 'rename',
                            label: t('common.rename'),
                            icon: 'pencil',
                            onSelect: () => {
                              setRenaming(item)
                              setRenameValue(item.question)
                            },
                          },
                          {
                            key: 'delete',
                            label: t('common.delete'),
                            icon: 'trash',
                            danger: true,
                            onSelect: () => setDeleting(item),
                          },
                        ]}
                      />
                    </div>
                    <h3 className="library-card__title">{item.question}</h3>
                    <p className="caption">{formatDate(item.createdAt, lang)}</p>
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Open ---------------------------------------------------------------- */}
      <Modal
        open={opened !== null}
        wide
        title={t('explain.resultTitle')}
        closeLabel={t('common.close')}
        onClose={() => setOpened(null)}
        footer={<Button onClick={() => setOpened(null)}>{t('common.close')}</Button>}
      >
        {opened ? <ExplanationView explanation={opened} headingLevel={3} /> : null}
      </Modal>

      {/* Rename -------------------------------------------------------------- */}
      <Modal
        open={renaming !== null}
        title={t('library.renameTitle')}
        closeLabel={t('common.close')}
        onClose={() => setRenaming(null)}
        footer={
          <>
            <Button onClick={() => setRenaming(null)}>{t('common.cancel')}</Button>
            <Button
              variant="primary"
              disabled={!renameValue.trim()}
              onClick={() => {
                if (renaming) {
                  void renameExplanation(renaming.id, renameValue.trim()).catch(() =>
                    setFailure(t('library.saveFailed')),
                  )
                }
                setRenaming(null)
                toast(t('library.renamed'))
              }}
            >
              {t('common.save')}
            </Button>
          </>
        }
      >
        <Field label={t('library.renameLabel')}>
          {(props) => (
            <Input
              {...props}
              value={renameValue}
              onChange={(event) => setRenameValue(event.target.value)}
            />
          )}
        </Field>
      </Modal>

      {/* Delete -------------------------------------------------------------- */}
      <Modal
        open={deleting !== null}
        title={t('library.deleteTitle')}
        description={
          deleting ? t('library.deleteBody', { title: deleting.question }) : undefined
        }
        closeLabel={t('common.close')}
        onClose={() => setDeleting(null)}
        footer={
          <>
            <Button onClick={() => setDeleting(null)}>{t('common.cancel')}</Button>
            <Button
              variant="danger"
              icon="trash"
              onClick={() => {
                if (deleting) {
                  void removeFromLibrary(deleting.id).catch(() =>
                    setFailure(t('library.saveFailed')),
                  )
                }
                setDeleting(null)
                toast(t('library.deleted'))
              }}
            >
              {t('common.delete')}
            </Button>
          </>
        }
      />
    </div>
  )
}
