import React, { useEffect, useState } from 'react'
import './titlebar.css'

const ICONS = {
  minimize: <path d="M2 8h10" />,
  maximize: <rect x="2" y="2" width="10" height="10" rx=".3" />,
  restore: <path d="M5 4.5V2h7v7H9.5m-7-4.5h7v7h-7z" />,
  close: <path d="m2.5 2.5 9 9m0-9-9 9" />,
}

function CaptionButton({ icon, label, onClick }) {
  return <button type="button" className={`caption-button caption-${icon}`}
    title={label} aria-label={label} onClick={onClick}>
    <svg viewBox="0 0 14 14" width="14" height="14" fill="none" stroke="currentColor"
      strokeWidth="1" aria-hidden="true">{ICONS[icon]}</svg>
  </button>
}

export function TitleBar({ api }) {
  const [visible, setVisible] = useState(false)
  const [maximized, setMaximized] = useState(false)

  useEffect(() => {
    if (!api) return undefined
    let disposed = false
    const syncSize = () => {
      api.window_is_maximized().then(value => {
        if (!disposed) setMaximized(value)
      }).catch(() => {})
    }
    api.window_has_custom_frame().then(value => {
      if (!disposed) setVisible(value)
    }).catch(() => {})
    syncSize()
    window.addEventListener('resize', syncSize)
    return () => {
      disposed = true
      window.removeEventListener('resize', syncSize)
    }
  }, [api])

  if (!visible) return null

  function control(action) {
    api.control_window(action).then(value => {
      if (action === 'toggle_maximize') setMaximized(value)
    }).catch(() => {})
  }

  return <header className="title-bar">
    <span className="title-name">Yolbulan</span>
    <div className="caption-buttons">
      <CaptionButton icon="minimize" label="Simge durumuna küçült" onClick={() => control('minimize')} />
      <CaptionButton icon={maximized ? 'restore' : 'maximize'}
        label={maximized ? 'Önceki boyuta dön' : 'Ekranı kapla'}
        onClick={() => control('toggle_maximize')} />
      <CaptionButton icon="close" label="Kapat" onClick={() => control('close')} />
    </div>
  </header>
}
