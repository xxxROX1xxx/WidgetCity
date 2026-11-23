"""Fetch WidgetCity releases and replace the portable executable on Windows."""

import ctypes
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from http.client import HTTPException
from pathlib import Path
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import psutil

from . import __version__

REPOSITORY = "xxxROX1xxx/WidgetCity"
LATEST = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES = f"https://github.com/{REPOSITORY}/releases"
ASSET_NAME = "WidgetCity.exe"
GITHUB_HOSTS = {"api.github.com", "github.com", "release-assets.githubusercontent.com",
                "objects.githubusercontent.com", "github-releases.githubusercontent.com"}
INSTALL_ARG = "--widgetcity-install"
RESUME_ARG = "--widgetcity-updated"
STAGE_PREFIX = ".widgetcity-update-"
INSTALLER = "updater.exe"
REPLACEMENT = "replacement.exe"
ROLLBACK = "rollback.exe"
READY = "ready"
MAX_ASSET_SIZE = 512 * 1024 * 1024


class UpdateError(Exception):
    pass


@dataclass(frozen=True)
class Release:
    tag: str
    url: str
    size: int
    sha256: str

    @property
    def page(self):
        return f"{RELEASES}/tag/{quote(self.tag, safe='')}"


@dataclass(frozen=True)
class StagedUpdate:
    target: Path
    directory: Path
    sha256: str


class GitHubRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        if parsed.scheme != "https" or parsed.hostname not in GITHUB_HOSTS:
            raise UpdateError("GitHub вернул неожиданный адрес загрузки.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def github_request(url, accept):
    request = Request(url, headers={"User-Agent": f"WidgetCity/{__version__}", "Accept": accept})
    return build_opener(GitHubRedirect()).open(request, timeout=10)


def version_number(tag):
    match = re.fullmatch(r"[vV]?(\d{1,9})\.(\d{1,9})\.(\d{1,9})(?:\+[a-zA-Z0-9.-]+)?", tag, re.ASCII)
    if not match:
        raise UpdateError("Тег релиза должен иметь формат v1.2.3.")
    return tuple(map(int, match.groups()))


def parse_release(data, installed):
    if not isinstance(data, dict) or not isinstance(data.get("tag_name"), str):
        raise UpdateError("GitHub вернул неполные данные о релизе.")
    if data.get("draft") or data.get("prerelease"):
        raise UpdateError("В GitHub Releases пока нет опубликованной стабильной версии.")
    tag = data["tag_name"]
    if version_number(tag) <= version_number(installed):
        return None
    assets = data.get("assets")
    if isinstance(assets, list):
        for asset in assets:
            if not isinstance(asset, dict) or asset.get("name") != ASSET_NAME or asset.get("state", "uploaded") != "uploaded":
                continue
            size = asset.get("size")
            if type(size) is not int or not 0 < size <= MAX_ASSET_SIZE:
                raise UpdateError("В релизе указан неподходящий размер файла WidgetCity.exe.")
            digest = asset.get("digest") or ""
            if digest and (not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest)):
                raise UpdateError("У файла релиза неверная контрольная сумма.")
            url = f"{RELEASES}/download/{quote(tag, safe='')}/{ASSET_NAME}"
            return Release(tag, url, size, digest.removeprefix("sha256:").lower())
    raise UpdateError(f"К релизу {tag} нужно приложить файл {ASSET_NAME}.")


def latest_release(installed=__version__):
    try:
        with github_request(LATEST, "application/vnd.github+json") as response:
            data = json.loads(response.read(1024 * 1024))
    except HTTPError as error:
        if error.code == 404:
            raise UpdateError("В GitHub Releases пока нет опубликованной версии.") from error
        if error.code in (403, 429):
            raise UpdateError("GitHub ограничил запросы. Попробуйте проверить обновления позже.") from error
        raise UpdateError(f"GitHub вернул ошибку HTTP {error.code}.") from error
    except ValueError as error:
        raise UpdateError("Не удалось прочитать данные релиза GitHub.") from error
    except (OSError, HTTPException) as error:
        raise UpdateError("Не удалось подключиться к GitHub.") from error
    return parse_release(data, installed)


def is_windows_x64(path):
    with path.open("rb") as file:
        header = file.read(64)
        if len(header) != 64 or header[:2] != b"MZ":
            return False
        file.seek(struct.unpack_from("<I", header, 60)[0])
        pe = file.read(24)
        if len(pe) != 24 or pe[:4] != b"PE\0\0":
            return False
        machine, flags = struct.unpack_from("<H16xH", pe, 4)
        return machine == 0x8664 and flags & 2 != 0 and flags & 0x2000 == 0


def prepare_update(release, target, progress, cancelled):
    target = target.resolve(strict=True)
    directory = Path(tempfile.mkdtemp(prefix=STAGE_PREFIX, dir=target.parent))
    try:
        replacement = directory / REPLACEMENT
        digest = hashlib.sha256()
        received = 0
        with github_request(release.url, "application/octet-stream") as response, replacement.open("xb") as output:
            while chunk := response.read(256 * 1024):
                if cancelled():
                    raise UpdateError("Скачивание отменено.")
                received += len(chunk)
                if received > release.size:
                    raise UpdateError("Загруженный файл превышает размер, указанный в релизе.")
                output.write(chunk)
                digest.update(chunk)
                progress(received * 100 // release.size)
        if received != release.size or (release.sha256 and digest.hexdigest() != release.sha256):
            raise UpdateError("Загруженный файл не прошёл проверку размера или контрольной суммы.")
        if not is_windows_x64(replacement):
            raise UpdateError("В релизе нужен исполняемый файл WidgetCity для Windows x64.")
        if cancelled():
            raise UpdateError("Скачивание отменено.")
        shutil.copyfile(target, directory / INSTALLER)
        return StagedUpdate(target, directory, digest.hexdigest())
    except BaseException:
        cleanup(directory)
        raise


def cleanup(directory):
    try:
        # A Windows process keeps its own executable open until its bootloader exits.
        for name in (INSTALLER, REPLACEMENT, ROLLBACK, READY):
            (directory / name).unlink(missing_ok=True)
        directory.rmdir()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


def safe_directory(value, target):
    directory = Path(value).resolve()
    if directory.is_dir() and directory.parent == target.parent and directory.name.startswith(STAGE_PREFIX):
        return directory
    raise UpdateError("Папка обновления не найдена рядом с WidgetCity.exe.")


def launch(executable, *args):
    return subprocess.Popen(
        [str(executable), *map(str, args)], cwd=executable.parent,
        env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"},
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def begin_install(staged):
    launch(staged.directory / INSTALLER, INSTALL_ARG, staged.target, staged.directory, os.getpid(), staged.sha256)


def replace_unlocked(source, target):
    deadline = monotonic() + 12
    while True:
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if monotonic() >= deadline:
                raise
            sleep(.2)


def wait_for_exit(pid):
    try:
        psutil.Process(pid).wait(timeout=30)
    except psutil.NoSuchProcess:
        pass


def apply_install(target, directory, pid, digest):
    replacement = directory / REPLACEMENT
    actual = hashlib.sha256()
    with replacement.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            actual.update(chunk)
    if actual.hexdigest() != digest:
        raise UpdateError("Файл обновления изменился во время установки.")
    wait_for_exit(pid)
    replace_unlocked(replacement, target)
    try:
        process = launch(target, RESUME_ARG, directory)
        deadline = monotonic() + 30
        while not (directory / READY).exists() and monotonic() < deadline:
            if process.poll() is not None:
                raise UpdateError("Новая версия завершилась при запуске.")
            sleep(.2)
    except (OSError, UpdateError):
        shutil.copyfile(directory / INSTALLER, directory / ROLLBACK)
        replace_unlocked(directory / ROLLBACK, target)
        launch(target, RESUME_ARG, directory)
        raise


def run_installer(args):
    try:
        target_name, folder, pid, digest = args
        target = Path(target_name).resolve(strict=True)
        directory = safe_directory(folder, target)
        if Path(sys.executable).resolve() != directory / INSTALLER or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise UpdateError("Не удалось подтвердить параметры установки.")
        apply_install(target, directory, int(pid), digest)
        return 0
    except (OSError, ValueError, UpdateError, psutil.Error) as error:
        ctypes.windll.user32.MessageBoxW(None, f"Не удалось установить обновление.\n\n{error}",
                                        "WidgetCity", 0x10)
        return 1


def confirm_install(args):
    if not getattr(sys, "frozen", False) or len(args) != 2 or args[0] != RESUME_ARG:
        return None
    try:
        directory = safe_directory(args[1], Path(sys.executable).resolve(strict=True))
        (directory / READY).touch()
        return directory
    except (OSError, UpdateError):
        return None
