import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _application_text_files() -> list[Path]:
    files = {
        ROOT / "app.py",
        ROOT / "config_app.json",
        ROOT / "config_camera.json",
    }
    files.update(ROOT.glob("*.bat"))
    files.update(ROOT.glob("*.ps1"))
    for directory, patterns in (
        (ROOT / "backend", ("*.py",)),
        (ROOT / "assets", ("*.js", "*.md")),
        (ROOT / "frontend", ("*.js", "*.html", "*.css")),
        (ROOT / "templates", ("*.py", "*.json", "*.md")),
        (ROOT / "diagnostics", ("*.py",)),
        (ROOT / ".github", ("*.py", "*.yml", "*.yaml")),
    ):
        for pattern in patterns:
            files.update(directory.rglob(pattern))
    return sorted(path for path in files if path.is_file())


def _literal_mode(call: ast.Call) -> str | None:
    mode_node = call.args[1] if len(call.args) > 1 else None
    for keyword in call.keywords:
        if keyword.arg == "mode":
            mode_node = keyword.value
            break
    if mode_node is None:
        return "r"
    if isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str):
        return mode_node.value
    return None


def _has_keyword(call: ast.Call, name: str) -> bool:
    return any(keyword.arg == name for keyword in call.keywords)


class _TextIoVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: list[tuple[int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:
        function = node.func
        is_builtin_open = isinstance(function, ast.Name) and function.id == "open"
        is_os_fdopen = (
            isinstance(function, ast.Attribute)
            and function.attr == "fdopen"
            and isinstance(function.value, ast.Name)
            and function.value.id == "os"
        )
        if is_builtin_open or is_os_fdopen:
            mode = _literal_mode(node)
            if (mode is None or "b" not in mode) and not _has_keyword(
                    node, "encoding"):
                self.violations.append((node.lineno, "text open without encoding"))

        if (
            isinstance(function, ast.Attribute)
            and function.attr in {"read_text", "write_text"}
            and not _has_keyword(node, "encoding")
        ):
            self.violations.append(
                (node.lineno, f"{function.attr} without encoding"))

        if (
            isinstance(function, ast.Attribute)
            and function.attr in {"encode", "decode"}
            and not node.args
            and not _has_keyword(node, "encoding")
        ):
            self.violations.append(
                (node.lineno, f"{function.attr} without encoding"))

        is_text_subprocess = (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id == "subprocess"
            and function.attr in {"run", "Popen", "check_output"}
            and any(
                keyword.arg in {"text", "universal_newlines"}
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in node.keywords
            )
        )
        if is_text_subprocess:
            for keyword_name in ("encoding", "errors"):
                if not _has_keyword(node, keyword_name):
                    self.violations.append((
                        node.lineno,
                        f"text subprocess without {keyword_name}",
                    ))
        self.generic_visit(node)


class EncodingBoundaryTests(unittest.TestCase):
    def test_application_owned_text_files_are_valid_utf8(self):
        invalid = []
        for path in _application_text_files():
            try:
                path.read_bytes().decode("utf-8")
            except UnicodeDecodeError as exc:
                invalid.append(f"{path.relative_to(ROOT)}: {exc}")
        self.assertEqual(invalid, [])

    def test_production_python_text_io_has_an_explicit_encoding(self):
        violations = []
        for path in _application_text_files():
            if path.suffix != ".py":
                continue
            visitor = _TextIoVisitor()
            visitor.visit(ast.parse(path.read_bytes(), filename=str(path)))
            violations.extend(
                f"{path.relative_to(ROOT)}:{line}: {message}"
                for line, message in visitor.violations
            )
        self.assertEqual(violations, [])

    def test_production_files_do_not_contain_common_utf8_mojibake(self):
        # Latin characters U+00C2/U+00C3/U+00D0/U+00D1 commonly appear when
        # UTF-8 bytes were decoded as a Windows single-byte code page.
        suspicious = tuple(chr(codepoint) for codepoint in (
            0x00C2, 0x00C3, 0x00D0, 0x00D1, 0xFFFD,
        ))
        violations = []
        for path in _application_text_files():
            text = path.read_bytes().decode("utf-8")
            if any(character in text for character in suspicious):
                violations.append(str(path.relative_to(ROOT)))
        self.assertEqual(violations, [])

    def test_windows_powershell_reads_and_writes_known_text_encodings(self):
        strips = (ROOT / "_setup_strips_printer.bat").read_text(
            encoding="utf-8")
        embedded_python = (ROOT / "_ensure_python.bat").read_text(
            encoding="utf-8")

        self.assertIn("Get-Content -Raw -Encoding UTF8", strips)
        self.assertIn("Get-Content -Encoding Ascii", embedded_python)
        self.assertIn("Set-Content -Encoding Ascii", embedded_python)

    def test_both_html_entry_points_declare_utf8(self):
        loading_source = (ROOT / "app.py").read_text(encoding="utf-8")
        frontend = (ROOT / "frontend" / "index.html").read_text(
            encoding="utf-8")

        self.assertIn('<meta charset="UTF-8">', loading_source)
        self.assertIn('<meta charset="UTF-8">', frontend)


if __name__ == "__main__":
    unittest.main()
