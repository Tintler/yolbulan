import React, { useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronLeft, ChevronRight, Clapperboard, ExternalLink, FileText, Folder, FolderOpen, Play, X } from 'lucide-react'
import { accept, CHECKABLE, clock, folderLabel, STATUS } from './bridge'
import { IconButton, Modal } from './ui'

function Highlighted({ text, spans = [], active = -1, startIndex = 0 }) {
  // The Python bridge reports Unicode character offsets.
  const characters = Array.from(text)
  const parts = []
  let cursor = 0
  spans.forEach(([start, end], index) => {
    if (end <= cursor) return
    parts.push(characters.slice(cursor, start).join(''))
    const match = startIndex + index
    parts.push(<mark key={match} data-match={match} className={match === active ? 'current-match' : undefined}>
      {characters.slice(Math.max(start, cursor), end).join('')}
    </mark>)
    cursor = end
  })
  parts.push(characters.slice(cursor).join(''))
  return parts
}

function Transcript({ entry, segments, onClose, playAt }) {
  const count = segments.reduce((total, segment) => total + (segment.highlights?.length || 0), 0)
  const [active, setActive] = useState(-1)
  const content = useRef(null)
  useEffect(() => {
    if (active >= 0) content.current.querySelector(`[data-match="${active}"]`)?.scrollIntoView({ block: 'center' })
  }, [active])
  let startIndex = 0
  return <Modal title={`Transkript · ${entry.name}`} onClose={onClose} className="transcript-modal" footer={<>
    <IconButton icon={ChevronLeft} label="Önceki eşleşme" disabled={!count}
      onClick={() => setActive((active < 0 ? 0 : active + count - 1) % count)} />
    <span>{count ? `${active + 1} / ${count}` : 'Eşleşme yok'}</span>
    <IconButton icon={ChevronRight} label="Sonraki eşleşme" disabled={!count}
      onClick={() => setActive((active + 1) % count)} />
  </>}>
    <div ref={content} className="transcript-lines">
      {segments.map((segment, index) => {
        const position = startIndex
        startIndex += segment.highlights?.length || 0
        return <div className="transcript-line" key={index}>
          <button className="time-link" onClick={() => { onClose(); playAt(segment.start) }}>
            {clock(segment.start)} – {clock(segment.end)}
          </button>
          <span><Highlighted text={segment.text} spans={segment.highlights} active={active} startIndex={position} /></span>
        </div>
      })}
    </div>
  </Modal>
}

export function Details({ entry, state, api, run }) {
  if (!entry) return <aside className="details details-empty">
    <span className="empty-icon"><Clapperboard aria-hidden="true" /></span>
    <h2>Video ayrıntıları</h2>
    <p>Önizleme ve hedef klasör için listeden bir video seçin.</p>
  </aside>
  return <VideoDetails key={entry.path} entry={entry} state={state} api={api} run={run} />
}

function VideoDetails({ entry, state, api, run }) {
  const [media, setMedia] = useState(null)
  const [segments, setSegments] = useState([])
  const [failedImage, setFailedImage] = useState(false)
  const [playback, setPlayback] = useState(null)
  const [playbackError, setPlaybackError] = useState(false)
  const [preparing, setPreparing] = useState(false)
  const [showTranscript, setShowTranscript] = useState(false)
  const player = useRef(null)
  const playbackRequest = useRef(0)
  const marked = segments.find(segment => segment.highlights?.length)
  const hit = entry.hits?.find(item => item.evidence)
  const excerpt = marked || (hit && { text: hit.evidence, start: hit.start })
  const poster = media?.thumbnail_url || entry.thumbnail_url

  useEffect(() => {
    let active = true
    api.get_preview(entry.path, 0, false).then(accept)
      .then(result => { if (active && playbackRequest.current === 0) setMedia(result) }).catch(() => {})
    return () => { active = false }
  }, [api, entry.path])

  useEffect(() => {
    if (!entry.has_text) return undefined
    let active = true
    api.get_transcript(entry.path).then(accept).then(result => { if (active) setSegments(result.segments || []) }).catch(() => {})
    return () => { active = false }
  }, [api, entry.path, entry.has_text, entry.match])

  useEffect(() => { setFailedImage(false) }, [poster])

  function seek(seconds, source) {
    if (!player.current?.readyState || player.current.getAttribute('src') !== source.url) return
    player.current.currentTime = Math.max(0, seconds - (source.offset || 0))
    player.current.play().catch(() => {})
  }

  async function playAt(seconds = 0) {
    if (playbackError) return run('open_video', entry.path)
    const request = ++playbackRequest.current
    let source = media
    const outsideClip = source?.preview_duration != null &&
      (seconds < source.offset || seconds >= source.offset + source.preview_duration)
    if (!source?.url || outsideClip) {
      setPreparing(true)
      try {
        source = accept(await api.get_preview(entry.path, seconds))
      } catch {
        if (request === playbackRequest.current) setPlaybackError(true)
        return null
      } finally {
        if (request === playbackRequest.current) setPreparing(false)
      }
    }
    if (request !== playbackRequest.current) return null
    if (!source.url) return run('open_video', entry.path)
    setMedia(source)
    setPlayback(seconds)
    seek(seconds, source)
    return null
  }

  const targets = [...new Set([...(state.targets || []), entry.target].filter(Boolean))]
  return <aside className="details" aria-label="Video ayrıntıları">
    <div className="preview">
      {playback !== null && media?.url && !playbackError
        ? <><video ref={player} src={media.url} autoPlay controls aria-label={entry.name}
            onLoadedMetadata={() => seek(playback, media)} onError={() => setPlaybackError(true)} />
          <IconButton icon={X} label="Oynatıcıyı kapat" className="close-player" onClick={() => setPlayback(null)} /></>
        : <button className="preview-button" disabled={preparing} onClick={() => playAt()} title="Videoyu oynat" aria-label="Videoyu oynat">
            {poster && !failedImage ? <img src={poster} alt="" onError={() => setFailedImage(true)} /> : <Clapperboard className="preview-placeholder" aria-hidden="true" />}
            {preparing ? <span className="preparing-preview" role="status">Önizleme hazırlanıyor…</span>
              : <span className="play-badge"><Play size={21} fill="currentColor" aria-hidden="true" /></span>}
          </button>}
    </div>
    {playbackError && <p className="muted preview-note">Önizleme oynatılamadı. Videoyu varsayılan oynatıcıda açabilirsiniz.</p>}
    <div className="video-heading">
      <h2 title={entry.path}>{entry.name}</h2>
      <div className="detail-tools">
        <IconButton icon={FolderOpen} label="Dosyayı klasörde göster" onClick={() => run('reveal_file', entry.path)} />
        <IconButton icon={ExternalLink} label="Videoyu varsayılan oynatıcıda aç" onClick={() => run('open_video', entry.path)} />
      </div>
    </div>
    <section className="detail-section">
      <div className="detail-section-heading">
        <h3>Eşleşen transkript</h3>
        {!!segments.length && <button className="text-button" onClick={() => setShowTranscript(true)}><FileText size={16} />Tam metin</button>}
      </div>
      {excerpt ? <div className="excerpt">
        {typeof excerpt.start === 'number' && <button className="time-link" onClick={() => playAt(excerpt.start)}>{clock(excerpt.start)}</button>}
        <p>“<Highlighted text={excerpt.text} spans={excerpt.highlights} />”</p>
      </div> : <div className="detail-message">
        <span className={`status status-${entry.status}`}>{entry.label || STATUS[entry.status]}</span>
        <span>{entry.note || entry.match || (segments.length ? 'Transkriptte eşleşme bulunamadı.' : 'Bu video için eşleşen transkript yok.')}</span>
      </div>}
    </section>
    <section className="detail-section target-section">
      <h3>Hedef klasör</h3>
      <div className="target-select"><Folder aria-hidden="true" /><select aria-label="Hedef klasör"
        value={entry.target || ''} disabled={!CHECKABLE.has(entry.status)}
        onChange={event => run('set_target', [entry.path], event.target.value || null)}>
        <option value="">Yerinde kalsın</option>
        {targets.map(target => <option value={target} key={target}>{folderLabel(target)}</option>)}
      </select><ChevronDown aria-hidden="true" /></div>
    </section>
    {showTranscript && <Transcript entry={entry} segments={segments} onClose={() => setShowTranscript(false)} playAt={playAt} />}
  </aside>
}
