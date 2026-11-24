from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar, QPushButton, QVBoxLayout, QWidget

from .catalog import BUILDINGS
from .steam import DOWNLOAD_STATUS, open_steam


def card_label(text="", accent=False):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setObjectName("section" if accent else "muted")
    return label


def text_time(value):
    try:
        return datetime.fromisoformat(value).strftime("%d.%m · %H:%M") if isinstance(value, str) else (
            datetime.fromtimestamp(value).strftime("%d.%m · %H:%M")
        )
    except (ValueError, TypeError, OSError, OverflowError):
        return "время неизвестно"


def degrees(value):
    return f"{value:+.0f} °C" if isinstance(value, (int, float)) else "—"


class ActivityContent(QWidget):
    def __init__(self, name, services):
        super().__init__()
        self.name, self.services = name, services
        self.last_items = None
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(1, 1, 1, 1)
        self.body.setSpacing(6)
        self.body.addWidget(card_label(BUILDINGS[name], True))
        self.status = card_label()
        self.body.addWidget(self.status)
        if name == "shop":
            self.progress = QProgressBar()
            self.progress.setAccessibleName("Ход загрузки Steam")
            self.body.addWidget(self.progress)
            self.body.addStretch()
            button = QPushButton("Открыть загрузки Steam")
            button.clicked.connect(self.open_downloads)
            self.body.addWidget(button)
        else:
            self.list = QListWidget()
            self.list.setWordWrap(True)
            self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.list.setAccessibleName(BUILDINGS[name])
            self.body.addWidget(self.list, 1)
            if name == "books":
                self.setup_notes()
        services.changed.connect(self.refresh)
        self.refresh()

    def setup_notes(self):
        actions = QHBoxLayout()
        self.copy_button = QPushButton("Копировать")
        self.pin_button = QPushButton("Закрепить")
        self.delete_button = QPushButton("Удалить")
        for button in (self.copy_button, self.pin_button, self.delete_button):
            actions.addWidget(button)
        self.body.addLayout(actions)
        self.copy_button.clicked.connect(self.copy_selected)
        self.pin_button.clicked.connect(self.pin_selected)
        self.delete_button.clicked.connect(self.delete_selected)
        self.list.currentItemChanged.connect(self.selection)
        self.list.itemDoubleClicked.connect(self.copy_selected)

    def item_rows(self, items):
        if self.last_items == items:
            return
        current = self.list.currentItem()
        selection = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.last_items = items
        self.list.clear()
        for text, tooltip, value in items:
            item = QListWidgetItem(text)
            item.setToolTip(tooltip)
            item.setData(Qt.ItemDataRole.UserRole, value)
            self.list.addItem(item)
            if value is not None and (value == selection or isinstance(selection, list) and value == tuple(selection)):
                self.list.setCurrentItem(item)
        if self.list.currentRow() < 0 and self.list.count():
            self.list.setCurrentRow(0)
        if self.name == "books":
            self.selection()

    def refresh(self):
        service = self.services
        if self.name == "mail":
            self.status.setText(service.mail_message)
            items = []
            for item in service.mail_entries:
                time = text_time(item["time"])
                summary = item["text"] or "Уведомление"
                items.append((f"{item['app']} · {time}\n{summary[:190]}", summary, item["key"]))
            if not items:
                items.append((service.empty_mail_message, "", None))
            self.item_rows(items)
        elif self.name == "weather":
            weather = service.current_weather()
            items = []
            if weather:
                headline = f"{degrees(weather.get('temperature'))} · {weather.get('place', '')}"
                updated = f"Обновлено {text_time(weather.get('updated'))} · Open-Meteo"
                extra = f"{service.weather_error} · " if service.weather_error else ""
                self.status.setText(f"{headline}\n{extra}{updated}")
                for row in weather.get("hourly") or []:
                    if not isinstance(row, list) or len(row) != 3:
                        continue
                    timestamp, temp, rain = row
                    if isinstance(timestamp, str):
                        detail = f"  ·  осадки {rain}%" if rain is not None else ""
                        items.append((f"{timestamp[11:16]}    {degrees(temp)}{detail}", "", timestamp))
            else:
                self.status.setText(service.weather_error or (
                    "Ожидаем прогноз" if service.options["weather_city"].strip() else "Укажите город во вкладке «Активности»"
                ))
            self.item_rows(items or [("Почасовой прогноз пока недоступен", "", None)])
        elif self.name == "shop":
            steam = service.steam
            if not service.enabled("shop"):
                self.status.setText("Активность магазина выключена")
            else:
                lines = [DOWNLOAD_STATUS[steam.status]]
                if steam.name:
                    lines.append(steam.name)
                    if steam.progress is None and steam.status == "downloading":
                        lines.append("Прогресс недоступен")
                self.status.setText("\n".join(lines))
            self.progress.setVisible(service.enabled("shop") and steam.progress is not None)
            if steam.progress is not None:
                self.progress.setValue(steam.progress)
        else:
            self.refresh_notes()

    def open_downloads(self):
        if not open_steam(downloads=True):
            self.status.setText("Не удалось открыть Steam")

    def refresh_notes(self):
        service = self.services
        self.status.setText("История WidgetCity" if service.history_enabled else "История выключена. Закреплённые заметки доступны.")
        items = [(f"Закреплено · {' '.join(text.split())[:100]}", text, (text, True)) for text in service.pin_notes]
        items.extend((" ".join(text.split())[:110], text, (text, False)) for text in service.recent)
        self.item_rows(items or [("Здесь появятся фрагменты и закреплённые заметки", "", None)])

    def selected(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def selection(self, *_):
        selected = self.selected()
        self.copy_button.setEnabled(bool(selected))
        self.delete_button.setEnabled(bool(selected))
        self.pin_button.setEnabled(bool(selected and selected[0] not in self.services.pin_notes))

    def copy_selected(self, *_):
        if selected := self.selected():
            self.services.copy(selected[0])

    def pin_selected(self):
        if selected := self.selected():
            self.services.pin(selected[0])

    def delete_selected(self):
        if selected := self.selected():
            self.services.delete_clip(*selected)
