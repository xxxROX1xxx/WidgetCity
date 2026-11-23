"""Win32 desktop composition and desktop icon bounds."""

import ctypes as ct
from ctypes import wintypes as wt
from dataclasses import dataclass
from uuid import UUID

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from .windows import api, is_visible, user32

KEY_COLOR = QColor(1, 0, 1)
KEY_COLORREF = 0x010001
STYLE = -16
EX_STYLE = -20
CHILD, POPUP = 0x40000000, 0x80000000
LAYERED, TRANSPARENT, TOPMOST = 0x80000, 0x20, 0x8
NO_ACTIVATE = 0x0010
FRAME_CHANGED = 0x0020
CALLBACK = ct.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
find = api(user32, "FindWindowW", wt.HWND, wt.LPCWSTR, wt.LPCWSTR)
find_after = api(user32, "FindWindowExW", wt.HWND, wt.HWND, wt.HWND, wt.LPCWSTR, wt.LPCWSTR)
enumerate_windows = api(user32, "EnumWindows", wt.BOOL, CALLBACK, wt.LPARAM)
get_parent = api(user32, "GetParent", wt.HWND, wt.HWND)
is_window = api(user32, "IsWindow", wt.BOOL, wt.HWND)
set_parent = api(user32, "SetParent", wt.HWND, wt.HWND, wt.HWND)
client_to_screen = api(user32, "ClientToScreen", wt.BOOL, wt.HWND, ct.POINTER(wt.POINT))
get_client_rect = api(user32, "GetClientRect", wt.BOOL, wt.HWND, ct.POINTER(wt.RECT))
get_style = api(user32, "GetWindowLongPtrW", ct.c_ssize_t, wt.HWND, ct.c_int)
set_style = api(user32, "SetWindowLongPtrW", ct.c_ssize_t, wt.HWND, ct.c_int, ct.c_ssize_t)
set_z_position = api(user32, "SetWindowPos", wt.BOOL, wt.HWND, wt.HWND, ct.c_int, ct.c_int, ct.c_int, ct.c_int, wt.UINT)
set_layered = api(user32, "SetLayeredWindowAttributes", wt.BOOL, wt.HWND, wt.DWORD, wt.BYTE, wt.DWORD)
send_timeout = api(user32, "SendMessageTimeoutW", ct.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM,
                   wt.LPARAM, wt.UINT, wt.UINT, ct.c_void_p)


@dataclass(frozen=True)
class ShellLayer:
    visual: int | None = None
    interactive: int | None = None
    icons: int | None = None
    icon_list: int | None = None

    @classmethod
    def discover(cls):
        progman = find("Progman", None)
        if not progman:
            return cls()
        icons = find_after(progman, None, "SHELLDLL_DefView", None)
        raised = bool(get_style(progman, EX_STYLE) & 0x00200000)
        if not icons or (raised and not find_after(progman, None, "WorkerW", None)):
            # Ask Explorer to expose its wallpaper surface. The shell owns these HWNDs.
            for flag in (0, 1):
                send_timeout(progman, 0x052C, 0xD, flag, 2, 150, None)
            icons = find_after(progman, None, "SHELLDLL_DefView", None)
        if icons and raised:
            return cls(progman, progman, icons, find_after(icons, None, "SysListView32", None))

        icon_host = progman if icons else None
        if not icon_host:
            @CALLBACK
            def find_icons(hwnd, _):
                nonlocal icon_host, icons
                if is_visible(hwnd):
                    icons = find_after(hwnd, None, "SHELLDLL_DefView", None)
                    if icons:
                        icon_host = hwnd
                        return False
                return True

            enumerate_windows(find_icons, 0)
        if not icon_host:
            return cls()
        worker = find_after(None, icon_host, "WorkerW", None)
        while worker:
            bounds = wt.RECT()
            if is_visible(worker) and get_client_rect(worker, ct.byref(bounds)) and bounds.right > 0 and bounds.bottom > 0:
                break
            worker = find_after(None, worker, "WorkerW", None)
        return cls(worker or icon_host, icon_host, icons, find_after(icons, None, "SysListView32", None))

    def valid(self):
        return self.visual and all(is_window(hwnd) for hwnd in (self.visual, self.interactive, self.icons))

    def place(self, widget, rect, *, interactive=False, opacity=255, passthrough=False):
        parent = self.interactive if interactive else self.visual
        hwnd = widget.surface_handle()
        widget.resize(rect.size())
        previous_parent = get_parent(hwnd)
        style = get_style(hwnd, STYLE)
        desired = (style & ~POPUP) | CHILD if parent else (style & ~CHILD) | POPUP
        frame_changed = style != desired
        if frame_changed:
            set_style(hwnd, STYLE, desired)
        if previous_parent != parent:
            set_parent(hwnd, parent)
            parent = get_parent(hwnd)
            if not parent and desired & CHILD:
                set_style(hwnd, STYLE, (desired & ~CHILD) | POPUP)
        ex_style = get_style(hwnd, EX_STYLE)
        desired = (ex_style | LAYERED) & ~TOPMOST
        desired = desired | TRANSPARENT if passthrough else desired & ~TRANSPARENT
        if ex_style != desired:
            set_style(hwnd, EX_STYLE, desired)
            frame_changed = True
        screen = QApplication.screenAt(rect.center()) or QApplication.primaryScreen()
        origin, scale = screen.geometry().topLeft(), screen.devicePixelRatio()
        native = origin + (rect.topLeft() - origin) * scale
        parent_origin = wt.POINT()
        if parent:
            client_to_screen(parent, ct.byref(parent_origin))
        if parent:
            after = self.icons if not interactive and parent == self.interactive else None
        else:
            after = None if interactive else 1  # HWND_TOP / HWND_BOTTOM for the desktop fallback
        set_layered(hwnd, KEY_COLORREF, opacity, 3)  # LWA_COLORKEY | LWA_ALPHA
        set_z_position(hwnd, after, native.x() - parent_origin.x, native.y() - parent_origin.y,
                       round(rect.width() * scale), round(rect.height() * scale),
                       NO_ACTIVATE | (FRAME_CHANGED if frame_changed else 0))

    def icon_rects(self):
        if not self.icon_list or not is_visible(self.icon_list):
            return []
        return desktop_icon_rects(self.icon_list)


class Variant(ct.Structure):
    class Value(ct.Union):
        _fields_ = [("child", ct.c_long), ("storage", ct.c_void_p * 2)]

    _fields_ = [("type", wt.USHORT), ("reserved", wt.USHORT * 3), ("value", Value)]


oleacc = ct.WinDLL("oleacc")
accessible_object = api(oleacc, "AccessibleObjectFromWindow", ct.c_long, wt.HWND, wt.DWORD,
                        ct.c_void_p, ct.POINTER(ct.c_void_p))
ACCESSIBLE = (ct.c_ubyte * 16).from_buffer_copy(UUID("618736e0-3c3d-11cf-810c-00aa00389b71").bytes_le)


def desktop_icon_rects(hwnd):
    """Read the shell list's accessibility bounds without modifying Explorer."""
    accessible = ct.c_void_p()
    if accessible_object(hwnd, 0xFFFFFFFC, ct.byref(ACCESSIBLE), ct.byref(accessible)) < 0 or not accessible:
        return []
    vtable = ct.cast(accessible, ct.POINTER(ct.POINTER(ct.c_void_p)))[0]
    release = ct.WINFUNCTYPE(wt.ULONG, ct.c_void_p)(vtable[2])
    child_count = ct.WINFUNCTYPE(ct.c_long, ct.c_void_p, ct.POINTER(ct.c_long))(vtable[8])
    location = ct.WINFUNCTYPE(ct.c_long, ct.c_void_p, ct.POINTER(ct.c_long), ct.POINTER(ct.c_long),
                              ct.POINTER(ct.c_long), ct.POINTER(ct.c_long), Variant)(vtable[22])
    rects = []
    try:
        count = ct.c_long()
        if child_count(accessible, ct.byref(count)) >= 0:
            for index in range(1, count.value + 1):
                variant = Variant(3, value=Variant.Value(child=index))  # VT_I4, a 1-based child ID
                x, y, width, height = ct.c_long(), ct.c_long(), ct.c_long(), ct.c_long()
                if location(accessible, ct.byref(x), ct.byref(y), ct.byref(width), ct.byref(height), variant) >= 0:
                    if width.value > 0 and height.value > 0:
                        rects.append(QRect(x.value, y.value, width.value, height.value))
    finally:
        release(accessible)
    return rects


def logical_rect(rect, screen):
    origin, scale = screen.geometry().topLeft(), screen.devicePixelRatio()
    point = origin + (rect.topLeft() - origin) / scale
    return QRect(QPoint(point), rect.size() / scale)
