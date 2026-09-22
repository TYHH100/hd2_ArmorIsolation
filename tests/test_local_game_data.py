import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import local_game_data as local
import game_compatibility as compatibility


class LocalGameTests(unittest.TestCase):
    def setUp(self):
        self.baseline = [{"id": "00000001", "archive": "0000000000000001", "bodies": []}]
        self.observation = {"schema": "hd2-local-game-observation/1", "write_authorized": False,
                            "status": "observed_layout_candidate", "game_dll_sha256": "a" * 64,
                            "kits": copy.deepcopy(self.baseline)}

    def compare(self, installed="a" * 64):
        result = local.compare_observation(self.observation, self.baseline, "a" * 64, installed)
        self.assertFalse(result["write_authorized"])
        return result

    def test_equal_snapshot_and_row_order_do_not_authorize_writes(self):
        self.assertEqual(self.compare()["status"], "matches_verified_snapshot")

    def test_changed_added_removed_reported_without_promoting_baseline(self):
        self.observation["kits"][0]["archive"] = "0000000000000002"
        self.observation["kits"].append({"id": "00000002"})
        result = self.compare()
        self.assertEqual(result["status"], "live_data_differs")
        self.assertEqual(result["changed"], [{"id": "00000001", "fields": ["archive"]}])
        self.assertEqual(result["added"], ["00000002"])
        self.assertEqual(self.baseline[0]["archive"], "0000000000000001")
        self.observation["kits"].pop(0)
        self.assertEqual(self.compare()["removed"], ["00000001"])

    def test_new_dll_and_stale_report_not_supported(self):
        self.assertEqual(self.compare("b" * 64)["status"], "stale_observation")
        self.observation["game_dll_sha256"] = "b" * 64
        self.assertEqual(self.compare("b" * 64)["status"], "new_version_candidate")

    def test_new_version_requires_assembly_in_comparison_evidence(self):
        self.observation["game_dll_sha256"] = "b" * 64
        native = {"mode": "signature-validated-v1", "functions": dict.fromkeys([
            "material_texture", "resource_lookup", "resource_redirect", "resource_online", "type_find"], 0x1000),
            "optional_function_errors": {"armor_assembly": "changed"}}
        self.observation["native_compatibility"] = native
        result = self.compare("b" * 64)
        self.assertEqual(result["status"], "new_version_candidate")
        self.assertEqual(result["native_layout_status"], "incompatible")
        self.assertFalse(result["export_ready"])
        native["functions"]["armor_assembly"] = 0x2000
        del native["optional_function_errors"]
        self.assertEqual(self.compare("b" * 64)["status"], "new_version_signature_compatible")

    def test_mode_alone_and_loaded_plugin_do_not_make_a_snapshot_usable(self):
        self.observation["game_dll_sha256"] = "b" * 64
        native = {"mode": "signature-validated-v1"}
        self.observation["native_compatibility"] = native
        self.assertEqual(self.compare("b" * 64)["native_layout_status"], "incompatible")
        native["functions"] = dict.fromkeys([
            "armor_assembly", "material_texture", "resource_lookup", "resource_redirect", "resource_online", "type_find"], 0x1000)
        self.observation["snapshot_stage"] = "observed_only"
        result = self.compare("b" * 64)
        self.assertEqual(result["status"], "new_version_snapshot_untrusted")
        self.assertEqual(result["native_layout_status"], "compatible")
        self.assertEqual(result["snapshot_status"], "observed_only")
        self.assertFalse(result["export_ready"])
        self.assertIn("更新通用插件并重启游戏", result["reason"])

    def test_native_diagnostics_report_all_functions_without_granting_compatibility(self):
        self.observation["game_dll_sha256"] = "b" * 64
        functions = {name: {"status": "matched", "rva": 0x1000} for name in local.NATIVE_FUNCTIONS}
        functions["armor_assembly"] = {"status": "failed", "error": "assembly layout changed"}
        diagnostics = {"required": 6, "matched": 5, "functions": functions}
        self.observation["native_diagnostics"] = diagnostics
        result = self.compare("b" * 64)
        self.assertEqual(result["native_diagnostics"], {
            "required": 6, "matched": 5, "failed_functions": {"armor_assembly": "assembly layout changed"}})
        self.assertEqual(result["status"], "new_version_candidate")
        self.assertNotEqual(result["native_layout_status"], "compatible")
        self.assertFalse(result["export_ready"])
        # Even six successful diagnostic rows cannot replace the complete native evidence.
        functions["armor_assembly"] = {"status": "matched", "rva": 0x2000}
        diagnostics["matched"] = 6
        result = self.compare("b" * 64)
        self.assertEqual(result["native_diagnostics"]["matched"], 6)
        self.assertEqual(result["status"], "new_version_candidate")
        self.assertFalse(result["export_ready"])

    def test_incomplete_or_inconsistent_native_diagnostics_are_ignored(self):
        functions = {name: {"status": "matched", "rva": 0x1000} for name in local.NATIVE_FUNCTIONS}
        for invalid in ("missing_function", "wrong_count", "wrong_required", "invalid_rva"):
            with self.subTest(invalid=invalid):
                diagnostics = {"required": 6, "matched": 6, "functions": copy.deepcopy(functions)}
                if invalid == "missing_function":
                    del diagnostics["functions"]["armor_assembly"]
                elif invalid == "wrong_count":
                    diagnostics["matched"] = 5
                elif invalid == "wrong_required":
                    diagnostics["required"] = 5
                else:
                    diagnostics["functions"]["armor_assembly"]["rva"] = True
                self.observation.update(game_dll_sha256="b" * 64, native_diagnostics=diagnostics)
                result = self.compare("b" * 64)
                self.assertNotIn("native_diagnostics", result)
                self.assertEqual(result["status"], "new_version_candidate")
                self.assertFalse(result["export_ready"])
        del self.observation["native_diagnostics"]
        self.assertNotIn("native_diagnostics", self.compare("b" * 64))

    def inspection_fixture(self, root, stage="observed_only"):
        game = root / "game"
        (game / "data/game").mkdir(parents=True)
        (game / "bin").mkdir()
        (game / "data/game/game.dll").write_bytes(b"new game")
        (game / "bin/helldivers2.exe").write_bytes(b"new executable")
        kits = root / "baseline.json"
        kits.write_text(json.dumps(self.baseline), encoding="utf-8")
        observation = copy.deepcopy(self.observation)
        observation.update(snapshot_stage=stage, game_dll_sha256=hashlib.sha256(b"new game").hexdigest())
        observation["native_compatibility"] = {
            "mode": "signature-validated-v1", "exe_sha256": hashlib.sha256(b"new executable").hexdigest(),
            "functions": dict.fromkeys([
                "armor_assembly", "material_texture", "resource_lookup", "resource_redirect", "resource_online", "type_find"], 0x1000)}
        observation["kits_sha256"] = compatibility.kits_digest(observation["kits"])
        return game, kits, observation

    def inspect_fixture(self, root, game, kits, observation):
        def run(command, **kwargs):
            Path(command[-1]).write_text(json.dumps(observation), encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch.object(local.subprocess, "run", side_effect=run):
            path, comparison = local.inspect_game(game, root / "output", root, kits, "a" * 64)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["observation"], observation)
        self.assertEqual(list((root / "output").iterdir()), [path])
        return comparison

    def test_inspection_reuses_export_without_promoting_or_overwriting_live_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game, kits, observation = self.inspection_fixture(root)
            exported = copy.deepcopy(observation)
            exported["snapshot_stage"] = "before_isolation"
            export_path = game / compatibility.EXPORT_NAME
            original_bytes = json.dumps(exported, indent=3).encode("utf-8")
            export_path.write_bytes(original_bytes)
            observation["kits"][0]["archive"] = "0000000000000002"
            observation["kits_sha256"] = compatibility.kits_digest(observation["kits"])
            with patch.object(compatibility, "save_export", side_effect=AssertionError("trusted export must be preserved")):
                result = self.inspect_fixture(root, game, kits, observation)
            self.assertTrue(result["export_ready"])
            self.assertEqual(result["export_source"], "existing")
            self.assertEqual(result["snapshot_status"], "observed_only")
            self.assertEqual(result["export_path"], str(export_path.resolve()))
            self.assertNotIn("export_error", result)
            self.assertEqual(export_path.read_bytes(), original_bytes)

    def test_untrusted_or_stale_export_cannot_make_observed_only_ready(self):
        for invalid in ("exe_hash", "snapshot_stage", "digest"):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                game, kits, observation = self.inspection_fixture(root)
                exported = copy.deepcopy(observation)
                exported["snapshot_stage"] = "before_isolation"
                if invalid == "exe_hash":
                    exported["native_compatibility"]["exe_sha256"] = "f" * 64
                elif invalid == "snapshot_stage":
                    exported["snapshot_stage"] = "observed_only"
                else:
                    exported["kits_sha256"] = "f" * 64
                export_path = game / compatibility.EXPORT_NAME
                original_bytes = json.dumps(exported).encode("utf-8")
                export_path.write_bytes(original_bytes)
                result = self.inspect_fixture(root, game, kits, observation)
                self.assertFalse(result["export_ready"])
                self.assertNotIn("export_path", result)
                self.assertIn("重启游戏", result["export_error"])
                self.assertEqual(export_path.read_bytes(), original_bytes)

    def test_clean_capture_is_validated_before_becoming_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game, kits, observation = self.inspection_fixture(root, "without_isolation")
            result = self.inspect_fixture(root, game, kits, observation)
            self.assertTrue(result["export_ready"])
            self.assertEqual(result["export_source"], "without_isolation")
            self.assertIsNotNone(compatibility.load_export(game, observation["game_dll_sha256"],
                                observation["native_compatibility"]["exe_sha256"]))

    def test_incomplete_native_capture_does_not_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game, kits, observation = self.inspection_fixture(root, "without_isolation")
            del observation["native_compatibility"]["functions"]["armor_assembly"]
            result = self.inspect_fixture(root, game, kits, observation)
            self.assertFalse(result["export_ready"])
            self.assertEqual(result["native_layout_status"], "incompatible")
            self.assertFalse((game / compatibility.EXPORT_NAME).exists())

    def test_duplicate_and_failed_observations(self):
        self.observation["kits"] *= 2
        with self.assertRaises(ValueError): self.compare()
        self.observation.update(status="unsupported_or_not_ready", error="not ready")
        self.assertEqual(self.compare()["reason"], "not ready")

    def test_failed_process_does_not_reuse_old_report_and_cleans_temporary_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kits = root / "kits.json"
            kits.write_text(json.dumps(self.baseline), encoding="utf-8")
            output = root / "output"
            output.mkdir()
            old = output / "local-game-analysis.json"
            old.write_text("old report", encoding="utf-8")
            with patch.object(local.subprocess, "run") as run:
                run.return_value.returncode = 1
                run.return_value.stderr = "not running"
                with self.assertRaisesRegex(ValueError, "not running"):
                    local.inspect_game(root / "game", output, root, kits, "a" * 64)
            self.assertEqual(old.read_text(), "old report")
            self.assertEqual(list(output.iterdir()), [old])

    def test_game_directory_cannot_be_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "游戏目录"):
                local.inspect_game(root, root / "data", root, root / "kits.json", "a" * 64)


if __name__ == "__main__":
    unittest.main()
