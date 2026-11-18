"""Python bridge for the Yolbulan desktop webview."""

import copy
import gc
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import traceback
import unicodedata
from collections import deque
from functools import wraps
from pathlib import Path

import ayikla as core
import ses_yonlendirme as audio_ai
from yolbulan_media import MediaCatalog


BASE = Path(__file__).resolve().parent
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else BASE
SETTINGS = APP_DIR / 'calisma_verisi' / 'gui_settings.json'
MODE_SPEECH, MODE_NAME = 'Dosya adı + ses analizi', 'Yalnızca dosya adı'
REVIEW, NO_MATCH, STAY = 'Incelenecekler', 'eslesme_yok', '— yerinde kalsın'
PROFILES = {
    'Hızlı': {'model': 'small', 'batch': 16, 'beam': 1, 'compute': 'float16'},
    'Dengeli': {'model': 'small', 'batch': 8, 'beam': 5, 'compute': 'float16'},
    'Hassas': {'model': 'large-v3', 'batch': 8, 'beam': 5, 'compute': 'float16'},
}
DEFAULTS = {'source': '', 'mode': MODE_SPEECH, 'theme': 'system', 'profile': 'Dengeli', 'model': 'small',
            'batch': 8, 'beam': 5, 'device': 'cuda', 'compute': 'float16', 'cuda_dir': '',
            'lm_host': '127.0.0.1', 'lm_port': 1234, 'lm_model': '', 'lm_thinking': 'model',
            'lm_whole': True, 'lm_chunk_size': 12000, 'lm_retries': 2}
CHOICES = {'mode': (MODE_SPEECH, MODE_NAME), 'theme': ('system', 'light', 'dark'),
           'profile': (*PROFILES, 'Özel'),
           'model': ('small', 'medium', 'large-v3', 'turbo'), 'device': ('cpu', 'cuda'),
           'compute': ('float16', 'int8_float16', 'int8'), 'lm_thinking': ('off', 'model')}
RANGES = {'batch': (1, 32), 'beam': (1, 10), 'lm_port': (1, 65535),
          'lm_chunk_size': (4000, 200000), 'lm_retries': (0, 5)}
CHECKABLE = {'name', 'speech', 'none', 'pending', 'error', 'move_failed'}
REANALYZABLE = {'name', 'speech', 'none', 'error', 'move_failed'}
_cuda_handles = {}


def configure_cuda(settings):
    if settings['device'] != 'cuda':
        return
    dlls = ('cublas64_12.dll', 'cudnn64_9.dll')
    if settings['cuda_dir']:
        path = Path(settings['cuda_dir']).resolve()
        if not all((path / name).is_file() for name in dlls):
            raise ValueError('CUDA DLL klasöründe cublas64_12.dll ve cudnn64_9.dll bulunmalı.')
        if path not in _cuda_handles:
            if hasattr(os, 'add_dll_directory'):
                _cuda_handles[path] = os.add_dll_directory(str(path))
            else:
                _cuda_handles[path] = None
            os.environ['PATH'] = str(path) + os.pathsep + os.environ.get('PATH', '')
    elif not all(shutil.which(name) for name in dlls):
        raise ValueError('CUDA DLL dosyaları bulunamadı. Ayarlar’dan CUDA DLL klasörünü seçin veya CPU kullanın.')


def _settings_values(values):
    changes = {}
    for key, value in values.items():
        if key not in DEFAULTS:
            continue
        if type(value) is not type(DEFAULTS[key]):
            raise ValueError(f'Ayar değeri geçersiz ({key}).')
        if isinstance(value, str):
            value = value.strip()
        if key in CHOICES and value not in CHOICES[key]:
            raise ValueError(f'Ayar seçeneği geçersiz ({key}).')
        if key in RANGES and not RANGES[key][0] <= value <= RANGES[key][1]:
            raise ValueError(f'Ayar aralık dışında ({key}).')
        changes[key] = value
    return changes


def _rules_values(values):
    if not isinstance(values, list) or not all(isinstance(rule, dict) for rule in values):
        raise ValueError('Kurallar bir liste olmalı.')
    normalized = []
    for rule in values:
        folder = rule.get('folder', '')
        names = core.rule_terms(rule, 'name')
        negatives = rule.get('name_negative_terms', [])
        if not isinstance(folder, str) or any(not isinstance(terms, list) or
                not all(isinstance(term, str) for term in terms) for terms in (names, negatives)):
            raise ValueError('Her kural bir klasör ve metin terimlerinden oluşmalı.')
        audio = rule.get('audio_description')
        if audio is None:
            audio = ', '.join(core.rule_terms(rule, 'speech'))
        if not isinstance(audio, str):
            raise ValueError(f'{folder}: Ses içeriği tanımı bir metin olmalı.')
        normalized.append({'folder': folder.strip(), 'name_terms': [term.strip() for term in names if term.strip()],
                           'name_negative_terms': [term.strip() for term in negatives if term.strip()],
                           'audio_description': audio.strip()})
    core.config_load({'rules': normalized})
    return sorted(normalized, key=lambda rule: rule['folder'].casefold())


def _target_for(hits):
    if not hits:
        return None
    return hits[0]['folder'] if len(hits) == 1 else REVIEW


def _match_text(hits):
    if any('start' in hit for hit in hits):
        return ', '.join(f'{hit["folder"]} {audio_ai.stamp(hit["start"])}' for hit in hits)
    if len(hits) > 1:
        return ' · '.join(f'{hit["folder"]}: {", ".join(hit["terms"])}' for hit in hits)
    return ', '.join(term for hit in hits for term in hit['terms'])


def _highlights(text, terms):
    """Return Unicode character offsets for matches in the source text."""
    characters, positions = [], []
    for offset, char in enumerate(text):
        for folded in unicodedata.normalize('NFD', char.casefold().replace('ı', 'i')):
            if not unicodedata.combining(folded):
                characters.append(folded)
                positions.append(offset)
    normalized = ''.join(characters)
    spans = set()
    for term in terms:
        needle = core.normalize(term.strip())
        if needle:
            for match in re.finditer(r'(?<!\w)' + re.escape(needle) + r'(?!\w)', normalized):
                spans.add((positions[match.start()], positions[match.end() - 1] + 1))
    return sorted(spans)


def _mutation(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            self._notice = ''
            try:
                method(self, *args, **kwargs)
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                self._notice = str(exc)
                return self._snapshot(error=str(exc))
            return self._snapshot()
    return call


def _native_only(method):
    method._serializable = False
    return method


class YolbulanApi:
    def __init__(self, state_dir=None):
        self._settings_file = Path(state_dir) / SETTINGS.name if state_dir is not None else SETTINGS
        self._state = self._settings_file.parent
        self._transcripts = self._state / 'transcripts'
        self._classifications = self._state / 'classifications'
        self._lock = threading.RLock()
        self._window = None
        self._root = None
        self._scan_rules = []
        self._entries = {}
        self._media = MediaCatalog()
        self._media_by_path = {}
        self._jobs = {}
        self._logs = deque(maxlen=1000)
        self._notice = ''
        self._progress = {'label': '', 'current': 0, 'total': 0, 'cancelled': False}
        self._can_undo = self._undo_available()
        self._settings = dict(DEFAULTS)
        self._rules = []
        try:
            self._rules = _rules_values(core.read_json(BASE / 'kurallar.json', {'rules': []})['rules'])
            saved = core.read_json(self._settings_file, {}) or {}
            if not isinstance(saved, dict):
                raise ValueError('Ayarlar bir JSON nesnesi olmalı.')
            self._settings.update(_settings_values(saved))
            if isinstance(saved.get('rules'), list):
                self._rules = _rules_values(saved['rules'])
        except (OSError, TypeError, KeyError, ValueError) as exc:
            self._notice = f'Kayıtlı ayarlar okunamadı: {exc}'
            self._log(self._notice)

    def _log(self, message):
        self._logs.append(message)

    def _snapshot(self, error=None):
        entries = []
        for path, entry in self._entries.items():
            source = self._media_by_path[path]
            entries.append({**entry, 'duration': source.duration,
                            'thumbnail_url': self._media.url(source, 'thumbnail')})
        result = {'ok': error is None, 'entries': entries, 'settings': self._settings, 'rules': self._rules,
                  'targets': self._targets(), 'jobs': list(self._jobs), 'progress': self._progress,
                  'logs': list(self._logs), 'notice': self._notice, 'profiles': PROFILES,
                  'can_undo': self._can_undo, 'root': str(self._root) if self._root is not None else ''}
        if error is not None:
            result['error'] = error
        return copy.deepcopy(result)

    def get_state(self):
        with self._lock:
            return self._snapshot()

    @_native_only
    def bind_window(self, window):
        self._window = window

    def set_window_theme(self, theme):
        native = getattr(self._window, 'native', None)
        if native is None or theme not in ('light', 'dark'):
            return
        from webview.platforms.winforms import DwmSetWindowAttribute

        DwmSetWindowAttribute(native.Handle.ToInt64(), 20, int(theme == 'dark'))

    def browse_folder(self, initial=''):
        try:
            from webview import FileDialog
            if self._window is None:
                raise RuntimeError('Uygulama penceresi hazır değil.')
            selected = self._window.create_file_dialog(FileDialog.FOLDER, directory=initial or '')
            return {'ok': True, 'path': selected[0] if selected else None}
        except (OSError, RuntimeError, ValueError) as exc:
            return {'ok': False, 'error': str(exc)}

    def _targets(self):
        return list(dict.fromkeys([rule['folder'] for rule in self._rules] + [REVIEW, NO_MATCH]))

    def _persist(self, settings, rules):
        core.write_json(self._settings_file, {**settings, 'rules': rules})

    @_mutation
    def save_settings(self, settings):
        if not isinstance(settings, dict):
            raise ValueError('Ayarlar okunamadı.')
        changes = _settings_values(settings)
        proposed = {**self._settings, **changes}
        if changes.get('profile') != self._settings['profile'] and changes.get('profile') in PROFILES:
            proposed.update({**PROFILES[changes['profile']], **changes})
        if changes.get('device') == 'cpu' and 'compute' not in changes:
            proposed['compute'] = 'int8'
        if proposed['lm_host'] and {'lm_host', 'lm_port'}.intersection(changes):
            audio_ai.base_url(proposed['lm_host'], proposed['lm_port'])
        mode_changed = proposed['mode'] != self._settings['mode']
        if mode_changed and 'analyze' in self._jobs:
            raise ValueError('Ses analizi sürerken analiz modu değiştirilemez.')
        self._persist(proposed, self._rules)
        self._settings = proposed
        if mode_changed:
            for entry in self._entries.values():
                if not entry['hits'] and not entry['analyzed'] and entry['status'] in ('pending', 'none'):
                    entry['status'] = 'none' if proposed['mode'] == MODE_NAME else 'pending'
        if changes.keys() - {'source', 'mode'}:
            self._log('Ayarlar kaydedildi.')

    def set_mode(self, mode):
        return self.save_settings({'mode': mode})

    @_mutation
    def save_rules(self, rules):
        proposed = _rules_values(rules)
        self._persist(self._settings, proposed)
        if self._entries and self._rules != proposed:
            self._notice = 'Kurallar değişti. Dosya adı sonuçlarını güncellemek için Adları tara’ya basın.'
        self._rules = proposed
        self._log('Kurallar kaydedildi.')

    def _make_entry(self, path, rules):
        hits = core.filename_rule_hits(path.name, rules)
        stat = core.fingerprint(path)
        key = str(path)
        return {'id': key, 'path': key, 'name': path.name, 'stat': stat, 'hits': hits, 'match': _match_text(hits),
                'status': 'name' if hits else ('none' if self._settings['mode'] == MODE_NAME else 'pending'),
                'label': None, 'note': None, 'target': _target_for(hits), 'checked': bool(hits),
                'analyzed': False, 'has_text': core.cache_path(self._transcripts, path).is_file()}

    def _register(self, entry):
        path, stat = entry['path'], entry['stat']
        source = self._media_by_path.get(path)
        if source is not None and source.stat == stat:
            return
        new_source = self._media.register(path, stat)
        if source is not None:
            self._media.unregister(source)
        self._media_by_path[path] = new_source

    def _remove(self, path):
        self._entries.pop(path)
        self._media.unregister(self._media_by_path.pop(path))

    @_mutation
    def scan_names(self, source=None):
        if self._jobs:
            raise ValueError('Geçerli işlem bitince klasörü yeniden tarayın.')
        if source is not None and not isinstance(source, str):
            raise ValueError('Video klasörü geçersiz.')
        folder_text = self._settings['source'] if source is None else source.strip()
        if not folder_text:
            raise ValueError('Video klasörünü seçin.')
        root = Path(folder_text).resolve(strict=True)
        if not root.is_dir():
            raise ValueError('Kaynak bir klasör olmalı.')
        if not self._rules:
            raise ValueError('Önce Kurallar’dan en az bir kural ekleyin.')
        if core.within(root, self._state):
            raise ValueError('Uygulamanın çalışma verisi video kaynağı olarak seçilemez.')
        rules = copy.deepcopy(self._rules)
        targets = {name.casefold() for name in self._targets()}
        entries = {}

        def walk_error(exc):
            raise exc

        for folder, dirs, files in os.walk(root, onerror=walk_error):
            parent = Path(folder)
            dirs[:] = sorted(d for d in dirs if not (parent == root and d.casefold() in targets)
                             and not (parent / d).is_symlink()
                             and not getattr(parent / d, 'is_junction', lambda: False)()
                             and not core.within(parent / d, self._state))
            for filename in sorted(files, key=str.casefold):
                path = parent / filename
                if path.suffix.lower() in core.EXTENSIONS and not path.is_symlink():
                    entries[str(path)] = self._make_entry(path, rules)
        proposed = {**self._settings, 'source': str(root)}
        self._persist(proposed, self._rules)
        for entry in entries.values():
            self._register(entry)
        for path in self._entries.keys() - entries.keys():
            self._media.unregister(self._media_by_path.pop(path))
        self._root, self._scan_rules = root, rules
        self._settings, self._entries = proposed, entries
        self._media.probe_durations(self._media_by_path.values())
        named = sum(entry['status'] == 'name' for entry in entries.values())
        self._log(f'Tarama: {len(entries)} video, {named} dosya adı eşleşmesi.')

    def _selected(self, paths):
        if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
            raise ValueError('Video seçimi geçersiz.')
        return [self._entries[path] for path in dict.fromkeys(paths) if path in self._entries]

    @_mutation
    def set_checked(self, paths, value):
        skipped = 0
        for entry in self._selected(paths):
            if entry['status'] in CHECKABLE:
                if value and not entry['target']:
                    skipped += 1
                else:
                    entry['checked'] = bool(value)
        if skipped:
            self._notice = f'Hedefi seçilmemiş {skipped} video işaretlenmedi.'

    @_mutation
    def set_target(self, paths, folder):
        if folder in ('', STAY):
            folder = None
        if folder is not None and folder not in self._targets():
            raise ValueError('Hedef klasör kurallarda bulunamadı.')
        for entry in self._selected(paths):
            if entry['status'] in CHECKABLE:
                entry.update(target=folder, checked=folder is not None)

    @_mutation
    def queue_for_speech(self, paths):
        if self._settings['mode'] == MODE_NAME:
            raise ValueError('Ses analizini içeren modu seçin.')
        for entry in self._selected(paths):
            if entry['status'] in REANALYZABLE:
                entry.update(status='pending', target=None, checked=False, label=None, note=None, analyzed=False)

    def list_models(self, host, port):
        try:
            models = audio_ai.list_models(host, port)
            if not models:
                raise ValueError('LM Studio model döndürmedi. Sunucuyu başlatıp bir metin modeli yükleyin.')
            return {'ok': True, 'models': models}
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            return {'ok': False, 'error': str(exc)}

    @_mutation
    def start_analysis(self):
        if 'analyze' in self._jobs:
            raise ValueError('Ses analizi zaten sürüyor.')
        settings = dict(self._settings)
        if settings['mode'] == MODE_NAME:
            raise ValueError('Ses analizini içeren modu seçin.')
        paths = [path for path, entry in self._entries.items() if entry['status'] == 'pending']
        if not paths:
            raise ValueError('Ses analizi bekleyen video yok.')
        rules = _rules_values(self._rules)
        if not any(rule['audio_description'] for rule in rules):
            raise ValueError('Ses analizi için Kurallar’da en az bir kurala Ses içeriği tanımı (AI) yazın.')
        if not settings['lm_model']:
            raise ValueError('Ayarlar’da LM Studio metin modeli seçin veya model kimliğini yazın.')
        audio_ai.base_url(settings['lm_host'], settings['lm_port'])
        configure_cuda(settings)
        for path in paths:
            self._entries[path].update(status='queued', label=None, note=None, checked=False)
        self._progress = {'label': f'Ses analizi · {len(paths)} video', 'current': 0, 'total': len(paths) * 2,
                          'cancelled': False}
        self._log(f'Ses analizi: {len(paths)} video · Whisper {settings["model"]} ({settings["device"].upper()}) '
                  f'→ LM Studio {settings["lm_model"]}')
        self._start_job('analyze', self._analyze, paths, rules, settings)

    @_mutation
    def cancel_analysis(self):
        cancellation = self._jobs.get('analyze')
        if cancellation is not None and not cancellation.is_set():
            cancellation.set()
            self._progress['cancelled'] = True
            self._log('Geçerli video veya LM Studio isteği bitince analiz duracak.')

    def _start_job(self, name, work, *args):
        cancellation = threading.Event()
        self._jobs[name] = cancellation
        thread = threading.Thread(target=self._run_job, args=(name, work, cancellation, args), daemon=name == 'analyze')
        thread.start()

    def _run_job(self, name, work, cancellation, args):
        error = None
        try:
            work(cancellation, *args)
        except Exception as exc:
            error = str(exc)
            with self._lock:
                self._notice = error
                self._log(f'HATA: {error}\n{traceback.format_exc()}')
        finally:
            with self._lock:
                self._jobs.pop(name)
                if name == 'analyze':
                    for entry in self._entries.values():
                        if entry['status'] in ('queued', 'working'):
                            entry.update(status='error' if error else 'pending', label=None, note=error)
                    counts = {key: sum(e['status'] == key for e in self._entries.values())
                              for key in ('speech', 'none', 'error')}
                    self._progress = {'label': '', 'current': 0, 'total': 0, 'cancelled': False}
                    label = 'Ses analizi durduruldu' if cancellation.is_set() else 'Ses analizi bitti'
                    self._log(f'{label} · {counts["speech"]} eşleşme · {counts["none"]} eşleşme yok · '
                              f'{counts["error"]} hata')
                elif name == 'move':
                    for path, entry in self._entries.items():
                        if entry['status'] == 'moving':
                            entry.update(status='move_failed', label=None, note=error or 'Taşıma tamamlanmadı.')
                            self._media_by_path[path].suspended.clear()
                if name in ('move', 'undo'):
                    self._can_undo = self._undo_available()

    def _update_working(self, path, label):
        with self._lock:
            self._entries[path].update(status='working', label=label)
            self._progress['label'] = f'{label} · {Path(path).name}'

    def _analysis_error(self, path, exc):
        with self._lock:
            self._entries[path].update(status='error', label=None, note=str(exc), checked=False)
            self._log(f'HATA · {Path(path).name}: {exc}')

    def _analyze(self, cancellation, paths, rules, settings):
        host, port, lm_model = (settings[key] for key in ('lm_host', 'lm_port', 'lm_model'))
        if lm_model not in audio_ai.list_models(host, port):
            raise RuntimeError(f'LM Studio model listesinde “{lm_model}” bulunamadı. Ayarlar’da Modelleri getir düğmesini kullanın.')
        engine = None
        transcripts = []
        whisper = {key: settings[key] for key in ('model', 'device', 'compute', 'batch', 'beam')}
        signature = json.dumps(whisper, sort_keys=True)
        for index, path in enumerate(paths, 1):
            if cancellation.is_set():
                break
            try:
                stat = core.fingerprint(path)
                cache_path = core.cache_path(self._transcripts, path)
                cached = core.read_json(cache_path)
                if not (cached and cached.get('fingerprint') == stat and cached.get('signature') == signature):
                    if engine is None:
                        self._update_working(path, 'Model yükleniyor')
                        engine = core.transcriber(*whisper.values())
                    self._update_working(path, 'Yazıya dökülüyor')
                    segments = engine(Path(path))
                    if core.fingerprint(path) != stat:
                        raise ValueError('Yazıya dökülürken kaynak video değişti.')
                    core.write_json(cache_path, {'source': path, 'fingerprint': stat, 'signature': signature,
                                                 'model': whisper['model'], 'segments': segments})
                transcripts.append((path, stat))
                with self._lock:
                    self._entries[path].update(status='queued', label='Metin hazır, sırada', has_text=True)
            except Exception as exc:
                self._analysis_error(path, exc)
            with self._lock:
                self._progress['current'] = index
        engine = None
        gc.collect()
        if not cancellation.is_set():
            with self._lock:
                self._progress['current'] = 2 * len(paths) - len(transcripts)
        for index, (path, stat) in enumerate(transcripts, 1):
            if cancellation.is_set():
                break
            self._update_working(path, 'LM Studio değerlendiriyor')
            try:
                hits = self._classify(path, stat, signature, rules, settings, cancellation)
                if hits is None or cancellation.is_set():
                    break
                if stat != core.fingerprint(path):
                    raise ValueError('Sınıflandırılırken kaynak video değişti.')
                with self._lock:
                    entry = self._entries[path]
                    entry.update(status='speech' if hits else 'none', label=None, hits=hits, match=_match_text(hits),
                                 stat=stat, analyzed=True, target=_target_for(hits) if hits else NO_MATCH, checked=True)
                    self._register(entry)
                    if hits:
                        self._log(f'EŞLEŞTİ · {Path(path).name}: {", ".join(hit["folder"] for hit in hits)}')
            except Exception as exc:
                self._analysis_error(path, exc)
            with self._lock:
                self._progress['current'] = 2 * len(paths) - len(transcripts) + index

    def _classify(self, path, stat, signature, rules, settings, cancellation):
        host, port, model = (settings[key] for key in ('lm_host', 'lm_port', 'lm_model'))
        thinking = settings['lm_thinking']
        chunk_size = 0 if settings['lm_whole'] else settings['lm_chunk_size']
        config = {'version': 4, 'fingerprint': stat, 'whisper': signature, 'lm_host': host, 'lm_port': port,
                  'lm_model': model, 'thinking': thinking, 'chunk_size': chunk_size,
                  'rules': [{'folder': rule['folder'], 'audio_description': rule['audio_description']} for rule in rules]}
        signature = hashlib.sha256(json.dumps(config, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
        cache_path = core.cache_path(self._classifications, path)
        cached = core.read_json(cache_path)
        if cached and cached.get('signature') == signature:
            return cached['hits']
        segments = core.read_json(core.cache_path(self._transcripts, path))['segments']

        def progress(current, total):
            self._update_working(path, f'LM Studio değerlendiriyor · {current}/{total} parça')

        def retry(attempt, maximum, message):
            with self._lock:
                self._log(f'YENİDEN DENENİYOR · {Path(path).name} · {attempt}/{maximum}: {message}')

        hits = audio_ai.classify(segments, rules, host, port, model, progress=progress, on_retry=retry,
                                 cancelled=cancellation.is_set, thinking=thinking, chunk_size=chunk_size,
                                 retries=settings['lm_retries'])
        if hits is not None:
            core.write_json(cache_path, {'signature': signature, 'hits': hits})
        return hits

    @_mutation
    def move_checked(self):
        if self._root is None or 'move' in self._jobs or 'undo' in self._jobs:
            raise ValueError('Şu anda video taşıma başlatılamaz.')
        entries = [entry for entry in self._entries.values() if entry['status'] in CHECKABLE
                   and entry['checked'] and entry['target']]
        if not entries:
            raise ValueError('Taşımak için hedefi olan videoları işaretleyin.')
        moves, media = [], []
        for entry in entries:
            path = entry['path']
            destination = self._root / entry['target'] / entry['name']
            moves.append({'source': path, 'destination': str(destination), 'fingerprint': entry['stat']})
            entry.update(status='moving', checked=False, note=None)
            source = self._media_by_path[path]
            source.suspended.set()
            media.append(source)
        self._start_job('move', self._move, moves, self._root, media)

    def _move(self, _cancellation, moves, root, media):
        for source in media:
            with source.lock:
                pass  # Drain readers before Windows attempts to rename the source.
        failed = 0

        def report(path, status, detail):
            nonlocal failed
            with self._lock:
                if status == 'moved':
                    self._remove(path)
                    self._log(f'TAŞINDI · {Path(path).name} → {Path(detail).parent.name}')
                else:
                    failed += 1
                    self._entries[path].update(status='move_failed', note=detail)
                    self._media_by_path[path].suspended.clear()
                    self._log(f'TAŞINAMADI · {Path(path).name}: {detail}')

        moved = core.apply(moves, root, self._state, reporter=report)
        with self._lock:
            self._log(f'Taşıma bitti · {moved} taşındı · {failed} taşınamadı')

    def _undo_available(self):
        try:
            with (self._state / 'moves.jsonl').open(encoding='utf-8') as file:
                statuses = {}
                for line in file:
                    if line.strip():
                        event = json.loads(line)
                        statuses[event['id']] = event['status']
            return any(status in ('moved', 'moving') for status in statuses.values())
        except (OSError, ValueError, KeyError):
            return False

    @_mutation
    def undo(self):
        if self._jobs:
            raise ValueError('Geçerli işlem bitince taşımayı geri alın.')
        if not self._can_undo:
            raise ValueError('Geri alınacak taşıma kaydı yok.')
        self._start_job('undo', self._undo)

    def _undo(self, _cancellation):
        other = 0

        def report(path, status, detail):
            nonlocal other
            with self._lock:
                if status == 'undone':
                    restored = Path(detail)
                    self._log(f'GERİ ALINDI · {restored.name}')
                    if self._root and core.within(restored, self._root) and detail not in self._entries:
                        try:
                            entry = self._make_entry(restored, self._scan_rules)
                            self._register(entry)
                            self._entries[detail] = entry
                        except OSError:
                            pass
                else:
                    other += 1
                    self._log(f'{"ATLANDI" if status == "skipped" else "HATA"} · {Path(path).name}: {detail}')

        restored = core.undo(self._state, reporter=report)
        with self._lock:
            self._log(f'Geri alma bitti · {len(restored)} video geri döndü · {other} atlandı veya hata')

    def _source(self, path):
        with self._lock:
            source = self._media_by_path.get(path)
        if source is None:
            raise ValueError('Video listede bulunamadı.')
        return source

    def get_preview(self, path, start=0, prepare=True):
        try:
            return {'ok': True, **self._media.preview(self._source(path), start, prepare)}
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            return {'ok': False, 'error': str(exc)}

    def get_transcript(self, path):
        try:
            with self._lock:
                entry = self._entries.get(path)
                if entry is None:
                    raise ValueError('Video listede bulunamadı.')
                terms = [term for hit in entry['hits'] for term in hit['terms']]
            cached = core.read_json(core.cache_path(self._transcripts, path))
            if not cached or not cached.get('segments'):
                raise ValueError('Bu video için henüz transkript oluşturulmadı.')
            if 'fingerprint' in cached and cached['fingerprint'] != core.fingerprint(path):
                raise ValueError('Video değiştiği için kayıtlı transkript güncel değil.')
            return {'ok': True, 'terms': terms, 'segments': [
                {**segment, 'highlights': _highlights(segment['text'], terms)} for segment in cached['segments']]}
        except (OSError, TypeError, ValueError, KeyError) as exc:
            return {'ok': False, 'error': str(exc)}

    def open_video(self, path):
        try:
            source = self._source(path)
            if not source.available():
                raise ValueError('Video değişmiş veya taşınmış. Klasörü yeniden tarayın.')
            os.startfile(source.path)
            return {'ok': True}
        except (OSError, TypeError, ValueError) as exc:
            return {'ok': False, 'error': str(exc)}

    def reveal_file(self, path):
        try:
            source = self._source(path)
            if not source.available():
                raise ValueError('Video değişmiş veya taşınmış. Klasörü yeniden tarayın.')
            subprocess.Popen(['explorer.exe', '/select,', str(source.path)])
            return {'ok': True}
        except (OSError, TypeError, ValueError) as exc:
            return {'ok': False, 'error': str(exc)}

    @_native_only
    def on_closing(self):
        with self._lock:
            if 'move' in self._jobs or 'undo' in self._jobs:
                message = 'Dosyalar taşınıyor. İşlem bitince pencereyi kapatabilirsiniz.'
                self._notice = message
                self._log(message)
                return False
            cancellation = self._jobs.get('analyze')
        if cancellation is not None:
            return self._window.create_confirmation_dialog('Analiz sürüyor', 'Ses analizi sürüyor. Çıkılsın mı?')
        return True

    @_native_only
    def close(self):
        with self._lock:
            cancellation = self._jobs.get('analyze')
            if cancellation is not None:
                cancellation.set()
        self._media.close()
