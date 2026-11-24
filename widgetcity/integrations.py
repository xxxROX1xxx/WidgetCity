import asyncio
import ctypes
import json
import logging
from contextlib import suppress
from time import monotonic

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from .config import mail_source_key, save_json
from .steam import SteamState, steam_state
from .weather import forecast

MAIL_STATUS = {
    "allowed": "Доступ к уведомлениям разрешён",
    "unspecified": "Разрешите доступ к уведомлениям Windows",
    "denied": "Доступ запрещён в настройках Windows",
    "unavailable": "Доступ к уведомлениям Windows недоступен",
    "disabled": "Активность почты выключена",
}


def selected_source(item, sources):
    return mail_source_key(item["id"]) in sources or mail_source_key(item["app"]) in sources


def notification_text(notification):
    with suppress(OSError, ValueError, AttributeError):
        visual = notification.notification.visual
        binding = visual.get_binding("ToastGeneric")
        if binding is None:
            binding = next(iter(visual.bindings), None)
        if binding is not None:
            return "\n".join(node.text for node in binding.get_text_elements() if node.text)[:1500]
    return ""


async def read_notifications(sources):
    from winrt.windows.ui.notifications import NotificationKinds
    from winrt.windows.ui.notifications.management import UserNotificationListener as Listener

    listener = Listener.current
    status = listener.get_access_status().name.lower()
    if status != "allowed":
        return status, {}, [], None
    notifications = await asyncio.wait_for(listener.get_notifications_async(NotificationKinds.TOAST), 6)
    status = listener.get_access_status().name.lower()
    if status != "allowed":
        return status, {}, [], None
    known, entries, current_keys = {}, [], set()
    complete = True
    allowed = {mail_source_key(source) for source in sources}
    for notification in notifications:
        try:
            info = notification.app_info
            source = info.app_user_model_id
            if not source:
                complete = False
                continue
            stamp = notification.creation_time
            key = f"{source}:{notification.id}:{stamp.isoformat()}"
            current_keys.add(key)
        except (OSError, ValueError, AttributeError):
            complete = False
            continue
        display = source
        with suppress(OSError, AttributeError):
            display = info.display_info.display_name or source
        known[source] = display
        item = {"id": source, "app": display}
        if selected_source(item, allowed):
            with suppress(OSError, ValueError, AttributeError):
                item.update(key=key, time=stamp.timestamp(), text=notification_text(notification), seen=False)
                entries.append(item)
    return status, known, entries, current_keys if complete else None


def notifications(sources):
    combase = ctypes.windll.combase
    initialized = combase.RoInitialize(1) >= 0
    try:
        return asyncio.run(read_notifications(sources))
    except (OSError, RuntimeError, ImportError, TimeoutError):
        return "unavailable", {}, [], None
    finally:
        if initialized:
            combase.RoUninitialize()


def clipboard_text(mime):
    if mime is None or not mime.hasText():
        return ""
    prefix = 'application/x-qt-windows-mime;value="'
    if mime.hasFormat(prefix + 'ExcludeClipboardContentFromMonitorProcessing"'):
        return ""
    policy = bytes(mime.data(prefix + 'CanIncludeInClipboardHistory"'))
    if len(policy) >= 4 and int.from_bytes(policy[:4], "little") == 0:
        return ""
    text = mime.text()
    return text[:4000] if text.strip() else ""


def read_json(path, default, *legacy_types):
    with suppress(OSError, ValueError):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, (type(default), *legacy_types)):
            return data
    return default


class Job(QThread):
    def __init__(self, function, args, parent):
        super().__init__(parent)
        self.function, self.args = function, args
        self.result, self.error = None, None

    def run(self):
        try:
            self.result = self.function(*self.args)
        except Exception as error:
            self.error = error


class Integrations(QObject):
    changed = Signal()
    clip_added = Signal()

    def __init__(self, config, clipboard, parent=None):
        super().__init__(parent)
        self.data = config.data
        self.clipboard = clipboard
        folder = config.path.parent
        self.mail_file = folder / "mail.json"
        self.weather_file = folder / "weather.json"
        self.notes_file = folder / "pinned-notes.json"
        self.pin_notes = [text[:4000] for text in read_json(self.notes_file, [])[:100] if isinstance(text, str)]
        self.recent = []
        self.writing_clip = False
        mail = read_json(self.mail_file, {}, list)
        if isinstance(mail, list):
            mail = {"entries": mail}
        entries, dismissed = mail.get("entries"), mail.get("dismissed")
        self.mail_dismissed = {key for key in dismissed if isinstance(key, str)} if isinstance(dismissed, list) else set()
        self.mail_entries = [entry for entry in (entries[:40] if isinstance(entries, list) else [])
                             if isinstance(entry, dict)
                             and all(isinstance(entry.get(key), str) for key in ("id", "app", "key", "text"))
                             and entry["key"] not in self.mail_dismissed
                             and isinstance(entry.get("time"), (int, float))]
        self.mail_status = "unspecified"
        self.mail_sources = {}
        self.mail_permission = None
        self.weather_data = read_json(self.weather_file, {})
        self.weather_error = ""
        self.steam = SteamState()
        self.schedule = {}
        self.scope = {}
        self.jobs = {}
        self.closed = False
        self.timer = QTimer(self, interval=1000)
        self.timer.timeout.connect(self.tick)
        self.clipboard.dataChanged.connect(self.capture_clip)
        self.timer.start()
        self.configure()

    @property
    def options(self):
        return self.data["integrations"]

    def enabled(self, key):
        return self.data["activities"][key]["enabled"]

    @property
    def history_enabled(self):
        return self.options["clipboard_enabled"] and self.enabled("books")

    def save(self, path, value):
        try:
            save_json(path, value)
        except OSError:
            logging.exception("Could not save %s", path.name)

    def save_mail(self):
        self.save(self.mail_file, {"entries": self.mail_entries, "dismissed": sorted(self.mail_dismissed)})

    def configure(self):
        city = self.options["weather_city"].strip()
        mail = tuple(self.options["mail_sources"])
        self.prune_mail()
        if self.options["clipboard_enabled"]:
            self.recent[:] = self.recent[:self.options["clipboard_limit"]]
        else:
            self.recent.clear()
        scope = {
            "mail": (mail,) if self.enabled("mail") else None,
            "weather": (city,) if self.enabled("weather") and city else None,
            "steam": (self.enabled("shop"), self.enabled("cyber")) if self.enabled("shop") or self.enabled("cyber") else None,
        }
        for key, args in scope.items():
            if self.scope.get(key) != args:
                self.schedule[key] = 0
                if key == "weather":
                    self.weather_error = ""
        self.scope = scope
        self.tick()
        self.changed.emit()

    def tick(self):
        if self.closed:
            return
        now = monotonic()
        if self.mail_permission is not None:
            self.finish_permission()
        for key, function, delay in (("mail", notifications, 3), ("weather", forecast, 900), ("steam", steam_state, 3)):
            args = self.scope.get(key)
            if args is not None and key not in self.jobs and now >= self.schedule.get(key, 0):
                job = Job(function, args, self)
                self.jobs[key] = job
                self.schedule[key] = now + delay
                job.finished.connect(self.finish_job)
                job.start()

    def finish_job(self):
        job = self.sender()
        key = next((key for key, entry in self.jobs.items() if entry is job), None)
        if key is None:
            return
        self.jobs.pop(key)
        job.deleteLater()
        if self.closed or self.scope.get(key) != job.args:
            return
        if key == "mail":
            self.merge_mail(*(job.result if job.error is None else ("unavailable", {}, [])))
        elif key == "weather":
            if job.error is None:
                self.weather_data, self.weather_error = job.result, ""
                self.save(self.weather_file, self.weather_data)
            else:
                self.weather_error = str(job.error) if isinstance(job.error, LookupError) else "Не удалось обновить прогноз"
                self.schedule[key] = monotonic() + 90
        else:
            state = job.result if job.error is None else SteamState()
            if self.steam == state:
                return
            self.steam = state
        self.changed.emit()

    @property
    def mail_message(self):
        return MAIL_STATUS[self.mail_status if self.enabled("mail") else "disabled"]

    @property
    def empty_mail_message(self):
        if not self.options["mail_sources"]:
            return "Выберите источники во вкладке «Активности»"
        if self.mail_status == "allowed" and self.enabled("mail"):
            return "Новых уведомлений пока нет. Почта получает их из центра уведомлений Windows (Win+N)."
        return "Доступ можно проверить во вкладке «Активности» → «Почта»."

    def request_notifications(self):
        if self.mail_permission is not None:
            return
        try:
            from winrt.windows.ui.notifications.management import UserNotificationListener as Listener

            self.mail_permission = Listener.current.request_access_async()
        except (OSError, RuntimeError, ImportError):
            self.mail_status = "unavailable"
            self.changed.emit()

    def finish_permission(self):
        try:
            if int(self.mail_permission.status) == 0:
                return
            self.mail_status = self.mail_permission.get_results().name.lower()
        except (OSError, RuntimeError):
            self.mail_status = "unavailable"
        self.mail_permission = None
        self.schedule["mail"] = 0
        self.changed.emit()

    def prune_mail(self):
        allowed = {mail_source_key(source) for source in self.options["mail_sources"]}
        data = [item for item in self.mail_entries if selected_source(item, allowed)]
        if data != self.mail_entries:
            self.mail_entries = data
            self.save_mail()

    def merge_mail(self, status, sources, entries, current_keys=None):
        self.mail_status = status if status in MAIL_STATUS else "unavailable"
        self.mail_sources.update(sources)
        existing = {item["key"]: item for item in self.mail_entries}
        allowed = {mail_source_key(source) for source in self.options["mail_sources"]}
        for item in entries:
            if item["key"] not in self.mail_dismissed and selected_source(item, allowed):
                existing.setdefault(item["key"], item)
        data = sorted(existing.values(), key=lambda item: item["time"], reverse=True)[:40]
        dismissed = self.mail_dismissed
        if status == "allowed" and current_keys is not None:
            dismissed = dismissed & current_keys
        if data != self.mail_entries or dismissed != self.mail_dismissed:
            self.mail_entries = data
            self.mail_dismissed = dismissed
            self.save_mail()

    def mark_mail_seen(self):
        if any(not item.get("seen") for item in self.mail_entries):
            for item in self.mail_entries:
                item["seen"] = True
            self.save_mail()
            self.changed.emit()

    def dismiss_seen_mail(self):
        seen = {item["key"] for item in self.mail_entries if item.get("seen")}
        if seen:
            self.mail_entries = [item for item in self.mail_entries if item["key"] not in seen]
            self.mail_dismissed.update(seen)
            self.save_mail()
            self.changed.emit()

    def current_weather(self):
        return self.weather_data if self.weather_data.get("query") == self.options["weather_city"].strip() else {}

    def refresh_weather(self):
        self.schedule["weather"] = 0
        self.tick()

    def capture_clip(self):
        if self.writing_clip or not self.history_enabled:
            return
        text = clipboard_text(self.clipboard.mimeData())
        if text:
            self.recent = [text, *(item for item in self.recent if item != text)][:self.options["clipboard_limit"]]
            self.clip_added.emit()
            self.changed.emit()

    def copy(self, text):
        self.writing_clip = True
        try:
            self.clipboard.setText(text)
        finally:
            self.writing_clip = False

    def pin(self, text):
        if text not in self.pin_notes:
            self.pin_notes = [text, *self.pin_notes][:100]
            self.save(self.notes_file, self.pin_notes)
            self.changed.emit()

    def delete_clip(self, text, pinned):
        if pinned:
            self.pin_notes.remove(text)
            self.save(self.notes_file, self.pin_notes)
        else:
            self.recent.remove(text)
        self.changed.emit()

    def clear_history(self):
        self.recent.clear()
        self.changed.emit()

    def close(self):
        self.closed = True
        self.timer.stop()
        if self.mail_permission is not None:
            with suppress(OSError, RuntimeError):
                self.mail_permission.cancel()
        for job in self.jobs.values():
            job.wait()
