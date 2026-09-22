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
import game_compatibility as compatibility
import build_generic_isolated as builder
import runtime_profile
from test_runtime_profile_export import manifest


class CompatibilityTests(unittest.TestCase):
    def test_capture_needs_complete_native_evidence(self):
        document = {"schema": "hd2-local-game-observation/1", "status": "observed_layout_candidate",
                    "write_authorized": False, "snapshot_stage": "before_isolation",
                    "game_dll_sha256": "a" * 64, "kits": [{"id": "00000001"}]}
        with self.assertRaises(ValueError): compatibility.validate_capture(document, "a" * 64, "b" * 64)
        document["native_compatibility"] = {"mode": "signature-validated-v1", "exe_sha256": "b" * 64,
            "functions": dict.fromkeys(["armor_assembly", "material_texture", "resource_lookup",
                                        "resource_redirect", "resource_online", "type_find"], 0x1000)}
        document["kits_sha256"] = compatibility.kits_digest(document["kits"])
        self.assertEqual(compatibility.validate_capture(document, "a" * 64, "b" * 64), document["kits"])
        optional = copy.deepcopy(document)
        del optional["native_compatibility"]["functions"]["armor_assembly"]
        optional["native_compatibility"]["optional_function_errors"] = {
            "armor_assembly": "native compatibility: function changed or unavailable: armor_assembly"}
        with self.assertRaises(ValueError): compatibility.validate_capture(optional, "a" * 64, "b" * 64)
        incomplete = copy.deepcopy(optional)
        del incomplete["native_compatibility"]["optional_function_errors"]
        with self.assertRaises(ValueError): compatibility.validate_capture(incomplete, "a" * 64, "b" * 64)
        for key, value in (("game_dll_sha256", "c" * 64), ("write_authorized", True), ("status", "not_ready"),
                           ("snapshot_stage", "observed_only"), ("snapshot_stage", "verified_baseline"),
                           ("kits_sha256", "f" * 64)):
            changed = copy.deepcopy(document)
            changed[key] = value
            with self.assertRaises(ValueError): compatibility.validate_capture(changed, "a" * 64, "b" * 64)

    def test_unknown_game_context_is_scoped_rechecked_and_cleans(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary)
            (game / "data/game").mkdir(parents=True)
            (game / "bin").mkdir()
            dll, exe = game / "data/game/game.dll", game / "bin/helldivers2.exe"
            dll.write_bytes(b"new game")
            exe.write_bytes(b"new engine")
            game_hash, exe_hash = builder.archive.sha256_file(dll), builder.archive.sha256_file(exe)
            snapshot = [{"id": "00000001"}]
            report = {"schema": "hd2-local-game-observation/1", "status": "observed_layout_candidate",
                      "write_authorized": False, "snapshot_stage": "without_isolation",
                      "game_dll_sha256": game_hash, "kits": snapshot,
                      "kits_sha256": compatibility.kits_digest(snapshot),
                      "native_compatibility": {"mode": "signature-validated-v1", "exe_sha256": exe_hash,
                      "functions": dict.fromkeys(["armor_assembly", "material_texture", "resource_lookup",
                                                  "resource_redirect", "resource_online", "type_find"], 0x1000)}}
            def run(command, **kwargs):
                Path(command[-1]).write_text(json.dumps(report), encoding="utf-8")
                return SimpleNamespace(returncode=0)
            with patch.object(compatibility.subprocess, "run", side_effect=run):
                with compatibility.game_context(game, game / "unused.json", lambda: (game, {})) as kits:
                    work = kits.parent
                    self.assertEqual(builder.validate_version(game, kits), snapshot)
                    self.assertEqual(compatibility.identity()["expected_game_dll_sha256"], game_hash)
                    before = builder.package_identity([], [{"id": "00000001"}])
                    dll.write_bytes(b"changed again")
                    with self.assertRaises(ValueError): compatibility.validate_current(game, kits)
                self.assertFalse(work.exists())
                self.assertIsNone(compatibility.CURRENT.get())
                self.assertNotEqual(before, builder.package_identity([], [{"id": "00000001"}]))
                dll.write_bytes(b"new game")
                exported = game / compatibility.EXPORT_NAME
                self.assertTrue(exported.is_file())
                self.assertEqual(list(game.glob(".armor-export-*")), [])
                # A fresh operation uses the saved game-root export with the game closed.
                with patch.object(compatibility.subprocess, "run", side_effect=AssertionError("must use export")):
                    with compatibility.game_context(game, game / "unused.json", lambda: (game, {})) as kits:
                        self.assertEqual(builder.validate_version(game, kits), snapshot)
                exe.write_bytes(b"updated engine")
                self.assertIsNone(compatibility.load_export(game, game_hash, builder.archive.sha256_file(exe)))
                exe.write_bytes(b"new engine")
                exported.write_text("broken json", encoding="utf-8")
                self.assertIsNone(compatibility.load_export(game, game_hash, exe_hash))

    def test_adaptive_profile_binds_snapshot_and_keeps_legacy_guards(self):
        source = manifest("cm14")
        source.update(expected_game_dll_sha256="a" * 64, expected_game_version="local-aaaaaaaaaaaaaaaa",
                      runtime_compatibility={"mode": "signature-validated-v1", "exe_sha256": "b" * 64,
                                             "kits_sha256": runtime_profile.KITS_SHA256})
        profile = runtime_profile.make_runtime_profile(source)
        self.assertEqual(profile["schema"], runtime_profile.ADAPTIVE_SCHEMA)
        self.assertEqual(profile["expected_game_dll_sha256"], "a" * 64)
        source["runtime_compatibility"]["kits_sha256"] = "c" * 64
        with self.assertRaises(ValueError): runtime_profile.make_runtime_profile(source)
        del source["runtime_compatibility"]
        with self.assertRaises(ValueError): runtime_profile.make_runtime_profile(source)


if __name__ == "__main__": unittest.main()
