import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { App } from './App'
import { I18nProvider } from './lib/i18n'
import { LiveProvider } from './lib/live'
import { StoreProvider, useStore } from './lib/store'
import { ToastProvider } from './components/ui'
import 'katex/dist/katex.min.css'
import './styles/tokens.css'
import './styles/base.css'
import './styles/ui.css'
import './styles/layout.css'
import './styles/anim.css'
import './styles/pages.css'
import './styles/markdown.css'

/** Bridges the interface language from the store into the i18n provider. */
function LocalizedApp() {
  const { uiLang, user } = useStore()
  return (
    <I18nProvider lang={uiLang}>
      {/* The socket is opened once, for the whole signed-in app, and only
          once there is a session: /ws refuses a connection without the
          cookie, so opening it earlier would just reconnect in a loop. */}
      <LiveProvider enabled={Boolean(user)}>
        <ToastProvider>
          <App />
        </ToastProvider>
      </LiveProvider>
    </I18nProvider>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <StoreProvider>
        <LocalizedApp />
      </StoreProvider>
    </BrowserRouter>
  </StrictMode>,
)
