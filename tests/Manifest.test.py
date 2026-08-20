from __future__ import annotations

import json
import re
import stat
import struct
import unittest
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar, cast

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "manifest.json"


class ManifestTests(unittest.TestCase):
    manifest: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_required_manifest_contract(self) -> None:
        manifest = self.manifest
        self.assertIs(type(manifest.get("schemaVersion")), int)
        self.assertEqual(manifest["schemaVersion"], 1)
        for key in ("id", "name", "version", "author", "license", "description"):
            self.assertIsInstance(manifest.get(key), str, key)
            self.assertTrue(manifest[key].strip(), key)
        self.assertRegex(manifest["id"], r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
        self.assertNotIn("..", manifest["id"])
        self.assertFalse(manifest["id"].startswith("omarchy."))
        self.assertRegex(manifest["version"], r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")
        self.assertEqual(manifest["license"], "MIT")
        self.assertTrue((ROOT / "LICENSE").is_file())

    def test_kinds_and_entry_points_are_complete_and_safe(self) -> None:
        manifest = self.manifest
        kinds = cast(list[Any], manifest.get("kinds"))
        self.assertIsInstance(kinds, list)
        self.assertTrue(kinds)
        self.assertEqual(len(kinds), len(set(kinds)))
        required = {
            "bar": "bar",
            "bar-widget": "barWidget",
            "menu": "menu",
            "overlay": "overlay",
            "panel": "panel",
            "service": "service",
        }
        entry_points = cast(dict[str, Any], manifest.get("entryPoints"))
        self.assertIsInstance(entry_points, dict)
        for kind in kinds:
            if kind in required:
                self.assertIn(required[kind], entry_points)
        for name, value in entry_points.items():
            self.assertIsInstance(value, str, name)
            path = PurePosixPath(value)
            self.assertFalse(path.is_absolute(), value)
            self.assertNotIn("..", path.parts, value)
            resolved = (ROOT / value).resolve()
            self.assertTrue(resolved.is_relative_to(ROOT.resolve()), value)
            self.assertTrue(resolved.is_file(), value)
            self.assertFalse((ROOT / value).is_symlink(), value)
        self.assertIn(self.manifest["barWidget"]["defaultSection"], {"left", "center", "right"})

    def test_settings_defaults_and_schema_cannot_drift(self) -> None:
        widget = self.manifest["barWidget"]
        defaults = widget["defaults"]
        schema = widget["schema"]
        self.assertIsInstance(defaults, dict)
        self.assertIsInstance(schema, list)
        rows = {row["key"]: row for row in schema}
        self.assertEqual(len(rows), len(schema), "setting keys must be unique")
        self.assertEqual(set(defaults), set(rows))
        for key, default in defaults.items():
            row = rows[key]
            self.assertIn(row["type"], {"boolean", "enum", "integer", "string"}, key)
            self.assertTrue(str(row.get("label") or "").strip(), key)
            self.assertTrue(str(row.get("description") or "").strip(), key)
            schema_default = row.get("defaultValue")
            if row["type"] == "enum":
                options = row.get("options")
                self.assertIsInstance(options, list, key)
                self.assertGreaterEqual(len(options), 2, key)
                normalized = {str(option).casefold() for option in options}
                self.assertIn(str(default).casefold(), normalized, key)
                self.assertIn(str(schema_default).casefold(), normalized, key)
                self.assertEqual(str(default).casefold(), str(schema_default).casefold(), key)
            else:
                self.assertEqual(default, schema_default, key)
            if row["type"] == "integer":
                self.assertIs(type(default), int, key)
                self.assertLessEqual(row["min"], default, key)
                self.assertLessEqual(default, row["max"], key)
                self.assertGreater(row["step"], 0, key)

    def test_release_metadata_and_assets_match(self) -> None:
        version = self.manifest["version"]
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        headings = re.findall(r"^## ([^ ]+) - \d{4}-\d{2}-\d{2}$", changelog, re.MULTILINE)
        self.assertTrue(headings)
        self.assertEqual(headings[0], version)
        for relative, minimum_width, minimum_height in (
            ("preview.png", 1200, 750),
            ("docs/images/panel-vault.png", 480, 480),
            ("docs/images/panel-search.png", 480, 240),
            ("docs/images/panel-settings.png", 480, 480),
            ("docs/images/onboarding.png", 1200, 400),
        ):
            with (ROOT / relative).open("rb") as stream:
                self.assertEqual(stream.read(8), b"\x89PNG\r\n\x1a\n", relative)
                length = struct.unpack(">I", stream.read(4))[0]
                self.assertEqual(stream.read(4), b"IHDR", relative)
                width, height = struct.unpack(">II", stream.read(min(length, 8)))
            self.assertGreaterEqual(width, minimum_width, relative)
            self.assertGreaterEqual(height, minimum_height, relative)

    def test_release_tree_has_no_symlinks_or_unsafe_executables(self) -> None:
        symlinks = [path for path in ROOT.rglob("*") if ".git" not in path.parts and path.is_symlink()]
        self.assertEqual(symlinks, [])
        helper_mode = (ROOT / "omawarden-agent.py").stat().st_mode
        self.assertTrue(helper_mode & stat.S_IXUSR)
        for path in ROOT.rglob("*"):
            if not path.is_file() or ".git" in path.parts:
                continue
            mode = path.stat().st_mode
            self.assertFalse(mode & (stat.S_IWGRP | stat.S_IWOTH), str(path.relative_to(ROOT)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
