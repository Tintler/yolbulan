import React, { useState } from 'react'
import { FolderOpen, Plus, Save, Trash2 } from 'lucide-react'
import { MODE_NAME, MODE_SPEECH } from './bridge'
import { IconButton } from './ui'

function Field({ label, help, className = '', children }) {
  return <label className={`field ${className}`} title={help}><span>{label}</span>{children}</label>
}

function Choice({ options, ...properties }) {
  return <select {...properties}>{options.map(option => {
    const [value, label] = Array.isArray(option) ? option : [option, option]
    return <option value={value} key={value}>{label}</option>
  })}</select>
}

function PreferencePage({ title, children, saving, onSave, dirty, onReset }) {
  return <form className="preference-page" onSubmit={onSave}>
    <header className="preference-header"><h1>{title}</h1></header>
    <div className="preference-scroll">{children}</div>
    <footer className="preference-footer">
      <button className="secondary button" type="button" onClick={onReset} disabled={!dirty || saving}>Vazgeç</button>
      <button className="primary button" disabled={!dirty || saving}><Save size={16} />{saving ? 'Kaydediliyor…' : 'Kaydet'}</button>
    </footer>
  </form>
}

export function Settings({ state, run }) {
  const [draft, setDraft] = useState(state.settings)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [models, setModels] = useState([])
  const dirty = Object.keys(draft).some(key => draft[key] !== state.settings[key])
  const profiles = state.profiles || {}

  function update(key, value) {
    setDraft(current => ({ ...current, [key]: value, ...(['model', 'batch', 'beam', 'compute'].includes(key) ? { profile: 'Özel' } : {}) }))
  }

  function selectProfile(profile) {
    setDraft(current => ({ ...current, ...profiles[profile], profile,
      ...(profile !== 'Özel' && current.device === 'cpu' ? { compute: 'int8' } : {}) }))
  }

  function selectDevice(device) {
    setDraft(current => ({ ...current, device,
      compute: device === 'cpu' ? 'int8' : profiles[current.profile]?.compute || current.compute }))
  }

  function text(key, properties = {}) {
    return <input value={draft[key] ?? ''} onChange={event => update(key, event.target.value)} {...properties} />
  }

  function number(key, min, max, step = 1) {
    return <input type="number" required min={min} max={max} step={step} value={draft[key]}
      onChange={event => update(key, event.target.value === '' ? '' : Number(event.target.value))} />
  }

  function choice(key, options) {
    const available = options.map(option => Array.isArray(option) ? option[0] : option)
    return <Choice value={draft[key]} options={available.includes(draft[key]) ? options : [...options, draft[key]]}
      onChange={event => update(key, event.target.value)} />
  }

  async function fetchModels() {
    setLoading(true)
    try {
      const result = await run('list_models', draft.lm_host.trim(), draft.lm_port)
      if (result?.models?.length) {
        setModels(result.models)
        if (!draft.lm_model) update('lm_model', result.models[0])
      }
    } finally { setLoading(false) }
  }

  async function pickCuda() {
    const result = await run('browse_folder', draft.cuda_dir)
    if (result?.path) update('cuda_dir', result.path)
  }

  async function save(event) {
    event.preventDefault()
    setSaving(true)
    try {
      const result = await run('save_settings', draft)
      if (result?.settings) setDraft(result.settings)
    } finally { setSaving(false) }
  }

  return <PreferencePage title="Ayarlar" saving={saving} dirty={dirty} onSave={save} onReset={() => setDraft(state.settings)}>
    <div className="settings-grid">
      <section className="setting-panel settings-general">
        <h2>Genel</h2>
        <div className="settings-fields">
          <Field label="Görünüm">{choice('theme', [['system', 'Sistem'], ['light', 'Açık'], ['dark', 'Koyu']])}</Field>
          <Field label="Analiz modu">{choice('mode', [MODE_SPEECH, MODE_NAME])}</Field>
        </div>
      </section>
      <section className="setting-panel">
        <h2>Konuşmayı yazıya dökme</h2>
        <div className="settings-fields">
          <Field label="Whisper profili" help="Hazır profiller model ve işlem ayarlarını birlikte uygular.">
            <Choice value={draft.profile} options={[...Object.keys(profiles), 'Özel']} onChange={event => selectProfile(event.target.value)} />
          </Field>
          <Field label="Model">{choice('model', ['small', 'medium', 'large-v3', 'turbo'])}</Field>
          <Field label="Aygıt"><Choice value={draft.device} options={[["cuda", "NVIDIA GPU (CUDA)"], ["cpu", "CPU"]]}
            onChange={event => selectDevice(event.target.value)} /></Field>
          <Field label="Hesaplama türü">{choice('compute', ['float16', 'int8_float16', 'int8'])}</Field>
          <Field label="Toplu iş boyutu" help="Aynı anda işlenecek ses parçası sayısı.">{number('batch', 1, 32)}</Field>
          <Field label="Beam" help="Yüksek değer daha geniş bir arama yapar.">{number('beam', 1, 10)}</Field>
          <div className="full-field">
            <Field label="CUDA DLL klasörü">{text('cuda_dir', { placeholder: 'cublas64_12.dll ve cudnn64_9.dll içeren klasör' })}</Field>
            <button className="secondary button" type="button" onClick={pickCuda}><FolderOpen size={17} />Gözat…</button>
          </div>
        </div>
      </section>
      <section className="setting-panel">
        <h2>LM Studio</h2>
        <div className="settings-fields">
          <Field label="IP adresi">{text('lm_host', { placeholder: '127.0.0.1' })}</Field>
          <Field label="Port">{number('lm_port', 1, 65535)}</Field>
          <div className="full-field">
            <Field label="Metin modeli">{text('lm_model', { list: 'loaded-models', placeholder: 'Model kimliği' })}</Field>
            <datalist id="loaded-models">{models.map(model => <option key={model} value={model} />)}</datalist>
            <button className="secondary button" type="button" disabled={loading || !draft.lm_port} onClick={fetchModels}>
              {loading ? 'Getiriliyor…' : 'Modelleri getir'}
            </button>
          </div>
          <Field label="Thinking">{choice('lm_thinking', [['model', 'Model ayarı'], ['off', 'Kapalı']])}</Field>
          <Field label="JSON yeniden deneme">{number('lm_retries', 0, 5)}</Field>
          <label className="boolean-field"><input type="checkbox" className="check" checked={draft.lm_whole}
            onChange={event => update('lm_whole', event.target.checked)} />Transkriptin tamamı tek istekte</label>
          {!draft.lm_whole && <Field label="Parça boyutu (karakter)">{number('lm_chunk_size', 4000, 200000)}</Field>}
        </div>
      </section>
    </div>
  </PreferencePage>
}

const blankRule = { folder: '', name_terms: '', name_negative_terms: '', audio_description: '' }
const editRules = rules => rules.map(rule => ({ ...rule, name_terms: rule.name_terms.join(', '),
  name_negative_terms: rule.name_negative_terms.join(', '), id: crypto.randomUUID() }))
const terms = value => value.split(',').map(term => term.trim()).filter(Boolean)

export function Rules({ state, run }) {
  const [draft, setDraft] = useState(() => editRules(state.rules))
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)

  function update(id, key, value) {
    setDraft(rules => rules.map(rule => rule.id === id ? { ...rule, [key]: value } : rule))
    setDirty(true)
  }

  function reset(rules) {
    setDraft(editRules(rules))
    setDirty(false)
  }

  async function save(event) {
    event.preventDefault()
    setSaving(true)
    const rules = draft.map(rule => ({ folder: rule.folder.trim(), name_terms: terms(rule.name_terms),
      name_negative_terms: terms(rule.name_negative_terms), audio_description: rule.audio_description.trim() }))
      .filter(rule => rule.folder || rule.name_terms.length || rule.name_negative_terms.length || rule.audio_description)
    try {
      const result = await run('save_rules', rules)
      if (result?.rules) reset(result.rules)
    } finally { setSaving(false) }
  }

  return <PreferencePage title="Kurallar" saving={saving} dirty={dirty} onSave={save} onReset={() => reset(state.rules)}>
    <p className="preference-intro">Her hedef için dosya adı terimi veya ses içeriği tanımı girin. Terimleri virgülle ayırın.</p>
    <div className="rule-list">
      {draft.map(rule => <section className="rule-card" key={rule.id}>
        <div className="rule-fields">
          <Field label="Hedef alt klasör"><input value={rule.folder} onChange={event => update(rule.id, 'folder', event.target.value)} /></Field>
          <Field label="Dosya adı terimleri (+)"><input value={rule.name_terms} onChange={event => update(rule.id, 'name_terms', event.target.value)} /></Field>
          <Field label="Dosya adı engelleri (−)"><input value={rule.name_negative_terms} onChange={event => update(rule.id, 'name_negative_terms', event.target.value)} /></Field>
          <Field label="Ses içeriği tanımı (AI)" className="rule-audio"><textarea rows={2} value={rule.audio_description}
            onChange={event => update(rule.id, 'audio_description', event.target.value)} /></Field>
        </div>
        <IconButton icon={Trash2} label={rule.folder ? `${rule.folder} kuralını sil` : 'Kuralı sil'}
          onClick={() => { setDraft(rules => rules.filter(item => item.id !== rule.id)); setDirty(true) }} />
      </section>)}
    </div>
    <button className="secondary button" type="button" onClick={() => {
      setDraft(rules => [...rules, { ...blankRule, id: crypto.randomUUID() }]); setDirty(true)
    }}><Plus size={17} />Kural ekle</button>
  </PreferencePage>
}
