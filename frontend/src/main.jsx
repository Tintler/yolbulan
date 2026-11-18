import React, { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { CircleAlert, Folder, Settings as SettingsIcon, SlidersHorizontal, Undo2, X } from 'lucide-react'
import { accept, connect } from './bridge'
import { Queue } from './queue'
import { Rules, Settings } from './preferences'
import { IconButton, Modal } from './ui'
import { TitleBar } from './titlebar'
import './style.css'
import './queue-status.css'

const RAIL = [['queue', 'Video kuyruğu', Folder], ['rules', 'Kurallar', SlidersHorizontal], ['settings', 'Ayarlar', SettingsIcon]]
const SYSTEM_THEME = matchMedia('(prefers-color-scheme: dark)')

function App() {
  const [api, setApi] = useState(null)
  const [state, setState] = useState(null)
  const [page, setPage] = useState('queue')
  const [view, setView] = useState('compact')
  const [modal, setModal] = useState(null)
  const [message, setMessage] = useState(null)
  const [systemTheme, setSystemTheme] = useState(() => SYSTEM_THEME.matches ? 'dark' : 'light')
  const confirmedNotice = useRef('')
  const revision = useRef(0)
  const commands = useRef(Promise.resolve())
  const ready = Boolean(state)
  const theme = state?.settings.theme || 'system'
  const resolvedTheme = theme === 'system' ? systemTheme : theme

  useEffect(() => { connect().then(setApi) }, [])

  useEffect(() => {
    const update = ({ matches }) => setSystemTheme(matches ? 'dark' : 'light')
    SYSTEM_THEME.addEventListener('change', update)
    update(SYSTEM_THEME)
    return () => SYSTEM_THEME.removeEventListener('change', update)
  }, [])

  useLayoutEffect(() => {
    document.documentElement.dataset.theme = resolvedTheme
  }, [resolvedTheme])

  useEffect(() => {
    if (ready) api.set_window_theme(resolvedTheme).catch(() => {})
  }, [api, ready, resolvedTheme, systemTheme])

  useEffect(() => {
    if (!api) return undefined
    let cancelled = false
    let timer
    async function poll() {
      const marker = revision.current
      try {
        const snapshot = accept(await api.get_state())
        if (!cancelled && marker === revision.current) {
          setState(snapshot)
          if (snapshot.notice && snapshot.notice !== confirmedNotice.current) {
            confirmedNotice.current = snapshot.notice
            setMessage({ text: snapshot.notice })
          }
        }
      } catch (error) {
        if (!cancelled) setMessage({ text: error.message, error: true })
      } finally {
        if (!cancelled) timer = setTimeout(poll, 800)
      }
    }
    poll()
    return () => { cancelled = true; clearTimeout(timer) }
  }, [api])

  useEffect(() => {
    if (!message || message.error) return undefined
    const timer = setTimeout(() => setMessage(null), 5500)
    return () => clearTimeout(timer)
  }, [message])

  function run(method, ...args) {
    const invoke = async () => {
      revision.current++
      try {
        const result = await api[method](...args)
        const snapshot = result?.state || result
        if (snapshot?.entries && snapshot?.settings) setState(snapshot)
        if (snapshot?.notice && snapshot.notice !== confirmedNotice.current) {
          confirmedNotice.current = snapshot.notice
          setMessage({ text: snapshot.notice })
        }
        return accept(result)
      } catch (error) {
        setMessage({ text: error.message, error: true })
        return null
      } finally { revision.current++ }
    }

    if (['list_models', 'browse_folder', 'open_video', 'reveal_file'].includes(method)) return invoke()
    const next = commands.current.then(invoke)
    commands.current = next
    return next
  }

  return <div className="app-shell">
    <TitleBar api={api} />
    <nav className="rail" aria-label="Yolbulan">
      <div className="rail-links">
        {RAIL.map(([key, label, icon]) => <IconButton key={key} icon={icon} label={label}
          aria-current={page === key ? 'page' : undefined} disabled={!state} onClick={() => setPage(key)} />)}
      </div>
    </nav>
    <main className="main-panel">
      {!state ? <div className="startup" role="status">Yolbulan açılıyor…</div> : <>
        <div className="queue-page" hidden={page !== 'queue'}>
          <Queue state={state} api={api} run={run} setModal={setModal} view={view} setView={setView} />
        </div>
        {page === 'rules' && <Rules state={state} run={run} />}
        {page === 'settings' && <Settings state={state} run={run} />}
      </>}
    </main>
    {modal?.name === 'logs' && <Modal title="İşlem günlüğü" onClose={() => setModal(null)}>
      {state.logs?.length ? <pre className="log-view">{state.logs.join('\n')}</pre> : <p>Henüz işlem kaydı yok.</p>}
    </Modal>}
    {modal?.name === 'undo' && <Modal title="Son taşımayı geri al" onClose={() => setModal(null)} footer={<>
      <button className="secondary button" onClick={() => setModal(null)}>Vazgeç</button>
      <button className="primary button" onClick={() => { setModal(null); run('undo') }}><Undo2 size={17} />Geri al</button>
    </>}><p>Son taşıma işleminde taşınan ve sonrasında değişmemiş videolar eski yerlerine dönsün mü?</p></Modal>}
    {message && <div className={`toast ${message.error ? 'toast-error' : ''}`} role={message.error ? 'alert' : 'status'}>
      {message.error && <CircleAlert size={18} aria-hidden="true" />}<span>{message.text}</span>
      <IconButton icon={X} label="Bildirimi kapat" onClick={() => setMessage(null)} />
    </div>}
  </div>
}

createRoot(document.getElementById('root')).render(<App />)
