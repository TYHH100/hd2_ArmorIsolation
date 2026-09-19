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

    def test_modular_directory_and_manifest_use_same_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text('{"Version":1,"Options":[]}', encoding="ascii")
            for index in range(2):
                (root / f"0123456789abcdef.patch_{index}").write_bytes(b"main")
            self.assertEqual(tool.resolve_source(root), manifest.resolve())
            self.assertEqual(tool.resolve_source(manifest), manifest.resolve())

    def test_analysis_dispatches_modular_and_single_patch_without_selecting_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text('{"Version":1,"Options":[]}', encoding="ascii")
            source = root / "0123456789abcdef.patch_0"
            source.write_bytes(b"main")
            calls = []

            def analyzer(kind):
                def analyze(args):
                    calls.append((kind, args.source))
                    self.assertEqual(args.target, [])
                    return {"source_kind": kind, "candidates": [
                        {"id": "12345678", "type": 0, "archive": "1234567890abcdef", "supported": True}],
                        "auto_selected": []}
                return analyze

            modules = {}
            for name, kind in (("build_generic_isolated", "single"), ("build_modular_isolated", "modular")):
                module = types.ModuleType(name)
                module.analyze = analyzer(kind)
                modules[name] = module
            with patch.dict(sys.modules, modules):
                for value, expected in ((source, "single"), (root, "modular"), (manifest, "modular")):
                    result = tool.analyze_source(value, root / "game", root / "reader", root / "kits.json")
                    self.assertEqual(result["source_kind"], expected)
                    self.assertEqual(result["auto_selected"], [])
                    self.assertEqual(result["candidates"][0]["name"], "12345678")
            self.assertEqual(calls, [("single", source.resolve()), ("modular", manifest.resolve()),
                                     ("modular", manifest.resolve())])

    def test_output_cannot_write_into_mod_or_game(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "mod/0123456789abcdef.patch_0"
            game = root / "game"
            for output in (source.parent, source.parent / "new", game, game / "data/new"):
                with self.assertRaises(ValueError):
                    tool.validate_output(output, source, game)
            self.assertEqual(tool.validate_output(root / "output", source, game), (root / "output").resolve())

    def test_modular_output_protects_entire_source_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mod = root / "mod"
            mod.mkdir()
            manifest = mod / "manifest.json"
            manifest.write_text('{}', encoding="ascii")
            for source in (mod, manifest):
                for output in (mod, mod / "accessory/generated", mod / "materials"):
                    with self.assertRaisesRegex(ValueError, "源模组"):
                        tool.validate_output(output, source, root / "game")

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

    def test_modular_package_keeps_source_manifest_in_integrity_records(self):
        self.exercise_pipeline(fail=False, modular=True)

    def test_modular_failure_cleans_preserved_tree_without_publishing(self):
        self.exercise_pipeline(fail=True, modular=True)

    def exercise_pipeline(self, fail, modular=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / ("mod/manifest.json" if modular else "mod/0123456789abcdef.patch_0")
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
                self.assertEqual(args.source, source.resolve())
                self.assertEqual(args.target, ["12345678"])
                args.output.mkdir()
                (args.output / "generated").mkdir()
                (args.output / "generated/generic_resource_map.hpp").write_text("header", encoding="ascii")
                manifest = {"package_id": package_id, "mapping": [],
                            "targets": [{"kit": "12345678", "type": 0}]}
                if modular:
                    original = args.output / "mod/original"
                    (original / "component").mkdir(parents=True)
                    (original / "manifest.json").write_bytes(source.read_bytes())
                    (original / "0.png").write_bytes(b"preserved preview")
                    (original / "component/0123456789abcdef.patch_0").write_bytes(b"isolated patch")
                    manifest.update(source_kind="modular", modular={"mod_directory": "mod/original",
                                    "required_options": [{"id": "0", "name": "Base"},
                                                         {"id": "1", "name": "Materials"}]})
                (args.output / "manifest.json").write_text(json.dumps(manifest), encoding="ascii")
                return manifest

            def fake_validator(command, log_path, log):
                self.assertIsInstance(command, list)
                self.assertEqual(Path(command[0]).name, "validate_runtime_profile.exe")
                self.assertEqual(len(list(Path(command[1]).glob("*.json"))), 1)
                if fail:
                    raise RuntimeError("validation failure")
                log_path.write_text("profile passed", encoding="ascii")

            module_name = "build_modular_isolated" if modular else "build_generic_isolated"
            module = types.ModuleType(module_name)
            module.build = fake_builder
            exporter = types.ModuleType("runtime_profile")
            exporter.make_runtime_profile = lambda manifest, kits: {"package_id": manifest["package_id"]}
            exporter.write_profile = lambda profile, path: path.write_text(json.dumps(profile), encoding="ascii")
            with patch.dict(sys.modules, {module_name: module, "runtime_profile": exporter}), \
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
                    self.assertEqual(len(manifest["package_files"]), 13 if modular else 10)
                    self.assertTrue(all(len(item["sha256"]) == 64 for item in manifest["package_files"]))
                    if modular:
                        preserved = package / "mod/original/manifest.json"
                        self.assertEqual(preserved.read_bytes(), source.read_bytes())
                        records = {item["path"]: item for item in manifest["package_files"]}
                        self.assertEqual(records["mod/original/manifest.json"]["sha256"], archive.sha256_file(preserved))
                        self.assertNotIn("manifest.json", records)
                        readme = (package / "README.md").read_text(encoding="utf-8")
                        self.assertIn("导入 `mod/original/`", readme)
                        self.assertIn("Guid 保持不变", readme)
                        self.assertIn("启用基础选项 `Base`、`Materials`", readme)
                        self.assertIn("材质分辨率仍按原清单单选", readme)
                        self.assertEqual(len(list((package / "runtime/ArmorIsolation").glob("*.json"))), 1)
                    self.assertEqual(list(output.iterdir()), [package])
                    with self.assertRaises(FileExistsError):
                        call()
                    self.assertEqual(list(output.iterdir()), [package])
            self.assertEqual(source.read_bytes(), b"unchanged source")


if __name__ == "__main__":
    unittest.main()
