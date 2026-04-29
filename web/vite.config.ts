import path from 'path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react-swc'
import tailwindcss from '@tailwindcss/vite'
import { lingui } from '@lingui/vite-plugin'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react({
      plugins: [['@lingui/swc-plugin', {}]],
    }),
    tailwindcss(),
    lingui(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'Praxys',
        short_name: 'Praxys',
        description: 'Science-based training for self-coached runners',
        theme_color: '#4a9e6e',
        background_color: '#fafafa',
        display: 'standalone',
        start_url: '/',
        scope: '/',
        icons: [
          { src: '/favicon.svg', sizes: 'any', type: 'image/svg+xml' },
        ],
      },
      workbox: {
        // Precache the app shell (JS, CSS, HTML, main icon) so repeat
        // visits load instantly from the service worker cache. API
        // requests intentionally excluded — fresh data matters.
        //
        // WOFF2 subsets (108 files, ~4.8 MB) also deliberately excluded:
        // browsers fetch them lazily via unicode-range as glyphs are
        // rendered, so precaching the full set would bloat the install
        // phase + use disk that most users never touch.
        globPatterns: ['**/*.{js,css,html,ico,svg}'],
        navigateFallbackDenylist: [/^\/api\//],
        maximumFileSizeToCacheInBytes: 3 * 1024 * 1024,
      },
    }),
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
          if (/node_modules[\\/]@tanstack[\\/]react-query[\\/]/.test(id)) return 'query'
          return undefined
        },
      },
    },
  },
})
