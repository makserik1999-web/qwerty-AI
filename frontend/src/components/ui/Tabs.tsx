import { useId, useRef } from 'react'

export interface TabItem<T extends string> {
  value: T
  label: string
}

interface TabsProps<T extends string> {
  label: string
  value: T
  items: TabItem<T>[]
  onChange: (value: T) => void
  children?: React.ReactNode
}

/** Tabs with roving focus and arrow-key navigation (WAI-ARIA tabs pattern). */
export function Tabs<T extends string>({
  label,
  value,
  items,
  onChange,
  children,
}: TabsProps<T>) {
  const baseId = useId()
  const listRef = useRef<HTMLDivElement>(null)

  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    const index = items.findIndex((item) => item.value === value)
    let next = index
    if (event.key === 'ArrowRight') next = index + 1
    else if (event.key === 'ArrowLeft') next = index - 1
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = items.length - 1
    else return
    event.preventDefault()
    const target = items[(next + items.length) % items.length]
    onChange(target.value)
    const buttons = listRef.current?.querySelectorAll('button')
    buttons?.[(next + items.length) % items.length]?.focus()
  }

  const activeIndex = items.findIndex((item) => item.value === value)

  return (
    <>
      <div
        className="tabs"
        role="tablist"
        aria-label={label}
        ref={listRef}
        onKeyDown={onKeyDown}
      >
        {items.map((item, index) => (
          <button
            key={item.value}
            type="button"
            role="tab"
            id={`${baseId}-tab-${item.value}`}
            aria-selected={item.value === value}
            aria-controls={`${baseId}-panel-${item.value}`}
            tabIndex={index === activeIndex ? 0 : -1}
            className="tabs__tab"
            onClick={() => onChange(item.value)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {children ? (
        <div
          role="tabpanel"
          id={`${baseId}-panel-${value}`}
          aria-labelledby={`${baseId}-tab-${value}`}
          tabIndex={0}
        >
          {children}
        </div>
      ) : null}
    </>
  )
}
