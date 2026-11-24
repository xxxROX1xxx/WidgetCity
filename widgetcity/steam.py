import ctypes
import os
import re
import winreg
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psutil
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from .config import game_exe
from .shell import CALLBACK, enumerate_windows, get_style, is_visible
from .windows import api, foreground_pid, user32, window_pid
from ctypes import wintypes as wt


LOG_UPDATE = re.compile(
    r"^\[([^]]+)] AppID (\d+) (?:(App|Workshop) )?"
    r"(state changed|update changed|update started|update canceled|update finished)\s*:\s*(.*)$"
)
VDF_PAIR = re.compile(r'"([^"\r\n]+)"\s*"((?:\\.|[^"\\])*)"')
GAME_FOLDER = "common"
DOWNLOAD_STATUS = {
    "downloading": "Загружается или обновляется",
    "paused": "Загрузка приостановлена",
    "queued": "Ожидает загрузки",
    "idle": "Загрузок и обновлений в очереди нет",
    "unavailable": "Данные о загрузках Steam недоступны",
}


@dataclass(frozen=True)
class SteamState:
    status: str = "unavailable"
    name: str = ""
    progress: int | None = None
    playing: bool = False


@dataclass(frozen=True)
class SteamTransfer:
    app_id: str
    channel: str
    status: str


def steam_path():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            return Path(winreg.QueryValueEx(key, "SteamPath")[0])
    except OSError:
        return None


def library_paths(steam):
    folders = [steam / "steamapps"]
    try:
        text = (folders[0] / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace")
        for key, path in VDF_PAIR.findall(text):
            if key == "path":
                folders.append(Path(path.replace("\\\\", "\\")) / "steamapps")
    except OSError:
        pass
    return tuple(dict.fromkeys(folders))


def content_activity(text, since):
    active, pending, games = {}, {}, set()
    for line in text.splitlines():
        event = LOG_UPDATE.search(line)
        if event is None:
            continue
        stamp, app_id, scope, action, payload = event.groups()
        try:
            timestamp = datetime.fromisoformat(stamp).timestamp()
        except ValueError:
            continue
        if timestamp < since - 2:
            continue
        flag_text, _, detail = payload.casefold().partition("(")
        flags = {part.strip() for part in flag_text.split(",")}
        channel = "workshop" if scope == "Workshop" else "app"
        token = (app_id, channel)
        if action == "state changed":
            if "app running" in flags:
                games.add(app_id)
            else:
                games.discard(app_id)
        paused = detail.startswith(("suspended", "paused")) or bool(flags & {"update paused", "suspended"})
        running = action == "update started" or bool(flags & {"downloading", "running update", "update running"})
        active.pop(token, None)
        if paused:
            pending[token] = SteamTransfer(app_id, channel, "paused")
        elif running and "stopping" not in flags and action not in ("update finished", "update canceled"):
            pending.pop(token, None)
            active[token] = SteamTransfer(app_id, channel, "downloading")
        elif action == "state changed":
            pending.pop(token, None)
            if "update queued" in flags or detail.startswith("update delayed"):
                pending[token] = SteamTransfer(app_id, channel, "queued")
        elif action == "update finished":
            pending.pop(token, None)
    return next(reversed(active.values()), next(reversed(pending.values()), None)), games


def download_details(app_id, folders):
    for folder in folders:
        try:
            text = (folder / f"appmanifest_{app_id}.acf").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        values = {key.casefold(): value for key, value in VDF_PAIR.findall(text)}
        try:
            size, received = int(values["bytestodownload"]), int(values["bytesdownloaded"])
            percent = int(received * 100 / size) if size > 0 and 0 <= received <= size else None
        except (ValueError, KeyError):
            percent = None
        return values.get("name", "").replace(r'\"', '"'), percent
    return "", None


def steam_state(downloads, games):
    steam = steam_path()
    if steam is None or not (steam / "steam.exe").is_file():
        return SteamState()
    processes = list(psutil.process_iter(["name"]))
    clients = [p for p in processes if (p.info["name"] or "").casefold() == "steam.exe"]
    if not clients:
        return SteamState("idle")
    folders = library_paths(steam)
    playing = False
    if games:
        prefixes = tuple(os.path.normcase(str(folder / GAME_FOLDER)) + os.sep for folder in folders)
        for process in processes:
            if not game_exe(process.info["name"] or ""):
                continue
            try:
                if os.path.normcase(process.exe()).startswith(prefixes):
                    playing = True
                    break
            except (psutil.Error, OSError):
                continue
    if not downloads and (playing or not games):
        return SteamState("idle", playing=playing)
    try:
        since = min(process.create_time() for process in clients)
        log = steam / "logs" / "content_log.txt"
        with log.open("rb") as file:
            size = file.seek(0, os.SEEK_END)
            file.seek(max(0, size - 256 * 1024))
            download, running_games = content_activity(file.read().decode("utf-8", errors="replace"), since)
    except (psutil.Error, OSError):
        return SteamState(playing=playing)
    playing = playing or bool(games and running_games)
    if downloads and download:
        name, progress = download_details(download.app_id, folders)
        return SteamState(download.status, name or f"Steam App {download.app_id}",
                          None if download.channel == "workshop" else progress, playing)
    return SteamState("idle", playing=playing)


get_title = api(user32, "GetWindowTextW", wt.INT, wt.HWND, wt.LPWSTR, wt.INT)
restore = api(user32, "ShowWindowAsync", wt.BOOL, wt.HWND, wt.INT)
foreground = api(user32, "SetForegroundWindow", wt.BOOL, wt.HWND)


def open_steam(downloads=False):
    if downloads:
        return QDesktopServices.openUrl(QUrl("steam://open/downloads"))
    clients = {p.pid for p in psutil.process_iter(["name"])
               if (p.info["name"] or "").casefold() in ("steam.exe", "steamwebhelper.exe")}
    if clients:
        windows = []

        @CALLBACK
        def find(hwnd, _):
            pid = wt.DWORD()
            window_pid(hwnd, ctypes.byref(pid))
            if pid.value in clients and is_visible(hwnd) and not (get_style(hwnd, -20) & 0x80):
                name = ctypes.create_unicode_buffer(100)
                get_title(hwnd, name, len(name))
                if name.value == "Steam":
                    windows.append(hwnd)
                    return False
            return True

        enumerate_windows(find, 0)
        if windows:
            restore(windows[0], 9)
            if foreground(windows[0]) or foreground_pid() in clients:
                return True
    return QDesktopServices.openUrl(QUrl("steam://open/main"))
