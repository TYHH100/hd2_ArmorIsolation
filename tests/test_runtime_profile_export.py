import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import runtime_profile as exporter


def manifest(name="b01"):
    return json.loads((ROOT / f"dist/{name}-isolated/manifest.json").read_text(encoding="utf-8"))


class RuntimeProfileExportTests(unittest.TestCase):
    def test_legacy_samples_preserve_every_private_id_and_derive_requirements(self):
        for sample, target_count, resource_count in (("cm14", 2, 51), ("b01", 8, 106)):
            with self.subTest(sample=sample):
                source = manifest(sample)
                before = copy.deepcopy(source)
                result = exporter.make_runtime_profile(source)
                self.assertEqual(source, before)
                self.assertEqual(len(result["selected_kit_metadata"]), target_count)
                self.assertEqual(len(result["mapping"]), resource_count)
                self.assertEqual(result["mapping"], [{key: row[key] for key in ("kit", "type", "source", "target")}
                                                     for row in source["mapping"]])
                self.assertEqual(result["piece_fields"], source["piece_fields"])
                self.assertEqual(len(result["package_id"]), 24)
                for target in result["selected_kit_metadata"]:
                    actual = {(row["type"], row["target"]) for row in result["required_resources"]
                              if row["kit"] == target["id"]}
                    expected = {(row["type"], row["target"]) for row in result["mapping"]
                                if row["kit"] in (target["id"], "00000000")}
                    self.assertEqual(actual, expected)

    def test_legacy_identity_uses_semantics_not_paths_or_row_order(self):
        source = manifest("cm14")
        expected = exporter.make_runtime_profile(source)["package_id"]
        source["source"] = "Z:/unrelated/source.patch_42"
        source["mapping"].reverse()
        source["piece_fields"].reverse()
        source["targets"].reverse()
        self.assertEqual(exporter.make_runtime_profile(source)["package_id"], expected)
        source["mapping"][0]["target"] = "fedcba9876543210"
        for field in source["piece_fields"]:
            if (field["kit"], field["source"]) == (source["mapping"][0]["kit"], source["mapping"][0]["source"]):
                field["target"] = "fedcba9876543210"
        self.assertNotEqual(exporter.make_runtime_profile(source)["package_id"], expected)

    def test_new_profile_retains_package_id_and_exact_per_kit_dependencies(self):
        source = manifest()
        baseline = exporter.make_runtime_profile(source)
        source["package_id"] = "1234567890abcdef12345678"
        source["selected_kit_metadata"] = baseline["selected_kit_metadata"]
        source["required_resources"] = baseline["required_resources"]
        first = source["targets"][0]["kit"]
        material_kind = f"{exporter.archive.MATERIAL:016x}"
        source["required_resources"] = [row for row in source["required_resources"]
                                        if not (row["kit"] == first and row["type"] == material_kind)]
        result = exporter.make_runtime_profile(source)
        self.assertEqual(result["package_id"], source["package_id"])
        self.assertEqual(result["required_resources"], source["required_resources"])
        self.assertEqual(result["selected_kit_metadata"], source["selected_kit_metadata"])
        self.assertEqual(set(result), {"schema", "package_id", "expected_game_version", "expected_game_dll_sha256",
                                       "selected_kit_metadata", "mapping", "piece_fields", "required_resources"})
        self.assertTrue(all(set(row) == {"kit", "type", "source", "target"} for row in result["mapping"]))

    def test_rejects_unknown_game_or_unbound_snapshot(self):
        for field, value in (("expected_game_version", "9.9.9.9"), ("expected_game_dll_sha256", "0" * 64),
                             ("source_kits_sha256", "0" * 64)):
            source = manifest()
            source[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                exporter.make_runtime_profile(source)
        with tempfile.TemporaryDirectory() as temporary:
            kits = Path(temporary) / "kits.json"
            kits.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "snapshot SHA256"):
                exporter.make_runtime_profile(manifest(), kits)

    def test_rejects_wrong_metadata_even_when_targets_exist(self):
        source = manifest()
        source["selected_kit_metadata"] = exporter.make_runtime_profile(source)["selected_kit_metadata"]
        source["selected_kit_metadata"][0]["bodies"][0]["pieces"][0]["weight"] += 1
        with self.assertRaisesRegex(ValueError, "differs from snapshot"):
            exporter.make_runtime_profile(source)
        source = manifest()
        source["targets"][0]["type"] = False
        with self.assertRaisesRegex(ValueError, "uint32"):
            exporter.make_runtime_profile(source)

    def test_rejects_malformed_or_unmapped_fields(self):
        for value in (-1, 0x100000000, True, 0x10):
            source = manifest()
            source["piece_fields"][0]["offset"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                exporter.make_runtime_profile(source)
        source = manifest()
        source["piece_fields"][0]["target"] = "0000000000000001"
        with self.assertRaisesRegex(ValueError, "matching resource mapping"):
            exporter.make_runtime_profile(source)

    def test_rejects_malformed_mappings_and_wrong_dependencies(self):
        for field, value in (("source", "1"), ("target", "z" * 16), ("kit", "ffffffff"),
                             ("type", "0000000000000001")):
            source = manifest()
            source["mapping"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                exporter.make_runtime_profile(source)
        source = manifest()
        source["required_resources"] = exporter.make_runtime_profile(source)["required_resources"]
        source["required_resources"][0]["kit"] = "ffffffff"
        with self.assertRaisesRegex(ValueError, "required resource"):
            exporter.make_runtime_profile(source)

    def test_export_does_not_overwrite_and_rejects_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = ROOT / "dist/cm14-isolated/manifest.json"
            result = exporter.export_manifest(source, directory)
            output = directory / f"{result['package_id']}.json"
            original = output.read_bytes()
            self.assertEqual(json.loads(original), result)
            with self.assertRaises(FileExistsError):
                exporter.export_manifest(source, directory)
            self.assertEqual(output.read_bytes(), original)
            with self.assertRaisesRegex(ValueError, "filename"):
                exporter.write_profile(result, directory / "wrong.json")
            invalid = directory / "invalid.json"
            invalid.write_text('{"mapping": [], "mapping": []}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
                exporter.export_manifest(invalid, directory)

    def test_failed_write_removes_its_partial_file(self):
        result = exporter.make_runtime_profile(manifest("cm14"))
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / f"{result['package_id']}.json"
            original_open = Path.open

            class FailingStream:
                def __enter__(self):
                    self.stream = original_open(output, "x", encoding="utf-8")
                    return self

                def write(self, value):
                    self.stream.write(value[:16])
                    raise OSError("simulated disk failure")

                def __exit__(self, *args):
                    self.stream.close()

            with patch.object(Path, "open", return_value=FailingStream()):
                with self.assertRaisesRegex(OSError, "disk failure"):
                    exporter.write_profile(result, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
