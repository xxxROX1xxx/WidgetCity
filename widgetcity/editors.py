from time import monotonic

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from .catalog import BUILDINGS, TREES
from .city import material_sprite, paint_building_effects, sprite


class SpritePreview(QWidget):
    def __init__(self, name, scenes=None):
        super().__init__()
        self.name, self.scenes = name, scenes
        self.setMinimumHeight(96)
        self.setMaximumHeight(125)

    def paintEvent(self, _event):
        painter = QPainter(self)
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0, QColor("#181522"))
        gradient.setColorAt(1, QColor("#2d2339"))
        painter.fillRect(self.rect(), gradient)
        scale = max(1, min(2, self.height() / 80))
        painter.translate(round((self.width() - 72*scale) / 2), round((self.height() - 80*scale) / 2))
        painter.scale(scale, scale)
        painter.drawImage(12, 52, sprite("stone0"))
        if self.scenes is None:
            painter.drawImage(0, -4, sprite(self.name))
            return
        palette = self.scenes.colors.get(self.name, {})
        painter.translate(0, -5)
        painter.drawImage(0, 0, material_sprite(self.name, palette.get("walls", ""), palette.get("roof", "")))
        painter.setOpacity(.82)
        painter.drawImage(0, 0, sprite(self.name + "_lit"))
        painter.setOpacity(1)
        paint_building_effects(painter, self.name, QPoint(0, 0), self.scenes, monotonic())


def tile(title):
    frame = QFrame()
    frame.setObjectName("panel")
    layout = QVBoxLayout(frame)
    label = QLabel(title)
    label.setObjectName("bindingLabel")
    layout.addWidget(label)
    return frame, layout


class BuildingEditor(QWidget):
    changed = Signal()

    def __init__(self, scenes):
        super().__init__()
        self.scenes = scenes
        self.previews = {}
        self.buttons = {}
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        for i, (key, title) in enumerate(BUILDINGS.items()):
            frame, inner = tile(title)
            preview = SpritePreview(key, scenes)
            self.previews[key] = preview
            inner.addWidget(preview, 1)
            actions = QHBoxLayout()
            for part, caption in (("walls", "Стены"), ("roof", "Крыша")):
                button = QPushButton(caption)
                button.setAccessibleName(f"{title} · {caption}")
                button.clicked.connect(lambda _, k=key, p=part: self.choose(k, p))
                actions.addWidget(button)
                self.buttons[key, part] = button
            inner.addLayout(actions)
            reset = QPushButton("Сбросить цвета")
            reset.clicked.connect(lambda _, k=key: self.reset(k))
            inner.addWidget(reset)
            layout.addWidget(frame, i // 3, i % 3)
            self.refresh_buttons(key)

    def refresh_buttons(self, key):
        colors = self.scenes.colors.get(key, {})
        for part in ("walls", "roof"):
            button = self.buttons[key, part]
            color = colors.get(part, "")
            button.setToolTip(color or "Цвет спрайта")
            button.setStyleSheet(f"border-left: 5px solid {color};" if color else "")

    def choose(self, key, part):
        title = "Цвет стен" if part == "walls" else "Цвет крыши"
        color = QColor(self.scenes.colors.get(key, {}).get(part, "#8b6674" if part == "walls" else "#625270"))
        chosen = QColorDialog.getColor(color, self, f"{title} · {BUILDINGS[key]}")
        if chosen.isValid():
            self.scenes.colors.setdefault(key, {})[part] = chosen.name()
            self.refresh_buttons(key)
            self.previews[key].update()
            self.changed.emit()

    def reset(self, key):
        if self.scenes.colors.pop(key, None) is not None:
            self.refresh_buttons(key)
            self.previews[key].update()
            self.changed.emit()

    def repaint_previews(self):
        for preview in self.previews.values():
            preview.update()


class TreeEditor(QWidget):
    changed = Signal()

    def __init__(self, appearance):
        super().__init__()
        self.appearance = appearance
        self.checks = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        for caption, selected in (("Включить все", True), ("Снять все", False)):
            button = QPushButton(caption)
            button.clicked.connect(lambda _, value=selected: self.select_all(value))
            header.addWidget(button)
        header.addStretch()
        outer.addLayout(header)
        grid = QGridLayout()
        grid.setSpacing(10)
        outer.addLayout(grid, 1)
        for i, (key, (title, art)) in enumerate(TREES.items()):
            frame, inner = tile(title)
            inner.addWidget(SpritePreview(art), 1)
            check = QCheckBox("Использовать в городе")
            check.setAccessibleName(title)
            check.setChecked(key in appearance["trees"])
            check.toggled.connect(self.write_selection)
            inner.addWidget(check)
            grid.addWidget(frame, i // 3, i % 3)
            self.checks[key] = check

    def select_all(self, selected):
        for check in self.checks.values():
            check.blockSignals(True)
            check.setChecked(selected)
            check.blockSignals(False)
        self.write_selection()

    def write_selection(self, *_):
        result = [key for key, check in self.checks.items() if check.isChecked()]
        if result != self.appearance["trees"]:
            self.appearance["trees"] = result
            self.changed.emit()
