import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import build_generic_isolated as generic
import build_modular_isolated as modular
from test_generic_builder import FakeReader, fixture, kit, unit

archive = generic.archive


def bones(name=b"bone_a"):
    return struct.pack("<IIfIII", 2, 1, 0.25, 0x11223344, 0x55667788, 7) + name + b"\0bone_b\0"


def skeleton_unit(bones_id, material=0):
    data = bytearray(unit(material))
    struct.pack_into("<Q", data, 8, bones_id)
    return bytes(data)


class BonesIsolationTests(unittest.TestCase):
    def test_bones_reference_is_typed_and_independent_of_materials(self):
        self.assertEqual(archive.murmur64a(b"bones"), archive.BONES)
        data = bytearray(0x80)
        struct.pack_into("<Q", data, 8, 10)
        self.assertEqual(archive.reference_fields(archive.UNIT, data), [(archive.BONES, 8)])
        unchanged, changes, _ = archive.rewrite_references(archive.UNIT, data, {(archive.UNIT, 10): 99})
        self.assertEqual(unchanged, data)
        self.assertEqual(changes, [])
        rewritten, changes, _ = archive.rewrite_references(archive.UNIT, data, {(archive.BONES, 10): 88})
        self.assertEqual(struct.unpack_from("<Q", rewritten, 8)[0], 88)
        self.assertEqual(rewritten[:8], data[:8])
        self.assertEqual(rewritten[16:], data[16:])
        self.assertEqual(changes[0]["kind"], "bones")

    def test_bones_payload_is_preserved_and_malformed_names_are_rejected(self):
        original = bones()
        rewritten, changes, external = archive.rewrite_references(archive.BONES, original, {})
        self.assertEqual(rewritten, original)
        self.assertEqual((changes, external), ([], set()))
        for bad in (b"short", struct.pack("<II", 0xffffffff, 1), original[:-1]):
            with self.subTest(payload=bad), self.assertRaises(ValueError):
                archive.reference_fields(archive.BONES, bad)

    def test_generic_build_clones_bones_once_and_tracks_each_kit_dependency(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = fixture(root, {(archive.UNIT, 10): skeleton_unit(10),
                                    (archive.BONES, 10): bones(), (archive.BONES, 11): bones(b"unused")})
            arguments = SimpleNamespace(source=source, game=root / "game", reader_tools=root / "reader",
                                        kits=root / "kits.json", target=["1", "2"],
                                        output=root / "output", coexist_manifest=[])
            with patch.object(generic, "validate_version", return_value=[kit(1, 10), kit(2, 10)]), \
                    patch.object(archive, "VanillaReader", FakeReader):
                manifest = generic.build(arguments)
            rows = [r for r in manifest["mapping"] if r["kind"] == "bones"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["kit"], "00000000")
            self.assertEqual(sum(r["type"] == f"{archive.BONES:016x}" for r in manifest["required_resources"]), 2)
            output = arguments.output / "patch" / generic.PATCH_NAME
            self.verify_unit_and_bones(output, manifest["mapping"], bones())
            self.assertEqual(manifest["excluded_resources"], [{"type": f"{archive.BONES:016x}",
                                                              "source": "000000000000000b"}])

    def test_modular_bones_variants_keep_payloads_and_unselected_unit_references_private(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mod = root / "mod"
            base = fixture(mod / "base", {(archive.UNIT, 10): skeleton_unit(10),
                                          (archive.BONES, 10): bones(),
                                          (archive.UNIT, 11): skeleton_unit(11),
                                          (archive.BONES, 11): bones(b"unused")})
            option = fixture(mod / "option", {(archive.BONES, 10): bones(b"option")})
            document = {"Version": 1, "Options": [
                {"Name": "Base", "Include": ["base/source"]},
                {"Name": "Optional bones", "Include": ["option/source"]}]}
            original = json.dumps(document).encode()
            (mod / "manifest.json").write_bytes(original)
            arguments = SimpleNamespace(source=mod, game=root / "game", reader_tools=root / "reader",
                                        kits=root / "kits.json", target=["1"], output=root / "output",
                                        coexist_manifest=[])
            with patch.object(generic, "validate_version", return_value=[kit(1, 10)]), \
                    patch.object(archive, "VanillaReader", FakeReader):
                manifest = modular.build(arguments)
            rows = manifest["mapping"] + manifest["preserved_unbound_mapping"]
            preserved = arguments.output / manifest["modular"]["mod_directory"]
            self.assertEqual((preserved / "manifest.json").read_bytes(), original)
            self.verify_unit_and_bones(preserved / base.relative_to(mod), rows, bones(), unused=True)
            data = (preserved / option.relative_to(mod)).read_bytes()
            entry = archive.parse_toc(data)[2][0]
            bone = next(r for r in rows if r["kind"] == "bones" and int(r["source"], 16) == 10)
            self.assertEqual(entry.key, (archive.BONES, int(bone["target"], 16)))
            self.assertEqual(data[entry.offsets[0]:entry.offsets[0] + entry.sizes[0]], bones(b"option"))

    def test_missing_external_bones_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "External Bones.*unresolved"):
            generic.inspect_external(FakeReader(), ["archive"], {(archive.BONES, 7)}, {})

    def verify_unit_and_bones(self, output, rows, expected, unused=False):
        data = output.read_bytes()
        entries = {e.key: e for e in archive.parse_toc(data)[2]}
        by_source = {(int(r["type"], 16), int(r["source"], 16)): int(r["target"], 16) for r in rows}
        for row in rows:
            kind, source, target = (int(row[k], 16) for k in ("type", "source", "target"))
            entry = entries[kind, target]
            payload = data[entry.offsets[0]:entry.offsets[0] + entry.sizes[0]]
            if kind == archive.UNIT:
                self.assertEqual(struct.unpack_from("<Q", payload, 8)[0], by_source[archive.BONES, source])
                self.assertNotEqual(by_source[archive.BONES, source], target)
            else:
                self.assertEqual(payload, bones(b"unused") if unused and source == 11 else expected)


if __name__ == "__main__":
    unittest.main()
