import asyncio
import ctypes
import logging
from contextlib import suppress
from dataclasses import dataclass
from queue import Empty, SimpleQueue
from threading import Event, Lock
from time import monotonic

from PySide6.QtCore import QThread, Signal


@dataclass(frozen=True)
class MediaState:
    source: str = ""
    title: str = ""
    artist: str = ""
    playing: bool = False
    previous: bool = False
    toggle: str = ""
    next: bool = False
    cover: bytes = b""
    route: int = 0
    status: str = "Нет медиасессии Windows"


def source_label(source):
    known = {"spotify": "Spotify", "yandexmusic": "Яндекс Музыка", "yandex.music": "Яндекс Музыка",
             "msedge": "Microsoft Edge", "chrome": "Google Chrome", "firefox": "Firefox"}
    lowered = source.casefold()
    return next((label for fragment, label in known.items() if fragment in lowered), source)


async def thumbnail(properties):
    from winrt.windows.storage.streams import DataReader

    reference = properties.thumbnail
    if reference is None:
        return b""
    stream = await reference.open_read_async()
    try:
        if not 0 < stream.size <= 10_000_000:
            return b""
        reader = DataReader(stream)
        try:
            count = await reader.load_async(stream.size)
            data = bytearray(count)
            reader.read_bytes(data)
            return bytes(data)
        finally:
            reader.close()
    finally:
        stream.close()


class MediaMonitor(QThread):
    changed = Signal(str, object)
    sources_changed = Signal(object)

    def __init__(self, source):
        super().__init__()
        self.lock = Lock()
        self.source = source
        self.cover_requested = False
        self.commands = SimpleQueue()

    def select(self, source):
        with self.lock:
            self.source = source

    def request_cover(self, visible):
        with self.lock:
            self.cover_requested = visible

    def command(self, route, command):
        if route and command:
            self.commands.put((route, command))

    def run(self):
        combase = ctypes.WinDLL("combase")
        initialized = combase.RoInitialize(1) >= 0
        try:
            asyncio.run(self.monitor())
        except (OSError, ImportError, RuntimeError):
            with self.lock:
                pinned = self.source
            self.changed.emit(pinned, MediaState(source=pinned, status="Медиасессии Windows недоступны"))
            logging.exception("Could not start GSMTC")
        finally:
            if initialized:
                combase.RoUninitialize()

    async def monitor(self):
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Manager,
            GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
        )

        manager = None
        current = media_token = None
        dirty = Event()
        route = 0
        previous_sources = previous_state = None
        metadata = ("", "", "")
        cover = b""
        cover_key = None
        cover_ready = False
        last_properties = 0.
        try:
            while not self.isInterruptionRequested():
                with self.lock:
                    pinned, wants_cover = self.source, self.cover_requested
                try:
                    if manager is None:
                        manager = await asyncio.wait_for(Manager.request_async(), 2)
                    sessions = {}
                    for session in manager.get_sessions():
                        sessions.setdefault(session.source_app_user_model_id, session)
                    sources = tuple(sorted(sessions, key=str.casefold))
                    if sources != previous_sources:
                        self.sources_changed.emit(sources)
                        previous_sources = sources
                    candidate = sessions.get(pinned) if pinned else manager.get_current_session()
                    if candidate != current:
                        self.unsubscribe(current, media_token)
                        current, media_token = candidate, None
                        if current is not None:
                            media_token = current.add_media_properties_changed(lambda *_: dirty.set())
                        route += 1
                        metadata, cover, cover_key, cover_ready = ("", "", ""), b"", None, False
                        dirty.set()
                    if current is None:
                        status = "Источник недоступен" if pinned else "Нет медиасессии Windows"
                        state = MediaState(source=pinned, status=status)
                    else:
                        await self.execute_commands(current, route)
                        info = current.get_playback_info()
                        controls = info.controls
                        playing = info.playback_status == Status.PLAYING
                        toggle = ("pause" if playing else "play")
                        if not (controls.is_pause_enabled if playing else controls.is_play_enabled):
                            toggle = "toggle" if controls.is_play_pause_toggle_enabled else ""
                        now = monotonic()
                        changed = dirty.is_set()
                        if changed or (wants_cover and (not cover_ready or now - last_properties > 2)):
                            dirty.clear()
                            properties = await asyncio.wait_for(current.try_get_media_properties_async(), 2)
                            if properties is not None:
                                metadata = (properties.title, properties.artist or properties.album_artist, properties.album_title)
                                if changed or cover_key != metadata:
                                    cover_ready = False
                                    cover = b""
                                if wants_cover and not cover_ready:
                                    cover_key, cover_ready = metadata, True
                                    with suppress(OSError, TimeoutError, TypeError, RuntimeError):
                                        cover = await asyncio.wait_for(thumbnail(properties), 2)
                            last_properties = now
                        state = MediaState(
                            source=current.source_app_user_model_id, title=metadata[0], artist=metadata[1],
                            playing=playing, previous=controls.is_previous_enabled, toggle=toggle,
                            next=controls.is_next_enabled, cover=cover, route=route, status="",
                        )
                except (OSError, TimeoutError, RuntimeError):
                    self.unsubscribe(current, media_token)
                    current, media_token, manager = None, None, None
                    state = MediaState(source=pinned, status="Медиасессия временно недоступна")
                if (pinned, state) != previous_state:
                    self.changed.emit(pinned, state)
                    previous_state = (pinned, state)
                await asyncio.sleep(.28 if wants_cover else .55)
        finally:
            self.unsubscribe(current, media_token)

    @staticmethod
    def unsubscribe(session, token):
        if session is not None and token is not None:
            with suppress(OSError, RuntimeError):
                session.remove_media_properties_changed(token)

    async def execute_commands(self, session, route):
        handlers = {
            "previous": session.try_skip_previous_async,
            "pause": session.try_pause_async,
            "play": session.try_play_async,
            "toggle": session.try_toggle_play_pause_async,
            "next": session.try_skip_next_async,
        }
        while not self.isInterruptionRequested():
            try:
                clicked_route, action = self.commands.get_nowait()
            except Empty:
                break
            if clicked_route == route and action in handlers:
                with suppress(OSError, TimeoutError, RuntimeError):
                    await asyncio.wait_for(handlers[action](), 2)
