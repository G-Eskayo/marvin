import { useEffect, useRef, useState } from 'react'
import '@fontsource/saira-condensed/600.css'
import '@fontsource/saira-condensed/800.css'
import '@fontsource/share-tech-mono/400.css'
import './boot.css'
import { shouldPlay } from '../lib/boot_view.js'
import { runBoot } from '../lib/boot_animation.js'

// Celestial-navigation boot sequence (#431, design on #428). Plays over the dashboard on the first load of each
// app launch; the dashboard renders underneath from saved state the whole time, so the boot never delays it.
// Every status it shows is real (electron/main/boot_data.js). Any click or key skips it.

// One request per page load, shared across StrictMode's double effect run (a second IPC call would get show:false).
let request = null
const fetchBoot = () => (request ??= window.api?.boot?.data?.() ?? Promise.resolve({ show: false }))

export default function BootSequence({ onOpenHealth }) {
  const [phase, setPhase] = useState('pending') // pending → playing → done
  const [data, setData] = useState(null)
  const root = useRef(null)
  const openHealth = useRef(onOpenHealth) // a ref, so App re-rendering (health polls) never restarts the boot
  openHealth.current = onOpenHealth

  useEffect(() => {
    let live = true
    fetchBoot()
      .then((res) => {
        if (!live) return
        const play = shouldPlay({
          show: res?.show,
          reducedMotion: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches,
          canAnimate: typeof Element !== 'undefined' && typeof Element.prototype.animate === 'function'
        })
        if (play && res.data) { setData(res.data); setPhase('playing') } else setPhase('done')
      })
      .catch(() => live && setPhase('done'))
    return () => { live = false }
  }, [])

  useEffect(() => {
    if (phase !== 'playing' || !root.current) return
    const boot = runBoot(root.current, data, { onDone: () => setPhase('done'), onOpenHealth: () => openHealth.current?.() })
    window.__marvinBoot = { total: boot.total, seek: boot.seek } // lets recordings seek the real boot frame by frame
    return () => { boot.cancel(); delete window.__marvinBoot }
  }, [phase, data])

  if (phase === 'done') return null
  if (phase === 'pending') return <div className="boot-root" aria-hidden="true" />

  return (
    <div className="boot-root" ref={root} role="presentation" aria-label="MARVIN starting up">
      <svg className="boot-sky" data-b="sky" viewBox="-640 -400 1280 800" preserveAspectRatio="xMidYMid slice">
        <defs>
          <filter id="boot-ml" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="1.6" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
          <filter id="boot-mn" x="-300%" y="-300%" width="700%" height="700%"><feGaussianBlur stdDeviation="2.6" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
          <filter id="boot-mc" x="-400%" y="-400%" width="900%" height="900%"><feGaussianBlur stdDeviation="6" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
          <radialGradient id="boot-mcore" cx="45%" cy="42%" r="60%"><stop offset="0" stopColor="#c8f5d6" /><stop offset=".55" stopColor="#6ff0a0" /><stop offset="1" stopColor="#5ae88a" /></radialGradient>
        </defs>
        <g data-b="field" /><g data-b="mark" /><g data-b="lock" />
      </svg>
      <div className="boot-hud boot-title" data-b="title"><h1>MARVIN</h1><div className="boot-sub">SYSTEMS ONLINE</div></div>
      <div className="boot-check">
        <div className="boot-hdr" data-b="hw"><span>SYSTEM CHECK</span><span data-b="chkN">000/000</span></div>
        <div className="boot-win"><div data-b="fw"><div className="boot-feed" data-b="feed" /></div></div>
        <div className="boot-sum" data-b="sum" />
      </div>
      <div className="boot-hud boot-bar" data-b="bar">
        <div className="boot-lbl"><span>VERIFYING</span><span data-b="barP">000%</span></div>
        <div className="boot-track"><div className="boot-fill" data-b="fill" /></div>
      </div>
      <div className="boot-hud boot-banner" data-b="banner"><span data-b="bannerT" /></div>
      <div className="boot-raster" /><div className="boot-sweep" data-b="sw1" /><div className="boot-sweep" data-b="sw2" />
    </div>
  )
}
