import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'BODYBRAIN_');
  const apiProxy = {
    target: env.BODYBRAIN_API_URL || 'http://127.0.0.1:8080',
    changeOrigin: true,
    headers: env.BODYBRAIN_API_TOKEN ? { Authorization: `Bearer ${env.BODYBRAIN_API_TOKEN}` } : undefined,
  };
  return {
    plugins: [react()],
    server: { proxy: { '/api': apiProxy } },
    preview: { proxy: { '/api': apiProxy } },
  };
});
