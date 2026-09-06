import { cx } from '../../lib/utils'

interface TableProps {
  caption: string
  /** Hide the caption visually but keep it for assistive technology. */
  hideCaption?: boolean
  children: React.ReactNode
  className?: string
}

export function Table({ caption, hideCaption = true, children, className }: TableProps) {
  return (
    <div className={cx('table-wrap', className)}>
      <table className="table">
        <caption className={hideCaption ? 'visually-hidden' : undefined}>
          {caption}
        </caption>
        {children}
      </table>
    </div>
  )
}
