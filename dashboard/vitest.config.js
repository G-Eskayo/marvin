// Tests render React components to static HTML (react-dom/server); the app's own build uses the
// automatic JSX runtime (electron.vite.config.js), so the tests must too.
export default {
  esbuild: { jsx: 'automatic' }
}
