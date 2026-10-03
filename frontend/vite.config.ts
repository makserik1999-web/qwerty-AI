import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendUrl = env.VITE_BACKEND_URL || 'http://backend:8000'
  const quizUrl = env.VITE_QUIZ_URL || 'http://quiz:8100'
  
  return {
    plugins: [react()],
    server: {
      host: '0.0.0.0',
      port: 3000,
      // The quiz service's prefixes come first: the first matching key wins,
      // and '/api' and '/ws' would otherwise swallow them.
      proxy: {
        '/api/quiz/': {
          target: quizUrl,
          changeOrigin: true,
        },
        '/api/play/': {
          target: quizUrl,
          changeOrigin: true,
        },
        '/ws/quiz/': {
          target: quizUrl.replace('http', 'ws'),
          ws: true,
        },
        '/api': {
          target: backendUrl,
          changeOrigin: true,
        },
        '/ws': {
          target: backendUrl.replace('http', 'ws'),
          ws: true,
        },
        '/media': {
          target: backendUrl,
          changeOrigin: true,
        },
      },
    },
  }
})

