import ctypes as ct
import ntpath
import os
import struct
from collections import defaultdict
from ctypes import wintypes as wt
from threading import Event, Lock
from time import monotonic

import psutil
from PySide6.QtCore import QThread, Signal


def api(library, name, result, *args):
    function = getattr(library, name)
    function.restype = result
    function.argtypes = args
    return function


user32 = ct.WinDLL("user32", use_last_error=True)
kernel32 = ct.WinDLL("kernel32", use_last_error=True)
get_foreground = api(user32, "GetForegroundWindow", wt.HWND)
is_visible = api(user32, "IsWindowVisible", wt.BOOL, wt.HWND)
is_minimized = api(user32, "IsIconic", wt.BOOL, wt.HWND)
window_pid = api(user32, "GetWindowThreadProcessId", wt.DWORD, wt.HWND, ct.POINTER(wt.DWORD))
key_state = api(user32, "GetAsyncKeyState", ct.c_short, ct.c_int)
tick_count = api(kernel32, "GetTickCount", wt.DWORD)
drive_type = api(kernel32, "GetDriveTypeW", wt.UINT, wt.LPCWSTR)
drive_bits = api(kernel32, "GetLogicalDrives", wt.DWORD)
device_open = api(kernel32, "CreateFileW", wt.HANDLE, wt.LPCWSTR, wt.DWORD, wt.DWORD,
                  ct.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE)
device_io = api(kernel32, "DeviceIoControl", wt.BOOL, wt.HANDLE, wt.DWORD, ct.c_void_p,
                wt.DWORD, ct.c_void_p, wt.DWORD, ct.POINTER(wt.DWORD), ct.c_void_p)
close_handle = api(kernel32, "CloseHandle", wt.BOOL, wt.HANDLE)


class LastInput(ct.Structure):
    _fields_ = [("size", wt.UINT), ("time", wt.DWORD)]


get_last_input = api(user32, "GetLastInputInfo", wt.BOOL, ct.POINTER(LastInput))


def foreground_pid():
    pid = wt.DWORD()
    hwnd = get_foreground()
    if hwnd and is_visible(hwnd) and not is_minimized(hwnd):
        window_pid(hwnd, ct.byref(pid))
    return pid.value


def idle_seconds():
    data = LastInput(ct.sizeof(LastInput))
    return ((tick_count() - data.time) & 0xFFFFFFFF) / 1000 if get_last_input(ct.byref(data)) else 0


def escape_pressed():
    return bool(key_state(0x1B) & 0x8000)


def mounted_drives():
    mask = drive_bits()
    return {chr(65 + index) + ":\\" for index in range(26) if mask & (1 << index)}


def usb_drive(root):
    kind = drive_type(root)
    if kind == 2:
        return True
    if kind != 3:
        return False
    # Some USB flash drives identify as fixed disks. Query the mounted volume's bus.
    handle = device_open("\\\\.\\" + root[:2], 0, 7, None, 3, 0, None)
    if not handle or handle == ct.c_void_p(-1).value:
        return False
    try:
        query = ct.create_string_buffer(12)  # StorageDeviceProperty, PropertyStandardQuery
        descriptor = ct.create_string_buffer(1024)
        returned = wt.DWORD()
        ok = device_io(handle, 0x002D1400, query, len(query), descriptor, len(descriptor), ct.byref(returned), None)
        return bool(ok and returned.value >= 32 and struct.unpack_from("<I", descriptor, 28)[0] == 7)
    finally:
        close_handle(handle)


def running_programs():
    programs = set()
    for p in psutil.process_iter(["name", "exe"]):
        try:
            info = p.info
            exe = info["exe"] or info["name"]
            if exe and exe.lower().endswith(".exe"):
                programs.add(exe)
        except (psutil.Error, OSError):
            continue
    return sorted(programs, key=lambda exe: (ntpath.basename(exe).casefold(), exe.casefold()))


def exe_matches(exe, name, path):
    if ntpath.dirname(exe):
        return bool(path and ntpath.normcase(path) == ntpath.normcase(exe))
    return exe.casefold() == name.casefold()


class DownloadWatch:
    TEMP_SUFFIXES = (".crdownload", ".part", ".tmp", ".download", ".partial", ".filepart", ".opdownload")

    def __init__(self):
        self.previous = None
        self.pending = {}

    def scan(self, folder, now):
        files = {}
        partial = set()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    try:
                        name = entry.name.casefold()
                        if name.startswith(".") or not entry.is_file(follow_symlinks=False):
                            continue
                        suffix = next((s for s in self.TEMP_SUFFIXES if name.endswith(s)), None)
                        if suffix:
                            partial.add(name[:-len(suffix)])
                        else:
                            stats = entry.stat(follow_symlinks=False)
                            files[name] = (entry.name, stats.st_size, stats.st_mtime_ns)
                    except OSError:
                        continue
        except OSError:
            self.previous = None
            self.pending.clear()
            return set()
        if self.previous is None:
            self.previous = files
            return set()
        completed = set()
        for name, signature in files.items():
            if self.previous.get(name) != signature or name in partial:
                self.pending[name] = now
            elif name in self.pending and now - self.pending[name] >= 2:
                # A writer can pause without closing the file. Sharing violations
                # mean the folder watcher should keep waiting.
                handle = device_open(os.path.join(folder, signature[0]), 0, 1, None, 3, 0, None)
                if handle == ct.c_void_p(-1).value and ct.get_last_error() in (32, 33):
                    continue
                if handle and handle != ct.c_void_p(-1).value:
                    close_handle(handle)
                del self.pending[name]
                completed.add(name)
        self.pending = {name: start for name, start in self.pending.items() if name in files}
        self.previous = files
        return completed


class TriggerMonitor(QThread):
    updated = Signal(int, object, object)
    programs = Signal(object)

    def __init__(self):
        super().__init__()
        self.lock = Lock()
        self.wake = Event()
        self.settings = {}
        self.version = 0
        self.list_requested = False

    def configure(self, settings):
        with self.lock:
            self.version += 1
            self.settings = settings
            version = self.version
        self.wake.set()
        return version

    def request_programs(self):
        with self.lock:
            self.list_requested = True
        self.wake.set()

    def stop(self):
        self.requestInterruption()
        self.wake.set()

    def run(self):
        previous_version = -1
        last_state = None
        last_pid = -1
        foreground = ("", "")
        drives = None
        watches = {}
        programs = []
        last_scan = -100.
        last_download_scan = -100.
        while not self.isInterruptionRequested():
            self.wake.clear()
            now = monotonic()
            with self.lock:
                version, settings = self.version, self.settings
                list_requested, self.list_requested = self.list_requested, False
            changed = version != previous_version
            enabled = {key: scene["bindings"] for key, scene in settings.items() if scene["enabled"]}
            rules = [rule for group in enabled.values() for rule in group]
            kinds = {rule["kind"] for rule in rules}
            if list_requested:
                try:
                    self.programs.emit(running_programs())
                except (psutil.Error, OSError):
                    self.programs.emit([])
            if "running" in kinds and (changed or now - last_scan >= .8):
                programs = self.matchable_processes(rules)
                last_scan = now
            if "foreground" in kinds:
                pid = foreground_pid()
                if pid != last_pid or changed:
                    foreground = self.process_identity(pid)
                    last_pid = pid
            else:
                last_pid = -1
            if "usb" in kinds:
                current = mounted_drives()
                usb_event = drives is not None and any(usb_drive(root) for root in current - drives)
                drives = current
            else:
                drives, usb_event = None, False
            if changed or now - last_download_scan >= .9:
                folders = {rule["folder"] for rule in rules if rule["kind"] == "download"}
                watches = {folder: watches.get(folder) or DownloadWatch() for folder in folders}
                file_events = {folder: watch.scan(folder, now) for folder, watch in watches.items()}
                last_download_scan = now
            else:
                file_events = {}
            idle = idle_seconds() if "idle" in kinds else 0
            levels, events = defaultdict(set), {}
            for key, group in enabled.items():
                arrivals = set()
                for rule in group:
                    kind = rule["kind"]
                    if kind == "running" and any(exe_matches(rule["exe"], *p) for p in programs):
                        levels[key].add((kind, ntpath.normcase(rule["exe"])))
                    elif kind == "foreground" and exe_matches(rule["exe"], *foreground):
                        levels[key].add((kind, ntpath.normcase(rule["exe"])))
                    elif kind == "idle" and idle >= rule["minutes"] * 60:
                        levels[key].add((kind, rule["minutes"]))
                    elif kind == "usb" and usb_event:
                        arrivals.add(("usb", ""))
                    elif kind == "download":
                        folder = rule["folder"]
                        arrivals.update((kind, ntpath.normcase(ntpath.join(folder, name)))
                                        for name in file_events.get(folder, ()))
                if arrivals:
                    events[key] = len(arrivals)
            if changed or events or levels != last_state:
                self.updated.emit(version, levels, events)
            last_state, previous_version = levels, version
            self.wake.wait(.23)

    @staticmethod
    def matchable_processes(rules):
        names = {ntpath.basename(r["exe"]).casefold() for r in rules if r["kind"] == "running"}
        paths = {ntpath.basename(r["exe"]).casefold() for r in rules
                 if r["kind"] == "running" and ntpath.dirname(r["exe"])}
        result = []
        for p in psutil.process_iter(["name"]):
            try:
                name = p.info["name"] or ""
                if name.casefold() in names:
                    path = ""
                    if name.casefold() in paths:
                        try:
                            path = p.exe()
                        except (psutil.Error, OSError):
                            pass
                    result.append((name, path))
            except (psutil.Error, OSError):
                continue
        return result

    @staticmethod
    def process_identity(pid):
        try:
            p = psutil.Process(pid)
            name = p.name()
            try:
                return name, p.exe()
            except (psutil.Error, OSError):
                return name, ""
        except (psutil.Error, OSError):
            return "", ""
