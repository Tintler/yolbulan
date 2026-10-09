"""Windows desktop interface for Yolbulan."""
import gc
import hashlib
import json
import os
import re
import shutil
import sys
import traceback
import unicodedata
from pathlib import Path

from PySide6.QtCore import (QAbstractTableModel, QEvent, QModelIndex, QObject, QSortFilterProxyModel,
    QThread, QTimer, Qt, Signal)
from PySide6.QtGui import (QBrush, QColor, QIcon, QKeySequence, QPalette, QShortcut, QTextCharFormat,
    QTextCursor, QTextLength, QTextTableFormat)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QStyle,
    QStyleOptionButton, QStyleOptionViewItem, QStyledItemDelegate, QTabWidget, QTableView, QTableWidget,
    QTableWidgetItem, QTextEdit, QToolButton, QVBoxLayout, QWidget)

import ayikla as core
import ses_yonlendirme as audio_ai

BASE = Path(__file__).resolve().parent
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else BASE
STATE = APP_DIR / 'calisma_verisi'
SETTINGS = STATE / 'gui_settings.json'
TRANSCRIPTS = STATE / 'transcripts'
CLASSIFICATIONS = STATE / 'classifications'
PROFILES = {
    'Hızlı': {'model': 'small', 'batch': 16, 'beam': 1, 'compute': 'float16'},
    'Dengeli': {'model': 'small', 'batch': 8, 'beam': 5, 'compute': 'float16'},
    'Hassas': {'model': 'large-v3', 'batch': 8, 'beam': 5, 'compute': 'float16'},
}
DEFAULTS = {'source': '', 'mode': 'Dosya adı + ses analizi', 'profile': 'Dengeli', 'model': 'small',
            'batch': 8, 'beam': 5, 'device': 'cuda', 'compute': 'float16', 'cuda_dir': '',
            'lm_host': '127.0.0.1', 'lm_port': 1234, 'lm_model': '', 'lm_thinking': 'model',
            'lm_chunk_size': 12000, 'lm_retries': 2}
MODE_SPEECH, MODE_NAME = 'Dosya adı + ses analizi', 'Yalnızca dosya adı'
REVIEW, NO_MATCH, STAY = 'Incelenecekler', 'eslesme_yok', '— yerinde kalsın'

# Order is also the sort order of the status column.
STATUS_COLORS = {'name': ('#caa9ff', '#7442a3'), 'speech': ('#caa9ff', '#7442a3'),
                 'none': ('#ffd874', '#865b00'), 'error': ('#ff9090', '#ad3030'),
                 'move_failed': ('#ff9090', '#ad3030'), 'working': ('#82bafc', '#155dad'),
                 'moving': ('#82bafc', '#155dad')}
STATUS = {'name': 'Ad eşleşti', 'speech': 'Ses eşleşti', 'none': 'Eşleşme yok', 'pending': 'Analiz bekliyor',
          'queued': 'Sırada', 'working': 'Analiz ediliyor', 'moving': 'Taşınıyor…', 'move_failed': 'Taşınamadı',
          'error': 'Hata'}
CHECKABLE = {'name', 'speech', 'none', 'pending', 'error', 'move_failed'}
REANALYZABLE = {'name', 'speech', 'none', 'error', 'move_failed'}
FILTERS = [('Tümü', None), ('Ad eşleşti', {'name'}), ('Ses eşleşti', {'speech'}), ('Eşleşme yok', {'none'}),
           ('Analiz bekliyor', {'pending', 'queued', 'working'}), ('Hata', {'error', 'move_failed'})]
SORT_ROLE = Qt.ItemDataRole.UserRole + 1
HAS_TEXT_ROLE = Qt.ItemDataRole.UserRole + 2
GRAYS = {False: {'button': '#505050', 'button_text': '#ffffff', 'off': '#d8d8d8', 'off_text': '#9a9a9a',
                 'checked': '#d2d2d2', 'checked_text': '#1a1a1a', 'border': '#b4b4b4'},
         True: {'button': '#d0d0d0', 'button_text': '#1a1a1a', 'off': '#3c3c3c', 'off_text': '#808080',
                'checked': '#5a5a5a', 'checked_text': '#f2f2f2', 'border': '#6a6a6a'}}
STYLE = '''
QPushButton#primary {{ background: {button}; color: {button_text}; border: none;
    border-radius: 4px; padding: 6px 16px; font-weight: 600; }}
QPushButton#primary:disabled {{ background: {off}; color: {off_text}; }}
QPushButton#chip, QPushButton#segment {{ background: palette(button); border: 1px solid {border};
    border-radius: 4px; padding: 3px 10px; }}
QPushButton#chip:checked, QPushButton#segment:checked {{ background: {checked}; color: {checked_text};
    border-color: {checked}; }}
QPushButton#link {{ border: none; color: palette(link); padding: 2px 4px; text-decoration: underline; }}
QPushButton#link:disabled {{ color: palette(mid); }}
QProgressBar {{ border: 1px solid {border}; border-radius: 3px; background: palette(base); }}
QProgressBar::chunk {{ background: #3b82f6; border-radius: 2px; }}
'''
_dll_handles = []


def transcript_highlight_spans(text, terms):
    """Return source-text offsets for whole-word matches, including Turkish case variants."""
    normalized = []
    positions = []
    for index, char in enumerate(text):
        for folded in unicodedata.normalize('NFD', char.casefold().replace('ı', 'i')):
            if not unicodedata.combining(folded):
                normalized.append(folded)
                positions.append(index)
    joined = ''.join(normalized)
    spans = set()
    for term in terms:
        needle = core.normalize(term.strip())
        if not needle:
            continue
        for found in re.finditer(r'(?<!\w)' + re.escape(needle) + r'(?!\w)', joined):
            spans.add((positions[found.start()], positions[found.end() - 1] + 1))
    return sorted(spans)


def normalize_rule(rule):
    return {'folder': rule.get('folder', ''),
            'name_terms': list(core.rule_terms(rule, 'name')),
            'audio_description': rule.get('audio_description', ', '.join(core.rule_terms(rule, 'speech'))),
            'name_negative_terms': list(rule.get('name_negative_terms', []))}


def sort_rules(rules):
    return sorted(rules, key=lambda r: r['folder'].casefold())


def default_rules():
    try:
        return sort_rules(normalize_rule(r) for r in core.read_json(BASE / 'kurallar.json', {'rules': []})['rules'])
    except (OSError, ValueError, KeyError, TypeError):
        return []


def target_for(hits):
    if not hits:
        return None
    return hits[0]['folder'] if len(hits) == 1 else REVIEW


def match_text(entry):
    hits = entry['hits']
    if any('start' in h for h in hits):
        return ', '.join(f'{h["folder"]} {audio_ai.stamp(h["start"])}' for h in hits)
    if len(hits) > 1:
        return ' · '.join(f'{h["folder"]}: {", ".join(h["terms"])}' for h in hits)
    return ', '.join(t for h in hits for t in h['terms'])


def is_dark():
    return QApplication.palette().color(QPalette.ColorRole.Base).lightness() < 128


def status_color(status):
    if status in STATUS_COLORS:
        return QColor(STATUS_COLORS[status][0 if is_dark() else 1])
    return QApplication.palette().color(QPalette.ColorRole.PlaceholderText)


def apply_theme(app):
    """Light blue row selection, gray controls and clearly different alternating rows."""
    palette = app.palette()
    dark = palette.color(QPalette.ColorRole.Base).lightness() < 128
    base = palette.color(QPalette.ColorRole.Base)
    palette.setColor(QPalette.ColorRole.AlternateBase, base.lighter(135) if dark else QColor('#ebebeb'))
    palette.setColor(QPalette.ColorRole.Highlight, QColor('#2f5f96' if dark else '#cfe2fa'))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor('#f2f2f2' if dark else '#1a1a1a'))
    palette.setColor(QPalette.ColorRole.Link, QColor('#c8c8c8' if dark else '#4a4a4a'))
    app.setPalette(palette)
    app.setStyleSheet(STYLE.format(**GRAYS[dark]))


def configure_cuda(settings):
    if settings['device'] != 'cuda':
        return
    folder = settings['cuda_dir'].strip()
    if folder:
        path = Path(folder)
        if not (path / 'cublas64_12.dll').is_file() or not (path / 'cudnn64_9.dll').is_file():
            raise ValueError('CUDA DLL klasöründe cublas64_12.dll ve cudnn64_9.dll bulunmalı.')
        os.environ['PATH'] = str(path) + os.pathsep + os.environ.get('PATH', '')
        if hasattr(os, 'add_dll_directory'):
            # Keep the handle alive until the application exits.
            _dll_handles.append(os.add_dll_directory(str(path)))
    elif not shutil.which('cublas64_12.dll') or not shutil.which('cudnn64_9.dll'):
        raise ValueError('CUDA DLL dosyaları bulunamadı. Ayarlar’dan CUDA DLL klasörünü seçin veya CPU kullanın.')


class Worker(QObject):
    progress = Signal(int, int)
    result = Signal(object)
    finished = Signal()

    def __init__(self, task, **kwargs):
        super().__init__()
        self.task, self.kwargs, self.cancelled = task, kwargs, False

    def report(self, kind):
        return lambda path, status, detail: self.result.emit((kind, (path, status, detail)))

    def run(self):
        try:
            if self.task == 'analyze':
                self.analyze(**self.kwargs)
            elif self.task == 'move':
                core.apply(self.kwargs['entries'], self.kwargs['root'], STATE, reporter=self.report('move_item'))
            else:
                core.undo(STATE, reporter=self.report('undo_item'))
        except Exception as exc:
            self.result.emit(('fatal', (self.task, str(exc), traceback.format_exc())))
        finally:
            self.finished.emit()

    def analyze(self, paths, rules, signature, model, device, compute, batch, beam,
                lm_host, lm_port, lm_model, lm_thinking, lm_chunk_size, lm_retries):
        models = audio_ai.list_models(lm_host, lm_port)
        if lm_model not in models:
            raise RuntimeError(f'LM Studio model listesinde “{lm_model}” bulunamadı. Ayarlar’da Modelleri getir düğmesini kullanın.')
        engine = None
        total = len(paths)
        transcripts = []
        # Finish Whisper for all videos, then release its VRAM before the text model runs.
        for index, path in enumerate(paths, 1):
            if self.cancelled:
                break
            path = Path(path)
            self.progress.emit(index - 1, total * 2)
            try:
                stat = core.fingerprint(path)
                cached = core.read_json(core.cache_path(TRANSCRIPTS, path))
                if not (cached and cached.get('fingerprint') == stat and cached.get('signature') == signature):
                    if engine is None:
                        self.result.emit(('working', (str(path), 'Model yükleniyor')))
                        engine = core.transcriber(model, device, compute, batch, beam)
                    self.result.emit(('working', (str(path), 'Yazıya dökülüyor')))
                    segments = engine(path)
                    core.write_json(core.cache_path(TRANSCRIPTS, path), {
                        'source': str(path), 'fingerprint': stat, 'signature': signature,
                        'model': model, 'segments': segments})
                transcripts.append((path, stat))
                self.result.emit(('transcribed', str(path)))
            except Exception as exc:
                self.result.emit(('error', (str(path), str(exc))))
            self.progress.emit(index, total * 2)
        engine = None
        gc.collect()
        for index, (path, stat) in enumerate(transcripts, 1):
            if self.cancelled:
                break
            self.progress.emit(total + index - 1, total * 2)
            self.result.emit(('working', (str(path), 'LM Studio değerlendiriyor')))
            try:
                segments = core.read_json(core.cache_path(TRANSCRIPTS, path))['segments']
                ai_signature = json.dumps({'version': 3, 'fingerprint': stat, 'whisper': signature,
                    'lm_host': lm_host, 'lm_port': lm_port, 'lm_model': lm_model,
                    'thinking': lm_thinking, 'chunk_size': lm_chunk_size,
                    'rules': [{'folder': r['folder'], 'audio_description': r.get('audio_description', '')}
                              for r in rules]}, ensure_ascii=False, sort_keys=True)
                ai_signature = hashlib.sha256(ai_signature.encode('utf-8')).hexdigest()
                ai_cache_path = core.cache_path(CLASSIFICATIONS, path)
                ai_cache = core.read_json(ai_cache_path)
                if ai_cache and ai_cache.get('signature') == ai_signature:
                    hits = ai_cache['hits']
                else:
                    hits = audio_ai.classify(segments, rules, lm_host, lm_port, lm_model,
                        progress=lambda current, parts: self.result.emit(
                            ('working', (str(path), f'LM Studio değerlendiriyor · {current}/{parts} parça'))),
                        on_retry=lambda attempt, maximum, message: self.result.emit(
                            ('ai_retry', (str(path), attempt, maximum, message))),
                        cancelled=lambda: self.cancelled, thinking=lm_thinking,
                        chunk_size=lm_chunk_size, retries=lm_retries)
                    if hits is None:
                        break
                    core.write_json(ai_cache_path, {'signature': ai_signature, 'hits': hits})
                self.result.emit(('classified', (str(path), stat, hits)))
            except Exception as exc:
                self.result.emit(('error', (str(path), str(exc))))
            self.progress.emit(total + index, total * 2)


class VideoModel(QAbstractTableModel):
    HEADERS = ['', 'Video', 'Durum', 'Eşleşen', 'Hedef', 'Metin']
    needs_target = Signal()

    def __init__(self):
        super().__init__()
        self.entries = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def flags(self, index):
        flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        if self.entries[index.row()]['status'] in CHECKABLE:
            if index.column() == 0:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
            elif index.column() == 4:
                flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        e = self.entries[index.row()]
        column, checkable = index.column(), e['status'] in CHECKABLE
        display = role == Qt.ItemDataRole.DisplayRole
        if column == 0:
            if role == Qt.ItemDataRole.CheckStateRole and checkable:
                return Qt.CheckState.Checked if e['checked'] else Qt.CheckState.Unchecked
            if role == SORT_ROLE:
                return int(checkable and e['checked'])
        elif column == 1:
            if display:
                return Path(e['path']).name
            if role == SORT_ROLE:
                return Path(e['path']).name.casefold()
            if role == Qt.ItemDataRole.ToolTipRole:
                return e['path']
        elif column == 2:
            if display:
                return e.get('label') or STATUS[e['status']]
            if role == SORT_ROLE:
                return list(STATUS).index(e['status'])
            if role == Qt.ItemDataRole.ForegroundRole:
                return QBrush(status_color(e['status']))
            if role == Qt.ItemDataRole.BackgroundRole and e['status'] in STATUS_COLORS:
                background = status_color(e['status'])
                background.setAlpha(60 if is_dark() else 40)
                return QBrush(background)
            if role == Qt.ItemDataRole.ToolTipRole:
                return e.get('note')
        elif column == 3:
            if display or role == SORT_ROLE:
                return match_text(e)
            if role == Qt.ItemDataRole.ToolTipRole:
                lines = [f'{h["folder"]} · {audio_ai.stamp(h["start"])} · {h["evidence"]}'
                         for h in e['hits'] if 'start' in h]
                return '\n'.join(lines) or match_text(e) or None
        elif column == 4:
            if display or role == SORT_ROLE:
                return e['target'] or (STAY if checkable else '—')
            if role == Qt.ItemDataRole.EditRole:
                return e['target'] or STAY
            if role == Qt.ItemDataRole.ForegroundRole and not e['target']:
                return QBrush(QApplication.palette().color(QPalette.ColorRole.PlaceholderText))
        elif column == 5:
            if role in (HAS_TEXT_ROLE, SORT_ROLE):
                return int(e['has_text'])
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        e = self.entries[index.row()]
        if e['status'] not in CHECKABLE:
            return False
        if index.column() == 0 and role == Qt.ItemDataRole.CheckStateRole:
            checked = int(getattr(value, 'value', value)) == Qt.CheckState.Checked.value
            if checked and not e['target']:
                self.needs_target.emit()
                return False
            e['checked'] = checked
        elif index.column() == 4 and role == Qt.ItemDataRole.EditRole:
            # Choosing a folder is a request to move; "stay" withdraws it.
            e['target'] = None if value == STAY else value
            e['checked'] = e['target'] is not None
        else:
            return False
        self.changed(e)
        return True

    def set_entries(self, entries):
        self.beginResetModel()
        self.entries = entries
        self.endResetModel()

    def find(self, path):
        return next((e for e in self.entries if e['path'] == path), None)

    def changed(self, entry):
        row = self.entries.index(entry)
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(self.HEADERS) - 1))

    def update(self, path, **fields):
        entry = self.find(path)
        if entry:
            entry.update(fields)
            self.changed(entry)
        return entry

    def remove(self, path):
        entry = self.find(path)
        if entry:
            row = self.entries.index(entry)
            self.beginRemoveRows(QModelIndex(), row, row)
            del self.entries[row]
            self.endRemoveRows()

    def append(self, entry):
        self.beginInsertRows(QModelIndex(), len(self.entries), len(self.entries))
        self.entries.append(entry)
        self.endInsertRows()


class VideoFilter(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.statuses, self.text = None, ''
        self.setSortRole(SORT_ROLE)

    def set_filter(self, statuses=None, text=None):
        if statuses is not None:
            self.statuses = statuses or None
        if text is not None:
            self.text = core.normalize(text.strip())
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        e = self.sourceModel().entries[row]
        return ((self.statuses is None or e['status'] in self.statuses) and
                (not self.text or self.text in core.normalize(Path(e['path']).name)))


class TargetDelegate(QStyledItemDelegate):
    def __init__(self, options, parent):
        super().__init__(parent)
        self.options = options

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.addItems([STAY, *self.options()])
        combo.activated.connect(lambda _index, c=combo: (self.commitData.emit(c), self.closeEditor.emit(c)))
        QTimer.singleShot(0, combo.showPopup)
        return combo

    def setEditorData(self, editor, index):
        editor.setCurrentText(index.data(Qt.ItemDataRole.EditRole))

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText())


class ButtonDelegate(QStyledItemDelegate):
    def __init__(self, on_click, parent):
        super().__init__(parent)
        self.on_click = on_click

    def paint(self, painter, option, index):
        style = option.widget.style() if option.widget else QApplication.style()
        item = QStyleOptionViewItem(option)
        self.initStyleOption(item, index)
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, item, painter, option.widget)
        if not index.data(HAS_TEXT_ROLE):
            return
        button = QStyleOptionButton()
        button.rect = option.rect.adjusted(4, 2, -4, -2)
        button.text = 'Aç'
        button.state = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Raised
        style.drawControl(QStyle.ControlElement.CE_PushButton, button, painter, option.widget)

    def editorEvent(self, event, model, option, index):
        if (event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton
                and index.data(HAS_TEXT_ROLE) and option.rect.contains(event.position().toPoint())):
            self.on_click(index)
            return True
        return False


class SettingsDialog(QDialog):
    """Rules and analysis settings share one window with two tabs."""

    def __init__(self, parent, settings, rules, tab=0):
        super().__init__(parent)
        self.setWindowTitle('Kurallar ve ayarlar')
        self.resize(980, 560)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.tabs.addTab(self.build_rules(rules), 'Kurallar')
        self.tabs.addTab(self.build_settings(settings), 'Ayarlar')
        self.tabs.setCurrentIndex(tab)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('Kaydet')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Vazgeç')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def build_rules(self, rules):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.rules = QTableWidget(0, 4)
        self.rules.setHorizontalHeaderLabels(['Hedef alt klasör', 'Dosya adı terimleri (+)',
                                              'Dosya adı engelleri (−)', 'Ses içeriği tanımı (AI)'])
        header = self.rules.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for column in range(1, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        self.rules.horizontalHeaderItem(1).setToolTip('Virgülle ayırın. Terim dosya adının herhangi bir yerinde aranır.')
        self.rules.horizontalHeaderItem(2).setToolTip('Bu terimlerden biri dosya adında geçerse bu hedef eşleşmez. Diğer hedefleri etkilemez.')
        self.rules.horizontalHeaderItem(3).setToolTip('LM Studio transkriptin tamamını bu tanıma göre değerlendirir. Örnek: Anne ile kızının aile bağları üzerine konuşması.')
        self.rules.verticalHeader().setVisible(False)
        self.rules.setWordWrap(True)
        for rule in rules:
            self.add_rule(rule)
        layout.addWidget(self.rules)
        controls = QHBoxLayout()
        add = QPushButton('+ Kural ekle')
        add.clicked.connect(lambda: self.add_rule(focus=True))
        remove = QPushButton('Seçili kuralı sil')
        remove.clicked.connect(self.remove_rule)
        controls.addWidget(add)
        controls.addWidget(remove)
        controls.addStretch()
        controls.addWidget(QLabel('Her kural için dosya adı terimi veya ses içeriği tanımından en az biri gerekli.'))
        layout.addLayout(controls)
        return page

    def add_rule(self, rule=None, focus=False):
        rule = rule or {'folder': '', 'name_terms': [], 'name_negative_terms': [], 'audio_description': ''}
        row = self.rules.rowCount()
        self.rules.insertRow(row)
        for column, text in enumerate((rule['folder'], ', '.join(rule['name_terms']),
                                       ', '.join(rule['name_negative_terms']), rule['audio_description'])):
            self.rules.setItem(row, column, QTableWidgetItem(text))
        if focus:
            self.rules.setCurrentCell(row, 0)
            self.rules.editItem(self.rules.item(row, 0))

    def remove_rule(self):
        row = self.rules.currentRow()
        if row < 0:
            return
        folder = self.rules.item(row, 0).text()
        if QMessageBox.question(self, 'Kuralı sil', f'“{folder or "Adsız kural"}” kuralı silinsin mi?') == QMessageBox.StandardButton.Yes:
            self.rules.removeRow(row)

    def collect_rules(self):
        def terms(text):
            return [t.strip() for t in text.split(',') if t.strip()]
        rules = []
        for row in range(self.rules.rowCount()):
            folder, names, negative, audio = (self.rules.item(row, c).text().strip() for c in range(4))
            if folder or names or negative or audio:
                rules.append({'folder': folder, 'name_terms': terms(names), 'audio_description': audio,
                              'name_negative_terms': terms(negative)})
        return rules

    def build_settings(self, s):
        page = QWidget()
        layout = QHBoxLayout(page)
        whisper = QGroupBox('Konuşmayı yazıya dökme (Whisper)')
        form = QFormLayout(whisper)
        self.profile = QComboBox()
        self.profile.addItems([*PROFILES, 'Özel'])
        self.profile.setToolTip('Hızlı, Dengeli ve Hassas hazır ayarları uygular. Tek tek değer değiştirince profil Özel olur.')
        self.model = QComboBox()
        self.model.addItems(['small', 'medium', 'large-v3', 'turbo'])
        self.model.setToolTip('Büyük modeller genellikle daha doğru, daha yavaş ve daha çok bellek kullanır.')
        self.device = QComboBox()
        self.device.addItems(['cuda', 'cpu'])
        self.batch = QSpinBox()
        self.batch.setRange(1, 32)
        self.batch.setToolTip('Aynı anda işlenen ses parçaları. Yüksek değer daha çok GPU belleği kullanır; 1 klasik işlem modudur.')
        self.beam = QSpinBox()
        self.beam.setRange(1, 10)
        self.beam.setToolTip('1 daha hızlı; 5 genellikle daha dikkatli ama yavaştır.')
        self.compute = QComboBox()
        self.compute.addItems(['float16', 'int8_float16', 'int8'])
        self.compute.setToolTip('float16 daha çok bellek; int8_float16 ve int8 daha az bellek kullanır.')
        self.cuda_dir = QLineEdit(s['cuda_dir'])
        self.cuda_dir.setPlaceholderText('cublas64_12.dll ve cudnn64_9.dll içeren klasör')
        cuda_row = QHBoxLayout()
        cuda_row.addWidget(self.cuda_dir, 1)
        cuda_browse = QPushButton('Gözat…')
        cuda_browse.clicked.connect(self.browse_cuda)
        cuda_row.addWidget(cuda_browse)
        for label, widget in (('Profil', self.profile), ('Model', self.model), ('GPU/CPU', self.device),
                              ('Toplu iş boyutu', self.batch), ('Beam', self.beam), ('Hesaplama', self.compute)):
            form.addRow(label + ':', widget)
        form.addRow('CUDA DLL klasörü:', cuda_row)
        self.model.setCurrentText(s['model'])
        self.device.setCurrentText(s['device'])
        self.batch.setValue(s['batch'])
        self.beam.setValue(s['beam'])
        self.compute.setCurrentText(s['compute'])
        self.profile.setCurrentText(s['profile'])
        self.profile.currentTextChanged.connect(self.profile_changed)
        self.model.currentTextChanged.connect(self.customize)
        self.batch.valueChanged.connect(self.customize)
        self.beam.valueChanged.connect(self.customize)
        self.compute.currentTextChanged.connect(self.customize)
        self.device.currentTextChanged.connect(self.device_changed)

        lm = QGroupBox('LM Studio')
        lm_form = QFormLayout(lm)
        self.lm_host = QLineEdit(s['lm_host'])
        self.lm_host.setPlaceholderText('127.0.0.1 veya yerel ağ IP adresi')
        self.lm_port = QSpinBox()
        self.lm_port.setRange(1, 65535)
        self.lm_port.setValue(s['lm_port'])
        self.lm_model = QComboBox()
        self.lm_model.setEditable(True)
        self.lm_model.setCurrentText(s['lm_model'])
        self.lm_model.setToolTip('LM Studio’da yüklü metin modelinin kimliği. Elle de yazabilirsiniz.')
        model_row = QHBoxLayout()
        model_row.addWidget(self.lm_model, 1)
        fetch = QPushButton('Modelleri getir')
        fetch.clicked.connect(self.load_lm_models)
        model_row.addWidget(fetch)
        self.lm_thinking = QComboBox()
        self.lm_thinking.addItems(['Model ayarı', 'Kapalı'])
        self.lm_thinking.setCurrentText('Kapalı' if s['lm_thinking'] == 'off' else 'Model ayarı')
        self.lm_thinking.setToolTip('Kapalı: istekte reasoning=off kullanılır; model desteklemiyorsa hata gösterilir.')
        self.lm_chunk_size = QSpinBox()
        self.lm_chunk_size.setRange(4000, 20000)
        self.lm_chunk_size.setSingleStep(1000)
        self.lm_chunk_size.setSuffix(' karakter')
        self.lm_chunk_size.setValue(s['lm_chunk_size'])
        self.lm_chunk_size.setToolTip('Her istekte kullanılan yaklaşık transkript uzunluğu. Komşu parçalar örtüşür.')
        self.lm_retries = QSpinBox()
        self.lm_retries.setRange(0, 5)
        self.lm_retries.setValue(s['lm_retries'])
        self.lm_retries.setToolTip('Geçersiz JSON veya doğrulanamayan alıntıda ek istek sayısı. Bağlantı hataları tekrar edilmez.')
        lm_form.addRow('IP adresi:', self.lm_host)
        lm_form.addRow('Port:', self.lm_port)
        lm_form.addRow('Metin modeli:', model_row)
        lm_form.addRow('Thinking:', self.lm_thinking)
        lm_form.addRow('Transkript penceresi:', self.lm_chunk_size)
        lm_form.addRow('JSON yeniden deneme:', self.lm_retries)
        layout.addWidget(whisper, 1)
        layout.addWidget(lm, 1)
        return page

    def browse_cuda(self):
        chosen = QFileDialog.getExistingDirectory(self, 'CUDA DLL klasörünü seç', self.cuda_dir.text())
        if chosen:
            self.cuda_dir.setText(chosen)

    def load_lm_models(self):
        try:
            models = audio_ai.list_models(self.lm_host.text(), self.lm_port.value())
            if not models:
                raise ValueError('LM Studio model döndürmedi. Sunucuyu başlatıp bir metin modeli yükleyin.')
            current = self.lm_model.currentText()
            self.lm_model.clear()
            self.lm_model.addItems(models)
            if current in models:
                self.lm_model.setCurrentText(current)
        except Exception as exc:
            QMessageBox.warning(self, 'LM Studio bağlantısı', str(exc))

    def profile_changed(self, name):
        if name not in PROFILES:
            return
        p = PROFILES[name]
        for widget, value in [(self.model, p['model']), (self.batch, p['batch']),
                              (self.beam, p['beam']), (self.compute, p['compute'])]:
            widget.blockSignals(True)
            (widget.setValue if isinstance(widget, QSpinBox) else widget.setCurrentText)(value)
            widget.blockSignals(False)
        self.device_changed(self.device.currentText())

    def customize(self, *_):
        if self.profile.currentText() != 'Özel':
            self.profile.blockSignals(True)
            self.profile.setCurrentText('Özel')
            self.profile.blockSignals(False)

    def device_changed(self, name):
        if name == 'cpu' and self.compute.currentText() != 'int8':
            self.compute.setCurrentText('int8')
        elif name == 'cuda' and self.compute.currentText() == 'int8' and self.profile.currentText() in PROFILES:
            self.compute.setCurrentText(PROFILES[self.profile.currentText()]['compute'])

    def accept(self):
        rules = self.collect_rules()
        try:
            core.config_load({'rules': [dict(r) for r in rules]})
        except ValueError as exc:
            self.tabs.setCurrentIndex(0)
            QMessageBox.warning(self, 'Kurallar kaydedilemedi', str(exc))
            return
        try:
            if self.lm_host.text().strip():
                audio_ai.base_url(self.lm_host.text(), self.lm_port.value())
        except ValueError as exc:
            self.tabs.setCurrentIndex(1)
            QMessageBox.warning(self, 'LM Studio adresi', str(exc))
            return
        self.result_rules = rules
        self.result_settings = {
            'profile': self.profile.currentText(), 'model': self.model.currentText(),
            'batch': self.batch.value(), 'beam': self.beam.value(), 'device': self.device.currentText(),
            'compute': self.compute.currentText(), 'cuda_dir': self.cuda_dir.text().strip(),
            'lm_host': self.lm_host.text().strip(), 'lm_port': self.lm_port.value(),
            'lm_model': self.lm_model.currentText().strip(),
            'lm_thinking': 'off' if self.lm_thinking.currentText() == 'Kapalı' else 'model',
            'lm_chunk_size': self.lm_chunk_size.value(), 'lm_retries': self.lm_retries.value()}
        super().accept()


def show_transcript(parent, path, terms):
    cached = core.read_json(core.cache_path(TRANSCRIPTS, path))
    if not cached or not cached.get('segments'):
        QMessageBox.information(parent, 'Transkript yok', 'Bu video için henüz transkript oluşturulmadı.')
        return
    dialog = QDialog(parent)
    dialog.setWindowTitle(f'Transkript · {Path(path).name}')
    dialog.resize(850, 620)
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(str(path)))
    text = QTextEdit()
    text.setReadOnly(True)
    palette = parent.palette()
    text.setPalette(palette)
    base = palette.color(QPalette.ColorRole.Base)
    alternate = palette.color(QPalette.ColorRole.AlternateBase)
    if base == alternate:
        alternate = base.lighter(110) if base.lightness() < 128 else base.darker(106)
    table_format = QTextTableFormat()
    table_format.setWidth(QTextLength(QTextLength.Type.PercentageLength, 100))
    table_format.setCellPadding(7)
    table_format.setCellSpacing(0)
    table_format.setBorder(0)
    table = text.textCursor().insertTable(len(cached['segments']), 1, table_format)
    matches = []
    for index, segment in enumerate(cached['segments']):
        cell = table.cellAt(index, 0)
        cell_format = cell.format()
        cell_format.setBackground(QBrush(base if index % 2 == 0 else alternate))
        cell.setFormat(cell_format)
        line = f'[{audio_ai.stamp(segment["start"])} – {audio_ai.stamp(segment["end"])}] {segment["text"]}'
        cell.firstCursorPosition().insertText(line)
        for start, end in transcript_highlight_spans(line, terms):
            matches.append((index, start, end))
    match_cursors = []
    highlight = QTextCharFormat()
    highlight.setBackground(QColor('#755c1b' if base.lightness() < 128 else '#ffe082'))
    for index, start, end in matches:
        cursor = table.cellAt(index, 0).firstCursorPosition()
        beginning = cursor.position()
        cursor.setPosition(beginning + start)
        cursor.setPosition(beginning + end, QTextCursor.MoveMode.KeepAnchor)
        cursor.mergeCharFormat(highlight)
        match_cursors.append(cursor)
    text.moveCursor(QTextCursor.MoveOperation.Start)
    layout.addWidget(text)
    navigation = QHBoxLayout()
    previous = QPushButton('◀ Önceki')
    next_match = QPushButton('Sonraki ▶')
    counter = QLabel('0 / 0' if match_cursors else 'Eşleşme yok')
    previous.setEnabled(bool(match_cursors))
    next_match.setEnabled(bool(match_cursors))
    active_match = [0]

    def show_match(index):
        if not match_cursors:
            return
        active_match[0] = index % len(match_cursors)
        # Mark the current match with its own color; a text selection would hide the highlight.
        current = QTextEdit.ExtraSelection()
        current.cursor = match_cursors[active_match[0]]
        current.format.setBackground(QColor('#b35c00' if base.lightness() < 128 else '#ffb74d'))
        text.setExtraSelections([current])
        caret = QTextCursor(current.cursor)
        caret.clearSelection()
        text.setTextCursor(caret)
        text.ensureCursorVisible()
        counter.setText(f'{active_match[0] + 1} / {len(match_cursors)}')

    previous.clicked.connect(lambda: show_match(active_match[0] - 1))
    next_match.clicked.connect(lambda: show_match(active_match[0] + 1))
    navigation.addStretch()
    navigation.addWidget(previous)
    navigation.addWidget(counter)
    navigation.addWidget(next_match)
    navigation.addStretch()
    layout.addLayout(navigation)
    close = QPushButton('Kapat')
    close.clicked.connect(dialog.accept)
    layout.addWidget(close)
    if match_cursors:
        QTimer.singleShot(0, lambda: show_match(0))
    dialog.exec()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Yolbulan')
        self.resize(1300, 800)
        self.jobs = {}
        self.root = None
        self.scan_rules = []
        self.load_error = None
        try:
            saved = core.read_json(SETTINGS, {}) or {}
        except (OSError, ValueError) as exc:
            saved, self.load_error = {}, str(exc)
        self.settings = {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}
        self.rules = (sort_rules(normalize_rule(r) for r in saved['rules'])
                      if isinstance(saved.get('rules'), list) else default_rules())

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel('Kaynak klasör:'))
        self.source = QLineEdit(self.settings['source'])
        self.source.setPlaceholderText('Videoların bulunduğu klasör; hedef alt klasörler bunun içinde oluşturulur')
        source_row.addWidget(self.source, 1)
        self.browse_btn = QPushButton('Gözat…')
        self.browse_btn.clicked.connect(self.browse)
        source_row.addWidget(self.browse_btn)
        source_row.addSpacing(12)
        self.mode_group = QButtonGroup(self)
        for index, (text, tip) in enumerate(((MODE_SPEECH, 'Dosya adı eşleşmeyen videolar ses analizine girebilir.'),
                                             (MODE_NAME, 'Yalnız dosya adına bakılır; Whisper ve LM Studio çalışmaz.'))):
            button = QPushButton(text)
            button.setObjectName('segment')
            button.setCheckable(True)
            button.setToolTip(tip)
            button.setChecked(self.settings['mode'] == text)
            self.mode_group.addButton(button, index)
            source_row.addWidget(button)
        if not self.mode_group.checkedButton():
            self.mode_group.button(0).setChecked(True)
        self.mode_group.idClicked.connect(self.mode_changed)
        outer.addLayout(source_row)

        actions = QHBoxLayout()
        self.scan_btn = QPushButton('Adları tara')
        self.scan_btn.setToolTip('Klasörü tarar ve dosya adlarını kurallarla eşleştirir. Hiçbir dosyayı taşımaz.')
        self.scan_btn.clicked.connect(self.scan_names)
        actions.addWidget(self.scan_btn)
        self.analyze_btn = QPushButton('Sesi analiz et')
        self.analyze_btn.setToolTip('“Analiz bekliyor” durumundaki videoları Whisper ile yazıya döker ve LM Studio ile değerlendirir.')
        self.analyze_btn.clicked.connect(self.start_analysis)
        actions.addWidget(self.analyze_btn)
        self.stop_btn = QPushButton('Durdur')
        self.stop_btn.setToolTip('Geçerli video veya LM Studio isteği bitince analiz durur.')
        self.stop_btn.clicked.connect(self.cancel_analysis)
        actions.addWidget(self.stop_btn)
        actions.addStretch()
        rules_btn = QPushButton('Kurallar')
        rules_btn.clicked.connect(lambda: self.open_settings(0))
        settings_btn = QPushButton('Ayarlar')
        settings_btn.clicked.connect(lambda: self.open_settings(1))
        actions.addWidget(rules_btn)
        actions.addWidget(settings_btn)
        outer.addLayout(actions)

        filters = QHBoxLayout()
        self.filter_group = QButtonGroup(self)
        for index, (label, statuses) in enumerate(FILTERS):
            chip = QPushButton(label)
            chip.setObjectName('chip')
            chip.setCheckable(True)
            chip.setChecked(index == 0)
            self.filter_group.addButton(chip, index)
            filters.addWidget(chip)
        self.filter_group.idClicked.connect(lambda index: self.proxy.set_filter(statuses=FILTERS[index][1] or set()))
        filters.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Videolarda ara')
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(260)
        self.search.textChanged.connect(lambda text: self.proxy.set_filter(text=text))
        filters.addWidget(self.search)
        outer.addLayout(filters)

        progress_row = QHBoxLayout()
        self.progress_label = QLabel()
        self.progress = QProgressBar()
        self.progress.setMaximumHeight(14)
        self.progress.setTextVisible(False)
        progress_row.addWidget(self.progress_label)
        progress_row.addWidget(self.progress, 1)
        self.progress_box = QWidget()
        self.progress_box.setLayout(progress_row)
        progress_row.setContentsMargins(0, 0, 0, 0)
        self.progress_box.setVisible(False)
        outer.addWidget(self.progress_box)

        self.model = VideoModel()
        self.model.needs_target.connect(self.target_hint)
        self.proxy = VideoFilter()
        self.proxy.setSourceModel(self.model)
        self.view = QTableView()
        self.view.setModel(self.proxy)
        self.view.setSortingEnabled(True)
        self.view.sortByColumn(1, Qt.SortOrder.AscendingOrder)
        self.view.setAlternatingRowColors(True)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.CurrentChanged |
                                  QAbstractItemView.EditTrigger.SelectedClicked)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(24)
        self.view.setWordWrap(False)
        self.view.setItemDelegateForColumn(4, TargetDelegate(self.target_options, self.view))
        self.view.setItemDelegateForColumn(5, ButtonDelegate(
            lambda index: self.open_transcript(self.entry_at(index)), self.view))
        header = self.view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column, width in ((0, 30), (2, 190), (3, 230), (4, 170), (5, 60)):
            header.resizeSection(column, width)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self.show_menu)
        QShortcut(QKeySequence(Qt.Key.Key_Space), self.view, self.toggle_selected,
                  context=Qt.ShortcutContext.WidgetShortcut)
        outer.addWidget(self.view, 1)

        bottom = QHBoxLayout()
        self.selection_label = QLabel()
        bottom.addWidget(self.selection_label)
        check_visible = QPushButton('Görünenleri işaretle')
        check_visible.setObjectName('link')
        check_visible.setToolTip('Listede görünen ve hedefi seçili videoları işaretler.')
        check_visible.clicked.connect(self.check_visible)
        clear = QPushButton('İşaretleri temizle')
        clear.setObjectName('link')
        clear.setToolTip('Tüm işaretleri kaldırır; hedef seçimleri korunur.')
        clear.clicked.connect(lambda: self.set_checked(self.model.entries, False))
        bottom.addWidget(check_visible)
        bottom.addWidget(clear)
        bottom.addStretch()
        self.undo_btn = QPushButton('Son taşımayı geri al')
        self.undo_btn.setToolTip('En son taşıma işleminde taşınan ve değişmemiş videoları eski yerine döndürür. '
                                 'Tekrar basınca bir önceki taşımaya geçer.')
        self.undo_btn.clicked.connect(self.undo)
        bottom.addWidget(self.undo_btn)
        self.move_btn = QPushButton('Seçilenleri taşı')
        self.move_btn.setObjectName('primary')
        self.move_btn.clicked.connect(self.move_checked)
        bottom.addWidget(self.move_btn)
        outer.addLayout(bottom)

        log_row = QHBoxLayout()
        self.log_toggle = QToolButton()
        self.log_toggle.setText('Günlük')
        self.log_toggle.setCheckable(True)
        self.log_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.log_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.log_toggle.setAutoRaise(True)
        self.log_toggle.toggled.connect(self.toggle_log)
        self.last_log = QLabel()
        self.last_log.setStyleSheet('color: palette(placeholder-text);')
        log_row.addWidget(self.log_toggle)
        log_row.addWidget(self.last_log, 1)
        outer.addLayout(log_row)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(130)
        self.log.setVisible(False)
        outer.addWidget(self.log)

        for signal in (self.model.dataChanged, self.model.rowsInserted, self.model.rowsRemoved, self.model.modelReset):
            signal.connect(self.update_controls)
        self.source.editingFinished.connect(self.save_settings)
        self.update_controls()
        if self.load_error:
            QTimer.singleShot(0, lambda: QMessageBox.warning(
                self, 'Ayarlar okunamadı', f'Kayıtlı ayarlar okunamadı; varsayılanlar kullanılıyor.\n\n{self.load_error}'))

    # ---- helpers -------------------------------------------------------------------------------

    def name_only(self):
        return self.mode_group.checkedId() == 1

    def target_options(self):
        return list(dict.fromkeys([r['folder'] for r in self.rules if r['folder']] + [REVIEW, NO_MATCH]))

    def entry_at(self, proxy_index):
        return self.model.entries[self.proxy.mapToSource(proxy_index).row()]

    def selected_entries(self):
        rows = {self.proxy.mapToSource(index).row() for index in self.view.selectionModel().selectedRows()}
        return [self.model.entries[row] for row in sorted(rows)]

    def log_message(self, message):
        self.log.appendPlainText(message)
        self.last_log.setText(message.splitlines()[0])

    def toggle_log(self, shown):
        self.log.setVisible(shown)
        self.last_log.setVisible(not shown)
        self.log_toggle.setArrowType(Qt.ArrowType.DownArrow if shown else Qt.ArrowType.RightArrow)

    def save_settings(self):
        self.settings['source'] = self.source.text().strip()
        self.settings['mode'] = MODE_NAME if self.name_only() else MODE_SPEECH
        try:
            core.write_json(SETTINGS, {**self.settings, 'rules': self.rules})
        except OSError as exc:
            self.log_message(f'Ayar kaydetme hatası: {exc}')

    def make_entry(self, path):
        hits = core.filename_rule_hits(path.name, self.scan_rules)
        return {'path': str(path), 'stat': core.fingerprint(path), 'hits': hits,
                'status': 'name' if hits else ('none' if self.name_only() else 'pending'),
                'label': None, 'note': None, 'target': target_for(hits), 'checked': bool(hits),
                'analyzed': False, 'has_text': core.cache_path(TRANSCRIPTS, path).is_file()}

    def update_controls(self, *_):
        entries = self.model.entries
        analyzing, busy = 'analyze' in self.jobs, bool(self.jobs)
        counts = {label: sum(statuses is None or e['status'] in statuses for e in entries)
                  for label, statuses in FILTERS}
        for index, (label, _statuses) in enumerate(FILTERS):
            self.filter_group.button(index).setText(f'{label} {counts[label]}')
        pending = sum(e['status'] == 'pending' for e in entries)
        self.analyze_btn.setText(f'Sesi analiz et ({pending})' if pending else 'Sesi analiz et')
        self.analyze_btn.setEnabled(not analyzing and not self.name_only() and pending > 0)
        self.analyze_btn.setVisible(not self.name_only())
        self.stop_btn.setVisible(not self.name_only())
        self.stop_btn.setEnabled(analyzing)
        self.scan_btn.setEnabled(not busy)
        self.source.setEnabled(not busy)
        self.browse_btn.setEnabled(not busy)
        for button in self.mode_group.buttons():
            button.setEnabled(not analyzing)
        checked = [e for e in entries if e['checked'] and e['target'] and e['status'] in CHECKABLE]
        self.selection_label.setText(f'{len(checked)} video işaretli')
        self.move_btn.setText(f'Seçilen {len(checked)} videoyu taşı' if checked else 'Seçilenleri taşı')
        self.move_btn.setEnabled(bool(checked) and 'move' not in self.jobs and 'undo' not in self.jobs)
        self.undo_btn.setEnabled(not busy)

    # ---- user actions --------------------------------------------------------------------------

    def browse(self):
        chosen = QFileDialog.getExistingDirectory(self, 'Video klasörü seç', self.source.text())
        if chosen:
            self.source.setText(chosen)
            self.save_settings()

    def open_settings(self, tab):
        dialog = SettingsDialog(self, self.settings, self.rules, tab)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        rules = sort_rules(dialog.result_rules)
        rules_changed = rules != self.rules
        self.rules = rules
        self.settings.update(dialog.result_settings)
        self.save_settings()
        self.log_message('Kurallar ve ayarlar kaydedildi.')
        if rules_changed and self.model.entries:
            self.statusBar().showMessage('Kurallar değişti. Dosya adı sonuçlarını güncellemek için Adları tara’ya basın.', 15000)

    def mode_changed(self, *_):
        for e in self.model.entries:
            if not e['hits'] and not e['analyzed'] and e['status'] in ('pending', 'none'):
                self.model.update(e['path'], status='none' if self.name_only() else 'pending')
        self.save_settings()
        self.update_controls()

    def scan_names(self):
        try:
            root = Path(self.source.text().strip()).resolve(strict=True)
            if not root.is_dir():
                raise ValueError('Kaynak bir klasör olmalı.')
            if not self.rules:
                raise ValueError('Önce Kurallar’dan en az bir kural ekleyin.')
            core.config_load({'rules': [dict(r) for r in self.rules]})
        except Exception as exc:
            QMessageBox.warning(self, 'Tarama yapılamadı', str(exc))
            return
        self.root, self.scan_rules = root, [dict(r) for r in self.rules]
        self.save_settings()
        targets = {r['folder'].casefold() for r in self.rules} | {REVIEW.casefold(), NO_MATCH.casefold()}
        entries = []
        try:
            for folder, dirs, files in os.walk(root):
                # Only the destination folders directly under the source are already sorted.
                dirs[:] = [d for d in dirs if not (Path(folder) / d).is_symlink() and
                           not (Path(folder) == root and d.casefold() in targets) and
                           not core.within(Path(folder) / d, STATE)]
                for filename in files:
                    path = Path(folder) / filename
                    if path.suffix.lower() in core.EXTENSIONS and not path.is_symlink():
                        entries.append(self.make_entry(path))
        except OSError as exc:
            QMessageBox.warning(self, 'Tarama yapılamadı', str(exc))
            return
        self.model.set_entries(entries)
        named = sum(e['status'] == 'name' for e in entries)
        self.log_message(f'Tarama: {len(entries)} video, {named} dosya adı eşleşmesi.')

    def set_checked(self, entries, value):
        skipped = 0
        for e in entries:
            if e['status'] in CHECKABLE and e['checked'] != value:
                if value and not e['target']:
                    skipped += 1
                    continue
                self.model.update(e['path'], checked=value)
        if skipped:
            self.statusBar().showMessage(f'Hedefi seçilmemiş {skipped} video işaretlenmedi.', 6000)

    def target_hint(self):
        self.statusBar().showMessage('Önce Hedef sütunundan bir klasör seçin; seçince video işaretlenir.', 6000)

    def set_target(self, entries, folder):
        target = None if folder == STAY else folder
        for e in entries:
            if e['status'] in CHECKABLE:
                self.model.update(e['path'], target=target, checked=target is not None)

    def toggle_selected(self):
        entries = [e for e in self.selected_entries() if e['status'] in CHECKABLE]
        self.set_checked(entries, not all(e['checked'] for e in entries))

    def check_visible(self):
        entries = [self.model.entries[self.proxy.mapToSource(self.proxy.index(row, 0)).row()]
                   for row in range(self.proxy.rowCount())]
        self.set_checked([e for e in entries if e['target']], True)

    def queue_for_speech(self, entries):
        for e in entries:
            if e['status'] in REANALYZABLE:
                self.model.update(e['path'], status='pending', checked=False, target=None, label=None,
                                  note=None, analyzed=False)

    def show_menu(self, position):
        entries = self.selected_entries()
        if not entries:
            return
        checkable = [e for e in entries if e['status'] in CHECKABLE]
        menu = QMenu(self)
        menu.addAction('İşaretle (Boşluk)', lambda: self.set_checked(checkable, True)).setEnabled(bool(checkable))
        menu.addAction('İşareti kaldır', lambda: self.set_checked(checkable, False)).setEnabled(bool(checkable))
        targets = menu.addMenu('Hedef')
        targets.setEnabled(bool(checkable))
        for option in [STAY, *self.target_options()]:
            targets.addAction(option, lambda o=option: self.set_target(checkable, o))
        if not self.name_only():
            again = [e for e in entries if e['status'] in REANALYZABLE]
            menu.addAction('Ses analizine ekle', lambda: self.queue_for_speech(again)).setEnabled(bool(again))
        if len(entries) == 1:
            menu.addSeparator()
            menu.addAction('Transkripti aç', lambda: self.open_transcript(entries[0])).setEnabled(entries[0]['has_text'])
        menu.exec(self.view.viewport().mapToGlobal(position))

    def open_transcript(self, entry):
        show_transcript(self, entry['path'], [t for hit in entry['hits'] for t in hit['terms']])

    def start_analysis(self):
        paths = [e['path'] for e in self.model.entries if e['status'] == 'pending']
        s = self.settings
        try:
            rules = core.config_load({'rules': [dict(r) for r in self.rules]})['rules']
            if not any(r.get('audio_description', '').strip() for r in rules):
                raise ValueError('Ses analizi için Kurallar’da en az bir kurala Ses içeriği tanımı (AI) yazın.')
            if not s['lm_model']:
                raise ValueError('Ayarlar’da LM Studio metin modeli seçin veya model kimliğini yazın.')
            audio_ai.base_url(s['lm_host'], s['lm_port'])
            configure_cuda(s)
        except Exception as exc:
            QMessageBox.warning(self, 'Ses analizi başlatılamadı', str(exc))
            return
        for path in paths:
            self.model.update(path, status='queued', label=None, note=None, checked=False)
        signature = json.dumps({'model': s['model'], 'device': s['device'], 'compute': s['compute'],
                                'batch': s['batch'], 'beam': s['beam']}, sort_keys=True)
        self.log_message(f'Ses analizi: {len(paths)} video · Whisper {s["model"]} ({s["device"].upper()}) '
                         f'→ LM Studio {s["lm_model"]}')
        self.progress.setValue(0)
        self.progress_label.setText(f'Ses analizi · {len(paths)} video')
        self.progress_box.setVisible(True)
        self.start_worker('analyze', paths=paths, rules=rules, signature=signature, model=s['model'],
            device=s['device'], compute=s['compute'], batch=s['batch'], beam=s['beam'],
            lm_host=s['lm_host'], lm_port=s['lm_port'], lm_model=s['lm_model'],
            lm_thinking=s['lm_thinking'], lm_chunk_size=s['lm_chunk_size'], lm_retries=s['lm_retries'])

    def cancel_analysis(self):
        if 'analyze' in self.jobs:
            self.jobs['analyze'][1].cancelled = True
            self.stop_btn.setEnabled(False)
            self.log_message('Geçerli video veya LM Studio isteği bitince analiz duracak.')

    def move_checked(self):
        ready = [e for e in self.model.entries if e['checked'] and e['target'] and e['status'] in CHECKABLE]
        if not ready:
            return
        moves = []
        for e in ready:
            destination = self.root / e['target'] / Path(e['path']).name
            moves.append({'source': e['path'], 'destination': str(destination), 'fingerprint': e['stat']})
            self.model.update(e['path'], status='moving', checked=False, note=None)
        self.move_results = {'moved': 0, 'failed': 0}
        self.start_worker('move', entries=moves, root=str(self.root))

    def undo(self):
        if QMessageBox.question(self, 'Son taşımayı geri al',
                                'En son taşıma işleminde taşınan ve sonrasında değişmemiş videolar '
                                'eski yerlerine dönsün mü?') != QMessageBox.StandardButton.Yes:
            return
        self.undo_results = {'undone': 0, 'other': 0}
        self.start_worker('undo')

    # ---- background work -----------------------------------------------------------------------

    def start_worker(self, task, **kwargs):
        thread = QThread(self)
        worker = Worker(task, **kwargs)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.on_progress)
        worker.result.connect(self.on_result)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self.on_thread_finished)
        self.jobs[task] = (thread, worker)
        self.update_controls()
        thread.start()

    def on_thread_finished(self):
        thread = self.sender()
        task = next((name for name, (job, _worker) in self.jobs.items() if job is thread), None)
        if task is None:
            return
        del self.jobs[task]
        thread.wait()
        thread.deleteLater()
        if task == 'analyze':
            for e in self.model.entries:
                if e['status'] in ('queued', 'working'):
                    self.model.update(e['path'], status='pending', label=None)
            self.progress_box.setVisible(False)
            counts = {key: sum(e['status'] == key for e in self.model.entries) for key in ('speech', 'none', 'error')}
            self.log_message(f'Ses analizi bitti · {counts["speech"]} eşleşme · {counts["none"]} eşleşme yok · '
                             f'{counts["error"]} hata')
        elif task == 'move':
            for e in self.model.entries:
                if e['status'] == 'moving':
                    self.model.update(e['path'], status='move_failed', note='Taşıma tamamlanmadı')
            self.log_message(f'Taşıma bitti · {self.move_results["moved"]} taşındı · '
                             f'{self.move_results["failed"]} taşınamadı')
        elif task == 'undo':
            self.log_message(f'Geri alma bitti · {self.undo_results["undone"]} video geri döndü · '
                             f'{self.undo_results["other"]} atlandı veya hata')
        self.update_controls()

    def on_progress(self, current, total):
        self.progress.setMaximum(max(1, total))
        self.progress.setValue(current)

    def on_result(self, value):
        kind, data = value
        if kind == 'working':
            path, label = data
            self.model.update(path, status='working', label=label)
            self.progress_label.setText(f'{label} · {Path(path).name}')
        elif kind == 'transcribed':
            self.model.update(data, status='queued', label='Metin hazır, sırada', has_text=True)
        elif kind == 'classified':
            path, stat, hits = data
            if hits:
                self.model.update(path, status='speech', label=None, hits=hits, stat=stat, analyzed=True,
                                  target=target_for(hits), checked=True)
                self.log_message(f'EŞLEŞTİ · {Path(path).name}: {", ".join(h["folder"] for h in hits)}')
            else:
                # Analysed videos without a match go to eslesme_yok unless the user unchecks them.
                self.model.update(path, status='none', label=None, hits=[], stat=stat, analyzed=True,
                                  target=NO_MATCH, checked=True)
        elif kind == 'ai_retry':
            path, attempt, maximum, message = data
            self.log_message(f'YENİDEN DENENİYOR · {Path(path).name} · {attempt}/{maximum}: {message}')
        elif kind == 'error':
            path, message = data
            self.model.update(path, status='error', label=None, note=message, checked=False)
            self.log_message(f'HATA · {Path(path).name}: {message}')
        elif kind == 'move_item':
            path, status, detail = data
            if status == 'moved':
                self.move_results['moved'] += 1
                self.model.remove(path)
                self.log_message(f'TAŞINDI · {Path(path).name} → {Path(detail).parent.name}')
            else:
                self.move_results['failed'] += 1
                self.model.update(path, status='move_failed', note=detail)
                self.log_message(f'TAŞINAMADI · {Path(path).name}: {detail}')
        elif kind == 'undo_item':
            path, status, detail = data
            if status == 'undone':
                self.undo_results['undone'] += 1
                self.log_message(f'GERİ ALINDI · {Path(detail).name}')
                restored = Path(detail)
                if self.root and core.within(restored, self.root) and not self.model.find(str(restored)):
                    try:
                        self.model.append(self.make_entry(restored))
                    except OSError:
                        pass
            else:
                self.undo_results['other'] += 1
                self.log_message(f'{"ATLANDI" if status == "skipped" else "HATA"} · {Path(path).name}: {detail}')
        elif kind == 'fatal':
            task, message, details = data
            self.log_message(f'HATA: {message}\n{details}')
            if task == 'analyze':
                for e in self.model.entries:
                    if e['status'] in ('queued', 'working'):
                        self.model.update(e['path'], status='error', label=None, note=message)
            QMessageBox.warning(self, 'İşlem durdu', message)

    def closeEvent(self, event):
        self.save_settings()
        if 'move' in self.jobs or 'undo' in self.jobs:
            QMessageBox.information(self, 'Taşıma sürüyor', 'Dosyalar taşınırken uygulama kapatılamaz. İşlem bitince tekrar deneyin.')
            event.ignore()
            return
        if 'analyze' in self.jobs:
            if QMessageBox.question(self, 'Analiz sürüyor', 'Ses analizi sürüyor. Çıkılsın mı?') != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            # Analysis only writes cache files atomically; nothing needs to be unwound.
            os._exit(0)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    apply_theme(app)
    icon = BASE / 'Yolbulan.png'
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
