import React, { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { ChevronDown, Folder, Search } from 'lucide-react'
import { folderLabel, searchable } from './bridge'
import './editors.css'

const STAY = { value: '', label: 'Yerinde kalsın' }

export function TargetPicker({ value, targets, disabled, onChange }) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [active, setActive] = useState(-1)
  const root = useRef(null)
  const trigger = useRef(null)
  const popup = useRef(null)
  const input = useRef(null)
  const list = useRef(null)
  const listId = useId()
  const query = searchable(search.trim())
  const folders = [...new Set([...(targets || []), value].filter(Boolean))]
  const choices = [STAY, ...folders.map(folder => ({ value: folder, label: folderLabel(folder) }))]
    .filter(option => searchable(option.label).includes(query) || searchable(option.value).includes(query))
  const cursor = Math.min(active, choices.length - 1)
  const optionId = index => `${listId}-${index}`

  useLayoutEffect(() => {
    if (!open || disabled) return undefined
    const panel = popup.current
    function position() {
      const rect = trigger.current.getBoundingClientRect()
      const width = Math.min(Math.max(rect.width, 230), window.innerWidth - 16)
      const below = window.innerHeight - rect.bottom - 12
      const above = rect.top - 12
      const upward = below < 274 && above > below
      panel.style.width = `${width}px`
      panel.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - width - 8))}px`
      panel.style.top = upward ? 'auto' : `${rect.bottom + 4}px`
      panel.style.bottom = upward ? `${window.innerHeight - rect.top + 4}px` : 'auto'
      panel.style.maxHeight = `${Math.min(300, upward ? above : below)}px`
    }
    function dismiss(event) {
      if (!root.current.contains(event.target)) setOpen(false)
    }
    function followScroll(event) {
      if (!(event.target instanceof Node && panel.contains(event.target))) position()
    }
    position()
    input.current.focus()
    document.addEventListener('pointerdown', dismiss)
    window.addEventListener('resize', position)
    window.addEventListener('scroll', followScroll, true)
    return () => {
      document.removeEventListener('pointerdown', dismiss)
      window.removeEventListener('resize', position)
      window.removeEventListener('scroll', followScroll, true)
    }
  }, [open, disabled])

  useEffect(() => {
    if (disabled) setOpen(false)
  }, [disabled])

  useEffect(() => {
    if (open && cursor >= 0) list.current?.children[cursor]?.scrollIntoView({ block: 'nearest' })
  }, [open, cursor, search])

  function show(index = -1) {
    setSearch('')
    setActive(index)
    setOpen(true)
  }

  function close() {
    setOpen(false)
    trigger.current.focus()
  }

  function choose(option) {
    close()
    if (option.value !== value) onChange(option.value || null)
  }

  function navigate(event) {
    if (event.nativeEvent.isComposing) return
    switch (event.key) {
      case 'ArrowDown':
      case 'ArrowUp': {
        event.preventDefault()
        if (!choices.length) return
        const direction = event.key === 'ArrowDown' ? 1 : -1
        setActive(cursor < 0 && direction < 0 ? choices.length - 1 : Math.max(0, Math.min(choices.length - 1, cursor + direction)))
        break
      }
      case 'Enter':
        event.preventDefault()
        if (choices.length) choose(choices[Math.max(0, cursor)])
        break
      case 'Escape':
        event.preventDefault()
        event.stopPropagation()
        close()
        break
    }
  }

  const label = value === undefined ? 'Hedef seç…' : value ? folderLabel(value) : STAY.label
  const expanded = open && !disabled
  return <div className="target-picker" ref={root} onBlur={event => {
    if (event.relatedTarget && !event.currentTarget.contains(event.relatedTarget)) setOpen(false)
  }}>
    <button ref={trigger} className="target-picker-trigger" type="button" disabled={disabled}
      aria-label={`Hedef klasör: ${label}`} aria-haspopup="listbox" aria-expanded={expanded} aria-controls={expanded ? listId : undefined}
      title={label} onClick={() => expanded ? setOpen(false) : show()} onKeyDown={event => {
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          event.preventDefault()
          show(event.key === 'ArrowDown' ? 0 : folders.length)
        }
      }}>
      <Folder size={16} aria-hidden="true" /><span>{label}</span><ChevronDown size={15} aria-hidden="true" />
    </button>
    {expanded && <div className="target-picker-popup" ref={popup}>
      <label className="target-picker-search"><Search size={15} aria-hidden="true" />
        <input ref={input} role="combobox" aria-label="Hedef klasörlerde ara" aria-expanded="true" aria-autocomplete="list"
          aria-controls={listId} aria-activedescendant={cursor >= 0 ? optionId(cursor) : undefined}
          value={search} placeholder="Klasörlerde ara" onChange={event => { setSearch(event.target.value); setActive(0) }}
          onKeyDown={navigate} />
      </label>
      <div ref={list} className="target-picker-list" role="listbox" id={listId} aria-label="Hedef klasörler">
        {choices.map((option, index) => <div className={index === cursor ? 'target-picker-option active' : 'target-picker-option'}
          role="option" aria-selected={option.value === value} id={optionId(index)} key={option.value}
          onMouseDown={event => event.preventDefault()} onClick={() => choose(option)}>{option.label}</div>)}
      </div>
      {!choices.length && <p className="target-picker-empty" role="status">Eşleşen klasör yok.</p>}
    </div>}
  </div>
}
