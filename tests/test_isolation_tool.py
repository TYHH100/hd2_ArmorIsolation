import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import armor_isolation_tool as tool
import build_cm14_isolated as archive


class ToolTests(unittest.TestCase):
    def test_prebuilt_runtime_must_match_release_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = {"schema": "hd2-armor-runtime-release/1", "runtime_schema": "hd2-armor-runtime/1",
                       "expected_game_dll_sha256": archive.DLL_SHA256, "sdk_api": 17,
                       "reshade_version": "6.5.1", "files": []}
            for name in ("ArmorIsolation.addon64", "ArmorIsolation.ini", "validate_runtime_profile.exe"):
                path = root / name
                path.write_bytes(name.encode("ascii"))
                release["files"].append({"name": name, "size": path.stat().st_size,
                                         "sha256": archive.sha256_file(path)})
            metadata = root / "runtime-release.json"
            metadata.write_text(json.dumps(release), encoding="ascii")
            self.assertEqual(tool.runtime_release(root)[0], root)
            (root / "ArmorIsolation.addon64").write_bytes(b"wrong build")
            with self.assertRaisesRegex(ValueError, "校验不符"):
                tool.runtime_release(root)
            release["runtime_schema"] = "unknown"
            metadata.write_text(json.dumps(release), encoding="ascii")
            with self.assertRaisesRegex(ValueError, "版本不匹配"):
                tool.runtime_release(root)

    def test_source_directory_never_selects_between_multiple_patches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "0123456789abcdef.patch_0"
            first.write_bytes(b"main")
            first.with_suffix(".patch_0.gpu_resources").write_bytes(b"gpu")
            self.assertEqual(tool.resolve_source(root), first.resolve())
            (root / "0123456789abcdef.patch_1").write_bytes(b"other")
            with self.assertRaisesRegex(ValueError, "2"):
                tool.resolve_source(root)
            with self.assertRaises(ValueError):
                tool.resolve_source(first.with_suffix(".patch_0.gpu_resources"))

    def test_output_cannot_write_into_mod_or_game(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "mod/0123456789abcdef.patch_0"
            game = root / "game"
            for output in (source.parent, source.parent / "new", game, game / "data/new"):
                with self.assertRaises(ValueError):
                    tool.validate_output(output, source, game)
            self.assertEqual(tool.validate_output(root / "output", source, game), (root / "output").resolve())

    def test_failed_staging_cleanup_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "keep.txt"
            existing.write_text("existing", encoding="ascii")
            with self.assertRaisesRegex(RuntimeError, "failure"):
                with tool.staging_directory(root) as staging:
                    (staging / "temporary.bin").write_bytes(b"temporary")
                    raise RuntimeError("failure")
            self.assertEqual(list(root.iterdir()), [existing])

    def test_runtime_validation_failure_does_not_publish_partial_package(self):
        self.exercise_pipeline(fail=True)

    def test_completed_package_keeps_hashes_and_no_visual_acceptance_claim(self):
        self.exercise_pipeline(fail=False)

    def exercise_pipeline(self, fail):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "mod/0123456789abcdef.patch_0"
            source.parent.mkdir()
            source.write_bytes(b"unchanged source")
            reader = root / "reader"
            reader.mkdir()
            (reader / "archive.py").write_text("", encoding="ascii")
            output = root / "output"
            package_id = "0123456789abcdef01234567"
            runtime = root / "prebuilt"
            runtime.mkdir()
            release = {"files": []}
            for name in ("ArmorIsolation.addon64", "ArmorIsolation.ini", "validate_runtime_profile.exe"):
                (runtime / name).write_bytes(name.encode("ascii"))
                release["files"].append({"name": name, "sha256": "a" * 64})
            (runtime / "runtime-release.json").write_text(json.dumps(release), encoding="ascii")
            (runtime / "licenses").mkdir()
            for name in ("nlohmann-json.LICENSE.MIT", "ReShade.LICENSE.md"):
                (runtime / "licenses" / name).write_text("license", encoding="ascii")

            def fake_builder(args):
                args.output.mkdir()
                (args.output / "generated").mkdir()
                (args.output / "generated/generic_resource_map.hpp").write_text("header", encoding="ascii")
                manifest = {"package_id": package_id, "mapping": [],
                            "targets": [{"kit": "12345678", "type": 0}]}
                (args.output / "manifest.json").write_text(json.dumps(manifest), encoding="ascii")
                return manifest

            def fake_validator(command, log_path, log):
                self.assertIsInstance(command, list)
                self.assertEqual(Path(command[0]).name, "validate_runtime_profile.exe")
                self.assertEqual(len(list(Path(command[1]).glob("*.json"))), 1)
                if fail:
                    raise RuntimeError("validation failure")
                log_path.write_text("profile passed", encoding="ascii")

            module = types.ModuleType("build_generic_isolated")
            module.build = fake_builder
            exporter = types.ModuleType("runtime_profile")
            exporter.make_runtime_profile = lambda manifest, kits: {"package_id": manifest["package_id"]}
            exporter.write_profile = lambda profile, path: path.write_text(json.dumps(profile), encoding="ascii")
            with patch.dict(sys.modules, {"build_generic_isolated": module, "runtime_profile": exporter}), \
                    patch.object(tool, "run_logged", side_effect=fake_validator), \
                    patch.object(tool, "runtime_release", return_value=(runtime, release)), \
                    patch.object(tool.shutil, "which", side_effect=AssertionError("No per-package compiler")):
                call = lambda: tool.generate_package(source, root / "game", reader, root / "kits.json",
                                                     ["12345678"], output, log=lambda _: None)
                if fail:
                    with self.assertRaisesRegex(RuntimeError, "validation failure"):
                        call()
                    self.assertEqual(list(output.iterdir()), [])
                else:
                    package = call()
                    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
                    self.assertFalse(manifest["game_runtime_verified"])
                    self.assertEqual(manifest["package_status"], "built_and_runtime_configuration_validated")
                    self.assertEqual(manifest["addon"]["mode"], "universal_runtime")
                    self.assertEqual((package / "runtime/ArmorIsolation.addon64").read_bytes(),
                                     (runtime / "ArmorIsolation.addon64").read_bytes())
                    self.assertEqual(len(manifest["package_files"]), 10)
                    self.assertTrue(all(len(item["sha256"]) == 64 for item in manifest["package_files"]))
                    self.assertEqual(list(output.iterdir()), [package])
                    with self.assertRaises(FileExistsError):
                        call()
                    self.assertEqual(list(output.iterdir()), [package])
            self.assertEqual(source.read_bytes(), b"unchanged source")


if __name__ == "__main__":
    unittest.main()
