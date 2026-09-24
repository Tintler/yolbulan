"""Local speech-based video sorter. Python 3.10+."""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
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


def matches(text, phrase):
    # Match whole words and phrases, without matching e.g. alien inside aliens.
    haystack, needle = normalize(text), normalize(phrase.strip())
    if not needle:
        return False
    return bool(re.search(r'(?<!\w)' + re.escape(needle) + r'(?!\w)', haystack))


def filename_matches(filename, phrase):
    """Find a term anywhere in the filename stem, including within a longer word."""
    needle = normalize(re.sub(r'[._]+', ' ', phrase.strip()))
    if not needle:
        return False
    stem = Path(filename).stem
    # Release-name separators can stand in for spaces in a multiword term.
    haystack = normalize(re.sub(r'[._]+', ' ', stem))
    return needle in haystack


def rule_terms(rule, channel):
    """Read independent GUI terms, retaining compatibility with old rules."""
    return rule.get(channel + '_terms', rule.get('terms', []))


def excluded(rule, filename):
    """A filename negative term vetoes only its own rule."""
    return any(filename_matches(filename, term) for term in rule.get('name_negative_terms', []))


def filename_rule_hits(filename, rules):
    """Prefer complete words/phrases; keep all partial matches if none is complete."""
    found = []
    haystack = normalize(re.sub(r'[._]+', ' ', Path(filename).stem))
    for rule in rules:
        if excluded(rule, filename):
            continue
        for term in rule_terms(rule, 'name'):
            if filename_matches(filename, term):
                needle = normalize(re.sub(r'[._]+', ' ', term.strip()))
                exact = bool(re.search(r'(?<!\w)' + re.escape(needle) + r'(?!\w)', haystack))
                found.append((exact, len(needle.replace(' ', '')), rule['folder'], term))
    if not found:
        return []
    if any(exact for exact, _length, _folder, _term in found):
        # A full word/phrase outranks fragments inside it; longer full phrases win.
        best = max(length for exact, length, _folder, _term in found if exact)
        found = [entry for entry in found if entry[0] and entry[1] == best]
    result = []
    for rule in rules:
        terms = [term for _exact, _length, folder, term in found if folder == rule['folder']]
        if terms:
            result.append({'folder': rule['folder'], 'terms': terms})
    return result


def within(path, parent):
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False


def config_load(path):
    cfg = read_json(path)
    if not isinstance(cfg, dict) or not isinstance(cfg.get('rules'), list):
        raise ValueError('Kural dosyasında rules listesi gerekli.')
    names = set()
    for rule in cfg['rules']:
        if not isinstance(rule, dict) or not isinstance(rule.get('folder'), str):
            raise ValueError('Her kural bir hedef klasör içermeli.')
        name = rule['folder']
        if name in ('', '.', '..') or Path(name).name != name or '/' in name or '\\' in name or name.casefold() in names:
            raise ValueError(f'Geçersiz veya tekrar eden klasör adı: {name}')
        names.add(name.casefold())
        name_terms, speech_terms = rule_terms(rule, 'name'), rule_terms(rule, 'speech')
        negative_name = rule.get('name_negative_terms', [])
        if (not isinstance(name_terms, list) or not isinstance(speech_terms, list) or
                not (name_terms or speech_terms) or
                any(not isinstance(t, str) or not t.strip() for t in name_terms + speech_terms)):
            raise ValueError(f'{name}: dosya adı veya ses için en az bir terim gerekli.')
        if (not isinstance(negative_name, list) or
                any(not isinstance(t, str) or not t.strip() for t in negative_name)):
            raise ValueError(f'{name}: negatif terimler dolu metinlerden oluşmalı.')
    review = cfg.get('review_folder', 'Incelenecekler')
    if review in ('', '.', '..') or Path(review).name != review or '/' in review or '\\' in review or review.casefold() in names:
        raise ValueError('Geçersiz review_folder.')
    cfg['review_folder'] = review
    return cfg


def fingerprint(path):
    st = path.stat()
    return {'size': st.st_size, 'mtime_ns': st.st_mtime_ns}


def cache_path(cache_root, path):
    key = hashlib.sha256(str(Path(path).resolve()).encode('utf-8')).hexdigest()
    return Path(cache_root) / (key + '.json')


def transcribe(path, model, device, compute_type):
    # Import only if a file actually requires transcription.
    from faster_whisper import WhisperModel
    engine = WhisperModel(model, device=device, compute_type=compute_type)
    segments, _info = engine.transcribe(str(path), vad_filter=True)
    return [{'start': round(s.start, 3), 'end': round(s.end, 3), 'text': s.text.strip()} for s in segments]


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


def candidates(root, output, state):
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not within(Path(folder) / d, output) and not within(Path(folder) / d, state)]
        for filename in files:
            p = Path(folder) / filename
            if p.suffix.lower() in EXTENSIONS and not p.is_symlink():
                yield p


def scan(args):
    root, output, state = (Path(p).resolve() for p in (args.source, args.destination, args.state))
    if not root.is_dir():
        raise ValueError('Kaynak klasör bulunamadı.')
    if root == output or within(root, output):
        raise ValueError('Kaynak klasör hedefin içinde olamaz.')
    if root == state or within(root, state):
        raise ValueError('Kaynak klasör çalışma klasörünün içinde olamaz.')
    cfg = config_load(args.rules)
    cache_root = state / 'transcripts'
    entries = []
    for path in candidates(root, output, state):
        stat = fingerprint(path)
        saved = read_json(cache_path(cache_root, path))
        if saved and saved.get('fingerprint') == stat and saved.get('model') == args.model:
            segments = saved['segments']
            print(f'Önbellek: {path}', flush=True)
        else:
            print(f'Çözümleniyor: {path}', flush=True)
            try:
                segments = transcribe(path, args.model, args.device, args.compute_type)
            except Exception as exc:
                print(f'HATA: {path}: {exc}', file=sys.stderr, flush=True)
                entries.append({'source': str(path), 'fingerprint': stat, 'status': 'error', 'error': str(exc)})
                continue
            write_json(cache_path(cache_root, path), {'source': str(path), 'fingerprint': stat, 'model': args.model, 'segments': segments})
        text = ' '.join(s['text'] for s in segments)
        hits = [{'folder': r['folder'], 'terms': [t for t in rule_terms(r, 'speech') if matches(text, t)]}
                for r in cfg['rules']]
        hits = [h for h in hits if h['terms']]
        if not hits:
            status, target = 'unmatched', None
        elif len(hits) > 1:
            status, target = 'review', output / cfg['review_folder'] / path.name
        else:
            status, target = 'matched', output / hits[0]['folder'] / path.name
        entries.append({'source': str(path), 'fingerprint': stat, 'status': status,
                        'hits': hits, 'destination': str(target) if target else None})
        print(f'  {status}: {", ".join(h["folder"] for h in hits) or "eşleşme yok"}', flush=True)
    plan = {'created_at': now(), 'source_root': str(root), 'destination_root': str(output), 'entries': entries}
    plan_path = state / 'plan.json'
    write_json(plan_path, plan)
    print(f'\nÖnizleme: {plan_path}\nEşleşen: {sum(x["status"] == "matched" for x in entries)}; '
          f'İncelenecek: {sum(x["status"] == "review" for x in entries)}; '
          f'Eşleşmeyen: {sum(x["status"] == "unmatched" for x in entries)}; '
          f'Hata: {sum(x["status"] == "error" for x in entries)}')


def apply(args, reporter=None):
    state = Path(args.state).resolve()
    plan = read_json(state / 'plan.json')
    if not plan:
        raise ValueError('Önizleme bulunamadı. Önce scan çalıştırın.')
    output = Path(plan['destination_root']).resolve()
    if args.plan_only:
        for e in plan['entries']:
            if e.get('destination'):
                print(f'{e["source"]} -> {e["destination"]}')
        return
    log_path = state / 'moves.jsonl'
    count = 0
    def report(src, status, detail=''):
        if reporter:
            reporter(str(src), status, detail)
    for e in plan['entries']:
        if e['status'] not in ('matched', 'review'):
            continue
        src, dst = Path(e['source']), Path(e['destination'])
        if not within(dst, output) or not within(src, plan['source_root']):
            print(f'ATLANDI (geçersiz yol): {src}', file=sys.stderr)
            report(src, 'skipped', 'Geçersiz yol')
            continue
        if not src.is_file() or src.is_symlink() or fingerprint(src) != e['fingerprint']:
            print(f'ATLANDI (dosya değişmiş/taşınmış): {src}', file=sys.stderr)
            report(src, 'skipped', 'Dosya değişmiş veya taşınmış')
            continue
        if dst.exists():
            print(f'ATLANDI (hedef dolu): {dst}', file=sys.stderr)
            report(src, 'skipped', 'Hedefte aynı adlı dosya var')
            continue
        # Open a destination exclusively to avoid silently overwriting an existing file.
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            fast = src.stat().st_dev == dst.parent.stat().st_dev
            record = {'id': uuid.uuid4().hex, 'time': now(), 'source': str(src), 'destination': str(dst),
                      'fingerprint': e['fingerprint'], 'status': 'moving' if fast else 'copied'}
            if fast:
                # Record intent before the fast move so interrupted moves remain undoable.
                append_move_event(log_path, record)
                move_within_volume(src, dst)
            else:
                with dst.open('xb') as target, src.open('rb') as source:
                    shutil.copyfileobj(source, target, 1024 * 1024)
                shutil.copystat(src, dst)
                if dst.stat().st_size != e['fingerprint']['size'] or fingerprint(src) != e['fingerprint']:
                    raise RuntimeError('Kopyalama sırasında kaynak değişti.')
                append_move_event(log_path, record)
                src.unlink()
            with log_path.open('a', encoding='utf-8') as f:
                f.write(json.dumps({'id': record['id'], 'time': now(), 'status': 'moved'}) + '\n')
                f.flush()
                os.fsync(f.fileno())
            count += 1
            print(f'TAŞINDI: {src} -> {dst}')
            report(src, 'moved', str(dst))
        except Exception as exc:
            # A copied destination is deliberately retained if the source may still exist.
            print(f'HATA: {src}: {exc}', file=sys.stderr)
            report(src, 'error', str(exc))
    print(f'Taşınan: {count}. Kayıt: {log_path}')


def append_move_event(log_path, event):
    with log_path.open('a', encoding='utf-8') as f:
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


def undo(args, reporter=None):
    log_path = Path(args.state).resolve() / 'moves.jsonl'
    if not log_path.exists():
        raise ValueError('Geri alma kaydı bulunamadı.')
    events = [json.loads(line) for line in log_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    moves = {e['id']: e for e in events if e['status'] in ('copied', 'moving')}
    statuses = {e['id']: e['status'] for e in events}
    count = 0
    for key, e in reversed(list(moves.items())):
        if statuses.get(key) not in ('moved', 'moving'):
            continue
        src, dst = Path(e['source']), Path(e['destination'])
        if src.exists() or not dst.is_file() or fingerprint(dst) != e['fingerprint']:
            print(f'ATLANDI (kaynak dolu veya hedef değişmiş): {dst}', file=sys.stderr)
            if reporter:
                reporter(str(dst), 'skipped', 'Kaynak dolu veya hedef değişmiş')
            continue
        src.parent.mkdir(parents=True, exist_ok=True)
        try:
            if dst.stat().st_dev == src.parent.stat().st_dev:
                move_within_volume(dst, src)
            else:
                with src.open('xb') as target, dst.open('rb') as source:
                    shutil.copyfileobj(source, target, 1024 * 1024)
                shutil.copystat(dst, src)
                if src.stat().st_size != e['fingerprint']['size']:
                    raise RuntimeError('Kopyalanan boyut farklı.')
                dst.unlink()
            with log_path.open('a', encoding='utf-8') as f:
                f.write(json.dumps({'id': key, 'time': now(), 'status': 'undone'}) + '\n')
                f.flush()
                os.fsync(f.fileno())
            count += 1
            print(f'GERİ ALINDI: {dst} -> {src}')
            if reporter:
                reporter(str(dst), 'undone', str(src))
        except Exception as exc:
            print(f'HATA: {dst}: {exc}', file=sys.stderr)
            if reporter:
                reporter(str(dst), 'error', str(exc))
    print(f'Geri alınan: {count}')


def main():
    parser = argparse.ArgumentParser(description='Yolbulan: yerel video ayıklama')
    sub = parser.add_subparsers(dest='command', required=True)
    scan_p = sub.add_parser('scan', help='Analiz et ve taşıma önizlemesini hazırla')
    scan_p.add_argument('source', help='Video klasörü')
    scan_p.add_argument('destination', help='Hedef ana klasör')
    scan_p.add_argument('--rules', default=str(Path(__file__).with_name('kurallar.json')))
    scan_p.add_argument('--state', default=str(Path(__file__).with_name('calisma_verisi')))
    scan_p.add_argument('--model', default='small', help='faster-whisper modeli: small, medium, large-v3 vb.')
    scan_p.add_argument('--device', choices=['auto', 'cpu', 'cuda'], default='auto')
    scan_p.add_argument('--compute-type', default='default')
    apply_p = sub.add_parser('apply', help='Önizlemeye göre dosyaları taşı')
    apply_p.add_argument('--state', default=str(Path(__file__).with_name('calisma_verisi')))
    apply_p.add_argument('--plan-only', action='store_true', help='Taşımadan önizlemeyi yazdır')
    undo_p = sub.add_parser('undo', help='Taşınan ve değişmemiş dosyaları geri al')
    undo_p.add_argument('--state', default=str(Path(__file__).with_name('calisma_verisi')))
    args = parser.parse_args()
    try:
        {'scan': scan, 'apply': apply, 'undo': undo}[args.command](args)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.exit(1, f'HATA: {exc}\n')


if __name__ == '__main__':
    main()
