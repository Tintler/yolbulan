"""Windows desktop interface for the local speech video sorter."""
import json
import os
import re
import shutil
import sys
import traceback
import unicodedata
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal, QTimer
from PySide6.QtGui import QBrush, QColor, QIcon, QPalette, QTextCharFormat, QTextCursor, QTextLength, QTextTableFormat
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QSplitter, QTextEdit,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import ayikla as core

BASE = Path(__file__).resolve().parent
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else BASE
STATE = APP_DIR / 'calisma_verisi'
SETTINGS = STATE / 'gui_settings.json'
PROFILES = {
    'Hızlı': {'model': 'small', 'batch': 16, 'beam': 1, 'compute': 'float16'},
    'Dengeli': {'model': 'small', 'batch': 8, 'beam': 5, 'compute': 'float16'},
    'Hassas': {'model': 'large-v3', 'batch': 8, 'beam': 5, 'compute': 'float16'},
}


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


class Worker(QObject):
    progress = Signal(int, int, str)
    result = Signal(object)
    finished = Signal()

    def __init__(self, task, **kwargs):
        super().__init__()
        self.task, self.kwargs, self.cancelled = task, kwargs, False

    def run(self):
        try:
            if self.task == 'analyze':
                self.analyze(**self.kwargs)
            else:
                core.apply(self.kwargs['args'], reporter=lambda path, status, detail:
                           self.result.emit(('move_item', (path, status, detail))))
                self.result.emit(('moved', None))
        except Exception as exc:
            self.result.emit(('fatal', f'{exc}\n{traceback.format_exc()}'))
        finally:
            self.finished.emit()

    def analyze(self, paths, rules, signature, model, device, compute, batch, beam):
        engine = None
        total = len(paths)
        for index, path in enumerate(paths, 1):
            if self.cancelled:
                break
            path = Path(path)
            self.progress.emit(index - 1, total, path.name)
            self.result.emit(('working', str(path)))
            try:
                stat = core.fingerprint(path)
                cached = core.read_json(core.cache_path(STATE / 'transcripts', path))
                if cached and cached.get('fingerprint') == stat and cached.get('signature') == signature:
                    segments = cached['segments']
                else:
                    if engine is None:
                        self.result.emit(('loading', str(path)))
                        engine = core.transcriber(model, device, compute, batch, beam)
                    self.result.emit(('working', str(path)))
                    segments = engine(path)
                    core.write_json(core.cache_path(STATE / 'transcripts', path), {
                        'source': str(path), 'fingerprint': stat, 'signature': signature,
                        'model': model, 'segments': segments})
                text = ' '.join(s['text'] for s in segments)
                hits = [{'folder': r['folder'], 'terms': [t for t in core.rule_terms(r, 'speech') if core.matches(text, t)]}
                        for r in rules]
                hits = [h for h in hits if h['terms']]
                if hits:
                    self.result.emit(('hit', {'path': str(path), 'stat': stat, 'hits': hits}))
                else:
                    self.result.emit(('unmatched', str(path)))
            except Exception as exc:
                self.result.emit(('error', {'path': str(path), 'message': str(exc)}))
            self.progress.emit(index, total, path.name)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Yolbulan')
        self.resize(1300, 760)
        self.rows = []
        self.remaining = []
        self.phase = 'ready'
        self.worker = self.thread = None
        self.settings = core.read_json(SETTINGS, {}) or {}
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel('Kaynak klasör:'))
        self.source = QLineEdit(self.settings.get('source', ''))
        source_row.addWidget(self.source, 1)
        self.refresh = QPushButton('Yenile')
        self.refresh.clicked.connect(self.scan_names)
        source_row.addWidget(self.refresh)
        browse = QPushButton('Gözat…')
        browse.clicked.connect(self.browse)
        source_row.addWidget(browse)
        outer.addLayout(source_row)
        outer.addWidget(QLabel('Hedefler kaynak klasörün alt klasörleri olarak oluşturulur.'))
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel('Çalışma modu:'))
        self.mode = QComboBox()
        self.mode.addItems(['Dosya adı + ses analizi', 'Yalnızca dosya adı'])
        self.mode.setCurrentText(self.settings.get('mode', 'Dosya adı + ses analizi'))
        self.mode.setToolTip('Yalnızca dosya adı: seçilen eşleşmeleri onayla ve taşı; diğer dosyaları olduğu yerde bırak. Whisper çalışmaz.')
        self.mode.currentTextChanged.connect(self.mode_changed)
        mode_row.addWidget(self.mode)
        mode_row.addStretch()
        outer.addLayout(mode_row)

        self.rules = QTableWidget(0, 4)
        self.rules.setHorizontalHeaderLabels(['Hedef alt klasör', 'Dosya adı terimleri (+)', 'Dosya adı engelleri (−)',
                                              'Ses terimleri'])
        self.rules.setSortingEnabled(True)
        self.rules.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for col in range(1, 4):
            self.rules.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        self.rules.horizontalHeaderItem(2).setToolTip('Bu terimlerden biri dosya adında geçerse bu hedef eşleşmez. Diğer hedefleri etkilemez.')
        self.rules.verticalHeader().setVisible(False)
        self.rules.setMinimumHeight(130)
        for rule in self.settings.get('rules', core.read_json(BASE / 'kurallar.json', {'rules': []})['rules']):
            self.add_rule(rule['folder'], ', '.join(core.rule_terms(rule, 'name')),
                          ', '.join(core.rule_terms(rule, 'speech')),
                          ', '.join(rule.get('name_negative_terms', [])))
        self.rules.sortItems(0, Qt.SortOrder.AscendingOrder)
        rule_controls = QHBoxLayout()
        rule_controls.addWidget(QLabel('Kurallar'))
        add = QPushButton('+ Kural ekle')
        add.clicked.connect(lambda: self.add_rule('', '', ''))
        rule_controls.addWidget(add)
        remove = QPushButton('Seçili kuralı sil')
        remove.clicked.connect(self.remove_rule)
        rule_controls.addWidget(remove)
        save_rules = QPushButton('Kuralları kaydet')
        save_rules.clicked.connect(self.save_settings)
        rule_controls.addWidget(save_rules)
        self.save_label = QLabel('')
        rule_controls.addWidget(self.save_label)
        rule_controls.addStretch()
        outer.addLayout(rule_controls)
        outer.addWidget(self.rules)

        opts = QGridLayout()
        opts.addWidget(QLabel('Whisper profili:'), 0, 0)
        self.profile = QComboBox()
        self.profile.addItems([*PROFILES, 'Özel'])
        self.profile.setCurrentText(self.settings.get('profile', 'Dengeli'))
        self.profile.currentTextChanged.connect(self.profile_changed)
        opts.addWidget(self.profile, 0, 1)
        model_label = QLabel('Model:')
        opts.addWidget(model_label, 0, 2)
        self.model = QComboBox()
        self.model.addItems(['small', 'medium', 'large-v3', 'turbo'])
        self.model.setCurrentText(self.settings.get('model', 'small'))
        opts.addWidget(self.model, 0, 3)
        opts.addWidget(QLabel('GPU/CPU:'), 0, 4)
        self.device = QComboBox()
        self.device.addItems(['cuda', 'cpu'])
        self.device.setCurrentText(self.settings.get('device', 'cuda'))
        opts.addWidget(self.device, 0, 5)
        batch_label = QLabel('Toplu iş boyutu:')
        opts.addWidget(batch_label, 1, 0)
        self.batch = QSpinBox()
        self.batch.setRange(1, 32)
        self.batch.setValue(self.settings.get('batch', 8))
        opts.addWidget(self.batch, 1, 1)
        beam_label = QLabel('Beam:')
        opts.addWidget(beam_label, 1, 2)
        self.beam = QSpinBox()
        self.beam.setRange(1, 10)
        self.beam.setValue(self.settings.get('beam', 5))
        opts.addWidget(self.beam, 1, 3)
        compute_label = QLabel('Hesaplama:')
        opts.addWidget(compute_label, 1, 4)
        self.compute = QComboBox()
        self.compute.addItems(['float16', 'int8_float16', 'int8'])
        self.compute.setCurrentText(self.settings.get('compute', 'float16'))
        opts.addWidget(self.compute, 1, 5)
        for label, widget, hint in (
            (model_label, self.model, 'Konuşmayı yazıya çeviren model. Büyük modeller genellikle daha doğru, daha yavaş ve daha çok bellek kullanır.'),
            (batch_label, self.batch, 'Aynı anda işlenen ses parçaları. Yüksek değer hız sağlayabilir ama daha çok GPU belleği kullanır; 1 klasik işlem modudur.'),
            (beam_label, self.beam, 'Her adımda değerlendirilen metin seçenekleri. 1 daha hızlı; 5 genellikle daha dikkatli ama yavaştır.'),
            (compute_label, self.compute, 'Modelin sayısal hassasiyeti: float16 daha çok bellek; int8_float16 ve int8 daha az bellek kullanır. Sonuç ve hız değişebilir.')):
            label.setToolTip(hint)
            widget.setToolTip(hint)
        self.profile.setToolTip('Hızlı, Dengeli ve Hassas hazır ayarları uygular. Tek tek değer değiştirince profil Özel olur; taramada ekranda seçili değerler kullanılır.')
        outer.addLayout(opts)
        cuda_row = QHBoxLayout()
        cuda_row.addWidget(QLabel('CUDA DLL klasörü (isteğe bağlı):'))
        self.cuda_dir = QLineEdit(self.settings.get('cuda_dir', ''))
        self.cuda_dir.setPlaceholderText('cublas64_12.dll ve cudnn64_9.dll içeren klasör')
        cuda_row.addWidget(self.cuda_dir, 1)
        cuda_browse = QPushButton('Gözat…')
        cuda_browse.clicked.connect(self.browse_cuda)
        cuda_row.addWidget(cuda_browse)
        outer.addLayout(cuda_row)
        self.model.currentTextChanged.connect(self.customize)
        self.batch.valueChanged.connect(self.customize)
        self.beam.valueChanged.connect(self.customize)
        self.compute.currentTextChanged.connect(self.customize)
        self.device.currentTextChanged.connect(self.device_changed)
        if self.profile.currentText() != 'Özel':
            self.profile_changed(self.profile.currentText())

        actions = QHBoxLayout()
        self.scan_btn = QPushButton('1 · Dosya adlarını tara')
        self.scan_btn.clicked.connect(self.scan_names)
        actions.addWidget(self.scan_btn)
        self.primary = QPushButton('Seçilenleri taşı; kalanları analiz et')
        self.primary.setEnabled(False)
        self.primary.clicked.connect(self.advance)
        actions.addWidget(self.primary)
        self.cancel = QPushButton('Analizi durdur')
        self.cancel.clicked.connect(self.cancel_worker)
        self.cancel.setEnabled(False)
        actions.addWidget(self.cancel)
        undo = QPushButton('Son taşımaları geri al')
        undo.clicked.connect(self.undo)
        actions.addWidget(undo)
        actions.addStretch()
        outer.addLayout(actions)
        self.stage_label = QLabel('Kaynak klasörü ve kuralları belirleyip taramayı başlatın.')
        outer.addWidget(self.stage_label)
        self.list = QTableWidget(0, 6)
        self.list.setHorizontalHeaderLabels(['Taşı', 'Video', 'Durum', 'Eşleşen', 'Hedef alt klasör', 'Metin'])
        self.list.verticalHeader().setVisible(False)
        self.list.verticalHeader().setDefaultSectionSize(25)
        self.list.setAlternatingRowColors(True)
        self.list.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        header = self.list.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.list.itemChanged.connect(self.update_count)
        outer.addWidget(self.list, 1)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        outer.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(90)
        outer.addWidget(self.log)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(400)
        self.save_timer.timeout.connect(self.save_settings)
        self.rules.itemChanged.connect(self.schedule_save)
        self.source.textChanged.connect(self.schedule_save)
        self.profile.currentTextChanged.connect(self.schedule_save)
        self.model.currentTextChanged.connect(self.schedule_save)
        self.device.currentTextChanged.connect(self.schedule_save)
        self.batch.valueChanged.connect(self.schedule_save)
        self.beam.valueChanged.connect(self.schedule_save)
        self.compute.currentTextChanged.connect(self.schedule_save)
        self.cuda_dir.textChanged.connect(self.schedule_save)
        self.mode.currentTextChanged.connect(self.schedule_save)

    def mode_changed(self, *_):
        self.update_count()
        if self.phase == 'names':
            self.update_name_summary()

    def add_rule(self, folder, name_terms, speech_terms=None, name_negative=''):
        if speech_terms is None:
            speech_terms = name_terms
        sorting = self.rules.isSortingEnabled()
        self.rules.setSortingEnabled(False)
        r = self.rules.rowCount()
        self.rules.insertRow(r)
        self.rules.setItem(r, 0, QTableWidgetItem(folder))
        self.rules.setItem(r, 1, QTableWidgetItem(name_terms))
        self.rules.setItem(r, 2, QTableWidgetItem(name_negative))
        self.rules.setItem(r, 3, QTableWidgetItem(speech_terms))
        self.rules.setSortingEnabled(sorting)
        if sorting:
            self.rules.sortItems(0, Qt.SortOrder.AscendingOrder)
        if hasattr(self, 'save_timer'):
            self.schedule_save()

    def remove_rule(self):
        row = self.rules.currentRow()
        if row >= 0:
            folder = self.rules.item(row, 0).text() if self.rules.item(row, 0) else ''
            if QMessageBox.question(self, 'Kuralı sil', f'“{folder or "Adsız kural"}” kuralı silinsin mi?',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            self.rules.removeRow(row)
            self.schedule_save()

    def schedule_save(self, *_):
        self.save_label.setText('Kaydediliyor…')
        self.save_timer.start()

    def browse(self):
        chosen = QFileDialog.getExistingDirectory(self, 'Video klasörü seç', self.source.text())
        if chosen:
            self.source.setText(chosen)

    def browse_cuda(self):
        chosen = QFileDialog.getExistingDirectory(self, 'CUDA DLL klasörünü seç', self.cuda_dir.text())
        if chosen:
            self.cuda_dir.setText(chosen)

    def configure_cuda(self):
        if self.device.currentText() != 'cuda':
            return
        folder = self.cuda_dir.text().strip()
        if folder:
            path = Path(folder)
            if not (path / 'cublas64_12.dll').is_file() or not (path / 'cudnn64_9.dll').is_file():
                raise ValueError('CUDA DLL klasöründe cublas64_12.dll ve cudnn64_9.dll bulunmalı.')
            os.environ['PATH'] = str(path) + os.pathsep + os.environ.get('PATH', '')
            if hasattr(os, 'add_dll_directory'):
                # Keep the handle alive until the application exits.
                self._dll_handle = os.add_dll_directory(str(path))
        elif not shutil.which('cublas64_12.dll') or not shutil.which('cudnn64_9.dll'):
            raise ValueError('CUDA DLL dosyaları bulunamadı. CUDA DLL klasörünü seçin veya CPU kullanın.')

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

    def get_rules(self):
        rules = []
        for row in range(self.rules.rowCount()):
            folder = self.rules.item(row, 0).text().strip()
            name_terms = [x.strip() for x in self.rules.item(row, 1).text().split(',') if x.strip()]
            speech_terms = [x.strip() for x in self.rules.item(row, 3).text().split(',') if x.strip()]
            negative_name = [x.strip() for x in self.rules.item(row, 2).text().split(',') if x.strip()]
            rules.append({'folder': folder, 'name_terms': name_terms, 'speech_terms': speech_terms,
                          'name_negative_terms': negative_name})
        temp = STATE / 'rules-validation.json'
        core.write_json(temp, {'rules': rules})
        core.config_load(temp)
        return rules

    def save_settings(self, *_):
        # Save drafts too; validation happens when scanning starts.
        rules = []
        for row in range(self.rules.rowCount()):
            folder = self.rules.item(row, 0).text() if self.rules.item(row, 0) else ''
            name_text = self.rules.item(row, 1).text() if self.rules.item(row, 1) else ''
            speech_text = self.rules.item(row, 3).text() if self.rules.item(row, 3) else ''
            negative_name = self.rules.item(row, 2).text() if self.rules.item(row, 2) else ''
            rules.append({'folder': folder,
                          'name_terms': [s.strip() for s in name_text.split(',') if s.strip()],
                          'speech_terms': [s.strip() for s in speech_text.split(',') if s.strip()],
                          'name_negative_terms': [s.strip() for s in negative_name.split(',') if s.strip()]})
        try:
            core.write_json(SETTINGS, {'source': self.source.text(), 'rules': rules,
                'mode': self.mode.currentText(),
                'profile': self.profile.currentText(), 'model': self.model.currentText(),
                'batch': self.batch.value(), 'beam': self.beam.value(),
                'device': self.device.currentText(), 'compute': self.compute.currentText(),
                'cuda_dir': self.cuda_dir.text().strip()})
            self.save_label.setText('Kaydedildi')
        except Exception as exc:
            self.save_label.setText('Kaydedilemedi')
            self.log_message(f'Ayar kaydetme hatası: {exc}')

    def log_message(self, message):
        self.log.appendPlainText(message)

    def scan_names(self):
        try:
            root = Path(self.source.text()).resolve(strict=True)
            if not root.is_dir():
                raise ValueError('Kaynak bir klasör olmalı.')
            rules = self.get_rules()
            self.save_settings()
            self.root = root
            self.active_rules = rules
            self.remaining = []
            self.rows = []
            self.list.setRowCount(0)
            folders = {r['folder'].casefold() for r in rules} | {'incelenecekler', 'eslesme_yok'}
            for folder, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d.casefold() not in folders and
                           not (Path(folder) / d).is_symlink()]
                for filename in files:
                    path = Path(folder) / filename
                    if path.suffix.lower() not in core.EXTENSIONS or path.is_symlink():
                        continue
                    hits = core.filename_rule_hits(path.name, rules)
                    self.rows.append({'path': str(path), 'stat': core.fingerprint(path), 'hits': hits,
                                      'status': 'Dosya adı eşleşti' if hits else
                                      ('Eşleşme yok' if self.mode.currentText() == 'Yalnızca dosya adı' else 'Analiz bekliyor')})
                    if not hits:
                        self.remaining.append(str(path))
            self.phase = 'names'
            self.name_unmatched = list(self.remaining)
            self.render_rows()
            self.update_name_summary()
            self.log_message('Dosya adı taraması tamamlandı. Taşınacakları işaretleyin.')
        except Exception as exc:
            QMessageBox.warning(self, 'Tarama yapılamadı', str(exc))

    def update_name_summary(self):
        name_only = self.mode.currentText() == 'Yalnızca dosya adı'
        for entry in self.rows:
            if not entry['hits'] and entry['status'] in ('Eşleşme yok', 'Analiz bekliyor'):
                self.set_status(entry['path'], 'Eşleşme yok' if name_only else 'Analiz bekliyor')
        matching = sum(entry['status'] == 'Dosya adı eşleşti' for entry in self.rows)
        detail = 'eşleşmeyen yerinde kalacak' if name_only else 'analiz edilecek video'
        self.stage_label.setText(f'Dosya adı: {matching} eşleşme, {len(self.name_unmatched)} {detail} · Toplam {len(self.rows)}')

    def render_rows(self):
        self.list.blockSignals(True)
        self.list.setRowCount(0)
        self.list.setRowCount(len(self.rows))
        for i, entry in enumerate(self.rows):
            selectable = ((self.phase == 'names' and entry['status'] == 'Dosya adı eşleşti') or
                          (self.phase == 'speech' and entry['status'] in ('Ses eşleşti · onay bekliyor', 'Eşleşme yok')))
            check = QTableWidgetItem('')
            check.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable
            if selectable:
                flags |= Qt.ItemFlag.ItemIsEnabled
            check.setFlags(flags)
            check.setCheckState(Qt.CheckState.Checked if selectable else Qt.CheckState.Unchecked)
            if not selectable:
                check.setToolTip('Salt okunur: bu aşamada taşıma için seçilemez.')
            self.list.setItem(i, 0, check)
            path = Path(entry['path'])
            item = QTableWidgetItem(path.name)
            item.setToolTip(str(path))
            self.list.setItem(i, 1, item)
            status_item = QTableWidgetItem(entry['status'])
            self.color_status(status_item, entry['status'])
            self.list.setItem(i, 2, status_item)
            self.list.setItem(i, 3, QTableWidgetItem(', '.join(t for h in entry['hits'] for t in h['terms'])))
            if selectable:
                target = QComboBox()
                target.addItems(list(dict.fromkeys([r['folder'] for r in self.active_rules] + ['Incelenecekler', 'eslesme_yok'])))
                if self.phase == 'speech' and entry['status'] == 'Eşleşme yok':
                    target.setCurrentText('eslesme_yok')
                elif entry['hits']:
                    target.setCurrentText(entry['hits'][0]['folder'] if len(entry['hits']) == 1 else 'Incelenecekler')
                self.list.setCellWidget(i, 4, target)
            else:
                folder = entry.get('destination_folder', '') if entry['status'] in ('Taşındı', 'Taşınıyor…') else ''
                target_item = QTableWidgetItem(folder or '—')
                target_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                target_item.setToolTip('Hedef belirlenmedi' if not folder else f'Hedef: {folder}')
                self.list.setItem(i, 4, target_item)
            button = QPushButton('Aç')
            button.clicked.connect(lambda _checked=False, p=entry['path']: self.open_transcript(p))
            self.list.setCellWidget(i, 5, button)
            self.refresh_transcript_button(entry['path'])
        self.list.blockSignals(False)
        self.update_count()

    def refresh_transcript_button(self, path):
        for i, entry in enumerate(self.rows):
            if entry['path'] == path:
                button = self.list.cellWidget(i, 5)
                if button:
                    button.setEnabled(core.cache_path(STATE / 'transcripts', path).is_file())
                    button.setToolTip('Kaydedilmiş transkripti aç' if button.isEnabled() else 'Henüz transkript yok')
                return

    def open_transcript(self, path):
        cached = core.read_json(core.cache_path(STATE / 'transcripts', path))
        if not cached or not cached.get('segments'):
            QMessageBox.information(self, 'Transkript yok', 'Bu video için henüz transkript oluşturulmadı.')
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f'Transkript · {Path(path).name}')
        dialog.resize(850, 620)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(str(path)))
        text = QTextEdit()
        text.setReadOnly(True)
        def stamp(seconds):
            whole = int(seconds)
            return f'{whole // 3600:02}:{(whole // 60) % 60:02}:{whole % 60:02}'
        entry = next((row for row in self.rows if row['path'] == path), None)
        terms = [term for hit in entry['hits'] for term in hit['terms']] if entry else []
        palette = self.list.palette()
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
            line = f'[{stamp(segment["start"])} – {stamp(segment["end"])}] {segment["text"]}'
            cursor = cell.firstCursorPosition()
            cursor.insertText(line)
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
            text.setTextCursor(match_cursors[active_match[0]])
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

    def set_status(self, path, status):
        for i, entry in enumerate(self.rows):
            if entry['path'] == path:
                entry['status'] = status
                if self.list.item(i, 2):
                    self.list.item(i, 2).setText(status)
                    self.color_status(self.list.item(i, 2), status)
                if status not in ('Dosya adı eşleşti', 'Ses eşleşti · onay bekliyor', 'Eşleşme yok'):
                    check = self.list.item(i, 0)
                    if check:
                        self.list.blockSignals(True)
                        check.setCheckState(Qt.CheckState.Unchecked)
                        check.setToolTip('Salt okunur: bu aşamada taşıma için seçilemez.')
                        check.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
                        self.list.blockSignals(False)
                    target = self.list.cellWidget(i, 4)
                    if target:
                        self.list.removeCellWidget(i, 4)
                        folder = entry.get('destination_folder', '') if status in ('Taşındı', 'Taşınıyor…') else ''
                        target_item = QTableWidgetItem(folder or '—')
                        target_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                        target_item.setToolTip('Hedef belirlenmedi' if not folder else f'Hedef: {folder}')
                        self.list.setItem(i, 4, target_item)
                break

    def color_status(self, item, status):
        dark = QApplication.palette().color(QPalette.ColorRole.Base).lightness() < 128
        if status == 'Taşındı':
            color = QColor('#79d49b' if dark else '#176c39')
        elif status == 'Eşleşme yok':
            color = QColor('#ffd874' if dark else '#865b00')
        elif status in ('Hata', 'Taşınamadı'):
            color = QColor('#ff9090' if dark else '#ad3030')
        elif status.startswith(('Analiz ediliyor', 'Model yükleniyor', 'Taşınıyor')):
            color = QColor('#82bafc' if dark else '#155dad')
        elif status.startswith(('Dosya adı eşleşti', 'Ses eşleşti')):
            color = QColor('#caa9ff' if dark else '#7442a3')
        else:
            color = QApplication.palette().color(QPalette.ColorRole.Text)
        item.setForeground(QBrush(color))
        background = QColor(color)
        background.setAlpha(26 if dark else 18)
        item.setBackground(QBrush(background))

    def update_count(self, *_):
        selected = sum(self.list.item(i, 0).checkState() == Qt.CheckState.Checked
                       for i in range(self.list.rowCount()) if self.list.item(i, 0))
        self.primary.setEnabled(self.phase in ('names', 'speech'))
        if self.phase == 'names':
            self.primary.setText(f'Seçilen {selected} videoyu taşı' +
                                 ('' if self.mode.currentText() == 'Yalnızca dosya adı' else '; kalanları analiz et'))
        elif self.phase == 'speech':
            self.primary.setText(f'Seçilen {selected} videoyu taşı')

    def advance(self):
        self.run_name_only = self.phase == 'names' and self.mode.currentText() == 'Yalnızca dosya adı'
        selected = []
        deferred = []
        for i, entry in enumerate(self.rows):
            if self.list.item(i, 0).checkState() == Qt.CheckState.Checked:
                e = dict(entry)
                e['status'] = 'matched'
                folder = self.list.cellWidget(i, 4).currentText()
                entry['destination_folder'] = folder
                e['destination'] = str(self.root / folder / Path(e['path']).name)
                selected.append({'source': e['path'], 'fingerprint': e['stat'],
                    'status': e['status'], 'destination': e['destination']})
            elif self.phase == 'names' and entry['hits'] and entry['status'] != 'Taşındı':
                deferred.append(entry['path'])
        if self.phase == 'names':
            # An unchecked name match is a request to decide using speech instead.
            self.remaining = [] if self.run_name_only else self.name_unmatched + deferred
            if self.remaining:
                try:
                    self.configure_cuda()
                except Exception as exc:
                    QMessageBox.warning(self, 'Ses analizi başlatılamadı', str(exc))
                    return
        if selected:
            self.pending_moves = selected
            for move in selected:
                self.set_status(move['source'], 'Taşınıyor…')
            self.stage_label.setText(f'{len(selected)} video taşınıyor' +
                                     (f' · ardından {len(self.remaining)} video analiz edilecek' if self.remaining else ''))
            plan = {'created_at': core.now(), 'source_root': str(self.root),
                    'destination_root': str(self.root), 'entries': selected}
            core.write_json(STATE / 'plan.json', plan)
            self.start_worker('move', args=type('Args', (), {'state': str(STATE), 'plan_only': False})())
        else:
            self.after_move()

    def start_worker(self, task, **kwargs):
        self.mode.setEnabled(False)
        self.scan_btn.setEnabled(False)
        self.refresh.setEnabled(False)
        self.primary.setEnabled(False)
        self.cancel.setEnabled(task == 'analyze')
        self.thread = QThread(self)
        self.worker = Worker(task, **kwargs)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.result.connect(self.on_result)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(lambda: self.on_finished(task))
        self.thread.start()

    def after_move(self):
        if self.phase == 'names' and self.run_name_only:
            self.phase = 'done'
            self.render_rows()
            self.stage_label.setText('Dosya adı işlemi bitti. Eşleşmeyenler ve seçilmeyenler yerinde kaldı.')
            self.scan_btn.setEnabled(True)
            self.refresh.setEnabled(True)
            self.mode.setEnabled(True)
            self.primary.setEnabled(False)
            return
        if self.phase == 'names':
            self.phase = 'analyzing'
            if self.remaining:
                try:
                    self.configure_cuda()
                except Exception as exc:
                    self.phase = 'names'
                    self.scan_btn.setEnabled(True)
                    self.refresh.setEnabled(True)
                    self.mode.setEnabled(True)
                    self.primary.setEnabled(True)
                    QMessageBox.warning(self, 'Ses analizi başlatılamadı', str(exc))
                    return
                signature = json.dumps({'model': self.model.currentText(), 'device': self.device.currentText(),
                    'compute': self.compute.currentText(), 'batch': self.batch.value(), 'beam': self.beam.value()}, sort_keys=True)
                for path in self.remaining:
                    self.set_status(path, 'Analiz bekliyor')
                self.render_rows()
                self.progress.setVisible(True)
                self.stage_label.setText(f'2 · Ses analizi başlıyor · {self.device.currentText().upper()} · {len(self.remaining)} video')
                self.log_message(f'Ses analizi başlıyor: {self.device.currentText().upper()}, {self.model.currentText()}, batch {self.batch.value()}')
                self.start_worker('analyze', paths=list(self.remaining), rules=list(self.active_rules),
                    signature=signature, model=self.model.currentText(), device=self.device.currentText(),
                    compute=self.compute.currentText(), batch=self.batch.value(), beam=self.beam.value())
            else:
                self.phase = 'done'
                self.stage_label.setText('Bitti: analiz edilecek video kalmadı.')
                self.scan_btn.setEnabled(True)
                self.refresh.setEnabled(True)
                self.mode.setEnabled(True)
        else:
            self.phase = 'done'
            self.stage_label.setText('Bitti. Eşleşmeyenler ve işaretlenmeyenler yerinde kaldı.')
            self.scan_btn.setEnabled(True)
            self.refresh.setEnabled(True)
            self.mode.setEnabled(True)
            self.primary.setEnabled(False)

    def on_progress(self, current, total, name):
        self.progress.setMaximum(max(1, total))
        self.progress.setValue(current)
        self.stage_label.setText(f'2 · Ses analizi ({self.device.currentText().upper()}): {current}/{total} tamamlandı · {name}')

    def on_result(self, value):
        kind, data = value
        if kind == 'move_item':
            path, status, detail = data
            if status == 'moved':
                self.set_status(path, 'Taşındı')
                self.log_message(f'TAŞINDI · {Path(path).name} → {Path(detail).parent.name}')
            else:
                self.set_status(path, 'Taşınamadı')
                self.log_message(f'{"ATLANDI" if status == "skipped" else "HATA"} · {Path(path).name}: {detail}')
        elif kind == 'hit':
            for entry in self.rows:
                if entry['path'] == data['path']:
                    entry['hits'] = data['hits']
                    entry['stat'] = data['stat']
                    break
            self.set_status(data['path'], 'Ses eşleşti · onay bekliyor')
            self.log_message(f'EŞLEŞTİ · {Path(data["path"]).name}: {", ".join(h["folder"] for h in data["hits"])}')
            self.refresh_transcript_button(data['path'])
        elif kind == 'unmatched':
            self.set_status(data, 'Eşleşme yok')
            self.log_message(f'EŞLEŞME YOK · {Path(data).name}')
            self.refresh_transcript_button(data)
        elif kind == 'loading':
            self.set_status(data, f'Model yükleniyor · {self.device.currentText().upper()}')
        elif kind == 'working':
            self.set_status(data, f'Analiz ediliyor · {self.device.currentText().upper()}')
        elif kind == 'error':
            self.set_status(data['path'], 'Hata')
            self.list.item(next(i for i, e in enumerate(self.rows) if e['path'] == data['path']), 2).setToolTip(data['message'])
            self.log_message(f'HATA: {Path(data["path"]).name}: {data["message"]}')
        elif kind == 'fatal':
            self.log_message(f'HATA: {data}')

    def on_finished(self, task):
        self.cancel.setEnabled(False)
        if task == 'move':
            moved = 0
            for entry in self.pending_moves:
                source, destination = Path(entry['source']), Path(entry['destination'])
                if not source.exists() and destination.exists():
                    self.set_status(str(source), 'Taşındı')
                    moved += 1
                else:
                    self.set_status(str(source), 'Taşınamadı')
            self.log_message(f'TOPLAM · Taşınan: {moved}, taşınamayan: {len(self.pending_moves) - moved}.')
            self.after_move()
        else:
            self.phase = 'speech'
            self.progress.setVisible(False)
            self.render_rows()
            matched = sum(e['status'] == 'Ses eşleşti · onay bekliyor' for e in self.rows)
            unmatched = sum(e['status'] == 'Eşleşme yok' for e in self.rows)
            errors = sum(e['status'] == 'Hata' for e in self.rows)
            self.stage_label.setText(f'2 · Ses analizi bitti · {matched} eşleşme · {unmatched} eşleşme yok · {errors} hata · ikinci onay')
            self.scan_btn.setEnabled(True)
            self.refresh.setEnabled(True)
            self.mode.setEnabled(True)
            self.log_message('Ses analizi bitti. Tüm videoların durumu listede; eşleşenleri kontrol edip onaylayın.')
            self.log_message(f'TOPLAM · Ses eşleşmesi: {matched}, eşleşme yok: {unmatched}, hata: {errors}.')

    def cancel_worker(self):
        if self.worker:
            self.worker.cancelled = True
            self.log_message('Mevcut video bitince analiz duracak.')

    def undo(self):
        if QMessageBox.question(self, 'Geri al', 'Kayıtlı ve değişmemiş taşımalar geri alınsın mı?') != QMessageBox.StandardButton.Yes:
            return
        try:
            results = []
            core.undo(type('Args', (), {'state': str(STATE)})(),
                      reporter=lambda path, status, detail: results.append((path, status, detail)))
            for path, status, detail in results:
                label = {'undone': 'GERİ ALINDI', 'skipped': 'ATLANDI', 'error': 'HATA'}[status]
                self.log_message(f'{label} · {Path(path).name}: {detail}')
            restored = sum(status == 'undone' for _, status, _ in results)
            self.log_message(f'TOPLAM · Geri alınan: {restored}, diğer: {len(results) - restored}.')
        except Exception as exc:
            QMessageBox.warning(self, 'Geri alma hatası', str(exc))


def main():
    app = QApplication(sys.argv)
    icon = BASE / 'Yolbulan.png'
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
