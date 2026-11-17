import React, { useEffect, useRef } from 'react'
import { X } from 'lucide-react'

export function Brand() {
  return <svg aria-hidden="true" viewBox="0 0 48 48" fill="none" className="brand-mark">
    <path d="M23 42c0-12-1-19-13-28M23 34c2-13 10-23 18-28" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" />
    <path d="m6 14 4-4m26-1 4 4" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" />
  </svg>
}

export function IconButton({ icon: Icon, label, className = '', ...props }) {
  return <button className={`icon-button ${className}`} type="button" title={label} aria-label={label} {...props}>
    <Icon aria-hidden="true" />
  </button>
}

export function Modal({ title, onClose, className = '', children, footer }) {
  const dialog = useRef(null)
  useEffect(() => {
    const element = dialog.current
    element.showModal()
    return () => element.close()
  }, [])
  return <dialog ref={dialog} className={`modal ${className}`} aria-label={title}
    onCancel={event => { event.preventDefault(); onClose() }}
    onClick={event => { if (event.target === event.currentTarget) onClose() }}>
    <div className="modal-shell">
      <header className="modal-header"><h2>{title}</h2><IconButton icon={X} label="Kapat" onClick={onClose} /></header>
      <div className="modal-body">{children}</div>
      {footer && <footer className="modal-footer">{footer}</footer>}
    </div>
  </dialog>
}
