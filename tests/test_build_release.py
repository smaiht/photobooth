import importlib.util
import hashlib
import os
import sys
import unittest
import urllib.parse
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / ".github" / "scripts" / "build_release.py"
SPEC = importlib.util.spec_from_file_location("build_release", SCRIPT_PATH)
build_release = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = build_release
SPEC.loader.exec_module(build_release)

PUBLISH_SCRIPT_PATH = ROOT / ".github" / "scripts" / "publish_release.py"
PUBLISH_SPEC = importlib.util.spec_from_file_location(
    "publish_release", PUBLISH_SCRIPT_PATH,
)
publish_release = importlib.util.module_from_spec(PUBLISH_SPEC)
sys.modules[PUBLISH_SPEC.name] = publish_release
PUBLISH_SPEC.loader.exec_module(publish_release)


class DeterministicReleaseTests(unittest.TestCase):
    def test_folder_sha_ignores_source_timestamps(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            stage = root / "stage"
            stage.mkdir()
            (stage / "app.py").write_text("print('same')\n", encoding="utf-8")
            nested = stage / "frontend" / "style.css"
            nested.parent.mkdir()
            nested.write_text("body { color: red; }\n", encoding="utf-8")

            first = build_release.folder_sha256(stage)

            for index, path in enumerate(sorted(stage.rglob("*"))):
                timestamp = 1_700_000_000 + index * 86_400
                os.utime(path, (timestamp, timestamp))
            second = build_release.folder_sha256(stage)

            self.assertEqual(first, second)

    def test_folder_archives_reconstruct_full_release(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            stage = root / "stage"
            output = root / "dist"
            files = {
                "app.py": b"app",
                "backend/main.py": b"backend",
                "assets/dots.svg": b"asset",
                "python/python.exe": b"python",
                "bin/ffmpeg.exe": b"ffmpeg",
                "templates/default/config.json": b"{}",
                "EDSDK_Win/EDSDK_64/Dll/EDSDK.dll": b"edsdk",
                "drivers/printer.zip": b"driver",
            }
            for name, payload in files.items():
                path = stage / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)

            metadata = build_release.build_archives(stage, output)

            self.assertEqual(
                set(metadata),
                {
                    "full", "app", "assets", "python", "bin", "templates",
                    "edsdk", "drivers",
                },
            )
            combined = {}
            for component in (
                "app", "assets", "python", "bin", "templates", "edsdk", "drivers",
            ):
                with zipfile.ZipFile(output / metadata[component]["file"]) as archive:
                    for name in archive.namelist():
                        self.assertNotIn(name, combined)
                        combined[name] = archive.read(name)
            with zipfile.ZipFile(output / metadata["full"]["file"]) as archive:
                full = {name: archive.read(name) for name in archive.namelist()}
            self.assertEqual(combined, full)
            self.assertIn("app.py", full)
            self.assertIn("assets/dots.svg", full)
            self.assertIn("python/python.exe", full)
            with zipfile.ZipFile(output / metadata["app"]["file"]) as archive:
                self.assertNotIn("assets/dots.svg", archive.namelist())
            with zipfile.ZipFile(output / metadata["assets"]["file"]) as archive:
                self.assertIn("assets/dots.svg", archive.namelist())
            saved = (output / "release-metadata.json").read_text(encoding="utf-8")
            self.assertIn(metadata["python"]["sha256"], saved)

            artifacts = publish_release.load_artifacts(
                output, output / "release-metadata.json",
            )
            full_path = output / build_release.ARCHIVE_NAMES["full"]
            self.assertEqual(
                metadata["full"]["sha256"],
                hashlib.sha256(full_path.read_bytes()).hexdigest(),
            )
            self.assertEqual(metadata["full"]["hash_type"], "zip")
            self.assertTrue(all(
                metadata[name]["hash_type"] == "folder"
                for name in metadata if name != "full"
            ))
            self.assertEqual(
                artifacts["full"]["sha256"], metadata["full"]["sha256"],
            )
            self.assertEqual(
                artifacts["python"]["sha256"],
                metadata["python"]["sha256"],
            )

    def test_reuses_remote_component_with_the_same_folder_sha(self):
        artifact = {
            "name": "python",
            "sha256": "a" * 64,
            "hash_type": "folder",
        }
        previous = {
            "artifacts": {
                "python": {
                    "path": "/updates/artifacts/python.zip",
                    "size": 123,
                    "sha256": "a" * 64,
                    "updated_at": "earlier",
                },
            },
        }

        record = publish_release.reusable_record(
            previous, artifact, "/updates/artifacts/python.zip",
        )

        self.assertEqual(record["path"], previous["artifacts"]["python"]["path"])
        self.assertEqual(record["sha256"], "a" * 64)
        self.assertEqual(record["hash_type"], "folder")
        record["size"] = 999
        self.assertEqual(previous["artifacts"]["python"]["size"], 123)

    def test_does_not_reuse_old_hashed_artifact_path(self):
        artifact = {
            "name": "python",
            "sha256": "a" * 64,
            "hash_type": "folder",
        }
        previous = {
            "artifacts": {
                "python": {
                    "path": "/updates/artifacts/python-aaaaaaaaaaaaaaaa.zip",
                    "size": 123,
                    "sha256": "a" * 64,
                },
            },
        }

        self.assertIsNone(publish_release.reusable_record(
            previous, artifact, "/updates/artifacts/python.zip",
        ))

    def test_remote_import_url_is_cache_busted_for_every_attempt(self):
        sha256 = "a" * 64
        first = publish_release.release_asset_source_url(
            "https://github.test/releases/download/latest",
            "photobooth-win.zip",
            sha256,
            "publish-123",
            1,
        )
        second = publish_release.release_asset_source_url(
            "https://github.test/releases/download/latest",
            "photobooth-win.zip",
            sha256,
            "publish-123",
            2,
        )

        self.assertNotEqual(first, second)
        first_url = urllib.parse.urlsplit(first)
        first_query = urllib.parse.parse_qs(first_url.query)
        second_query = urllib.parse.parse_qs(
            urllib.parse.urlsplit(second).query,
        )
        self.assertEqual(
            first_url.path,
            "/releases/download/latest/photobooth-win.zip",
        )
        self.assertEqual(first_query["photobooth_sha256"], [sha256])
        self.assertEqual(first_query["publish_nonce"], ["publish-123"])
        self.assertEqual(first_query["attempt"], ["1"])
        self.assertEqual(second_query["attempt"], ["2"])

    def test_github_upload_order_matches_yandex_import_order(self):
        workflow = (ROOT / ".github" / "workflows" / "build.yml").read_text(
            encoding="utf-8",
        )
        filenames = list(publish_release.ARTIFACT_FILES.values())
        positions = [
            workflow.index(f"dist/{filename}")
            for filename in filenames
        ]

        self.assertEqual(positions, sorted(positions))
        self.assertIn("preserve_order: true", workflow)
        self.assertIn("Start-Sleep -Seconds 1", workflow)
        self.assertNotIn("files: dist/*.zip", workflow)


if __name__ == "__main__":
    unittest.main()
