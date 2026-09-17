export type IconName =
  | 'alert'
  | 'arrowRight'
  | 'book'
  | 'check'
  | 'checkCircle'
  | 'chevronDown'
  | 'chevronLeft'
  | 'chevronRight'
  | 'clipboard'
  | 'close'
  | 'download'
  | 'file'
  | 'grid'
  | 'info'
  | 'lightbulb'
  | 'logOut'
  | 'mail'
  | 'menu'
  | 'minus'
  | 'moon'
  | 'more'
  | 'pause'
  | 'pencil'
  | 'phone'
  | 'play'
  | 'plus'
  | 'refresh'
  | 'replay'
  | 'search'
  | 'settings'
  | 'sliders'
  | 'sparkle'
  | 'sun'
  | 'trash'
  | 'upload'
  | 'volumeOff'
  | 'volumeOn'
  | 'wallet'
  | 'warning'

const PATHS: Record<IconName, React.ReactNode> = {
  alert: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v5M12 16.5v.01" />
    </>
  ),
  arrowRight: <path d="M4 12h15m-6-6 6 6-6 6" />,
  book: (
    <>
      <path d="M5 4h11a2 2 0 0 1 2 2v14H7a2 2 0 0 1-2-2V4Z" />
      <path d="M5 17h13" />
    </>
  ),
  check: <path d="m4.5 12.5 5 5 10-11" />,
  checkCircle: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m8 12.5 2.5 2.5L16 9.5" />
    </>
  ),
  chevronDown: <path d="m6 9.5 6 6 6-6" />,
  chevronLeft: <path d="m14.5 6-6 6 6 6" />,
  chevronRight: <path d="m9.5 6 6 6-6 6" />,
  clipboard: (
    <>
      <path d="M9 4h6v3H9z" />
      <path d="M9 5.5H6.5v14h11v-14H15" />
      <path d="m9.5 13 2 2 3.5-4" />
    </>
  ),
  close: <path d="m6 6 12 12M18 6 6 18" />,
  download: <path d="M12 4v11m0 0 4-4m-4 4-4-4M5 19h14" />,
  file: (
    <>
      <path d="M13 4H7a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V9l-5-5Z" />
      <path d="M13 4v5h5" />
    </>
  ),
  grid: (
    <>
      <rect x="4" y="4" width="7" height="7" rx="1" />
      <rect x="13" y="4" width="7" height="7" rx="1" />
      <rect x="4" y="13" width="7" height="7" rx="1" />
      <rect x="13" y="13" width="7" height="7" rx="1" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5M12 7.5v.01" />
    </>
  ),
  lightbulb: (
    <>
      <path d="M9 17h6M10 20h4" />
      <path d="M12 3a6 6 0 0 0-3.5 10.9V17h7v-3.1A6 6 0 0 0 12 3Z" />
    </>
  ),
  logOut: <path d="M14 5H6v14h8M15 12H10m5 0-2.5-2.5M15 12l-2.5 2.5M18 9l3 3-3 3" />,
  mail: (
    <>
      <rect x="3" y="5.5" width="18" height="13" rx="2" />
      <path d="m4 7 8 6 8-6" />
    </>
  ),
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  minus: <path d="M6 12h12" />,
  moon: <path d="M20 14.5A8.2 8.2 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5Z" />,
  more: (
    <>
      <circle cx="6" cy="12" r="1.4" />
      <circle cx="12" cy="12" r="1.4" />
      <circle cx="18" cy="12" r="1.4" />
    </>
  ),
  pause: <path d="M9 5v14M15 5v14" />,
  pencil: (
    <>
      <path d="M4 20h4l10-10-4-4L4 16v4Z" />
      <path d="m14 6 4 4" />
    </>
  ),
  phone: (
    <path d="M7 3.5h3l1.5 4-2 1.5a11 11 0 0 0 5.5 5.5l1.5-2 4 1.5v3a2 2 0 0 1-2.2 2A16.5 16.5 0 0 1 5 5.7 2 2 0 0 1 7 3.5Z" />
  ),
  play: <path d="M8 5.5v13l11-6.5-11-6.5Z" />,
  plus: <path d="M12 6v12M6 12h12" />,
  refresh: (
    <>
      <path d="M20 12a8 8 0 1 1-2.6-5.9" />
      <path d="M20 4v4h-4" />
    </>
  ),
  replay: (
    <>
      <path d="M4 12a8 8 0 1 0 2.6-5.9" />
      <path d="M4 4v4h4" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="6" />
      <path d="m16 16 4 4" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3.5v2M12 18.5v2M4.9 7.8l1.8 1M17.3 15.2l1.8 1M4.9 16.2l1.8-1M17.3 8.8l1.8-1" />
    </>
  ),
  sliders: (
    <>
      <path d="M5 7h14M5 12h14M5 17h14" />
      <circle cx="9" cy="7" r="2" />
      <circle cx="15" cy="12" r="2" />
      <circle cx="8" cy="17" r="2" />
    </>
  ),
  sparkle: (
    <path d="M12 4l1.8 4.8L18.5 10l-4.7 1.2L12 16l-1.8-4.8L5.5 10l4.7-1.2L12 4Z" />
  ),
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4" />
    </>
  ),
  trash: (
    <>
      <path d="M5 7h14M10 7V5h4v2M6.5 7l.8 12h9.4l.8-12" />
      <path d="M10.5 11v5M13.5 11v5" />
    </>
  ),
  upload: <path d="M12 20V9m0 0 4 4m-4-4-4 4M5 5h14" />,
  volumeOn: <path d="M15.536 8.464a5 5 0 0 1 0 7.072M12 6 8 10H5v4h3l4 4V6Z" />,
  volumeOff: <path d="M12 6 8 10H5v4h3l4 4V6ZM17 9l4 6m0-6-4 6" />,
  wallet: (
    <>
      <path d="M4 8a2 2 0 0 1 2-2h11v4" />
      <path d="M4 8v9a2 2 0 0 0 2 2h13V10H6a2 2 0 0 1-2-2Z" />
      <path d="M16 14h.01" />
    </>
  ),
  warning: (
    <>
      <path d="M12 4 2.8 20h18.4L12 4Z" />
      <path d="M12 10v4M12 17.5v.01" />
    </>
  ),
}

interface IconProps {
  name: IconName
  size?: number
  className?: string
  /** Icons are decorative by default; pass a label when the icon is the only content. */
  label?: string
}

export function Icon({ name, size = 20, className, label }: IconProps) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={label ? undefined : true}
      role={label ? 'img' : undefined}
      aria-label={label}
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  )
}
