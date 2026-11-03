import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import ShowWindow from './components/ShowWindow.jsx'
import './index.css'

// A `marvin show` window (#715) loads this same page with #show=<project>: only the viewer, no tabs.
const showProject = (() => {
  const m = window.location.hash.match(/^#show=([^&]+)/)
  try {
    return m ? decodeURIComponent(m[1]) : null
  } catch {
    return null
  }
})()

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    {showProject ? <ShowWindow project={showProject} /> : <App />}
  </React.StrictMode>
)
