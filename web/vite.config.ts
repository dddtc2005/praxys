import path from 'path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react-swc'
import tailwindcss from '@tailwindcss/vite'
import { lingui } from '@lingui/vite-plugin'

export default defineConfig({
  plugins: [
    react({
      plugins: [['@lingui/swc-plugin', {}]],
    }),
    tailwindcss(),
    lingui(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
  build: {
    // Vendor chunks that get their own cacheable file. Splitting helps
    // returning visitors: the app-code chunk changes every deploy (its
    // hash rotates) but recharts / react-markdown / @tanstack/react-query
    // rarely change, so their hashed filenames stay stable across
    // deploys and the browser keeps them cached.
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (/node_modules[\\/](react-router-dom|react-dom|react)[\\/]/.test(id)) return 'react-vendor'
          if (/node_modules[\\/]recharts[\\/]/.test(id)) return 'recharts'
          if (/node_modules[\\/](react-markdown|remark-gfm)[\\/]/.test(id)) return 'markdown'
          if (/node_modules[\\/]@tanstack[\\/]react-query[\\/]/.test(id)) return 'query'
          return undefined
        },
      },
    },
  },
})
