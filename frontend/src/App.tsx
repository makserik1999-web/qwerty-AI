import { useEffect } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AppShell } from './components/layout/AppShell'
import { useStore } from './lib/store'
import { Billing } from './pages/Billing'
import { Check } from './pages/Check'
import { Explain } from './pages/Explain'
import { Generate } from './pages/Generate'
import { Landing } from './pages/Landing'
import { Library } from './pages/Library'
import { Settings } from './pages/Settings'
import { SignIn } from './pages/SignIn'
import { SignUp } from './pages/SignUp'

/** Sends signed-out visitors to the sign-in page. */
function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user } = useStore()
  if (!user) return <Navigate to="/signin" replace />
  return <>{children}</>
}

/** Teacher-only areas fall back to Explain for students. */
function RequireTeacher({ children }: { children: React.ReactNode }) {
  const { user } = useStore()
  if (user?.role !== 'teacher') return <Navigate to="/app/explain" replace />
  return <>{children}</>
}

function ScrollToTop() {
  const { pathname } = useLocation()
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [pathname])
  return null
}

export function App() {
  return (
    <>
      <ScrollToTop />
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/signup" element={<SignUp />} />
        <Route path="/signin" element={<SignIn />} />
        <Route
          path="/app"
          element={
            <RequireAuth>
              <AppShell />
            </RequireAuth>
          }
        >
          <Route index element={<Navigate to="/app/explain" replace />} />
          <Route path="explain" element={<Explain />} />
          <Route path="library" element={<Library />} />
          <Route
            path="generate"
            element={
              <RequireTeacher>
                <Generate />
              </RequireTeacher>
            }
          />
          <Route
            path="check"
            element={
              <RequireTeacher>
                <Check />
              </RequireTeacher>
            }
          />
          <Route
            path="billing"
            element={
              <RequireTeacher>
                <Billing />
              </RequireTeacher>
            }
          />
          <Route path="settings" element={<Settings />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  )
}
