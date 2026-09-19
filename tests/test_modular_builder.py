import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import build_modular_isolated as builder
from test_generic_builder import FakeReader, fixture, kit, material, unit

archive = builder.archive


def make_mod(root, *, unused=False, empty_lanes=True):
    mod = root / "mod-source"
    resources = {(archive.UNIT, 10): unit(20)}
    data = {(archive.MATERIAL, 20): material(30), (archive.TEXTURE, 30): b"texture"}
    if unused:
        resources[archive.UNIT, 11] = unit(21)
        data.update({(archive.MATERIAL, 21): material(31), (archive.TEXTURE, 31): b"unused"})
    fixture(mod / "model", resources, gpu=b"base-mesh", create_empty_lanes=empty_lanes)
    variant = bytearray(unit(20))
    variant[0] = 9
    fixture(mod / "accessory", {(archive.UNIT, 10): bytes(variant)}, gpu=b"accessory-mesh",
            create_empty_lanes=empty_lanes)
    fixture(mod / "data", data, gpu=b"shared-data", create_empty_lanes=empty_lanes)
    document = {"Version": 1, "Guid": "original-identity", "Name": "Original mod", "Custom": {"keep": True},
                "Options": [{"Name": name, "Include": [f"{name}/source"]} for name in ("model", "data", "accessory")]}
    (mod / "manifest.json").write_text(json.dumps(document) + "\n", encoding="utf-8")
    (mod / "icon.png").write_bytes(b"original-bitmap")
    (mod / "empty-directory").mkdir()
    (mod / "model/old.hd2mm-backup").write_bytes(b"original-backup")
    return mod


def args(root, mod, targets=("1",)):
    return SimpleNamespace(source=mod, game=root / "game", reader_tools=root / "reader", kits=root / "kits.json",
                           target=list(targets), output=root / "output", coexist_manifest=[])


def build(arguments, kits):
    with patch.object(builder.generic, "validate_version", return_value=kits), \
            patch.object(archive, "VanillaReader", FakeReader):
        return builder.build(arguments)


class ModularBuilderTests(unittest.TestCase):
    def test_legacy_root_mod_passes_public_analysis_and_complete_build(self):
        import armor_isolation_tool as tool
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mod = fixture(root).parent
            original = b'{"Guid":"original","Name":"legacy","IconPath":"preview.png"}\r\n'
            (mod / "manifest.json").write_bytes(original)
            (mod / "preview.png").write_bytes(b"image")
            with patch.object(builder.generic, "validate_version", return_value=[kit(1, 10)]):
                analysis = tool.analyze_source(mod, root / "game", root / "reader", root / "kits.json")
            self.assertEqual(analysis["modular"]["manifest_format"], "legacy")
            self.assertEqual(analysis["modular"]["option_count"], 0)
            self.assertTrue(analysis["candidates"][0]["supported"])
            self.assertEqual(analysis["auto_selected"], [])
            arguments = args(root, mod)
            manifest = build(arguments, [kit(1, 10)])
            output = arguments.output / manifest["modular"]["mod_directory"]
            self.assertEqual((output / "manifest.json").read_bytes(), original)
            self.assertEqual((output / "preview.png").read_bytes(), b"image")
            self.assertEqual(len(manifest["mapping"]), 3)
            self.assertEqual(manifest["modular"]["required_options"][0]["id"], "root")

    def test_legacy_exclusive_variants_share_private_ids_and_keep_original_choices(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mod = root / "legacy-options"
            first = fixture(mod / "first", gpu=b"first model")
            second = fixture(mod / "second", gpu=b"second model")
            document = {"Name": "legacy", "Options": [first.parent.relative_to(mod).as_posix(),
                                                       second.parent.relative_to(mod).as_posix()]}
            original = json.dumps(document).encode()
            (mod / "manifest.json").write_bytes(original)
            arguments = args(root, mod)
            manifest = build(arguments, [kit(1, 10)])
            self.assertEqual(len(manifest["modular"]["required_options"]), 1)
            self.assertEqual(manifest["modular"]["option_count"], 2)
            self.assertEqual(manifest["modular"]["patches"][0]["mapping"],
                             manifest["modular"]["patches"][1]["mapping"])
            self.assertEqual((arguments.output / manifest["modular"]["mod_directory"] / "manifest.json").read_bytes(), original)

    def test_preserves_tree_bytes_and_private_overlay_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mod = make_mod(root)
            arguments = args(root, mod, ("1", "2"))
            manifest = build(arguments, [kit(1, 10), kit(2, 10)])
            output = arguments.output / manifest["modular"]["mod_directory"]
            self.assertEqual({p.relative_to(mod) for p in mod.rglob("*")},
                             {p.relative_to(output) for p in output.rglob("*")})
            for relative in ("manifest.json", "icon.png", "model/old.hd2mm-backup"):
                self.assertEqual((mod / relative).read_bytes(), (output / relative).read_bytes())
            self.assertEqual(len(manifest["mapping"]), 4)
            units = [row for row in manifest["mapping"] if row["kind"] == "unit"]
            self.assertEqual(len({row["target"] for row in units}), 2)
            for record in manifest["modular"]["patches"]:
                if record["path"].startswith(("model/", "accessory/")):
                    self.assertEqual({row["target"] for row in record["mapping"]}, {row["target"] for row in units})
                    self.assertEqual(record["source_resources"], 1)
                    self.assertEqual(record["output_resources"], 2)
            self.assertEqual([row["name"] for row in manifest["modular"]["required_options"]], ["model", "data"])
            self.assertFalse(manifest["game_runtime_verified"])

    def test_unselected_resources_are_preserved_privately_without_runtime_ownership(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mod = make_mod(root, unused=True)
            manifest = build(args(root, mod), [kit(1, 10), kit(2, 11)])
            self.assertEqual(len(manifest["mapping"]), 3)
            self.assertEqual(len(manifest["preserved_unbound_mapping"]), 3)
            all_rows = manifest["mapping"] + manifest["preserved_unbound_mapping"]
            self.assertEqual(len({row["target"] for row in all_rows}), 6)
            self.assertTrue(all(row["source"] != row["target"] for row in all_rows))
            self.assertEqual(len(manifest["modular"]["patches"]), 3)

    def test_absent_zero_lanes_remain_absent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mod = make_mod(root, empty_lanes=False)
            arguments = args(root, mod)
            manifest = build(arguments, [kit(1, 10)])
            output = arguments.output / manifest["modular"]["mod_directory"]
            self.assertEqual(list(output.rglob("*.stream")), [])
            self.assertTrue(manifest["payloads_verified"])

    def test_missing_common_material_supplier_does_not_produce_partial_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mod = make_mod(root)
            # A new material exists only inside an optional model override.
            special = fixture(mod / "special", {(archive.UNIT, 10): unit(22),
                                                 (archive.MATERIAL, 22): material(30)})
            manifest_path = mod / "manifest.json"
            document = json.loads(manifest_path.read_text())
            document["Options"].append({"Name": "special", "Include": [special.parent.relative_to(mod).as_posix()]})
            manifest_path.write_text(json.dumps(document))
            arguments = args(root, mod)
            with self.assertRaisesRegex(ValueError, "common supplier"):
                build(arguments, [kit(1, 10)])
            self.assertFalse(arguments.output.exists())

    def test_resolution_options_only_require_one_private_texture_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mod = root / "resolution-mod"
            fixture(mod / "model", {(archive.UNIT, 10): unit(20)}, gpu=b"geometry")
            for name, texture, pixels in (("low", 30, b"low-pixels"), ("high", 31, b"larger-high-pixels")):
                fixture(mod / name, {(archive.MATERIAL, 20): material(texture), (archive.TEXTURE, texture): b"texture"}, gpu=pixels)
            document = {"Version": 1, "Name": "resolutions", "Options": [
                {"Name": "model", "Include": ["model/source"]},
                {"Name": "textures", "SubOptions": [{"Name": name, "Include": [f"{name}/source"]} for name in ("low", "high")]}]}
            (mod / "manifest.json").write_text(json.dumps(document))
            manifest = build(args(root, mod), [kit(1, 10)])
            self.assertEqual(len(manifest["mapping"]), 3)
            private = [row["target"] for row in manifest["mapping"] if row["kind"] == "texture"]
            self.assertEqual(len(private), 1)
            for row in manifest["modular"]["patches"]:
                if row["path"].startswith(("low/", "high/")):
                    textures = [item["target"] for item in row["mapping"] if item["kind"] == "texture"]
                    self.assertEqual(textures, private)
            self.assertEqual([row["name"] for row in manifest["modular"]["required_options"]], ["model", "textures"])

    def test_failed_write_removes_own_tree_and_preserves_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mod = make_mod(root)
            original = (mod / "manifest.json").read_bytes()
            arguments = args(root, mod)
            with patch.object(builder.generic, "write_archive", side_effect=OSError("write failed")):
                with self.assertRaisesRegex(OSError, "write failed"):
                    build(arguments, [kit(1, 10)])
            self.assertFalse(arguments.output.exists())
            self.assertEqual((mod / "manifest.json").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
