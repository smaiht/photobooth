import re
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class _MarkupInventory(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        element_id = attributes.get("id")
        if element_id:
            self.ids.add(element_id)
        if tag == "script" and attributes.get("src"):
            self.scripts.append(attributes["src"])


class FrontendStaticContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "frontend" / "index.html").read_text(
            encoding="utf-8")
        cls.app_source = (ROOT / "frontend" / "app.js").read_text(
            encoding="utf-8")
        cls.markup = _MarkupInventory()
        cls.markup.feed(cls.html)

    def test_every_static_app_element_id_exists_in_markup(self):
        referenced_ids = set(re.findall(
            r'document\.getElementById\(\s*["\']([^"\']+)["\']\s*\)',
            self.app_source,
        ))
        self.assertTrue(referenced_ids)
        self.assertEqual(referenced_ids - self.markup.ids, set())

    def test_core_loads_before_scripts_that_use_it(self):
        core_index = self.markup.scripts.index("core.js")
        self.assertLess(
            core_index,
            self.markup.scripts.index("../assets/dev/preview.js"),
        )
        self.assertLess(core_index, self.markup.scripts.index("app.js"))

    def test_preview_assets_exist(self):
        assets = ROOT / "assets" / "dev"
        expected = {
            "live-view.svg",
            "template-grid.svg",
            "template-strips.svg",
        }
        expected.update(
            f"photo-{index}-{variant}.svg"
            for index in range(1, 5)
            for variant in ("framed", "unframed")
        )
        missing = sorted(name for name in expected if not (assets / name).is_file())
        self.assertEqual(missing, [])


class FrontendNodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if cls.node is None:
            raise RuntimeError("Node.js is required for frontend tests")

    def run_node(self, *arguments):
        completed = subprocess.run(
            [self.node, *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_javascript_syntax(self):
        for relative_path in (
            "frontend/core.js",
            "frontend/app.js",
            "assets/dev/preview.js",
        ):
            with self.subTest(script=relative_path):
                self.run_node("--check", relative_path)

    def test_frontend_core_behavior(self):
        self.run_node("--test", "tests/js/frontend_core.test.js")


if __name__ == "__main__":
    unittest.main()
