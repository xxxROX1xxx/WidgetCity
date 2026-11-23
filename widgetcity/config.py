import json
import logging
import ntpath
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QIODevice, QSaveFile, QStandardPaths

MAX_SEED = 999_999
SCHEMA_VERSION = 2
SIZES = {"small": "Маленький", "medium": "Средний", "large": "Большой"}
SCENES = {
    "cafe": ("Кафе", "Тёплые окна и вывеска бара", "▰"),
    "phone": ("Телефонная станция", "Сигнальный фонарь на крыше", "◆"),
    "warehouse": ("Склад", "Фургон и рабочий с коробкой", "▣"),
    "station": ("Вокзал", "Поезд и выгрузка посылки", "▥"),
    "night": ("Ночной город", "Гаснущие окна и кот на улице", "☾"),
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
        "player": {"card": True, "music": True, "source": ""},
        "activities": {
            key: {"enabled": True, "bindings": rules}
            for key, rules in {
                "cafe": [{"kind": "running", "exe": "Spotify.exe"}],
                "phone": [{"kind": "running", "exe": "Discord.exe"}, {"kind": "foreground", "exe": "Telegram.exe"}],
                "warehouse": [{"kind": "usb"}],
                "station": [{"kind": "download", "folder": default_folder()}],
                "night": [{"kind": "idle", "minutes": 5}],
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
                                rule for rule in scene["bindings"] if valid_rule(rule)
                            ]
            version = saved.get("version")
            if type(version) is not int or version < SCHEMA_VERSION:
                for rule in self.data["activities"]["phone"]["bindings"]:
                    if rule["kind"] == "foreground" and ntpath.basename(rule["exe"]).casefold() == "discord.exe":
                        rule["kind"] = "running"
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError):
            logging.exception("Could not read %s", self.path)

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            file = QSaveFile(str(self.path))
            if not file.open(QIODevice.OpenModeFlag.WriteOnly):
                raise OSError(file.errorString())
            payload = json.dumps(self.data, ensure_ascii=False, indent=2).encode("utf-8")
            if file.write(payload) != len(payload):
                file.cancelWriting()
                raise OSError(file.errorString())
            if not file.commit():
                raise OSError(file.errorString())
        except OSError:
            logging.exception("Could not save %s", self.path)

    def activity_snapshot(self):
        return deepcopy(self.data["activities"])


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
