import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import armor_isolation_tool as tool


class ToolTests(unittest.TestCase):
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

    def test_compiler_failure_does_not_publish_partial_package(self):
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
            package_id = "0123456789abcdef"

            def fake_builder(args):
                args.output.mkdir()
                (args.output / "generated").mkdir()
                (args.output / "generated/generic_resource_map.hpp").write_text("header", encoding="ascii")
                manifest = {"package_id": package_id, "mapping": [],
                            "targets": [{"kit": "12345678", "type": 0}]}
                (args.output / "manifest.json").write_text(json.dumps(manifest), encoding="ascii")
                return manifest

            def fake_compiler(command, log_path, log):
                self.assertIsInstance(command, list)
                if fail:
                    raise RuntimeError("compiler failure")
                addon_dir = Path(command[command.index("-OutputDirectory") + 1])
                (addon_dir / f"ArmorIsolation_{package_id}.addon64").write_bytes(b"addon")
                build_dir = Path(command[command.index("-BuildDirectory") + 1])
                build_dir.mkdir()
                (build_dir / "probe_generic_resources.exe").write_bytes(b"probe")
                log_path.write_text("tests passed", encoding="ascii")

            module = types.ModuleType("build_generic_isolated")
            module.build = fake_builder
            with patch.dict(sys.modules, {"build_generic_isolated": module}), \
                    patch.object(tool, "run_build", side_effect=fake_compiler), \
                    patch.object(tool.shutil, "which", return_value="pwsh"):
                call = lambda: tool.generate_package(source, root / "game", reader, root / "kits.json",
                                                     ["12345678"], output, log=lambda _: None)
                if fail:
                    with self.assertRaisesRegex(RuntimeError, "compiler failure"):
                        call()
                    self.assertEqual(list(output.iterdir()), [])
                else:
                    package = call()
                    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
                    self.assertFalse(manifest["game_runtime_verified"])
                    self.assertEqual(manifest["package_status"], "built_and_locally_tested")
                    self.assertEqual(len(manifest["package_files"]), 6)
                    self.assertTrue(all(len(item["sha256"]) == 64 for item in manifest["package_files"]))
                    self.assertEqual(list(output.iterdir()), [package])
                    with self.assertRaises(FileExistsError):
                        call()
                    self.assertEqual(list(output.iterdir()), [package])
            self.assertEqual(source.read_bytes(), b"unchanged source")


if __name__ == "__main__":
    unittest.main()
