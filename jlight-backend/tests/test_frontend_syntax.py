"""Syntax-check inline JavaScript in the main JLIGHT frontend using Node.js."""
from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class InlineScriptParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.scripts = []
        self._active = False
        self._external = False
        self._parts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "script":
            self._active = True
            self._external = any(k.lower() == "src" for k, _ in attrs)
            self._parts = []

    def handle_data(self, data):
        if self._active and not self._external:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "script" and self._active:
            if not self._external and "".join(self._parts).strip():
                self.scripts.append("".join(self._parts))
            self._active = False
            self._external = False
            self._parts = []


class FrontendSyntaxTests(unittest.TestCase):
    def test_inline_scripts_parse(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is not installed")
        parser = InlineScriptParser()
        parser.feed((ROOT / "index.html").read_text(encoding="utf-8"))
        self.assertTrue(parser.scripts, "No inline JavaScript was found")
        for index, script in enumerate(parser.scripts):
            with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8") as handle:
                handle.write(script)
                handle.flush()
                result = subprocess.run([node, "--check", handle.name], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f"Inline script {index + 1} has a syntax error:\n{result.stderr}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
