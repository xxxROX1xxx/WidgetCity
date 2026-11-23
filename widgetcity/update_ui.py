import logging
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox

from . import __version__
from .updates import StagedUpdate, UpdateError, begin_install, cleanup, latest_release, prepare_update


class UpdateJob(QThread):
    progress = Signal(int)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation
        self.result = self.error = None

    def run(self):
        try:
            self.result = self.operation(self)
        except UpdateError as error:
            self.error = str(error)
        except Exception as error:
            logging.exception("WidgetCity update failed")
            self.error = f"Не удалось получить обновление.\n{error}"


class UpdateController(QObject):
    def __init__(self, settings):
        super().__init__(settings)
        self.settings = settings
        self.job = self.on_success = None
        settings.update_requested.connect(self.check)

    @Slot()
    def check(self):
        if self.job is None:
            self.start(lambda _job: latest_release(), self.offer, "Проверка…")

    def start(self, operation, on_success, status):
        self.settings.update_status(status)
        self.on_success = on_success
        self.job = UpdateJob(operation, self)
        self.job.progress.connect(self.report_progress)
        self.job.finished.connect(self.finished)
        self.job.start()

    @Slot(int)
    def report_progress(self, percent):
        self.settings.update_status(f"Скачивание {percent}%")

    @Slot()
    def finished(self):
        job, callback = self.job, self.on_success
        if job is None:
            return
        self.job = self.on_success = None
        job.deleteLater()
        self.settings.update_status()
        if job.error:
            QMessageBox.information(self.settings, "Обновления WidgetCity", job.error)
        else:
            callback(job.result)

    def offer(self, release):
        if release is None:
            QMessageBox.information(self.settings, "Обновления WidgetCity",
                                    f"У вас уже установлена актуальная версия {__version__}.")
            return
        portable = getattr(sys, "frozen", False)
        dialog = QMessageBox(self.settings)
        dialog.setWindowTitle("Обновления WidgetCity")
        dialog.setText(f"Доступна версия {release.tag}.")
        dialog.setInformativeText(
            "WidgetCity скачает сборку и перезапустится после установки." if portable
            else "При запуске из исходников готовую сборку можно скачать со страницы релиза."
        )
        accept = dialog.addButton("Установить" if portable else "Открыть релиз", QMessageBox.ButtonRole.AcceptRole)
        cancel = dialog.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(accept)
        dialog.setEscapeButton(cancel)
        dialog.exec()
        if dialog.clickedButton() == accept:
            if portable:
                target = Path(sys.executable)
                self.start(lambda job: prepare_update(release, target, job.progress.emit, job.isInterruptionRequested),
                           self.install, "Скачивание 0%")
            else:
                QDesktopServices.openUrl(QUrl(release.page))
        dialog.deleteLater()

    def install(self, staged):
        try:
            begin_install(staged)
        except OSError as error:
            cleanup(staged.directory)
            QMessageBox.warning(self.settings, "Обновления WidgetCity",
                                f"Не удалось запустить установку.\n{error}")
            return
        QApplication.quit()

    def stop(self):
        if self.job is not None:
            self.job.requestInterruption()
            self.job.wait()
            if isinstance(self.job.result, StagedUpdate):
                cleanup(self.job.result.directory)
            self.job = None
