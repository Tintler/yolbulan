"""Serve selected local videos and thumbnails to the desktop webview."""

import math
import re
import secrets
import tempfile
import threading
from collections import deque
from fractions import Fraction
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import islice
from pathlib import Path
from urllib.parse import urlsplit

import av

import ayikla as core


PREVIEW_SECONDS = 24
THUMBNAIL_DECODE_LIMIT = 120
VIDEO_CODECS = {'video/mp4': {'h264', 'av1', 'vp9'}, 'video/webm': {'vp8', 'vp9', 'av1'}}
AUDIO_CODECS = {'video/mp4': {'aac', 'mp3', 'opus'}, 'video/webm': {'vorbis', 'opus'}}


def _size(width, height, max_width, max_height):
    scale = min(1, max_width / width, max_height / height)
    return tuple(max(2, round(value * scale / 2) * 2) for value in (width, height))


def _picture(frame):
    encoder = av.CodecContext.create('mjpeg', 'w')
    encoder.width, encoder.height = _size(frame.width, frame.height, 480, 270)
    encoder.pix_fmt = 'yuvj420p'
    encoder.time_base = Fraction(1, 1)
    frame = frame.reformat(encoder.width, encoder.height, format=encoder.pix_fmt)
    frame.pts = 0
    frame.time_base = encoder.time_base
    return b''.join(bytes(packet) for packet in [*encoder.encode(frame), *encoder.encode(None)])


def _visible_pixels(frame):
    sample = frame.reformat(width=48, height=28, format='gray')
    plane = sample.planes[0]
    pixels = memoryview(plane)
    bright = 0
    for y in range(sample.height):
        start = y * plane.line_size
        bright += sum(value >= 32 for value in pixels[start:start + sample.width])
    return bright / (sample.width * sample.height)


class _Source:
    def __init__(self, path, stat):
        self.path = Path(path)
        self.stat = stat
        self.token = secrets.token_urlsafe(24)
        self.lock = threading.Lock()
        self.suspended = threading.Event()
        self.duration = None
        self.content_type = None
        self.inspected = False
        self.picture_attempted = False
        self.picture = None

    def available(self):
        if self.suspended.is_set():
            return False
        try:
            return not self.path.is_symlink() and core.fingerprint(self.path) == self.stat
        except OSError:
            return False

    def inspect(self, include_picture=False):
        with self.lock:
            if not self.available():
                raise ValueError('Video değişmiş veya taşınmış. Klasörü yeniden tarayın.')
            generate_picture = include_picture and not self.picture_attempted
            if self.inspected and not generate_picture:
                return
            with av.open(str(self.path)) as container:
                if not container.streams.video:
                    raise ValueError('Dosyada okunabilir bir video akışı bulunamadı.')
                stream = container.streams.video[0]
                if not self.inspected:
                    self._read_metadata(container, stream)
                    self.inspected = True
                if generate_picture:
                    self._thumbnail(container, stream)
                    self.picture_attempted = True

    def _read_metadata(self, container, stream):
        if container.duration is not None:
            self.duration = container.duration / av.time_base
        elif stream.duration is not None:
            self.duration = float(stream.duration * stream.time_base)
        formats = set(container.format.name.split(','))
        if self.path.suffix.lower() in {'.mp4', '.m4v'} and 'mp4' in formats:
            candidate = 'video/mp4'
        elif self.path.suffix.lower() == '.webm' and 'webm' in formats:
            candidate = 'video/webm'
        else:
            candidate = None
        if (candidate and stream.codec_context.name in VIDEO_CODECS[candidate] and
                all(audio.codec_context.name in AUDIO_CODECS[candidate] for audio in container.streams.audio)):
            self.content_type = candidate

    def _thumbnail(self, container, stream):
        try:
            best_frame = None
            best_score = -1
            time_base = stream.time_base
            duration = float(stream.duration * time_base) if stream.duration and time_base else self.duration
            if time_base:
                origin = stream.start_time
                if origin is None:
                    origin = round((container.start_time or 0) / av.time_base / time_base)
                offsets = [duration * fraction for fraction in (.5, .65, .8, .35)] if duration and duration > 0 else [16, 8, 3]
                for offset in offsets:
                    target = origin + int(offset / time_base)
                    try:
                        container.seek(target, stream=stream)
                        frame = None
                        for frame in islice(container.decode(stream), THUMBNAIL_DECODE_LIMIT):
                            if frame.pts is None or frame.pts >= target:
                                break
                    except (av.FFmpegError, OSError, ValueError):
                        continue
                    if frame is not None:
                        score = _visible_pixels(frame)
                        if score >= .1 and (frame.pts is None or frame.pts >= target):
                            self.picture = _picture(frame)
                            return
                        if score > best_score:
                            best_frame, best_score = frame, score

            # Non-seekable or very short media can still have decodable frames at the start.
            if best_score < .1:
                try:
                    with av.open(str(self.path)) as fallback:
                        for frame in islice(fallback.decode(fallback.streams.video[0]), 0, THUMBNAIL_DECODE_LIMIT, 6):
                            score = _visible_pixels(frame)
                            if score > best_score:
                                best_frame, best_score = frame, score
                            if score >= .1:
                                break
                except (av.FFmpegError, OSError, ValueError):
                    pass
            if best_frame is not None:
                self.picture = _picture(best_frame)
        except (av.FFmpegError, OSError, ValueError):
            # A thumbnail decoding failure should not disable the player.
            pass

    def make_clip(self, path, start):
        with self.lock:
            if not self.available():
                raise ValueError('Video değişmiş veya taşınmış. Klasörü yeniden tarayın.')
            if path.is_file():
                return
            temporary = path.with_suffix('.part')
            try:
                self._encode_clip(temporary, start)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)

    def _encode_clip(self, path, start):
        with av.open(str(self.path)) as source, av.open(str(path), 'w', format='mp4',
                options={'movflags': 'faststart'}) as output:
            video = source.streams.video[0]
            audio = next(iter(source.streams.audio), None)
            origin = (source.start_time or 0) / av.time_base
            beginning = origin + start
            ending = beginning + PREVIEW_SECONDS
            if start:
                source.seek(round(beginning * av.time_base))
            video_out = output.add_stream('libx264', rate=30, options={'preset': 'ultrafast', 'crf': '24'})
            video_out.width, video_out.height = _size(video.width or 720, video.height or 404, 720, 404)
            video_out.pix_fmt = 'yuv420p'
            video_out.codec_context.time_base = Fraction(1, 1000)
            audio_out = output.add_stream('aac', rate=48000) if audio is not None else None
            audio_pos = 0
            if audio_out is not None:
                audio_out.layout = 'stereo'
                resampler = av.AudioResampler(format='fltp', layout='stereo', rate=48000)
            last_pts = -1
            streams = [video, audio] if audio is not None else [video]
            for packet in source.demux(*streams):
                if self.suspended.is_set():
                    raise ValueError('Video taşınıyor.')
                for frame in packet.decode():
                    timestamp = frame.time
                    if timestamp is None or not beginning <= timestamp < ending:
                        continue
                    if packet.stream == video:
                        pts = round((timestamp - beginning) * 1000)
                        if pts <= last_pts:
                            continue
                        frame = frame.reformat(video_out.width, video_out.height, format=video_out.pix_fmt)
                        frame.pts = pts
                        frame.time_base = video_out.codec_context.time_base
                        last_pts = pts
                        output.mux(video_out.encode(frame))
                    else:
                        frame.pts = None
                        for sample in resampler.resample(frame):
                            sample.pts = audio_pos
                            audio_pos += sample.samples
                            output.mux(audio_out.encode(sample))
                if packet.stream == video and packet.dts is not None and packet.dts * packet.time_base >= ending:
                    break
            if last_pts < 0:
                raise ValueError('Seçilen konumda oynatılabilir bir video karesi bulunamadı.')
            output.mux(video_out.encode(None))
            if audio_out is not None:
                for sample in resampler.resample(None):
                    sample.pts = audio_pos
                    audio_pos += sample.samples
                    output.mux(audio_out.encode(sample))
                output.mux(audio_out.encode(None))


def _byte_range(header, size):
    if not header:
        return 0, size - 1
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', header)
    if not match or not size:
        raise ValueError('Invalid range')
    first, last = match.groups()
    if first:
        start, end = int(first), min(int(last), size - 1) if last else size - 1
    elif last and int(last) > 0:
        start, end = max(0, size - int(last)), size - 1
    else:
        raise ValueError('Invalid range')
    if start > end:
        raise ValueError('Invalid range')
    return start, end


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._serve()

    def do_HEAD(self):
        self._serve()

    def log_message(self, *_args):
        pass

    def _serve(self):
        match = re.fullmatch(r'/([\w-]+)/(thumbnail|source|clip-\d+)', urlsplit(self.path).path)
        if not match:
            self.send_error(404)
            return
        token, kind = match.groups()
        catalog = self.server.catalog
        source = catalog.lookup(token)
        if source is None or not source.available():
            self.send_error(404)
            return
        try:
            if kind == 'thumbnail':
                with catalog.thumbnail_slots:
                    source.inspect(include_picture=True)
                if source.picture is None:
                    self.send_error(404)
                    return
                self._headers('image/jpeg', len(source.picture), 0, len(source.picture) - 1, False)
                if self.command == 'GET':
                    self.wfile.write(source.picture)
            elif kind == 'source' and source.content_type:
                self._send_file(source, source.path, source.content_type)
            elif kind.startswith('clip-'):
                self._send_file(source, catalog.clip_path(source, int(kind[5:])), 'video/mp4')
            else:
                self.send_error(404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except (av.FFmpegError, OSError, ValueError):
            self.send_error(404)

    def _headers(self, content_type, size, start, end, partial):
        self.send_response(206 if partial else 200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(max(0, end - start + 1)))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cross-Origin-Resource-Policy', 'cross-origin')
        self.send_header('Cache-Control', 'private, max-age=300' if content_type == 'image/jpeg' else 'no-store')
        if partial:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()

    def _send_file(self, source, path, content_type):
        size = path.stat().st_size
        header = self.headers.get('Range')
        try:
            start, end = _byte_range(header, size)
        except ValueError:
            self.send_response(416)
            self.send_header('Content-Range', f'bytes */{size}')
            self.end_headers()
            return
        self._headers(content_type, size, start, end, bool(header))
        if self.command != 'GET':
            return
        position = start
        while position <= end:
            # Release the Windows file handle before every socket write so playback cannot block a move.
            try:
                with source.lock:
                    if source.suspended.is_set():
                        return
                    with path.open('rb') as file:
                        file.seek(position)
                        block = file.read(min(1024 * 1024, end - position + 1))
            except OSError:
                return
            if not block:
                return
            self.wfile.write(block)
            position += len(block)


class MediaCatalog:
    def __init__(self):
        self._lock = threading.Lock()
        self._probe_condition = threading.Condition(self._lock)
        self._probe_queue = deque()
        self._probe_started = False
        self._closed = False
        self._sources = {}
        self._server = None
        self._temporary = None
        self.thumbnail_slots = threading.BoundedSemaphore(2)
        self._clip_slots = threading.BoundedSemaphore(1)

    def register(self, path, stat):
        with self._lock:
            if self._server is None:
                self._server = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
                self._server.catalog = self
                threading.Thread(target=self._server.serve_forever, daemon=True).start()
            source = _Source(path, stat)
            self._sources[source.token] = source
            return source

    def lookup(self, token):
        with self._lock:
            return self._sources.get(token)

    def probe_durations(self, sources):
        with self._probe_condition:
            self._probe_queue = deque(source for source in sources if not source.inspected)
            if self._probe_queue and not self._probe_started:
                for _ in range(2):
                    threading.Thread(target=self._probe_worker, daemon=True).start()
                self._probe_started = True
            self._probe_condition.notify_all()

    def _probe_worker(self):
        while True:
            with self._probe_condition:
                self._probe_condition.wait_for(lambda: self._closed or self._probe_queue)
                if self._closed:
                    return
                source = self._probe_queue.popleft()
            try:
                source.inspect()
            except (av.FFmpegError, OSError, ValueError):
                pass

    def unregister(self, source):
        with self._lock:
            self._sources.pop(source.token, None)
            source.suspended.set()

    def url(self, source, kind):
        return f'http://127.0.0.1:{self._server.server_port}/{source.token}/{kind}'

    def clip_path(self, source, start):
        with self._lock:
            if self._temporary is None:
                self._temporary = tempfile.TemporaryDirectory(prefix='yolbulan-onizleme-', ignore_cleanup_errors=True)
            return Path(self._temporary.name) / f'{source.token}-{start}.mp4'

    def preview(self, source, start, prepare):
        source.inspect()
        thumbnail = self.url(source, 'thumbnail')
        descriptor = {'thumbnail_url': thumbnail, 'duration': source.duration}
        if source.content_type:
            return {**descriptor, 'url': self.url(source, 'source'), 'content_type': source.content_type,
                    'offset': 0, 'preview_duration': source.duration, 'requires_clip': False}
        if not prepare:
            return {**descriptor, 'url': None, 'content_type': 'video/mp4', 'offset': 0,
                    'preview_duration': None, 'requires_clip': True}
        if not isinstance(start, (int, float)) or not math.isfinite(start):
            raise ValueError('Önizleme konumu geçersiz.')
        offset = max(0, int(start))
        if source.duration:
            offset = min(offset, max(0, int(source.duration - 1)))
        with self._clip_slots:
            source.make_clip(self.clip_path(source, offset), offset)
        return {**descriptor, 'url': self.url(source, f'clip-{offset}'), 'content_type': 'video/mp4', 'offset': offset,
                'preview_duration': min(PREVIEW_SECONDS, source.duration - offset) if source.duration else PREVIEW_SECONDS,
                'requires_clip': True}

    def close(self):
        with self._probe_condition:
            self._closed = True
            self._probe_condition.notify_all()
            for source in self._sources.values():
                source.suspended.set()
            self._sources.clear()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._temporary is not None:
            self._temporary.cleanup()
