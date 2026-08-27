import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from backend import custom_templates
from backend.config import template_pack_dir


class CustomTemplatePackTests(unittest.TestCase):
    @staticmethod
    def _png() -> bytes:
        output = io.BytesIO()
        Image.new("RGB", (10, 10), "white").save(output, format="PNG")
        return output.getvalue()

    @staticmethod
    def _config(background: str = "bg.png") -> bytes:
        return json.dumps({
            "print_size": [10, 10],
            "templates": {
                "grid": {
                    "photo_size_px": {"width": 10, "height": 10},
                    "preview_rotation": "none",
                    "preview_split": "none",
                    "print_layout": {
                        "background": background,
                        "photos": [{
                            "photo_index": 0,
                            "x": 0,
                            "y": 0,
                            "rotate": "none",
                        }],
                    },
                },
            },
        }).encode()

    @staticmethod
    def _snapshot(files: dict[str, bytes]) -> dict[str, dict]:
        return {
            name: {
                "size": len(payload),
                "md5": hashlib.md5(payload).hexdigest(),
                "remote_path": f"/remote/demo/{name}",
            }
            for name, payload in files.items()
        }

    def test_custom_pack_overrides_system_and_invalid_update_keeps_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            system_root = root / "templates"
            custom_root = root / "templates_custom"
            stage_root = custom_root / ".sync"
            (system_root / "demo").mkdir(parents=True)
            (system_root / "demo" / "config.json").write_text(
                '{"templates":{"system":{}}}', encoding="utf-8")
            custom_root.mkdir()
            stage_root.mkdir()

            files = {"config.json": self._config(), "bg.png": self._png()}

            def download(metadata, destination, _token):
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(files[Path(metadata["remote_path"]).name])

            with patch.object(custom_templates, "_download_file", download):
                changed = custom_templates._sync_pack(
                    "demo", self._snapshot(files), custom_root, stage_root,
                    "token", 4, "grid",
                )
            self.assertTrue(changed)
            self.assertEqual(
                template_pack_dir("demo", system_root, custom_root),
                custom_root / "demo",
            )
            installed = (custom_root / "demo" / "config.json").read_bytes()

            files["config.json"] = self._config("missing.png")
            with patch.object(custom_templates, "_download_file", download):
                with self.assertRaisesRegex(ValueError, "missing or unsafe"):
                    custom_templates._sync_pack(
                        "demo", self._snapshot(files), custom_root, stage_root,
                        "token", 4, "grid",
                    )
            self.assertEqual(
                (custom_root / "demo" / "config.json").read_bytes(),
                installed,
            )


if __name__ == "__main__":
    unittest.main()
