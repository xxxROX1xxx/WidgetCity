from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from widgetcity.city import BOX_TRIP, TRAIN_TRAVEL, Layout, Renderer, Scenes, StationDelivery
from widgetcity.windows import DownloadWatch


class StationTest(TestCase):
    def test_one_scan_reports_each_completed_file(self):
        with TemporaryDirectory() as path:
            folder = Path(path)
            (folder / "existing.zip").write_bytes(b"existing")
            for name in ("one.zip", "two.zip"):
                (folder / (name + ".crdownload")).write_bytes(b"data")
            watch = DownloadWatch()
            self.assertEqual(watch.scan(folder, 1), set())
            for name in ("one.zip", "two.zip"):
                (folder / (name + ".crdownload")).rename(folder / name)
            self.assertEqual(watch.scan(folder, 4), set())
            self.assertEqual(watch.scan(folder, 7), {"one.zip", "two.zip"})
            self.assertEqual(watch.scan(folder, 10), set())

    def test_new_boxes_extend_the_same_stop(self):
        scenes = Scenes()
        scenes.deliver(100, 2)
        first = scenes.delivery
        first_departure = first.departure
        scenes.deliver(104, 1)
        self.assertIs(scenes.delivery, first)
        self.assertEqual(first.arrival, 100)
        self.assertAlmostEqual(first.departure, first_departure + BOX_TRIP)
        self.assertAlmostEqual(first.loading_end - first.loading_start, 3 * BOX_TRIP)
        renderer = Renderer(Layout(48217, "medium"))
        for trip in range(3):
            when = first.loading_start + trip * BOX_TRIP
            carrying = {prop.art for prop in renderer.actors(scenes, when + .2)}
            returning = {prop.art for prop in renderer.actors(scenes, when + BOX_TRIP * .8)}
            self.assertIn("crate", carrying)
            self.assertNotIn("crate", returning)
            self.assertIn("engine", carrying)

    def test_box_added_during_departure_does_not_turn_the_train_around(self):
        delivery = StationDelivery.start(100, 1)
        departure = delivery.departure
        delivery.add(departure + .1, 3)
        self.assertEqual(delivery.departure, departure)
        self.assertTrue(delivery.active(departure + TRAIN_TRAVEL))
        self.assertFalse(delivery.active(delivery.loading_end))

    def test_disabling_station_clears_the_queue(self):
        scenes = Scenes()
        scenes.configure({"station": {"enabled": True}})
        scenes.update_triggers({}, {"station": 2})
        self.assertIsNotNone(scenes.delivery)
        scenes.configure({"station": {"enabled": False}})
        scenes.update_triggers({}, {"station": 1})
        self.assertIsNone(scenes.delivery)
