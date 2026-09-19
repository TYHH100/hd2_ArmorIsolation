import json
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from modular_source import _no_link, load_catalog


PATCH = "0123456789abcdef.patch_0"


class ModularSourceTests(unittest.TestCase):
    def write_manifest(self, root, options=None, **extra):
        value = {"Version": 1, "Guid": "original-guid", "Name": "source",
                 "Options": options or [], **extra}
        data = b"\xef\xbb\xbf" + json.dumps(value, indent=2).encode("utf-8") + b"\r\n"
        (root / "manifest.json").write_bytes(data)
        return data

    def add_patch(self, root, directory, data=b"main"):
        folder = root / directory
        folder.mkdir(parents=True, exist_ok=True)
        main = folder / PATCH
        main.write_bytes(data)
        main.with_name(PATCH + ".stream").write_bytes(b"")
        main.with_name(PATCH + ".gpu_resources").write_bytes(b"gpu")
        return main.relative_to(root)

    def test_options_keep_exclusive_children_and_nonrecursive_includes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = self.add_patch(root, "body")
            first = self.add_patch(root, "head/first", b"first")
            second = self.add_patch(root, "head/second", b"second")
            self.write_manifest(root, [
                {"Name": "body", "Include": ["body"]},
                {"Name": "head", "Include": ["head"], "SubOptions": [
                    {"Name": "first", "Include": ["head\\first"]},
                    {"Name": "second", "Include": ["head/second"]},
                    {"Name": "default", "Include": ["head/default"]}]}])
            catalog = load_catalog(root / "manifest.json")
            self.assertEqual(set(catalog.patch_paths), {base, first, second})
            self.assertEqual(catalog.options[1]["patch_paths"], ())
            self.assertEqual(catalog.options[1]["suboptions_mode"], "exclusive")
            self.assertEqual(catalog.patch_options[first], ("1/0",))
            self.assertEqual(catalog.patch_options[second], ("1/1",))
            self.assertEqual(catalog.missing_includes,
                             ({"option": "1/2", "include": "head/default", "path": "head/default"},))
            self.assertFalse((root / "head/default").exists())

    def test_passthrough_preserves_bytes_names_unknown_fields_and_empty_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            root.mkdir()
            main = self.add_patch(root, "body")
            (root / "nested/empty").mkdir(parents=True)
            (root / "nested/readme.bin").write_bytes(b"\x00raw\xff\r\n")
            backup = root / (".patch-backup_29_" + PATCH + ".hd2mm-backup")
            backup.write_bytes(b"original backup")
            manifest_bytes = self.write_manifest(root, [{"Name": "body", "Include": ["body"],
                                                        "FutureField": {"enabled": True}}], Extra=[1, 2])
            catalog = load_catalog(root)
            destination = Path(directory) / "output"
            catalog.copy_passthrough(destination)
            self.assertEqual((destination / "manifest.json").read_bytes(), manifest_bytes)
            self.assertEqual((destination / "nested/readme.bin").read_bytes(), b"\x00raw\xff\r\n")
            self.assertEqual((destination / backup.name).read_bytes(), b"original backup")
            self.assertTrue((destination / "nested/empty").is_dir())
            self.assertFalse((destination / main).exists())
            self.assertEqual(list((destination / "body").iterdir()), [])
            self.assertEqual(catalog.manifest["Extra"], [1, 2])
            self.assertEqual(catalog.manifest["Guid"], "original-guid")
            self.assertEqual(len(catalog.serializable_inventory()), len(catalog.files))
            with self.assertRaisesRegex(ValueError, "empty"):
                catalog.copy_passthrough(destination)
            with self.assertRaisesRegex(ValueError, "outside"):
                catalog.copy_passthrough(root / "output")

    def test_source_guard_detects_same_length_edit_and_file_or_directory_changes(self):
        for kind in ("edit", "file", "directory"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.write_manifest(root)
                payload = root / "note.txt"
                payload.write_bytes(b"aaaa")
                catalog = load_catalog(root)
                catalog.verify_unchanged()
                if kind == "edit":
                    payload.write_bytes(b"bbbb")
                elif kind == "file":
                    (root / "new.txt").write_bytes(b"")
                else:
                    (root / "empty").mkdir()
                with self.assertRaisesRegex(ValueError, "changed"):
                    catalog.verify_unchanged()

    def test_escape_and_existing_file_includes_are_rejected(self):
        for include in ("../outside", "body/../../outside", "C:\\outside", "\\\\server\\share", "/outside",
                        "body:stream", "manifest.json"):
            with self.subTest(include=include), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.write_manifest(root, [{"Name": "bad", "Include": [include]}])
                with self.assertRaises(ValueError):
                    load_catalog(root)

    def test_orphan_nonempty_lane_rejected_but_empty_lane_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_manifest(root)
            lane = root / (PATCH + ".stream")
            lane.write_bytes(b"")
            catalog = load_catalog(root)
            self.assertIn(lane.relative_to(root), catalog.passthrough_paths)
            lane.write_bytes(b"orphan")
            with self.assertRaisesRegex(ValueError, "no main patch"):
                load_catalog(root)

    def test_shared_include_tracks_all_owners_and_root_include_is_direct_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            direct = self.add_patch(root, ".")
            nested = self.add_patch(root, "nested")
            self.write_manifest(root, [{"Name": "root", "Include": [""]},
                                       {"Name": "first", "Include": ["nested"]},
                                       {"Name": "second", "Include": ["nested"]}])
            catalog = load_catalog(root)
            self.assertEqual(catalog.patch_options[direct], ("0",))
            self.assertEqual(catalog.patch_options[nested], ("1", "2"))

    def test_symbolic_links_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            root.mkdir()
            self.write_manifest(root)
            external = Path(directory) / "external"
            external.mkdir()
            try:
                (root / "linked").symlink_to(external, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"Symlink creation unavailable: {error}")
            with self.assertRaisesRegex(ValueError, "links|reparse"):
                load_catalog(root)

    def test_windows_reparse_attribute_is_rejected_without_symlink_privilege(self):
        metadata = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        with patch.object(Path, "lstat", return_value=metadata):
            with self.assertRaisesRegex(ValueError, "reparse"):
                _no_link(Path("junction"))

    def test_unreferenced_patch_remains_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            direct = self.add_patch(root, ".")
            nested = self.add_patch(root, "body")
            self.write_manifest(root, [{"Name": "body", "Include": ["body"]}])
            catalog = load_catalog(root)
            self.assertEqual(catalog.unreferenced_patch_paths, (direct,))
            self.assertEqual(catalog.patch_options[nested], ("0",))

    def test_duplicate_keys_and_wrong_version_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for data in (b'{"Version":1,"Version":1}', b'{"Version":true}', b'{"Version":2}',
                         b'{"Version":0}', b'{"Options":[{"Name":"not a legacy directory"}]}'):
                (root / "manifest.json").write_bytes(data)
                with self.assertRaises(ValueError):
                    load_catalog(root)

    def test_legacy_without_choices_loads_only_root_and_preserves_manifest(self):
        for optional in ({}, {"Options": None}, {"Options": []}):
            with self.subTest(optional=optional), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "input"
                root.mkdir()
                direct = self.add_patch(root, ".")
                nested = self.add_patch(root, "nested")
                data = json.dumps({"Guid": "legacy", "Name": "original", **optional}).encode() + b"\r\n"
                (root / "manifest.json").write_bytes(data)
                catalog = load_catalog(root)
                self.assertEqual(catalog.options, ())
                self.assertEqual(catalog.patch_options[direct], ("root",))
                self.assertEqual(catalog.unreferenced_patch_paths, (nested,))
                output = Path(directory) / "output"
                catalog.copy_passthrough(output)
                self.assertEqual((output / "manifest.json").read_bytes(), data)
                self.assertNotIn("Version", catalog.manifest)

    def test_legacy_choices_form_one_exclusive_group_without_root_overlay(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            direct = self.add_patch(root, ".")
            first = self.add_patch(root, "first")
            second = self.add_patch(root, "second")
            document = {"Name": "legacy", "Options": ["first", "second"]}
            (root / "manifest.json").write_text(json.dumps(document), encoding="utf-8")
            catalog = load_catalog(root)
            self.assertEqual(catalog.manifest, document)
            self.assertEqual(len(catalog.options), 1)
            self.assertEqual(catalog.options[0]["patch_paths"], ())
            self.assertEqual(catalog.options[0]["suboptions_mode"], "exclusive")
            self.assertEqual(catalog.patch_options[first], ("0/0",))
            self.assertEqual(catalog.patch_options[second], ("0/1",))
            self.assertEqual(catalog.unreferenced_patch_paths, (direct,))

    def test_null_options_and_suboptions_are_empty_without_changing_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = self.write_manifest(root, Options=None)
            catalog = load_catalog(root)
            self.assertEqual(catalog.options, ())
            self.assertIsNone(catalog.manifest["Options"])
            self.assertEqual(catalog.manifest_bytes, original)
            original = self.write_manifest(root, [{"Name": "base", "SubOptions": None}])
            catalog = load_catalog(root)
            self.assertEqual(catalog.options[0]["suboptions"], ())
            self.assertIsNone(catalog.manifest["Options"][0]["SubOptions"])
            self.assertEqual(catalog.manifest_bytes, original)

    def test_second_suboption_level_is_rejected_but_empty_declaration_is_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            options = [{"Name": "parent", "SubOptions": [{"Name": "child", "SubOptions": None}]}]
            self.write_manifest(root, options)
            self.assertEqual(len(load_catalog(root).options[0]["suboptions"]), 1)
            options[0]["SubOptions"][0]["SubOptions"] = [{"Name": "grandchild"}]
            self.write_manifest(root, options)
            with self.assertRaisesRegex(ValueError, "one level"):
                load_catalog(root)


if __name__ == "__main__":
    unittest.main()
