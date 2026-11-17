import React, { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDown, ArrowRight, ArrowUp, ChevronDown, Clapperboard, Filter, Folder, FolderOpen, Grid2X2, List, ListChecks, RefreshCw, Search, Undo2, X } from 'lucide-react'
import { CHECKABLE, clock, folderLabel, MODE_NAME, MODE_SPEECH, REANALYZABLE, searchable, STATUS } from './bridge'
import { Details } from './details'
import { IconButton } from './ui'

const FILTERS = [
  ['all', 'Tümü', () => true],
  ['matched', 'Eşleşenler', entry => ['name', 'speech'].includes(entry.status)],
  ['review', 'İncelenecekler', entry => !['name', 'speech', 'moving'].includes(entry.status) || entry.target === 'Incelenecekler'],
  ['name', 'Ad eşleşti', entry => entry.status === 'name'],
  ['speech', 'Ses eşleşti', entry => entry.status === 'speech'],
  ['none', 'Eşleşme yok', entry => entry.status === 'none'],
  ['pending', 'Analiz bekliyor', entry => ['pending', 'queued', 'working'].includes(entry.status)],
  ['error', 'Hata', entry => ['error', 'move_failed'].includes(entry.status)],
]

const names = new Intl.Collator('tr', { numeric: true, sensitivity: 'base' })

function Checkbox({ label, checked, indeterminate, ...props }) {
  const input = useRef(null)
  useEffect(() => { input.current.indeterminate = Boolean(indeterminate) }, [indeterminate])
  return <input ref={input} className="check" type="checkbox" aria-label={label} title={label} checked={checked} {...props} />
}

function Thumbnail({ url }) {
  const [failed, setFailed] = useState(false)
  useEffect(() => { setFailed(false) }, [url])
  return <span className="thumbnail">
    {url && !failed ? <img loading="lazy" decoding="async" src={url} alt="" onError={() => setFailed(true)} /> : <Clapperboard size={22} aria-hidden="true" />}
  </span>
}

function SourcePicker({ source, state, run, busy }) {
  const [open, setOpen] = useState(false)
  const [path, setPath] = useState(source)
  const root = useRef(null)
  const pathField = useRef(null)
  const label = source.replace(/[\\/]+$/, '').split(/[\\/]+/).slice(-2).join(' / ')

  useEffect(() => setPath(source), [source])
  useEffect(() => {
    if (!open) return undefined
    pathField.current.focus()
    function dismiss(event) {
      if ((event.type === 'pointerdown' && !root.current.contains(event.target)) || event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', dismiss)
    document.addEventListener('keydown', dismiss)
    return () => {
      document.removeEventListener('pointerdown', dismiss)
      document.removeEventListener('keydown', dismiss)
    }
  }, [open])

  async function browse() {
    const result = await run('browse_folder', path)
    if (result?.path) {
      setPath(result.path)
      await run('save_settings', { source: result.path })
    }
  }

  async function scan(event) {
    event.preventDefault()
    if (await run('scan_names', path.trim())) setOpen(false)
  }

  return <div ref={root} className="source-picker">
    <button type="button" className="source-toggle" onClick={() => setOpen(!open)}
      aria-label="Kaynak klasör" aria-expanded={open} title={source || 'Kaynak klasör seç'}>
      <Folder aria-hidden="true" /><span>{source ? label : 'Kaynak klasör seç'}</span><ChevronDown aria-hidden="true" />
    </button>
    {open && <form className="source-popover" onSubmit={scan}>
      <label className="field"><span>Kaynak klasör</span><input ref={pathField} value={path} disabled={busy}
        placeholder="Videoların bulunduğu klasör" onChange={event => setPath(event.target.value)} required /></label>
      <label className="field"><span>Analiz modu</span><select value={state.settings.mode} disabled={state.jobs.includes('analyze')}
        onChange={event => run('set_mode', event.target.value)}>
        <option>{MODE_SPEECH}</option><option>{MODE_NAME}</option>
      </select></label>
      <div className="form-actions">
        <button className="secondary button" type="button" disabled={busy} onClick={browse}><FolderOpen size={17} />Gözat…</button>
        <button className="primary button" disabled={busy || !path.trim()}><RefreshCw size={16} />Adları tara</button>
      </div>
    </form>}
  </div>
}

function EmptyQueue({ source, hasEntries, busy, run }) {
  async function pickAndScan() {
    const folder = await run('browse_folder', source)
    if (folder?.path) {
      await run('save_settings', { source: folder.path })
      await run('scan_names', folder.path)
    }
  }
  return <div className="queue-empty">
    <span className="empty-icon"><FolderOpen aria-hidden="true" /></span>
    <h2>{hasEntries ? 'Bu görünümde video yok' : 'Video kuyruğu boş'}</h2>
    <p>{hasEntries ? 'Aramayı veya filtreyi değiştirin.' : 'Videolarınızı listelemek için kaynak klasörü tarayın.'}</p>
    {!hasEntries && <button className="primary button" disabled={busy}
      onClick={() => source ? run('scan_names', source) : pickAndScan()}>
      {source ? <RefreshCw size={17} /> : <FolderOpen size={18} />}{source ? 'Adları tara' : 'Klasör seç ve tara'}
    </button>}
    {!hasEntries && source && <button className="text-button" disabled={busy} onClick={pickAndScan}>Başka klasör seç</button>}
  </div>
}

export function Queue({ state, api, run, setModal, view, setView }) {
  const { entries, settings, jobs } = state
  const [filter, setFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState({ key: 'name', direction: 1 })
  const [selection, setSelection] = useState({ active: null, anchor: null, paths: [] })
  const [context, setContext] = useState(null)
  const [filterOpen, setFilterOpen] = useState(false)
  const listRef = useRef(null)
  const source = settings.source || ''
  const busy = Boolean(jobs.length)
  const matched = entries.filter(entry => entry.checked && entry.target && CHECKABLE.has(entry.status))
  const pending = entries.filter(entry => entry.status === 'pending').length
  const analyzing = jobs.includes('analyze')
  const nameOnly = settings.mode === MODE_NAME

  const visible = useMemo(() => {
    const query = searchable(search.trim())
    const predicate = FILTERS.find(([key]) => key === filter)[2]
    return entries.filter(entry => predicate(entry) && (!query ||
      searchable([entry.name, entry.path, entry.match, entry.target, STATUS[entry.status]].filter(Boolean).join(' ')).includes(query)))
      .sort((first, second) => {
        if (sort.key === 'duration') {
          if (first.duration == null && second.duration != null) return 1
          if (second.duration == null && first.duration != null) return -1
          const ordered = (first.duration || 0) - (second.duration || 0)
          if (ordered) return sort.direction * ordered
        }
        return sort.direction * names.compare(first[sort.key] || first.name, second[sort.key] || second.name) ||
          names.compare(first.path, second.path)
      })
  }, [entries, filter, search, sort])
  const active = visible.find(entry => entry.path === selection.active) || visible[0]
  const selectionPaths = new Set(selection.paths)
  const selected = new Set(visible.filter(entry => selectionPaths.has(entry.path)).map(entry => entry.path))
  if (!selected.size && active) selected.add(active.path)
  const checkable = visible.filter(entry => entry.target && CHECKABLE.has(entry.status))
  const visibleChecked = checkable.filter(entry => entry.checked).length
  const allChecked = checkable.length > 0 && visibleChecked === checkable.length

  useEffect(() => {
    if (!context && !filterOpen) return undefined
    function dismiss(event) {
      if (event.key === 'Escape' || (event.type === 'pointerdown' && !event.target.closest('.floating-menu, .filter-options'))) {
        setContext(null)
        setFilterOpen(false)
      }
    }
    document.addEventListener('pointerdown', dismiss)
    document.addEventListener('keydown', dismiss)
    return () => {
      document.removeEventListener('pointerdown', dismiss)
      document.removeEventListener('keydown', dismiss)
    }
  }, [context, filterOpen])

  function select(entry, event = {}) {
    if (event.shiftKey) {
      const anchor = visible.findIndex(item => item.path === (selection.anchor || active?.path))
      const index = visible.indexOf(entry)
      const start = anchor < 0 ? index : anchor
      const paths = visible.slice(Math.min(start, index), Math.max(start, index) + 1).map(item => item.path)
      setSelection({ active: entry.path, anchor: visible[start].path,
        paths: event.ctrlKey || event.metaKey ? [...new Set([...selected, ...paths])] : paths })
    } else if (event.ctrlKey || event.metaKey) {
      const paths = new Set(selected)
      if (paths.has(entry.path)) paths.delete(entry.path)
      else paths.add(entry.path)
      setSelection({ active: entry.path, anchor: entry.path, paths: [...paths] })
    } else setSelection({ active: entry.path, anchor: entry.path, paths: [entry.path] })
  }

  function toggle(entry) {
    if (!CHECKABLE.has(entry.status)) return
    run('set_checked', [entry.path], !entry.checked)
  }

  function toggleSelection(rows) {
    const eligible = rows.filter(entry => CHECKABLE.has(entry.status))
    run('set_checked', eligible.map(entry => entry.path), !eligible.every(entry => entry.checked))
  }

  function keyboard(event, entry, index) {
    if (event.currentTarget !== event.target) return
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      if (event.key === ' ') toggleSelection(visible.filter(row => selected.has(row.path)))
      else select(entry, event)
    }
    if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
      event.preventDefault()
      const next = Math.max(0, Math.min(visible.length - 1, index + (event.key === 'ArrowUp' ? -1 : 1)))
      select(visible[next], event)
      listRef.current.querySelector(`[data-row="${next}"]`)?.focus()
    }
  }

  function order(key) {
    if (sort.key === key) setSort({ key, direction: -sort.direction })
    else setSort({ key, direction: 1 })
  }

  function sortHeading(label, key) {
    const Arrow = sort.direction === 1 ? ArrowUp : ArrowDown
    return <button type="button" className="sort-heading" onClick={() => order(key)}>
      {label}{sort.key === key && <Arrow size={14} aria-hidden="true" />}
    </button>
  }

  const progress = state.progress || {}
  return <>
    <div className={`workspace is-${view}`}>
      <section className="queue" aria-label="Video kuyruğu">
        <div className="queue-tools">
          <div className="queue-top">
            <h1>Video kuyruğu</h1>
            <SourcePicker source={source} state={state} run={run} busy={busy} />
            <div className="view-toggle" role="group" aria-label="Liste görünümü">
              <button type="button" onClick={() => setView('compact')} aria-pressed={view === 'compact'}><List size={17} />Kompakt</button>
              <button type="button" onClick={() => setView('visual')} aria-pressed={view === 'visual'}><Grid2X2 size={17} />Görselli</button>
            </div>
          </div>
          <div className="queue-toolbar">
            <div className="filter-group" role="group" aria-label="Video filtreleri">
              {FILTERS.slice(0, 3).map(([key, label, predicate]) => <button className="pill" type="button" key={key}
                title={`${entries.filter(predicate).length} video`} aria-pressed={key === filter} onClick={() => setFilter(key)}>{label}</button>)}
              <div className="filter-options">
                <IconButton icon={Filter} label="Duruma göre filtrele" aria-expanded={filterOpen} onClick={() => setFilterOpen(!filterOpen)}
                  className={FILTERS.slice(3).some(([key]) => key === filter) ? 'active-filter' : ''} />
                {filterOpen && <div className="floating-menu">
                  {FILTERS.slice(3).map(([key, label, predicate]) => <button type="button" key={key}
                    aria-pressed={key === filter} onClick={() => { setFilter(key); setFilterOpen(false) }}>
                    {label}<span>{entries.filter(predicate).length}</span>
                  </button>)}
                </div>}
              </div>
            </div>
            <div className="queue-actions">
              <label className="queue-search"><Search size={16} aria-hidden="true" />
                <input aria-label="Videolarda ara" placeholder="Ara" value={search} onChange={event => setSearch(event.target.value)} />
                {search && <IconButton icon={X} label="Aramayı temizle" onClick={() => setSearch('')} />}
              </label>
              <IconButton icon={RefreshCw} label="Adları tara" disabled={busy || !source} onClick={() => run('scan_names', source)} />
            </div>
          </div>
          {(analyzing || pending > 0 && !nameOnly) && <div className="analysis-bar">
            {analyzing ? <>
              <span title={progress.label}>{progress.label || 'Ses analizi sürüyor'}</span>
              <progress max={progress.total || 1} value={progress.current || 0} aria-label="Ses analizi ilerlemesi" />
              <button className="text-button" disabled={progress.cancelled} onClick={() => run('cancel_analysis')}>Durdur</button>
            </> : <button className="text-button" disabled={busy} onClick={() => run('start_analysis')}>Sesi analiz et ({pending})</button>}
          </div>}
        </div>
        {visible.length ? <div className="list-scroll" ref={listRef} onScroll={context ? () => setContext(null) : undefined}>
          <table className="video-table">
            <thead><tr>
              <th className="check-cell"><Checkbox label="Görünen hedefli videoları işaretle" checked={allChecked}
                indeterminate={!allChecked && visibleChecked > 0} disabled={!checkable.length}
                onChange={() => run('set_checked', checkable.map(entry => entry.path), !allChecked)} /></th>
              {view === 'visual' && <th className="thumbnail-cell" aria-label="Küçük resim" />}
              <th className="filename-cell" aria-sort={sort.key === 'name' ? sort.direction === 1 ? 'ascending' : 'descending' : 'none'}>{sortHeading('Dosya adı', 'name')}</th>
              {view === 'compact' && <th className="duration-cell" aria-sort={sort.key === 'duration' ? sort.direction === 1 ? 'ascending' : 'descending' : 'none'}>{sortHeading('Süre', 'duration')}</th>}
              <th className="folder-cell" aria-sort={sort.key === 'target' ? sort.direction === 1 ? 'ascending' : 'descending' : 'none'}>{sortHeading('Önerilen klasör', 'target')}</th>
            </tr></thead>
            <tbody>{visible.map((entry, index) => <tr key={entry.path} tabIndex={active?.path === entry.path ? 0 : -1}
              data-row={index} aria-selected={selected.has(entry.path)} className={selected.has(entry.path) ? 'selected-row' : ''}
              onClick={event => select(entry, event)} onKeyDown={event => keyboard(event, entry, index)}
              onDoubleClick={() => run('open_video', entry.path)} onContextMenu={event => {
                event.preventDefault()
                const rows = selected.has(entry.path) ? visible.filter(row => selected.has(row.path)) : [entry]
                if (selected.has(entry.path)) setSelection(current => ({ ...current, active: entry.path, paths: [...selected] }))
                else select(entry)
                setContext({ entry, rows, x: Math.max(2, Math.min(event.clientX, window.innerWidth - 245)),
                  y: Math.max(2, Math.min(event.clientY, window.innerHeight - 250)) })
              }}>
              <td className="check-cell"><Checkbox label={`${entry.name} ${entry.checked ? 'işaretini kaldır' : 'işaretle'}`}
                checked={Boolean(entry.checked)} disabled={!CHECKABLE.has(entry.status)} onChange={() => toggle(entry)}
                onClick={event => { event.stopPropagation(); if (!selected.has(entry.path)) select(entry) }}
                onDoubleClick={event => event.stopPropagation()} /></td>
              {view === 'visual' && <td className="thumbnail-cell"><Thumbnail url={entry.thumbnail_url} /></td>}
              <td className="filename-cell"><span title={entry.path}>{entry.name}</span></td>
              {view === 'compact' && <td className="duration-cell">{clock(entry.duration)}</td>}
              <td className="folder-cell"><span className={!entry.target ? 'muted' : undefined}
                title={entry.note || entry.label || STATUS[entry.status]}>
                <Folder aria-hidden="true" />{entry.target ? folderLabel(entry.target) : entry.label || STATUS[entry.status]}
              </span></td>
            </tr>)}</tbody>
          </table>
        </div> : <EmptyQueue source={source} hasEntries={Boolean(entries.length)} busy={busy} run={run} />}
      </section>
      <Details entry={active} state={state} api={api} run={run} />
    </div>
    <footer className="queue-footer">
      <strong>{matched.length} video seçildi</strong>
      <div className="footer-actions">
        <IconButton icon={X} label="İşaretleri temizle" disabled={!matched.length}
          onClick={() => run('set_checked', matched.map(entry => entry.path), false)} />
        <IconButton icon={ListChecks} label="Günlük" onClick={() => setModal({ name: 'logs' })} />
        <IconButton icon={Undo2} label="Son taşımayı geri al" disabled={busy || !state.can_undo}
          onClick={() => setModal({ name: 'undo' })} />
      </div>
      <button className="primary move-button" disabled={!matched.length || jobs.includes('move') || jobs.includes('undo')}
        onClick={() => run('move_checked')}>
        {jobs.includes('move') ? 'Taşınıyor…' : matched.length ? `${matched.length} videoyu taşı` : 'Seçilenleri taşı'}<ArrowRight aria-hidden="true" />
      </button>
    </footer>
    {context && <div className="floating-menu context-menu" style={{ left: context.x, top: context.y }}>
      <button disabled={!context.rows.some(row => CHECKABLE.has(row.status))} onClick={() => { toggleSelection(context.rows); setContext(null) }}>
        {context.rows.filter(row => CHECKABLE.has(row.status)).every(row => row.checked) ? 'İşareti kaldır' : 'İşaretle'}</button>
      <label className="context-target"><span>Hedef klasör</span><select defaultValue="__choose__" disabled={!context.rows.some(row => CHECKABLE.has(row.status))}
        onChange={event => { run('set_target', context.rows.map(row => row.path), event.target.value || null); setContext(null) }}>
        <option value="__choose__" disabled>Hedef seç…</option><option value="">Yerinde kalsın</option>
        {state.targets.map(folder => <option value={folder} key={folder}>{folderLabel(folder)}</option>)}
      </select></label>
      {!nameOnly && <button disabled={!context.rows.some(row => REANALYZABLE.has(row.status))}
        onClick={() => { run('queue_for_speech', context.rows.map(row => row.path)); setContext(null) }}>Ses analizine ekle</button>}
      {context.rows.length === 1 && <>
        <button onClick={() => { run('open_video', context.entry.path); setContext(null) }}>Videoyu aç</button>
        <button onClick={() => { run('reveal_file', context.entry.path); setContext(null) }}>Dosyayı klasörde göster</button>
      </>}
    </div>}
  </>
}
