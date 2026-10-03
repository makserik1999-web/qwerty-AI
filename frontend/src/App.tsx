import { Suspense, lazy, useEffect } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AppShell } from './components/layout/AppShell'
import { Spinner } from './components/ui'
import { useI18n } from './lib/i18n'
import { useStore } from './lib/store'
import { Billing } from './pages/Billing'
import { Check } from './pages/Check'
import { Explain } from './pages/Explain'
import { Generate } from './pages/Generate'
import { LessonPlan } from './pages/LessonPlan'
import { Landing } from './pages/Landing'
import { Library } from './pages/Library'
import { Settings } from './pages/Settings'
import { SignIn } from './pages/SignIn'
import { SignUp } from './pages/SignUp'

/* Quizzes are a module of their own, loaded when first opened - like the
   service behind them, they could leave this app without untangling it. A
   student's phone arriving at /join loads that module and nothing teachers
   use. */
const QuizList = lazy(() => import('./quiz/pages/QuizList').then((m) => ({ default: m.QuizList })))
const QuizEditor = lazy(() =>
  import('./quiz/pages/QuizEditor').then((m) => ({ default: m.QuizEditor })),
)
const QuizResults = lazy(() =>
  import('./quiz/pages/QuizResults').then((m) => ({ default: m.QuizResults })),
)
const QuizHost = lazy(() => import('./quiz/pages/QuizHost').then((m) => ({ default: m.QuizHost })))
const Join = lazy(() => import('./quiz/pages/Join').then((m) => ({ default: m.Join })))

/**
 * Sends signed-out visitors to the sign-in page.
 *
 * The wait matters. Who someone is now comes from /api/auth/me rather than
 * from local storage, and until that answers there is no user - so redirecting
 * straight away would bounce every signed-in person off the page they opened,
 * on every reload, and land them on the sign-in screen they do not need.
 */
function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, checkingSession } = useStore()
  if (checkingSession) return <SessionCheck />
  if (!user) return <Navigate to="/signin" replace />
  return <>{children}</>
}

/**
 * Teacher-only areas fall back to Explain for students.
 *
 * The role is read from the account, not from anything the browser kept, so
 * this cannot be talked out of by editing local storage the way it could when
 * the session was persisted there. It is still only the interface: the screens
 * behind it have no endpoints of their own yet, and each will have to check
 * the role itself when it does.
 */
function RequireTeacher({ children }: { children: React.ReactNode }) {
  const { user, checkingSession } = useStore()
  if (checkingSession) return <SessionCheck />
  if (user?.role !== 'teacher') return <Navigate to="/app/explain" replace />
  return <>{children}</>
}

/** Held for one request, so it says what is happening rather than flashing. */
function SessionCheck() {
  const { t } = useI18n()
  return (
    <div className="session-check" role="status" aria-live="polite">
      <Spinner />
      <span className="text-sm text-secondary">{t('common.loading')}</span>
    </div>
  )
}

function Lazy({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<SessionCheck />}>{children}</Suspense>
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
          path="/join"
          element={
            <Lazy>
              <Join />
            </Lazy>
          }
        />
        <Route
          path="/join/:code"
          element={
            <Lazy>
              <Join />
            </Lazy>
          }
        />
        <Route
          path="/host/:sessionId"
          element={
            <RequireTeacher>
              <Lazy>
                <QuizHost />
              </Lazy>
            </RequireTeacher>
          }
        />
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
            path="plan"
            element={
              <RequireTeacher>
                <LessonPlan />
              </RequireTeacher>
            }
          />
          <Route
            path="quizzes"
            element={
              <RequireTeacher>
                <Lazy>
                  <QuizList />
                </Lazy>
              </RequireTeacher>
            }
          />
          <Route
            path="quizzes/:quizId"
            element={
              <RequireTeacher>
                <Lazy>
                  <QuizEditor />
                </Lazy>
              </RequireTeacher>
            }
          />
          <Route
            path="quizzes/:quizId/runs/:sessionId"
            element={
              <RequireTeacher>
                <Lazy>
                  <QuizResults />
                </Lazy>
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
