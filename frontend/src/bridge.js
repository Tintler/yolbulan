export function connect() {
  if (window.pywebview?.api) return Promise.resolve(window.pywebview.api)
  return new Promise(resolve => {
    window.addEventListener('pywebviewready', () => resolve(window.pywebview.api), { once: true })
  })
}

export function accept(result) {
  if (!result || result.ok === false) {
    throw new Error(result?.error || 'İşlem tamamlanamadı.')
  }
  return result
}

export const MODE_SPEECH = 'Dosya adı + ses analizi'
export const MODE_NAME = 'Yalnızca dosya adı'

export const STATUS = {
  name: 'Ad eşleşti', speech: 'Ses eşleşti', none: 'Eşleşme yok',
  pending: 'Analiz bekliyor', queued: 'Sırada', working: 'Analiz ediliyor',
  moving: 'Taşınıyor', move_failed: 'Taşınamadı', error: 'Hata',
}

export const CHECKABLE = new Set(['name', 'speech', 'none', 'pending', 'error', 'move_failed'])
export const REANALYZABLE = new Set(['name', 'speech', 'none', 'error', 'move_failed'])

export function folderLabel(folder) {
  return { Incelenecekler: 'İncelenecekler', eslesme_yok: 'Eşleşme yok' }[folder] || folder
}

export function clock(seconds) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds)) return '—'
  const time = Math.max(0, Math.floor(seconds))
  const part = value => String(value).padStart(2, '0')
  const hours = Math.floor(time / 3600)
  const minutes = Math.floor(time / 60) % 60
  return `${hours ? `${part(hours)}:` : ''}${part(minutes)}:${part(time % 60)}`
}

export function searchable(text) {
  return text.toLocaleLowerCase('tr').replace(/ı/g, 'i').normalize('NFD').replace(/\p{M}/gu, '')
}
