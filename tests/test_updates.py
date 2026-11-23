import hashlib
import io
import struct
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from urllib.error import HTTPError

from widgetcity.updates import (
    ASSET_NAME, INSTALLER, LATEST, REPLACEMENT, Release, UpdateError, apply_install,
    latest_release, parse_release, prepare_update,
)


def executable():
    image = bytearray(256)
    image[:2] = b"MZ"
    struct.pack_into("<I", image, 60, 64)
    struct.pack_into("<4sH16xH", image, 64, b"PE\0\0", 0x8664, 2)
    return bytes(image)


class UpdateTest(TestCase):
    def test_selects_only_windows_asset_on_newer_release(self):
        data = {
            "tag_name": "v1.10.0",
            "assets": [{"name": "other.exe", "size": 100}, {"name": ASSET_NAME, "size": 256}],
        }
        release = parse_release(data, "1.9.0")
        self.assertTrue(release.url.endswith("/download/v1.10.0/WidgetCity.exe"))
        self.assertIsNone(parse_release(data, "1.10.0"))
        self.assertIsNone(parse_release(data, "1.11.0"))
        data["assets"].pop()
        with self.assertRaisesRegex(UpdateError, ASSET_NAME):
            parse_release(data, "1.9.0")

    def test_repo_without_published_release(self):
        error = HTTPError(LATEST, 404, "Not Found", {}, None)
        with patch("widgetcity.updates.github_request", side_effect=error):
            with self.assertRaisesRegex(UpdateError, "опубликованной версии"):
                latest_release()

    def test_stages_verified_binary_and_preserves_current_executable(self):
        new = executable()
        release = Release("v1.0.1", "asset", len(new), hashlib.sha256(new).hexdigest())
        with TemporaryDirectory() as folder:
            target = Path(folder) / ASSET_NAME
            target.write_bytes(b"old-app")
            progress = []
            with patch("widgetcity.updates.github_request", return_value=io.BytesIO(new)):
                staged = prepare_update(release, target, progress.append, lambda: False)
            self.assertEqual(target.read_bytes(), b"old-app")
            self.assertEqual((staged.directory / INSTALLER).read_bytes(), b"old-app")
            self.assertEqual((staged.directory / REPLACEMENT).read_bytes(), new)
            self.assertEqual(progress[-1], 100)

    def test_checksum_mismatch_clears_stage(self):
        new = executable()
        release = Release("v1.0.1", "asset", len(new), "0" * 64)
        with TemporaryDirectory() as folder:
            target = Path(folder) / ASSET_NAME
            target.write_bytes(b"old-app")
            with patch("widgetcity.updates.github_request", return_value=io.BytesIO(new)):
                with self.assertRaises(UpdateError):
                    prepare_update(release, target, lambda _percent: None, lambda: False)
            self.assertEqual(list(Path(folder).iterdir()), [target])
            self.assertEqual(target.read_bytes(), b"old-app")

    def test_restores_previous_build_when_new_executable_cannot_start(self):
        new = executable()
        with TemporaryDirectory() as folder:
            target = Path(folder) / ASSET_NAME
            target.write_bytes(b"old-app")
            stage = Path(folder) / "stage"
            stage.mkdir()
            (stage / INSTALLER).write_bytes(b"old-app")
            (stage / REPLACEMENT).write_bytes(new)
            with patch("widgetcity.updates.wait_for_exit"), patch(
                "widgetcity.updates.launch", side_effect=[OSError("failed to start"), None]
            ) as start:
                with self.assertRaises(OSError):
                    apply_install(target, stage, 123, hashlib.sha256(new).hexdigest())
            self.assertEqual(target.read_bytes(), b"old-app")
            self.assertEqual(start.call_count, 2)
