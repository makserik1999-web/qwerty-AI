import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { App } from './App'
import { I18nProvider } from './lib/i18n'
import { StoreProvider, useStore } from './lib/store'
import { ToastProvider } from './components/ui'
import './styles/tokens.css'
import './styles/base.css'
import './styles/ui.css'
import './styles/layout.css'
import './styles/anim.css'
import './styles/pages.css'

/** Bridges the interface language from the store into the i18n provider. */
function LocalizedApp() {
  const { uiLang } = useStore()
  return (
    <I18nProvider lang={uiLang}>
      <ToastProvider>
        <App />
      </ToastProvider>
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
