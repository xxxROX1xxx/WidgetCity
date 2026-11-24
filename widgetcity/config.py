import json
import logging
import ntpath
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QIODevice, QSaveFile, QStandardPaths

from .catalog import BUILDINGS, TREES

MAX_SEED = 999_999
SCHEMA_VERSION = 4
DEFAULT_MAIL_SOURCES = ("Telegram", "Discord")
MAIL_SOURCE_ALIASES = {
    "telegram desktop": "telegram",
    "telegram.exe": "telegram",
    "telegram.telegramdesktop": "telegram",
    "telegram.telegramdesktop.store": "telegram",
    "telegrammessengerllp.telegramdesktop_t4vj0pshhgkwm!telegram.telegramdesktop.store": "telegram",
    "discord.exe": "discord",
    "com.squirrel.discord.discord": "discord",
    "com.squirrel.discordptb.discordptb": "discord",
    "com.squirrel.discordcanary.discordcanary": "discord",
}
SIZES = {"small": "Маленький", "medium": "Средний", "large": "Большой"}
SCENES = {
    "cafe": ("Кафе", "Тёплые окна и вывеска бара", "▰"),
    "phone": ("Телефонная станция", "Сигнальный фонарь на крыше", "◆"),
    "warehouse": ("Склад", "Фургон и рабочий с коробкой", "▣"),
    "station": ("Вокзал", "Поезд и выгрузка посылки", "▥"),
    "night": ("Ночной город", "Гаснущие окна и кот на улице", "☾"),
    "mail": ("Почта", "Флажок у почтового ящика при новом уведомлении", "✉"),
    "weather": ("Метеостанция", "Флюгер, лужи и прохожие под зонтиками", "☂"),
    "shop": ("Магазин приложений", "Доставка коробок во время загрузки Steam", "▣"),
    "books": ("Книжная лавка", "Записка в витрине при копировании текста", "▤"),
    "cyber": ("Киберклуб", "Неоновая вывеска во время игры", "◆"),
}


def default_folder():
    return QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)


def defaults():
    return {
        "version": SCHEMA_VERSION,
        "seed": 48217,
        "size": "medium",
        "scale": 100,
        "visible": True,
        "position": None,
        "appearance": {"colors": {}, "trees": list(TREES)},
        "integrations": {"mail_sources": list(DEFAULT_MAIL_SOURCES), "weather_city": "",
                         "clipboard_enabled": False, "clipboard_limit": 25},
        "player": {"card": True, "music": True, "source": ""},
        "activities": {
            key: {"enabled": True, "bindings": rules}
            for key, rules in {
                "cafe": [{"kind": "running", "exe": "Spotify.exe"}],
                "phone": [{"kind": "running", "exe": "Discord.exe"}, {"kind": "foreground", "exe": "Telegram.exe"}],
                "warehouse": [{"kind": "usb"}],
                "station": [{"kind": "download", "folder": default_folder()}],
                "night": [{"kind": "idle", "minutes": 5}],
                "mail": [], "weather": [], "shop": [], "books": [], "cyber": [],
            }.items()
        },
    }


class Config:
    def __init__(self):
        base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
        self.path = Path(base) / "settings.json"
        self.data = defaults()
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(saved, dict):
                return
            for key in ("seed", "scale"):
                if type(saved.get(key)) is int:
                    self.data[key] = max(50, min(160, saved[key])) if key == "scale" else max(0, min(MAX_SEED, saved[key]))
            if saved.get("size") in tuple(SIZES):
                self.data["size"] = saved["size"]
            if type(saved.get("visible")) is bool:
                self.data["visible"] = saved["visible"]
            pos = saved.get("position")
            if isinstance(pos, list) and len(pos) == 2 and all(type(n) is int for n in pos):
                self.data["position"] = pos
            player = saved.get("player")
            if isinstance(player, dict):
                for key, value in self.data["player"].items():
                    if isinstance(player.get(key), type(value)):
                        self.data["player"][key] = player[key]
            activities = saved.get("activities")
            if isinstance(activities, dict):
                for key in SCENES:
                    scene = activities.get(key)
                    if isinstance(scene, dict):
                        if type(scene.get("enabled")) is bool:
                            self.data["activities"][key]["enabled"] = scene["enabled"]
                        if isinstance(scene.get("bindings"), list):
                            self.data["activities"][key]["bindings"] = [
                                rule for rule in scene["bindings"] if valid_rule(rule) and (
                                    key != "cyber" or rule["kind"] == "running" and game_exe(rule["exe"])
                                )
                            ]
            version = saved.get("version")
            if type(version) is not int or version < 2:
                for rule in self.data["activities"]["phone"]["bindings"]:
                    if rule["kind"] == "foreground" and ntpath.basename(rule["exe"]).casefold() == "discord.exe":
                        rule["kind"] = "running"
            self.load_editors(saved)
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError):
            logging.exception("Could not read %s", self.path)

    def load_editors(self, saved):
        appearance = saved.get("appearance")
        if isinstance(appearance, dict):
            trees = appearance.get("trees")
            if isinstance(trees, list):
                self.data["appearance"]["trees"] = [key for key in TREES if key in trees]
            colors = appearance.get("colors")
            if isinstance(colors, dict):
                for key in BUILDINGS:
                    palette = colors.get(key)
                    if isinstance(palette, dict):
                        self.data["appearance"]["colors"][key] = {
                            part: palette[part] for part in ("walls", "roof")
                            if valid_color(palette.get(part))
                        }
        integrations = saved.get("integrations")
        if isinstance(integrations, dict):
            settings = self.data["integrations"]
            for key, value in settings.items():
                if type(integrations.get(key)) is type(value):
                    settings[key] = integrations[key]
            # Version 3 started with an empty list. Seed that list once on upgrade.
            if saved.get("version") == 3 and not settings["mail_sources"]:
                settings["mail_sources"] = list(DEFAULT_MAIL_SOURCES)
            settings["mail_sources"] = [name[:256] for name in settings["mail_sources"][:50]
                                        if isinstance(name, str) and name.strip()]
            settings["weather_city"] = settings["weather_city"][:120]
            settings["clipboard_limit"] = max(5, min(100, settings["clipboard_limit"]))

    def save(self):
        try:
            save_json(self.path, self.data)
        except OSError:
            logging.exception("Could not save %s", self.path)

    def activity_snapshot(self):
        return deepcopy(self.data["activities"])


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    file = QSaveFile(str(path))
    if not file.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(file.errorString())
    payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    if file.write(payload) != len(payload):
        file.cancelWriting()
        raise OSError(file.errorString())
    if not file.commit():
        raise OSError(file.errorString())


def valid_color(color):
    return (isinstance(color, str) and len(color) == 7 and color.startswith("#")
            and all(char in "0123456789abcdefABCDEF" for char in color[1:]))


def mail_source_key(source):
    key = source.strip().casefold()
    return MAIL_SOURCE_ALIASES.get(key, key)


def game_exe(exe):
    name = ntpath.basename(exe).casefold()
    return (name.endswith(".exe") and name not in {
        "steam.exe", "steamwebhelper.exe", "steamservice.exe", "steamerrorreporter.exe",
        "steamerrorreporter64.exe", "gameoverlayui.exe",
    })


def valid_rule(rule):
    if not isinstance(rule, dict):
        return False
    kind = rule.get("kind")
    if kind in ("running", "foreground"):
        return isinstance(rule.get("exe"), str) and rule["exe"].lower().endswith(".exe")
    if kind == "download":
        return isinstance(rule.get("folder"), str) and bool(rule["folder"].strip())
    if kind == "idle":
        return type(rule.get("minutes")) is int and 1 <= rule["minutes"] <= 120
    return kind == "usb"
