import { defineConfig, externalizeDepsPlugin } from 'electron-vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    build: {
      rollupOptions: {
        input: {
          index: resolve(__dirname, 'electron/main/index.js')
        },
        output: { format: 'cjs' }
      }
    }
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    build: {
      rollupOptions: {
        input: {
          index: resolve(__dirname, 'electron/preload/index.js')
        },
        output: { format: 'cjs' }
      }
    }
  },
  renderer: {
    root: '.',
    build: {
      rollupOptions: {
        input: {
          index: resolve(__dirname, 'index.html')
        }
      },
      commonjsOptions: {
        include: [/node_modules/]
      }
    },
    optimizeDeps: {
      include: [
        'recharts',
        'd3-scale',
        'd3-shape',
        'd3-path',
        'd3-color',
        'd3-interpolate',
        'd3-time',
        'd3-time-format'
      ]
    },
    plugins: [react()],
    resolve: {
      alias: {
        '@': resolve(__dirname, 'src'),
        '@components': resolve(__dirname, 'src/components')
      }
    }
  }
})
