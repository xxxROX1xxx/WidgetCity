import asyncio
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import AsyncMock, Mock, PropertyMock, patch

from PySide6.QtCore import QCoreApplication, QMimeData, QObject, Signal

from widgetcity.catalog import BUILDINGS, TREES
from widgetcity.city import BOX_TRIP, SHOP_TRAVEL, Layout, Renderer, Scenes, material_sprite, sprite
from widgetcity.config import Config, defaults, game_exe, save_json
from widgetcity.integrations import Integrations, read_json, read_notifications
from widgetcity.steam import SteamTransfer, content_activity, download_details


class LayoutEditingTest(TestCase):
    def test_default_mail_sources_and_removal_survive_reload(self):
        with TemporaryDirectory() as root, patch("widgetcity.config.QStandardPaths.writableLocation", return_value=root):
            config = Config()
            sources = config.data["integrations"]["mail_sources"]
            self.assertEqual(sources, ["Telegram", "Discord"])
            sources.clear()
            config.save()
            self.assertEqual(Config().data["integrations"]["mail_sources"], [])

    def test_upgrade_adds_defaults_only_to_an_empty_v3_list(self):
        with TemporaryDirectory() as root, patch("widgetcity.config.QStandardPaths.writableLocation", return_value=root):
            path = Path(root) / "settings.json"
            for previous, expected in (([], ["Telegram", "Discord"]), (["Outlook"], ["Outlook"])):
                save_json(path, {"version": 3, "integrations": {"mail_sources": previous}})
                self.assertEqual(Config().data["integrations"]["mail_sources"], expected)

    def test_tree_selection_preserves_plan_and_new_landmarks(self):
        for size in ("small", "medium", "large"):
            for seed in (0, 12, 48217, 999999):
                original = Layout(seed, size)
                self.assertTrue(set(BUILDINGS) <= original.landmarks.keys())
                self.assertEqual(len(set(original.landmarks.values())), len(original.landmarks))
                pine = Layout(seed, size, ["pine"])
                self.assertEqual(pine.props, Layout(seed, size, ["pine"]).props)
                self.assertEqual(pine.tiles, original.tiles)
                self.assertEqual(pine.landmarks, original.landmarks)
                self.assertEqual(pine.fixed_props, original.fixed_props)
                trees = {name for _, name in TREES.values()}
                without_sakura = Layout(seed, size, TREES.keys() - {"sakura"})
                variants = {(p.u, p.v): p.art for p in without_sakura.props if p.art in trees}
                for prop in original.props:
                    if prop.art in trees and prop.art != TREES["sakura"][1]:
                        self.assertEqual(variants[prop.u, prop.v], prop.art)
                for prop in pine.props:
                    if prop not in pine.fixed_props:
                        self.assertEqual(prop.art, TREES["pine"][1])
                pine.set_trees([])
                self.assertEqual(set(pine.props), set(original.fixed_props))

    def test_color_masks_leave_other_parts_and_lights_untouched(self):
        for name in BUILDINGS:
            base = sprite(name)
            colored = material_sprite(name, "", "#8a5290")
            mask = sprite(name + "_roof")
            differences = [(x, y) for y in range(base.height()) for x in range(base.width())
                           if colored.pixel(x, y) != base.pixel(x, y)]
            self.assertGreater(len(differences), 10)
            self.assertTrue(all(mask.pixelColor(x, y).alpha() for x, y in differences))
            self.assertTrue(all(colored.pixelColor(x, y).alpha() == base.pixelColor(x, y).alpha()
                                for x, y in differences))

    def test_saved_colors_and_empty_tree_catalog_reload(self):
        with TemporaryDirectory() as root, patch("widgetcity.config.QStandardPaths.writableLocation", return_value=root):
            config = Config()
            config.data["appearance"] = {"colors": {"cafe": {"roof": "#923cad"}}, "trees": []}
            config.data["seed"] = 243
            config.save()
            restored = Config()
            self.assertEqual(restored.data["appearance"], config.data["appearance"])
            self.assertEqual(restored.data["seed"], 243)


class Clipboard(QObject):
    dataChanged = Signal()

    def __init__(self):
        super().__init__()
        self.content = QMimeData()

    def mimeData(self):
        return self.content

    def setText(self, text):
        self.content = QMimeData()
        self.content.setText(text)
        self.dataChanged.emit()


class IntegrationTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        root = TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.config = Config()
        self.config.path = Path(root.name) / "settings.json"
        self.config.data = defaults()
        self.clipboard = Clipboard()
        with patch.object(Integrations, "tick"):
            self.services = Integrations(self.config, self.clipboard)
        self.addCleanup(self.services.close)

    def test_notifications_filter_storage_and_mark_seen(self):
        prefs = self.config.data["integrations"]
        prefs["mail_sources"] = ["First"]
        item = {"id": "test-first", "app": "First", "time": 20., "key": "1", "text": "hello", "seen": False}
        other = dict(item, id="test-second", app="Second", key="2")
        self.services.merge_mail("allowed", {}, [item, other])
        self.assertEqual(read_json(self.services.mail_file, []), [item])
        self.services.mark_mail_seen()
        self.assertTrue(read_json(self.services.mail_file, [])[0]["seen"])
        prefs["mail_sources"] = []
        self.services.prune_mail()
        self.assertEqual(read_json(self.services.mail_file, []), [])

    def test_default_sources_match_windows_names_and_ids(self):
        telegram = {"id": "Telegram.TelegramDesktop", "app": "Telegram Desktop",
                    "time": 20., "key": "1", "text": "hello", "seen": False}
        discord = dict(telegram, id="com.squirrel.Discord.Discord", app="Discord", key="2")
        other = dict(telegram, id="spare", app="Telegram Backup", key="3")
        self.services.merge_mail("allowed", {}, [telegram, discord, other])
        self.assertEqual(self.services.mail_entries, [telegram, discord])
        self.config.data["integrations"]["mail_sources"].remove("Telegram")
        self.services.prune_mail()
        self.assertEqual(self.services.mail_entries, [discord])

    def test_mail_keeps_selected_windows_toasts_with_incomplete_metadata(self):
        stamp = datetime(2026, 11, 24, tzinfo=timezone.utc)
        telegram = SimpleNamespace(
            app_info=SimpleNamespace(
                app_user_model_id="TelegramMessengerLLP.TelegramDesktop_t4vj0pshhgkwm!Telegram.TelegramDesktop.Store",
            ),
            id=1, creation_time=stamp,
            notification=SimpleNamespace(visual=SimpleNamespace(
                get_binding=lambda _: None,
                bindings=[SimpleNamespace(get_text_elements=lambda: [SimpleNamespace(text="Тест")])],
            )),
        )
        discord = Mock(id=2, creation_time=stamp, app_info=SimpleNamespace(
            app_user_model_id="com.squirrel.DiscordPTB.DiscordPTB",
            display_info=SimpleNamespace(display_name="Discord PTB"),
        ))
        type(discord).notification = PropertyMock(side_effect=OSError)
        unrelated = Mock(app_info=SimpleNamespace(app_user_model_id="other", display_info=None))
        unrelated_content = PropertyMock(side_effect=AssertionError("Unselected notification was read"))
        type(unrelated).notification = unrelated_content
        listener = SimpleNamespace(current=SimpleNamespace(
            get_access_status=lambda: SimpleNamespace(name="ALLOWED"),
            get_notifications_async=AsyncMock(return_value=[telegram, discord, unrelated]),
        ))
        with patch("winrt.windows.ui.notifications.management.UserNotificationListener", listener):
            self.services.merge_mail(*asyncio.run(read_notifications(("Telegram", "Discord"))))
        unrelated_content.assert_not_called()
        self.assertEqual([entry["text"] for entry in self.services.mail_entries], ["Тест", ""])
        self.assertEqual(len(read_json(self.services.mail_file, [])), 2)

    def test_clipboard_requires_opt_in_and_pins_are_separate(self):
        self.clipboard.setText("before consent")
        self.assertEqual(self.services.recent, [])
        prefs = self.config.data["integrations"]
        prefs["clipboard_enabled"] = True
        prefs["clipboard_limit"] = 5
        for index in range(8):
            self.clipboard.setText(f"Note {index}")
        self.assertEqual(len(self.services.recent), 5)
        text = self.services.recent[0]
        self.services.pin(text)
        self.services.clear_history()
        self.assertEqual(self.services.recent, [])
        self.assertEqual(read_json(self.services.notes_file, []), [text])
        self.services.copy(text)
        self.assertEqual(self.services.recent, [])
        self.clipboard.content.setData(
            'application/x-qt-windows-mime;value="CanIncludeInClipboardHistory"', b"\0\0\0\0",
        )
        self.clipboard.dataChanged.emit()
        self.assertEqual(self.services.recent, [])
        self.config.data["activities"]["books"]["enabled"] = False
        self.clipboard.setText("Activity disabled")
        self.assertEqual(self.services.recent, [])
        self.services.delete_clip(text, True)
        self.assertEqual(read_json(self.services.notes_file, []), [])


class ShopDeliveryTest(TestCase):
    def test_van_stays_parked_for_repeated_trips_then_leaves(self):
        scenes = Scenes()
        scenes.configure({"shop": {"enabled": True}})
        renderer = Renderer(Layout(48217, "medium"))
        scenes.external = {"shop"}
        scenes.refresh_shop(100)
        delivery = scenes.shop_delivery
        parked, _ = renderer.layout.landmarks["shop"]

        for trip in range(7):
            time = delivery.loading_start + trip * BOX_TRIP
            scenes.refresh_shop(time)
            self.assertIs(scenes.shop_delivery, delivery)
            carrying = renderer.actors(scenes, time + .3)
            returning = renderer.actors(scenes, time + BOX_TRIP * .8)
            self.assertIn("crate", {prop.art for prop in carrying})
            self.assertNotIn("crate", {prop.art for prop in returning})
            self.assertEqual(next(prop.u for prop in carrying if prop.art == "van"), parked)

        scenes.external.clear()
        scenes.refresh_shop(time + .3)
        self.assertAlmostEqual(delivery.departure, time + BOX_TRIP)
        self.assertEqual([prop.art for prop in renderer.actors(scenes, delivery.departure + .3)], ["van"])
        scenes.refresh_shop(delivery.departure + SHOP_TRAVEL)
        self.assertIsNone(scenes.shop_delivery)

    def test_resuming_during_the_last_trip_keeps_the_same_van(self):
        scenes = Scenes()
        scenes.configure({"shop": {"enabled": True}})
        scenes.external = {"shop"}
        scenes.refresh_shop(100)
        delivery = scenes.shop_delivery
        scenes.external.clear()
        scenes.refresh_shop(103)
        scenes.external = {"shop"}
        scenes.refresh_shop(104)
        self.assertIs(scenes.shop_delivery, delivery)
        self.assertIsNone(delivery.departure)
        scenes.configure({"shop": {"enabled": False}})
        scenes.refresh_shop(105)
        self.assertIsNone(scenes.shop_delivery)


class SteamActivityTest(TestCase):
    def test_steam_logs_track_games_and_download_state(self):
        lines = [
            "[2026-11-23 15:38:10] AppID 730 state changed : Fully Installed,App Running,",
            "[2026-11-23 15:38:12] AppID 440 update changed : Running Update,Downloading,",
        ]
        self.assertEqual(content_activity("\n".join(lines), 0), (SteamTransfer("440", "app", "downloading"), {"730"}))
        lines.extend((
            "[2026-11-23 15:38:15] AppID 730 state changed : Fully Installed,",
            "[2026-11-23 15:38:20] AppID 440 update changed : None,",
        ))
        self.assertEqual(content_activity("\n".join(lines), 0), (None, set()))
        self.assertFalse(game_exe(r"C:\Steam\steam.exe"))
        with TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "appmanifest_440.acf").write_text(
                '"name" "Test Game"\n"BytesToDownload" "240"\n"BytesDownloaded" "60"', encoding="utf-8",
            )
            self.assertEqual(download_details("440", [path]), ("Test Game", 25))
            self.assertEqual(download_details("730", [path]), ("", None))

    def test_app_update_lines_distinguish_queued_running_and_suspended(self):
        rows = []

        def add(message):
            rows.append(f"[2026-11-23 15:38:10] AppID 730 {message}")
            return content_activity("\n".join(rows), 0)[0]

        queued = add("state changed : Update Required,Fully Installed,Update Queued, (Update delayed for 600 secs)")
        self.assertEqual(queued, SteamTransfer("730", "app", "queued"))
        active = add("App update changed : Running Update,Downloading,Staging,")
        self.assertEqual(active, SteamTransfer("730", "app", "downloading"))
        self.assertEqual(add("App update changed : Running Update,Verifying Installed,"), active)
        paused = add("update canceled : Disabled (Suspended)")
        self.assertEqual(paused, SteamTransfer("730", "app", "paused"))
        self.assertEqual(add("App update changed : Running Update,Downloading,Stopping,"), paused)
        self.assertEqual(add("App update changed : None"), paused)
        self.assertEqual(add("state changed : Update Required,Fully Installed,Update Queued, (Suspended)"), paused)
        self.assertEqual(add("App update changed : Running Update,Downloading,Staging,"), active)
        self.assertIsNone(add("update finished : download 1/1"))

    def test_workshop_update_survives_a_game_state_change(self):
        lines = [
            "[2026-11-23 15:38:10] AppID 730 Workshop update changed : Running Update,Downloading,",
            "[2026-11-23 15:38:11] AppID 730 state changed : Fully Installed,App Running,",
        ]
        self.assertEqual(content_activity("\n".join(lines), 0), (SteamTransfer("730", "workshop", "downloading"), {"730"}))

    def test_neon_fades_after_the_last_game(self):
        scenes = Scenes()
        scenes.configure({"cyber": {"enabled": True}})
        scenes.external.add("cyber")
        scenes.refresh_neon(100)
        self.assertAlmostEqual(scenes.neon(102), 1)
        scenes.external.clear()
        scenes.refresh_neon(102)
        self.assertGreater(scenes.neon(102.5), 0)
        self.assertLess(scenes.neon(102.5), 1)
        self.assertEqual(scenes.neon(104), 0)
