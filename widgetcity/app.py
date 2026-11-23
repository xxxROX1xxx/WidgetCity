import logging
import sys
from time import monotonic

from PySide6.QtCore import QLockFile, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import __version__
from .city import Layout, Renderer, SPRITES, Scenes
from .config import Config
from .desktop import DesktopCity
from .media import MediaMonitor, MediaState
from .settings import STYLE, Settings
from .update_ui import UpdateController
from .updates import cleanup, confirm_install
from .windows import TriggerMonitor


def city_icon():
    return QIcon(str(SPRITES / "widgetcity.ico"))


class Application:
    def __init__(self, app, config):
        self.app, self.config, self.data = app, config, config.data
        self.scenes = Scenes()
        self.renderer = self.build_city()
        self.triggers = TriggerMonitor()
        self.trigger_version = 0
        self.media = MediaMonitor(self.data["player"]["source"])
        self.media_state = MediaState()
        self.player_source = None
        self.settings = Settings(config, self.renderer, self.scenes, self.triggers)
        self.updater = UpdateController(self.settings)
        self.desktop = DesktopCity(self.renderer, self.scenes, self.data["position"], self.data["scale"])
        self.desktop.open_changed = self.media.request_cover
        self.frames = QTimer(timerType=Qt.TimerType.CoarseTimer)
        self.frames.timeout.connect(self.frame)
        self.save_timer = QTimer(interval=200, singleShot=True)
        self.save_timer.timeout.connect(self.config.save)

        self.settings.changed.connect(self.changed)
        self.settings.test_scene.connect(self.test_scene)
        self.settings.move_mode.connect(self.move_mode)
        self.settings.reset_location.connect(self.reset_location)
        self.settings.visibility_changed.connect(self.sync_frames)
        self.desktop.view.position_changed.connect(self.save_position)
        self.desktop.player.command.connect(self.media.command)
        self.triggers.updated.connect(self.apply_triggers)
        self.media.changed.connect(self.apply_media)
        self.media.sources_changed.connect(self.settings.source_options)

        self.tray = QSystemTrayIcon(app.windowIcon())
        self.tray.setToolTip("WidgetCity")
        self.menu = QMenu()
        self.menu.addAction("Открыть настройки", self.open_settings)
        self.tray_visibility = self.menu.addAction("", self.settings.toggle_visibility)
        self.tray_move = self.menu.addAction("Переместить город", self.tray_move_mode)
        self.menu.addSeparator()
        self.menu.addAction("Выход", self.app.quit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.tray_clicked)
        self.tray.show()
        self.app.aboutToQuit.connect(self.shutdown)
        self.app.screenAdded.connect(self.connect_screen)
        self.app.screenRemoved.connect(lambda _screen: QTimer.singleShot(0, self.reposition))
        for screen in self.app.screens():
            self.connect_screen(screen)

        self.configure_triggers()
        self.configure_player()
        self.triggers.start()
        self.media.start()
        self.apply_visibility()

    def connect_screen(self, screen):
        screen.availableGeometryChanged.connect(self.reposition)

    def reposition(self, *_):
        self.desktop.place()
        self.desktop.view.update()

    def build_city(self):
        return Renderer(Layout(self.data["seed"], self.data["size"]))

    def changed(self, key):
        if key in ("seed", "size"):
            self.renderer = self.build_city()
            self.desktop.set_layout(self.renderer)
            self.settings.preview.renderer = self.renderer
            self.settings.scene_preview.renderer = self.renderer
            self.settings.preview.update()
            self.settings.scene_preview.update()
        elif key == "scale":
            self.desktop.set_scale(self.data["scale"])
        elif key == "activities":
            self.configure_triggers()
            self.refresh_music()
            self.frame()
        elif key == "visible":
            self.apply_visibility()
        elif key == "player":
            self.configure_player()
            self.frame()
        self.save_timer.start()

    def configure_triggers(self):
        activities = self.config.activity_snapshot()
        self.scenes.configure(activities)
        self.trigger_version = self.triggers.configure(activities)

    def configure_player(self):
        settings = self.data["player"]
        source = settings["source"]
        if source != self.player_source:
            self.player_source = source
            self.media_state = MediaState(source=source, status="Ожидание медиасессии…")
            self.desktop.player.apply(self.media_state)
            self.media.select(source)
        self.desktop.allow_player(settings["card"])
        self.refresh_music()

    def apply_triggers(self, version, levels, events):
        if version == self.trigger_version:
            self.scenes.update_triggers(levels, events)
            self.frame()

    def apply_media(self, selected_source, state):
        if selected_source != self.player_source:
            return
        self.media_state = state
        self.desktop.player.apply(state)
        self.refresh_music()
        self.frame()

    def refresh_music(self):
        player = self.data["player"]
        self.scenes.music = (self.scenes.enabled.get("cafe", False) and player["music"]
                             and self.media_state.playing
                             and (not player["source"] or player["source"] == self.media_state.source))

    def test_scene(self, key):
        self.scenes.test(key)
        self.frame()

    def sync_frames(self):
        self.frame()

    def frame(self):
        now = monotonic()
        self.scenes.refresh_night()
        visible_city = self.desktop.view.isVisible()
        if visible_city:
            self.desktop.view.update()
        previews = ()
        if not self.settings.isMinimized():
            previews = tuple(p for p in (self.settings.preview, self.settings.scene_preview) if p.isVisible())
        for preview in previews:
            preview.update()
        if visible_city or previews:
            interval = self.scenes.interval(now)
            if not self.frames.isActive() or self.frames.interval() != interval:
                self.frames.start(interval)
        else:
            self.frames.stop()

    def apply_visibility(self):
        visible = self.data["visible"]
        if not visible and self.settings.move.isChecked():
            self.settings.move.setChecked(False)
        self.desktop.show(visible)
        self.tray_visibility.setText("Скрыть город" if visible else "Показать город")
        self.settings.sync_status()
        self.sync_frames()

    def move_mode(self, enabled):
        if enabled and not self.data["visible"]:
            self.settings.set_value("visible", True)
        self.desktop.move_mode(enabled)
        self.tray_move.setText("Завершить перемещение" if enabled else "Переместить город")
        self.sync_frames()

    def tray_move_mode(self):
        self.settings.move.setChecked(not self.settings.move.isChecked())
        if self.settings.move.isChecked() and not self.settings.isVisible():
            self.tray.showMessage("WidgetCity", "Перетащите город. Завершите перемещение через меню трея.")

    def save_position(self, position):
        self.data["position"] = position
        self.save_timer.start()

    def reset_location(self):
        self.desktop.position = None
        self.reposition()
        self.save_position(None)

    def open_settings(self):
        if self.settings.isMinimized():
            self.settings.showNormal()
        else:
            self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()

    def tray_clicked(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.open_settings()

    def shutdown(self):
        self.frames.stop()
        self.save_timer.stop()
        self.config.save()
        self.desktop.show(False)
        self.tray.hide()
        self.triggers.stop()
        self.media.requestInterruption()
        self.updater.stop()
        self.triggers.wait()
        self.media.wait()


def main():
    logging.basicConfig(level=logging.INFO)
    app = QApplication(sys.argv)
    app.setApplicationName("WidgetCity")
    app.setApplicationDisplayName("WidgetCity")
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setWindowIcon(city_icon())
    temp = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation)
    lock = QLockFile(temp + "/WidgetCity.lock")
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        QMessageBox.information(None, "WidgetCity", "WidgetCity уже запущен. Откройте настройки через значок в трее.")
        return 0
    city = Application(app, Config())
    city.open_settings()
    stage = confirm_install(sys.argv[1:])
    if stage is not None:
        def clear_stage(attempts=12):
            if not cleanup(stage) and attempts > 1:
                QTimer.singleShot(1000, lambda: clear_stage(attempts - 1))

        QTimer.singleShot(1000, clear_stage)
    return app.exec()
