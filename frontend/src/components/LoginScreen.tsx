import { useState } from 'react';
import { AuthResult } from '../hooks/useApi';

interface LoginScreenProps {
  onLogin: (username: string, password: string) => Promise<AuthResult>;
  onSignup: (username: string, email: string, password: string) => Promise<AuthResult>;
}

type Mode = 'login' | 'signup';

const USERNAME_RE = /^[A-Za-z0-9_]{3,30}$/;
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export const LoginScreen: React.FC<LoginScreenProps> = ({ onLogin, onSignup }) => {
  const [mode, setMode] = useState<Mode>('login');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const validate = (): string => {
    if (!USERNAME_RE.test(username.trim())) {
      return 'Username must be 3-30 characters: letters, digits, underscore';
    }
    if (mode === 'signup') {
      const emailTrimmed = email.trim();
      if (emailTrimmed && !EMAIL_RE.test(emailTrimmed)) {
        return 'Invalid email address';
      }
      if (password.length < 8) {
        return 'Password must be at least 8 characters';
      }
      if (password !== confirmPassword) {
        return 'Passwords do not match';
      }
    }
    if (!password) {
      return 'Password is required';
    }
    return '';
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }

    setIsLoading(true);
    try {
      const result =
        mode === 'login'
          ? await onLogin(username.trim(), password)
          : await onSignup(username.trim(), email.trim(), password);

      if (!result.ok) {
        setError(result.error || 'Something went wrong. Please try again.');
        setPassword('');
        setConfirmPassword('');
      }
      // On success the parent switches to the authenticated view.
    } finally {
      setIsLoading(false);
    }
  };

  const switchMode = (next: Mode) => {
    setMode(next);
    setError('');
    setPassword('');
    setConfirmPassword('');
  };

  return (
    <div className="min-h-screen bg-dark-900 flex items-center justify-center p-4">
      {/* Animated background */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-40 -right-40 w-80 h-80 bg-accent-primary/10 rounded-full blur-3xl animate-pulse-slow" />
        <div className="absolute -bottom-40 -left-40 w-80 h-80 bg-accent-secondary/10 rounded-full blur-3xl animate-pulse-slow" style={{ animationDelay: '1s' }} />
      </div>

      <div className="relative w-full max-w-md">
        {/* Logo/Header */}
        <div className="text-center mb-8 animate-fade-in">
          <div className="inline-flex items-center justify-center w-20 h-20 rounded-2xl bg-gradient-to-br from-accent-primary to-accent-secondary mb-4 shadow-lg shadow-accent-primary/30">
            <svg className="w-10 h-10 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                    d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
            </svg>
          </div>
          <h1 className="text-3xl font-bold text-white tracking-tight">Anyq</h1>
          <p className="text-gray-500 mt-2">Interactive Learning Platform</p>
        </div>

        {/* Auth Form */}
        <div className="bg-dark-800 rounded-2xl border border-dark-600 p-8 shadow-xl animate-slide-up">
          {/* Mode tabs */}
          <div className="flex mb-6 bg-dark-700 rounded-xl p-1">
            <button
              type="button"
              onClick={() => switchMode('login')}
              className={`flex-1 py-2 rounded-lg text-sm font-medium transition-all duration-200 ${
                mode === 'login'
                  ? 'bg-accent-primary text-white shadow'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              Sign In
            </button>
            <button
              type="button"
              onClick={() => switchMode('signup')}
              className={`flex-1 py-2 rounded-lg text-sm font-medium transition-all duration-200 ${
                mode === 'signup'
                  ? 'bg-accent-primary text-white shadow'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              Create Account
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label htmlFor="username" className="block text-sm font-medium text-gray-400 mb-2">
                Username
              </label>
              <input
                id="username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full bg-dark-700 border border-dark-500 rounded-xl px-4 py-3
                         text-white placeholder-gray-500
                         focus:border-accent-primary focus:ring-1 focus:ring-accent-primary
                         transition-all duration-200"
                placeholder="Enter username"
                required
                autoComplete="username"
              />
            </div>

            {mode === 'signup' && (
              <div>
                <label htmlFor="email" className="block text-sm font-medium text-gray-400 mb-2">
                  Email <span className="text-gray-600">(optional)</span>
                </label>
                <input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full bg-dark-700 border border-dark-500 rounded-xl px-4 py-3
                           text-white placeholder-gray-500
                           focus:border-accent-primary focus:ring-1 focus:ring-accent-primary
                           transition-all duration-200"
                  placeholder="you@example.com"
                  autoComplete="email"
                />
              </div>
            )}

            <div>
              <label htmlFor="password" className="block text-sm font-medium text-gray-400 mb-2">
                Password
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-dark-700 border border-dark-500 rounded-xl px-4 py-3
                         text-white placeholder-gray-500
                         focus:border-accent-primary focus:ring-1 focus:ring-accent-primary
                         transition-all duration-200"
                placeholder={mode === 'signup' ? 'At least 8 characters' : 'Enter password'}
                required
                autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
              />
            </div>

            {mode === 'signup' && (
              <div>
                <label htmlFor="confirmPassword" className="block text-sm font-medium text-gray-400 mb-2">
                  Confirm Password
                </label>
                <input
                  id="confirmPassword"
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="w-full bg-dark-700 border border-dark-500 rounded-xl px-4 py-3
                           text-white placeholder-gray-500
                           focus:border-accent-primary focus:ring-1 focus:ring-accent-primary
                           transition-all duration-200"
                  placeholder="Repeat password"
                  required
                  autoComplete="new-password"
                />
              </div>
            )}

            {error && (
              <div className="bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3 animate-fade-in">
                <div className="flex items-center gap-2 text-red-400">
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                          d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <span className="text-sm font-medium">{error}</span>
                </div>
              </div>
            )}

            <button
              type="submit"
              disabled={isLoading}
              className={`w-full py-3 px-4 rounded-xl font-semibold text-white
                         transition-all duration-200 flex items-center justify-center gap-2
                         ${isLoading
                           ? 'bg-dark-600 cursor-not-allowed'
                           : 'bg-gradient-to-r from-accent-primary to-accent-secondary hover:shadow-lg hover:shadow-accent-primary/30 hover:scale-[1.02]'
                         }`}
            >
              {isLoading ? (
                <>
                  <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  {mode === 'login' ? 'Signing in...' : 'Creating account...'}
                </>
              ) : (
                <>
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                          d="M11 16l-4-4m0 0l4-4m-4 4h14m-5 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h7a3 3 0 013 3v1" />
                  </svg>
                  {mode === 'login' ? 'Sign In' : 'Create Account'}
                </>
              )}
            </button>
          </form>

          {/* Footer */}
          <div className="mt-6 pt-6 border-t border-dark-600 text-center">
            <p className="text-xs text-gray-600">
              {mode === 'login'
                ? "Don't have an account? "
                : 'Already have an account? '}
              <button
                type="button"
                onClick={() => switchMode(mode === 'login' ? 'signup' : 'login')}
                className="text-accent-secondary hover:underline font-medium"
              >
                {mode === 'login' ? 'Create one' : 'Sign in'}
              </button>
            </p>
          </div>
        </div>

        {/* Version */}
        <div className="text-center mt-6 text-xs text-gray-600">
          <span className="font-mono">Anyq</span> v1.0
        </div>
      </div>
    </div>
  );
};