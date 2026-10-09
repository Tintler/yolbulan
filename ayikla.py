"""Rule matching, transcription and safe, undoable moves for Yolbulan."""
import hashlib
import json
import os
import re
import shutil
import tempfile
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path

EXTENSIONS = {'.mp4', '.mkv', '.webm', '.mov', '.avi', '.m4v'}


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        tmp = f.name
    os.replace(tmp, path)


def read_json(path, default=None):
    if not Path(path).exists():
        return default
    return json.loads(Path(path).read_text(encoding='utf-8'))


def normalize(s):
    s = s.casefold().replace('ı', 'i')
    return ''.join(c for c in unicodedata.normalize('NFD', s) if not unicodedata.combining(c))


def name_key(text):
    """Release-name separators can stand in for spaces in a multiword term."""
    return normalize(re.sub(r'[._]+', ' ', text.strip()))


def filename_matches(filename, phrase):
    """Find a term anywhere in the filename stem, including within a longer word."""
    needle = name_key(phrase)
    return bool(needle) and needle in name_key(Path(filename).stem)


def rule_terms(rule, channel):
    """Read independent GUI terms, retaining compatibility with old rules."""
    return rule.get(channel + '_terms', rule.get('terms', []))


def excluded(rule, filename):
    """A filename negative term vetoes only its own rule."""
    return any(filename_matches(filename, term) for term in rule.get('name_negative_terms', []))


def _spans(haystack, needle):
    spans, start = [], haystack.find(needle)
    while start != -1:
        spans.append((start, start + len(needle)))
        start = haystack.find(needle, start + 1)
    return spans


def _whole_word(haystack, span):
    start, end = span
    return ((start == 0 or not re.match(r'\w', haystack[start - 1])) and
            (end == len(haystack) or not re.match(r'\w', haystack[end])))


def filename_rule_hits(filename, rules):
    """Match terms anywhere in the name; a hit lying wholly inside a longer
    whole-word hit is dropped, independent hits for other rules are kept."""
    haystack = name_key(Path(filename).stem)
    found = []
    for rule in rules:
        if excluded(rule, filename):
            continue
        for term in rule_terms(rule, 'name'):
            needle = name_key(term)
            spans = _spans(haystack, needle) if needle else []
            if spans:
                found.append({'folder': rule['folder'], 'term': term, 'spans': spans,
                              'whole': [s for s in spans if _whole_word(haystack, s)]})

    def inside_longer_word(span, other):
        return any(a <= span[0] and span[1] <= b and b - a > span[1] - span[0] for a, b in other['whole'])

    kept = [hit for hit in found
            if not all(any(inside_longer_word(span, other) for other in found if other is not hit)
                       for span in hit['spans'])]
    result = []
    for rule in rules:
        terms = [hit['term'] for hit in kept if hit['folder'] == rule['folder']]
        if terms:
            result.append({'folder': rule['folder'], 'terms': terms})
    return result


def within(path, parent):
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False


def valid_folder_name(name):
    return (isinstance(name, str) and name not in ('', '.', '..') and Path(name).name == name
            and '/' not in name and '\\' not in name)


def config_load(cfg):
    if not isinstance(cfg, dict) or not isinstance(cfg.get('rules'), list):
        raise ValueError('Kural dosyasında rules listesi gerekli.')
    names = set()
    for rule in cfg['rules']:
        if not isinstance(rule, dict) or not isinstance(rule.get('folder'), str):
            raise ValueError('Her kural bir hedef klasör içermeli.')
        name = rule['folder']
        if not valid_folder_name(name) or name.casefold() in names:
            raise ValueError(f'Geçersiz veya tekrar eden klasör adı: {name or "(boş)"}')
        names.add(name.casefold())
        name_terms = rule_terms(rule, 'name')
        audio_description = rule.get('audio_description', '')
        if (not isinstance(name_terms, list) or not isinstance(audio_description, str) or
                not (name_terms or audio_description.strip()) or
                any(not isinstance(t, str) or not t.strip() for t in name_terms)):
            raise ValueError(f'{name}: dosya adı terimi veya ses içeriği tanımı gerekli.')
        negative_name = rule.get('name_negative_terms', [])
        if (not isinstance(negative_name, list) or
                any(not isinstance(t, str) or not t.strip() for t in negative_name)):
            raise ValueError(f'{name}: negatif terimler dolu metinlerden oluşmalı.')
    review = cfg.get('review_folder', 'Incelenecekler')
    if not valid_folder_name(review) or review.casefold() in names:
        raise ValueError('Geçersiz review_folder.')
    cfg['review_folder'] = review
    return cfg


def fingerprint(path):
    st = Path(path).stat()
    return {'size': st.st_size, 'mtime_ns': st.st_mtime_ns}


def cache_path(cache_root, path):
    key = hashlib.sha256(str(Path(path).resolve()).encode('utf-8')).hexdigest()
    return Path(cache_root) / (key + '.json')


def transcriber(model, device='cuda', compute_type='float16', batch_size=8, beam_size=5):
    """Create one reusable engine; batch_size=1 uses the original pipeline."""
    from faster_whisper import WhisperModel, BatchedInferencePipeline
    engine = WhisperModel(model, device=device, compute_type=compute_type)
    pipeline = BatchedInferencePipeline(model=engine) if batch_size > 1 else engine

    def run(path):
        options = {'vad_filter': True, 'beam_size': beam_size}
        if batch_size > 1:
            options['batch_size'] = batch_size
        segments, _ = pipeline.transcribe(str(path), **options)
        return [{'start': round(s.start, 3), 'end': round(s.end, 3), 'text': s.text.strip()} for s in segments]

    return run


def append_move_event(log_path, event):
    with Path(log_path).open('a', encoding='utf-8') as f:
        f.write(json.dumps(event, ensure_ascii=False) + '\n')
        f.flush()
        os.fsync(f.fileno())


def move_within_volume(src, dst):
    """Fast same-volume move; never overwrite an existing destination."""
    if os.name == 'nt':
        # Windows rename refuses to overwrite, unlike POSIX rename.
        os.rename(src, dst)
    else:
        os.link(src, dst)  # Exclusive destination creation.
        src.unlink()


def apply(entries, root, state, reporter=None):
    """Move each {'source', 'destination', 'fingerprint'} entry; one call is one undo batch."""
    state = Path(state).resolve()
    state.mkdir(parents=True, exist_ok=True)
    log_path = state / 'moves.jsonl'
    batch = uuid.uuid4().hex
    count = 0

    def report(src, status, detail=''):
        if reporter:
            reporter(str(src), status, detail)

    for e in entries:
        src, dst = Path(e['source']), Path(e['destination'])
        if not within(dst, root) or not within(src, root):
            report(src, 'skipped', 'Geçersiz yol')
            continue
        if not src.is_file() or src.is_symlink() or fingerprint(src) != e['fingerprint']:
            report(src, 'skipped', 'Dosya değişmiş veya taşınmış')
            continue
        if dst.exists():
            report(src, 'skipped', 'Hedefte aynı adlı dosya var')
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            fast = src.stat().st_dev == dst.parent.stat().st_dev
            record = {'id': uuid.uuid4().hex, 'batch': batch, 'time': now(), 'source': str(src),
                      'destination': str(dst), 'fingerprint': e['fingerprint'],
                      'status': 'moving' if fast else 'copied'}
            if fast:
                # Record intent before the fast move so interrupted moves remain undoable.
                append_move_event(log_path, record)
                move_within_volume(src, dst)
            else:
                # Open the destination exclusively to avoid silently overwriting a file.
                with dst.open('xb') as target, src.open('rb') as source:
                    shutil.copyfileobj(source, target, 1024 * 1024)
                shutil.copystat(src, dst)
                if dst.stat().st_size != e['fingerprint']['size'] or fingerprint(src) != e['fingerprint']:
                    raise RuntimeError('Kopyalama sırasında kaynak değişti.')
                append_move_event(log_path, record)
                src.unlink()
            append_move_event(log_path, {'id': record['id'], 'time': now(), 'status': 'moved'})
            count += 1
            report(src, 'moved', str(dst))
        except Exception as exc:
            # A copied destination is deliberately retained if the source may still exist.
            report(src, 'error', str(exc))
    return count


def undo(state, reporter=None):
    """Undo the most recent move batch that still has undoable moves."""
    log_path = Path(state).resolve() / 'moves.jsonl'
    if not log_path.exists():
        raise ValueError('Geri alınacak taşıma kaydı yok.')
    events = [json.loads(line) for line in log_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    moves = {e['id']: e for e in events if e['status'] in ('copied', 'moving')}
    statuses = {e['id']: e['status'] for e in events}
    pending = [e for key, e in moves.items() if statuses.get(key) in ('moved', 'moving')]
    if not pending:
        raise ValueError('Geri alınacak taşıma kalmadı.')
    # Records written before batches existed form one batch together.
    batch = pending[-1].get('batch')
    restored = []
    for e in reversed([e for e in pending if e.get('batch') == batch]):
        src, dst = Path(e['source']), Path(e['destination'])
        if src.exists() or not dst.is_file() or fingerprint(dst) != e['fingerprint']:
            if reporter:
                reporter(str(dst), 'skipped', 'Kaynak dolu veya hedef değişmiş')
            continue
        try:
            src.parent.mkdir(parents=True, exist_ok=True)
            if dst.stat().st_dev == src.parent.stat().st_dev:
                move_within_volume(dst, src)
            else:
                with src.open('xb') as target, dst.open('rb') as source:
                    shutil.copyfileobj(source, target, 1024 * 1024)
                shutil.copystat(dst, src)
                if src.stat().st_size != e['fingerprint']['size']:
                    raise RuntimeError('Kopyalanan boyut farklı.')
                dst.unlink()
            append_move_event(log_path, {'id': e['id'], 'time': now(), 'status': 'undone'})
            restored.append(str(src))
            if reporter:
                reporter(str(dst), 'undone', str(src))
        except Exception as exc:
            if reporter:
                reporter(str(dst), 'error', str(exc))
    return restored
