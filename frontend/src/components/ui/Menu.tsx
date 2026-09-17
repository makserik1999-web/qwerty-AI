import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { cx } from '../../lib/utils'
import { IconButton } from './Button'
import { Icon, type IconName } from './Icon'

export interface MenuItem {
  key: string
  label: string
  icon?: IconName
  danger?: boolean
  onSelect: () => void
}

interface MenuProps {
  label: string
  items: MenuItem[]
  align?: 'start' | 'end'
  /** Opens upward when the trigger sits at the bottom of its container. */
  side?: 'bottom' | 'top'
  /** Icon-only trigger. Ignored when `text` is given. */
  icon?: IconName
  /** Renders a labelled trigger instead of an icon button. */
  text?: string
  /** Marks one item as the current choice. */
  selectedKey?: string
}

/** Menu with outside-click and Escape handling, shared by every dropdown. */
export function Menu({
  label,
  items,
  align = 'end',
  side = 'bottom',
  icon = 'more',
  text,
  selectedKey,
}: MenuProps) {
  const [open, setOpen] = useState(false)
  const [resolvedAlign, setResolvedAlign] = useState(align)
  const rootRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const id = useId()

  /* A trigger near either edge of the window would push its menu off-screen,
     so the alignment flips to whichever side fits. */
  useLayoutEffect(() => {
    if (!open) {
      setResolvedAlign(align)
      return
    }
    const rect = listRef.current?.getBoundingClientRect()
    if (!rect) return
    const margin = 8
    if (rect.left < margin) setResolvedAlign('start')
    else if (rect.right > window.innerWidth - margin) setResolvedAlign('end')
  }, [open, align])

  useEffect(() => {
    if (!open) return
    function onPointerDown(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  const triggerProps = {
    'aria-expanded': open,
    'aria-haspopup': 'menu' as const,
    'aria-controls': open ? id : undefined,
    onClick: () => setOpen((value) => !value),
  }

  return (
    <div className="menu" ref={rootRef}>
      {text ? (
        <button
          type="button"
          className="menu__trigger"
          aria-label={label}
          {...triggerProps}
        >
          <span>{text}</span>
          <Icon name="chevronDown" size={14} />
        </button>
      ) : (
        <IconButton icon={icon} label={label} {...triggerProps} />
      )}

      {open ? (
        <div
          ref={listRef}
          className={cx(
            'menu__list',
            `menu__list--${resolvedAlign}`,
            `menu__list--${side}`,
          )}
          id={id}
          role="menu"
        >
          {items.map((item) => {
            const selected = selectedKey === item.key
            return (
              <button
                key={item.key}
                type="button"
                role={selectedKey === undefined ? 'menuitem' : 'menuitemradio'}
                aria-checked={selectedKey === undefined ? undefined : selected}
                className={cx(
                  'menu__item',
                  item.danger && 'is-danger',
                  selected && 'is-selected',
                )}
                onClick={() => {
                  setOpen(false)
                  item.onSelect()
                }}
              >
                {item.icon ? <Icon name={item.icon} size={16} /> : null}
                <span className="grow">{item.label}</span>
                {selected ? <Icon name="check" size={16} /> : null}
              </button>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}
