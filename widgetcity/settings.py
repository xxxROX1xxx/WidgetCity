import ntpath
from random import SystemRandom
from time import monotonic

from PySide6.QtCore import QDir, QEvent, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QSizePolicy, QSlider, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from . import __version__
from .city import SPRITES
from .config import MAX_SEED, SCENES, SIZES, default_folder, valid_rule
from .media import source_label

QDir.addSearchPath("cityart", str(SPRITES))

STYLE = """
QWidget#settings, QDialog { background: #18151f; color: #f0e2e7; }
QWidget { color: #f0e2e7; font-family: "Segoe UI"; font-size: 13px; }
QFrame#panel, QFrame#activityList { background: #211c29; border: 1px solid #382c40; border-radius: 13px; }
QFrame#previewFrame { background: #211a2a; border: 1px solid #3a2c43; border-radius: 13px; }
QFrame#rule { background: #382c40; max-height: 1px; border: 0; }
QLabel#title { font-size: 30px; font-weight: 700; color: #f9eaf0; }
QLabel#section { font-size: 18px; font-weight: 650; color: #faeaf0; }
QLabel#subtitle, QLabel#muted { color: #ac9bb3; }
QLabel#small { color: #af9bb2; font-size: 11px; }
QLabel#accent { color: #e7a37c; font-size: 11px; font-weight: 700; }
QLabel#bindingLabel { color: #e9cad7; font-weight: 600; }
QPushButton, QComboBox, QSpinBox, QLineEdit {
    background: #2a2233; color: #f2e1e9; border: 1px solid #49374e;
    padding: 6px 11px; border-radius: 7px; min-height: 21px;
}
QPushButton:hover, QComboBox:hover { background: #37283c; border-color: #765166; }
QPushButton:pressed { background: #442d43; }
QPushButton:focus, QComboBox:focus, QLineEdit:focus, QSpinBox:focus { border-color: #bd7e69; }
QPushButton:disabled { color: #776b7f; background: #27202e; border-color: #372c40; }
QPushButton#primary { color: #231823; background: #e4a17d; border-color: #e4a17d; font-weight: 700; }
QPushButton#primary:hover { background: #f7b58b; }
QPushButton#tab { border: 0; border-radius: 7px; background: transparent; color: #af9bb2; padding: 6px 14px; }
QPushButton#tab:hover { background: #292133; color: #f3dee8; }
QPushButton#tab:checked { background: #362739; color: #f5b18a; font-weight: 700; }
QPushButton#transport { background: #322435; color: #f7c38f; border: 1px solid #574052;
    min-height: 0; padding: 0; border-radius: 5px; font-family: "Segoe UI Symbol"; }
QPushButton#transport:hover { background: #493041; border-color: #ae745e; }
QPushButton#transport:disabled { background: #292030; color: #786778; border-color: #382c3d; }
QComboBox::drop-down { width: 24px; border-left: 1px solid #49374e; }
QComboBox::down-arrow, QSpinBox::down-arrow { image: url(cityart:arrow_down.png); width: 9px; height: 9px; }
QSpinBox::up-arrow { image: url(cityart:arrow_up.png); width: 9px; height: 9px; }
QSpinBox::up-button, QSpinBox::down-button { width: 18px; border: 0; background: #38293d; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #58384e; }
QComboBox QAbstractItemView, QListWidget { color: #f3dfe9; background: #241d2d; border: 1px solid #46374e;
    selection-background-color: #4a3046; selection-color: #fbdce3; outline: 0; }
QListWidget { border-radius: 8px; padding: 4px; }
QListWidget::item { padding: 9px; border-radius: 5px; }
QListWidget::item:hover { background: #382a40; }
QListWidget::item:selected { background: #4a3046; color: #fbdce3; }
QSlider { min-height: 23px; }
QSlider::groove:horizontal { height: 5px; border-radius: 2px; background: #49364e; }
QSlider::sub-page:horizontal { border-radius: 2px; background: #b97767; }
QSlider::handle:horizontal { background: #fac091; border: 1px solid #f3a477; width: 13px; height: 13px;
    margin: -4px 0; border-radius: 7px; }
QSlider::handle:horizontal:hover { background: #ffe0af; }
QCheckBox { spacing: 9px; }
QCheckBox::indicator { border: 1px solid #6b4d68; background: #30263a; border-radius: 4px; width: 15px; height: 15px; }
QCheckBox::indicator:checked { background: #dc9976; border: 3px solid #734b5d; width: 11px; height: 11px; }
QCheckBox::indicator:hover { border-color: #e9a47d; }
QToolTip { background: #322637; color: #f4dbe4; border: 1px solid #6c4c61; }
QMenu { background: #281f2e; border: 1px solid #553d55; padding: 5px; }
QMenu::item { padding: 6px 25px 6px 12px; }
QMenu::item:selected { background: #4a3046; }
QMenu::separator { height: 1px; background: #513a51; margin: 3px; }
"""


def label(text, kind="", wrap=False):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setObjectName(kind)
    widget.setWordWrap(wrap)
    return widget


def rule():
    widget = QFrame()
    widget.setObjectName("rule")
    widget.setFixedHeight(1)
    return widget


def panel(name="panel", margin=18, spacing=10):
    frame = QFrame()
    frame.setObjectName(name)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(margin, margin, margin, margin)
    layout.setSpacing(spacing)
    return frame, layout


def button(text, accent=False):
    widget = QPushButton(text)
    if accent:
        widget.setObjectName("primary")
    return widget


class Preview(QWidget):
    def __init__(self, renderer, scenes, compact=False):
        super().__init__()
        self.renderer, self.scenes = renderer, scenes
        if compact:
            self.setMinimumSize(174, 104)
            self.setMaximumHeight(133)
        else:
            self.setMinimumSize(330, 285)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName("Живой предпросмотр города")

    def paintEvent(self, _event):
        p = QPainter(self)
        background = QLinearGradient(0, 0, self.width() * .7, self.height())
        for offset, color in ((0., "#171323"), (.66, "#232038"), (1., "#302438")):
            background.setColorAt(offset, QColor(color))
        p.fillRect(self.rect(), background)
        for i in range(58):
            x = (53 * i + i*i * 11) % max(1, self.width())
            y = (37 * i + i*i * 3) % max(1, self.height())
            p.fillRect(x, y, 1 + (i % 11 == 0), 1, QColor(188, 152, 190, 28 + (i * 7) % 75))
        natural = self.renderer.size
        fit = min((self.width() - 20) / natural.width(), (self.height() - 12) / natural.height())
        scale = min(1.55, fit)
        p.translate(round((self.width() - scale * natural.width()) / 2),
                    round((self.height() - scale * natural.height()) / 2))
        p.scale(scale, scale)
        self.renderer.paint(p, self.scenes, monotonic(), scale=scale)


class ProgramPicker(QDialog):
    def __init__(self, parent, monitor):
        super().__init__(parent)
        self.setWindowTitle("Запущенные программы")
        self.resize(540, 410)
        self.monitor = monitor
        self.programs = []
        self.selected = ""
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Найти программу по имени или пути")
        self.search.textChanged.connect(self.fill)
        layout.addWidget(self.search)
        self.entries = QListWidget()
        self.entries.itemDoubleClicked.connect(lambda _: self.accept())
        self.entries.addItem("Получаем список программ…")
        layout.addWidget(self.entries)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Выбрать")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        monitor.programs.connect(self.read_programs)
        monitor.request_programs()

    def read_programs(self, items):
        self.programs = items
        self.fill()

    def fill(self):
        self.entries.clear()
        search = self.search.text().casefold()
        for exe in self.programs:
            if search in exe.casefold():
                item = QListWidgetItem(f"{ntpath.basename(exe)}   ·   {exe}" if ntpath.dirname(exe) else exe)
                item.setData(Qt.ItemDataRole.UserRole, exe)
                self.entries.addItem(item)
        self.entries.setCurrentRow(0)

    def accept(self):
        item = self.entries.currentItem()
        self.selected = item.data(Qt.ItemDataRole.UserRole) if item else ""
        if self.selected:
            super().accept()


class BindingDialog(QDialog):
    def __init__(self, parent, monitor, original=None):
        super().__init__(parent)
        self.monitor, self.result_rule = monitor, None
        self.setWindowTitle("Изменить привязку" if original else "Добавить привязку")
        self.setMinimumWidth(495)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        self.kind = QComboBox()
        for name in ("Программа", "Подключение флешки", "Загрузка файла в папку", "Бездействие"):
            self.kind.addItem(name)
        layout.addWidget(label("Условие запуска", "section"))
        layout.addWidget(self.kind)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)
        programs = QWidget()
        program_layout = QVBoxLayout(programs)
        program_layout.setContentsMargins(0, 0, 0, 0)
        self.exe = QLineEdit()
        self.exe.setPlaceholderText(r"Например, Spotify.exe или C:\Программы\Spotify.exe")
        program_layout.addWidget(self.exe)
        picks = QHBoxLayout()
        running, browse = button("Из запущенных…"), button("Указать .exe…")
        running.clicked.connect(self.pick_program)
        browse.clicked.connect(self.pick_file)
        picks.addWidget(running)
        picks.addWidget(browse)
        program_layout.addLayout(picks)
        self.when = QComboBox()
        self.when.addItem("Программа запущена", "running")
        self.when.addItem("Окно активно", "foreground")
        program_layout.addWidget(self.when)
        self.stack.addWidget(programs)
        self.stack.addWidget(label("Срабатывает при подключении USB-накопителя.", "muted", True))
        download = QWidget()
        download_layout = QHBoxLayout(download)
        download_layout.setContentsMargins(0, 0, 0, 0)
        self.folder = QLineEdit(default_folder())
        folder_browse = button("Папка…")
        folder_browse.clicked.connect(self.pick_folder)
        download_layout.addWidget(self.folder, 1)
        download_layout.addWidget(folder_browse)
        self.stack.addWidget(download)
        idle = QWidget()
        idle_layout = QFormLayout(idle)
        idle_layout.setContentsMargins(0, 0, 0, 0)
        self.minutes = QSpinBox(minimum=1, maximum=120, value=5, suffix=" мин")
        idle_layout.addRow("Время без действий", self.minutes)
        self.stack.addWidget(idle)
        self.kind.currentIndexChanged.connect(self.stack.setCurrentIndex)
        self.error = label("", "accent")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Сохранить")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if original:
            kind = original["kind"]
            self.kind.setCurrentIndex({"running": 0, "foreground": 0, "usb": 1, "download": 2, "idle": 3}[kind])
            self.exe.setText(original.get("exe", ""))
            self.when.setCurrentIndex(int(kind == "foreground"))
            if kind == "download":
                self.folder.setText(original["folder"])
            if kind == "idle":
                self.minutes.setValue(original["minutes"])

    def pick_program(self):
        dialog = ProgramPicker(self, self.monitor)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.exe.setText(dialog.selected)
        dialog.deleteLater()

    def pick_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Укажите файл программы", "", "Программы (*.exe)")
        if path:
            self.exe.setText(ntpath.normpath(path))

    def pick_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Выберите папку для загрузок", self.folder.text())
        if path:
            self.folder.setText(ntpath.normpath(path))

    def accept(self):
        index = self.kind.currentIndex()
        binding = (
            {"kind": self.when.currentData(), "exe": self.exe.text().strip().strip('"')},
            {"kind": "usb"},
            {"kind": "download", "folder": self.folder.text().strip()},
            {"kind": "idle", "minutes": self.minutes.value()},
        )[index]
        if not valid_rule(binding):
            self.error.setText("Укажите имя или путь к файлу .exe." if index == 0 else "Укажите папку.")
            return
        self.result_rule = binding
        super().accept()


def binding_name(binding):
    kind = binding["kind"]
    if kind in ("running", "foreground"):
        prefix = "Запущена" if kind == "running" else "Активное окно"
        return f"{prefix}   ·   {ntpath.basename(binding['exe'])}"
    if kind == "usb":
        return "Подключение флешки"
    if kind == "download":
        return f"Файл загружен   ·   {binding['folder']}"
    return f"Бездействие   ·   {binding['minutes']} мин"


class Settings(QWidget):
    changed = Signal(str)
    test_scene = Signal(str)
    move_mode = Signal(bool)
    reset_location = Signal()
    visibility_changed = Signal()
    update_requested = Signal()

    def __init__(self, config, renderer, scenes, monitor):
        super().__init__()
        self.config, self.monitor = config, monitor
        self.data = config.data
        self.setObjectName("settings")
        self.setWindowTitle("WidgetCity")
        self.resize(972, 665)
        self.setMinimumSize(795, 608)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 22, 24, 18)
        outer.setSpacing(15)
        header = QHBoxLayout()
        header.setSpacing(14)
        mark = label("")
        mark.setFixedSize(47, 47)
        mark.setPixmap(QApplication.windowIcon().pixmap(47, 47))
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(mark, alignment=Qt.AlignmentFlag.AlignVCenter)
        heading = QVBoxLayout()
        heading.setSpacing(1)
        heading.addWidget(label("WidgetCity", "title"))
        heading.addWidget(label("Ночной город на рабочем столе", "subtitle"))
        header.addLayout(heading)
        header.addStretch()
        self.update_button = button("Обновить")
        self.update_button.setObjectName("updateButton")
        self.update_button.setToolTip("Проверить обновления в GitHub Releases")
        self.update_button.clicked.connect(self.update_requested)
        header.addWidget(self.update_button)
        self.hide_city = button("")
        self.hide_city.clicked.connect(self.toggle_visibility)
        header.addWidget(self.hide_city)
        outer.addLayout(header)
        outer.addWidget(rule())
        nav = QHBoxLayout()
        group = QButtonGroup(self)
        for index, text in enumerate(("Город", "Активности")):
            tab = button(text)
            tab.setObjectName("tab")
            tab.setCheckable(True)
            tab.setChecked(index == 0)
            group.addButton(tab, index)
            nav.addWidget(tab)
        nav.addStretch()
        outer.addLayout(nav)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.city_page(renderer, scenes))
        self.pages.addWidget(self.activities_page(renderer, scenes))
        group.idClicked.connect(self.pages.setCurrentIndex)
        self.pages.currentChanged.connect(lambda _: self.visibility_changed.emit())
        outer.addWidget(self.pages, 1)
        footer = QHBoxLayout()
        self.status = label("", "small")
        footer.addWidget(self.status)
        footer.addStretch()
        footer.addWidget(label("Настройки сохраняются автоматически", "small"))
        footer.addWidget(label(f"v{__version__}", "small"))
        outer.addLayout(footer)
        self.sync_status()

    def update_status(self, status=""):
        self.update_button.setText(status or "Обновить")
        self.update_button.setEnabled(not status)

    def city_page(self, renderer, scenes):
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        frame, preview_layout = panel("previewFrame", 14, 10)
        preview_header = QHBoxLayout()
        preview_header.addWidget(label("●  ЖИВОЙ ПРЕДПРОСМОТР", "accent"))
        preview_header.addStretch()
        self.preview_status = label("", "small")
        preview_header.addWidget(self.preview_status)
        preview_layout.addLayout(preview_header)
        self.preview = Preview(renderer, scenes)
        preview_layout.addWidget(self.preview, 1)
        preview_layout.addWidget(label("Нажмите на кафе на рабочем столе, чтобы открыть плеер.", "small", True))
        layout.addWidget(frame, 7)
        controls, values = panel()
        controls.setMinimumWidth(316)
        controls.setMaximumWidth(355)
        values.addWidget(label("Планировка", "section"))
        values.addWidget(label("Размер города", "bindingLabel"))
        size = QComboBox()
        for key, title in SIZES.items():
            size.addItem(title, key)
        size.setCurrentIndex(size.findData(self.data["size"]))
        size.currentIndexChanged.connect(lambda _: self.set_value("size", size.currentData()))
        values.addWidget(size)
        seed_row = QHBoxLayout()
        seed_row.addWidget(label("Сид", "bindingLabel"), 1)
        self.seed_number = QSpinBox(minimum=0, maximum=MAX_SEED, value=self.data["seed"], keyboardTracking=False)
        self.seed_number.setAccessibleName("Сид")
        self.seed_number.setFixedWidth(105)
        seed_row.addWidget(self.seed_number)
        values.addLayout(seed_row)
        self.seed = QSlider(Qt.Orientation.Horizontal, minimum=0, maximum=MAX_SEED, value=self.data["seed"])
        self.seed.setAccessibleName("Ползунок сида")
        self.seed.sliderMoved.connect(self.show_seed)
        self.seed.valueChanged.connect(self.slider_seed_changed)
        self.seed.sliderReleased.connect(lambda: self.apply_seed(self.seed.value()))
        self.seed_number.valueChanged.connect(self.apply_seed)
        values.addWidget(self.seed)
        randomize = button("Случайный город", True)
        randomize.clicked.connect(self.randomize)
        values.addWidget(randomize)
        values.addWidget(rule())
        values.addWidget(label("Размещение", "section"))
        scale_row = QHBoxLayout()
        scale_row.addWidget(label("Масштаб", "bindingLabel"), 1)
        self.scale_label = label(f"{self.data['scale']} %", "accent")
        scale_row.addWidget(self.scale_label)
        values.addLayout(scale_row)
        scale = QSlider(Qt.Orientation.Horizontal, minimum=50, maximum=160, value=self.data["scale"])
        scale.setAccessibleName("Масштаб")
        scale.valueChanged.connect(self.change_scale)
        values.addWidget(scale)
        place = QHBoxLayout()
        self.move = button("Переместить")
        self.move.setCheckable(True)
        self.move.toggled.connect(self.move_toggled)
        place.addWidget(self.move, 1)
        reset = button("В угол")
        reset.setToolTip("Вернуть город в правый нижний угол")
        reset.clicked.connect(self.reset_location)
        place.addWidget(reset)
        values.addLayout(place)
        values.addStretch()
        layout.addWidget(controls, 4)
        return page

    def activities_page(self, renderer, scenes):
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        navigation, left = panel("activityList", 14, 9)
        navigation.setFixedWidth(225)
        left.addWidget(label("Сценки города", "section"))
        self.scene_list = QListWidget()
        self.scene_list.setMinimumHeight(184)
        for key, (name, _, icon) in SCENES.items():
            item = QListWidgetItem(f"{icon}   {name}")
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.scene_list.addItem(item)
        left.addWidget(self.scene_list, 1)
        self.scene_preview = Preview(renderer, scenes, compact=True)
        left.addWidget(self.scene_preview)
        layout.addWidget(navigation)
        detail, right = panel()
        top = QHBoxLayout()
        top_text = QVBoxLayout()
        self.scene_name, self.scene_description = label("", "section"), label("", "muted")
        top_text.addWidget(self.scene_name)
        top_text.addWidget(self.scene_description)
        top.addLayout(top_text, 1)
        self.try_scene = button("Проверить", True)
        self.try_scene.clicked.connect(lambda: self.test_scene.emit(self.scene_key()))
        top.addWidget(self.try_scene, alignment=Qt.AlignmentFlag.AlignTop)
        right.addLayout(top)
        self.enabled = QCheckBox("Активность включена")
        self.enabled.toggled.connect(self.toggle_scene)
        right.addWidget(self.enabled)
        right.addWidget(rule())
        right.addWidget(label("Привязки", "bindingLabel"))
        self.bindings = QListWidget()
        self.bindings.setAccessibleName("Привязки выбранной активности")
        self.bindings.setMinimumHeight(91)
        self.bindings.currentRowChanged.connect(self.binding_selection)
        self.bindings.itemDoubleClicked.connect(lambda _: self.edit_binding(True))
        right.addWidget(self.bindings, 1)
        actions = QHBoxLayout()
        add = button("+ Добавить")
        add.clicked.connect(lambda: self.edit_binding(False))
        self.edit = button("Изменить")
        self.edit.clicked.connect(lambda: self.edit_binding(True))
        self.remove = button("Удалить")
        self.remove.clicked.connect(self.remove_binding)
        for control in (add, self.edit, self.remove):
            actions.addWidget(control)
        actions.addStretch()
        right.addLayout(actions)
        self.cafe_settings = QWidget()
        cafe = QVBoxLayout(self.cafe_settings)
        cafe.setContentsMargins(0, 0, 0, 0)
        cafe.setSpacing(8)
        cafe.addWidget(rule())
        cafe.addWidget(label("Музыкальный плеер", "bindingLabel"))
        choices = QHBoxLayout()
        for key, name in (("card", "Карточка по клику"), ("music", "Вывеска и ноты при музыке")):
            toggle = QCheckBox(name)
            toggle.setChecked(self.data["player"][key])
            toggle.toggled.connect(lambda checked, key=key: self.set_player(key, checked))
            choices.addWidget(toggle)
        choices.addStretch()
        cafe.addLayout(choices)
        sources = QHBoxLayout()
        sources.addWidget(label("Источник", "muted"))
        self.source = QComboBox()
        self.source.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.source.setMinimumContentsLength(22)
        self.source.currentIndexChanged.connect(lambda _: self.set_player("source", self.source.currentData()))
        sources.addWidget(self.source, 1)
        cafe.addLayout(sources)
        right.addWidget(self.cafe_settings)
        layout.addWidget(detail, 1)
        self.source_options(())
        self.scene_list.currentRowChanged.connect(self.load_scene)
        self.scene_list.setCurrentRow(0)
        return page

    def scene_key(self):
        return self.scene_list.currentItem().data(Qt.ItemDataRole.UserRole)

    def load_scene(self):
        key = self.scene_key()
        name, description, _ = SCENES[key]
        self.scene_name.setText(name)
        self.scene_description.setText(description)
        self.enabled.blockSignals(True)
        self.enabled.setChecked(self.data["activities"][key]["enabled"])
        self.enabled.blockSignals(False)
        self.try_scene.setEnabled(self.enabled.isChecked())
        self.cafe_settings.setVisible(key == "cafe")
        self.load_bindings()

    def load_bindings(self, selection=0):
        self.bindings.clear()
        for binding in self.data["activities"][self.scene_key()]["bindings"]:
            item = QListWidgetItem(binding_name(binding))
            item.setToolTip(binding.get("exe", binding.get("folder", item.text())))
            self.bindings.addItem(item)
        if self.bindings.count():
            self.bindings.setCurrentRow(min(selection, self.bindings.count() - 1))
        else:
            item = QListWidgetItem("Нет привязок")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.bindings.addItem(item)
        self.binding_selection()

    def binding_selection(self):
        selected = self.bindings.currentRow() >= 0 and bool(self.data["activities"][self.scene_key()]["bindings"])
        self.edit.setEnabled(selected)
        self.remove.setEnabled(selected)

    def edit_binding(self, edit):
        key = self.scene_key()
        bindings = self.data["activities"][key]["bindings"]
        row = self.bindings.currentRow()
        if edit and not 0 <= row < len(bindings):
            return
        dialog = BindingDialog(self, self.monitor, bindings[row] if edit else None)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if edit:
                bindings[row] = dialog.result_rule
            else:
                row = len(bindings)
                bindings.append(dialog.result_rule)
            self.changed.emit("activities")
            self.load_bindings(row)
        dialog.deleteLater()

    def remove_binding(self):
        bindings = self.data["activities"][self.scene_key()]["bindings"]
        row = self.bindings.currentRow()
        if 0 <= row < len(bindings):
            bindings.pop(row)
            self.changed.emit("activities")
            self.load_bindings(row)

    def toggle_scene(self, enabled):
        self.try_scene.setEnabled(enabled)
        self.data["activities"][self.scene_key()]["enabled"] = enabled
        self.changed.emit("activities")

    def source_options(self, sources):
        selected = self.data["player"]["source"]
        self.source.blockSignals(True)
        self.source.clear()
        self.source.addItem("Текущая медиасессия Windows", "")
        for source in sources:
            self.source.addItem(source_label(source), source)
            self.source.setItemData(self.source.count() - 1, source, Qt.ItemDataRole.ToolTipRole)
        if selected and selected not in sources:
            self.source.addItem(f"{source_label(selected)} · недоступен", selected)
        self.source.setCurrentIndex(self.source.findData(selected))
        self.source.blockSignals(False)

    def set_player(self, key, value):
        if self.data["player"][key] != value:
            self.data["player"][key] = value
            self.changed.emit("player")

    def set_value(self, key, value):
        if self.data[key] != value:
            self.data[key] = value
            self.changed.emit(key)
            self.sync_status()

    def show_seed(self, seed):
        self.seed_number.blockSignals(True)
        self.seed_number.setValue(seed)
        self.seed_number.blockSignals(False)

    def slider_seed_changed(self, seed):
        if self.seed.isSliderDown():
            self.show_seed(seed)
        else:
            self.apply_seed(seed)

    def apply_seed(self, seed):
        self.show_seed(seed)
        self.seed.blockSignals(True)
        self.seed.setValue(seed)
        self.seed.blockSignals(False)
        self.set_value("seed", seed)

    def randomize(self):
        seed = SystemRandom().randrange(MAX_SEED)
        self.apply_seed(seed + (seed >= self.data["seed"]))

    def change_scale(self, scale):
        self.scale_label.setText(f"{scale} %")
        self.set_value("scale", scale)

    def move_toggled(self, enabled):
        self.move.setText("Завершить" if enabled else "Переместить")
        self.move_mode.emit(enabled)
        self.sync_status()

    def toggle_visibility(self):
        self.set_value("visible", not self.data["visible"])

    def sync_status(self):
        self.hide_city.setText("Скрыть город" if self.data["visible"] else "Показать город")
        self.preview_status.setText(f"{SIZES[self.data['size']]}  ·  Сид {self.data['seed']}")
        status = "Перетащите город и нажмите «Завершить»." if self.move.isChecked() else (
            "●  Город на рабочем столе" if self.data["visible"] else "○  Город скрыт")
        self.status.setText(status)

    def showEvent(self, event):
        super().showEvent(event)
        self.visibility_changed.emit()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.visibility_changed.emit()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self.visibility_changed.emit()

    def closeEvent(self, event):
        if self.move.isChecked():
            self.move.setChecked(False)
        self.hide()
        event.ignore()
