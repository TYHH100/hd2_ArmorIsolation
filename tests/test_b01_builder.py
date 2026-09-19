import json
import hashlib
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import build_b01_isolated as builder

archive = builder.archive


def unit(material):
    data = bytearray(0x90)
    struct.pack_into("<I", data, 0x70, 0x80)
    struct.pack_into("<IIQ", data, 0x80, 1, 0x12345678, material)
    return data


def material(texture, base=0):
    data = bytearray(0x94)
    struct.pack_into("<Q", data, 0x18, base)
    struct.pack_into("<I", data, 0x40, 1)
    struct.pack_into("<IQ", data, 0x88, 0x11223344, texture)
    return data


class B01BuilderTests(unittest.TestCase):
    def test_all_four_variants_and_helmets_are_explicit_targets(self):
        kits = json.loads((Path(__file__).parents[1] / "docs/armor-isolation-live-kits.json").read_text(encoding="utf-8"))
        targets = builder.select_targets(kits)
        self.assertEqual([len(builder.target_pieces(k)) for k in targets], [22] * 4 + [1] * 4)
        self.assertEqual(len({k["id"] for k in targets}), 8)
        with self.assertRaises(ValueError):
            builder.select_targets([k for k in kits if k["id"] != "df8e4ada"])

    def test_dependency_closure_excludes_unused_materials_and_default_cape(self):
        target = {"id": "test", "bodies": [{"pieces": [
            {"slot": 2, "resources": {"unit": "a", "material_lut": "21"}},
            {"slot": 1, "resources": {"unit": "b", "material_lut": "0"}},
        ]}]}
        resources = {(archive.UNIT, 10): unit(20), (archive.UNIT, 11): unit(21),
                     (archive.MATERIAL, 20): material(30, 100),
                     (archive.MATERIAL, 21): material(31),
                     (archive.TEXTURE, 30): b"texture", (archive.TEXTURE, 31): b"unused",
                     (archive.TEXTURE, 33): b"dynamic"}
        data, entries = bytearray(), {}
        for key, payload in resources.items():
            entries[key] = archive.Entry((key[1], key[0], len(data), 0, 0, 0, 0, len(payload), 0, 0, 16, 16, 0))
            data.extend(payload)
        selected, external = builder.dependency_closure(target, data, entries)
        self.assertEqual(selected, {(archive.UNIT, 10), (archive.MATERIAL, 20),
                                    (archive.TEXTURE, 30), (archive.TEXTURE, 33)})
        self.assertEqual(external, {(archive.MATERIAL, 100)})
        del entries[archive.UNIT, 10]
        with self.assertRaises(ValueError):
            builder.dependency_closure(target, data, entries)

    def test_shared_materials_are_mod_private_while_units_stay_kit_private(self):
        keys = {(archive.UNIT, 10), (archive.MATERIAL, 20), (archive.TEXTURE, 30)}
        plans = [({"id": kit_id}, keys) for kit_id, _, _ in builder.TARGETS]
        shared, mappings, rows = builder.make_resource_mappings(plans, [10, 20, 30])
        self.assertEqual(len(rows), 10)
        self.assertEqual(len(shared), 2)
        self.assertEqual(len({m[archive.UNIT, 10] for m in mappings.values()}), 8)
        self.assertEqual(len({m[archive.MATERIAL, 20] for m in mappings.values()}), 1)
        self.assertEqual(len({m[archive.TEXTURE, 30] for m in mappings.values()}), 1)
        self.assertEqual(sum(r["kit"] == "00000000" for r in rows), 2)
        self.assertTrue(all(r["kit"] != "00000000" for r in rows if r["kind"] == "unit"))
        self.assertFalse({10, 20, 30} & {int(r["target"], 16) for r in rows})
        self.assertEqual(len({int(r["target"], 16) >> 32 for r in rows}), len(rows))

    def test_helmet_lod_repair_is_source_guarded_and_preserves_other_bytes(self):
        source_id = 0x781134771DD69FBE
        data = bytearray([0xAA] * 0x160)
        for offset, before, _ in builder.HELMET_LOD_FIELDS:
            struct.pack_into("<I", data, offset, before)
        with self.assertRaises(ValueError):
            builder.repair_helmet_lod(source_id, data)
        with patch.dict(builder.HELMET_LOD_SOURCE_HASHES, {source_id: hashlib.sha256(data).hexdigest()}):
            fixed, changes = builder.repair_helmet_lod(source_id, data)
        allowed = {i for offset, _, _ in builder.HELMET_LOD_FIELDS for i in range(offset, offset + 4)}
        self.assertEqual(len(changes), 4)
        for index in range(len(data)):
            if index not in allowed:
                self.assertEqual(data[index], fixed[index])
        for offset, _, desired in builder.HELMET_LOD_FIELDS:
            self.assertEqual(struct.unpack_from("<I", fixed, offset)[0], desired)
        self.assertEqual(builder.repair_helmet_lod(0xBC20D0B4EFFF128C, data), (data, []))
        struct.pack_into("<I", data, 0xDC, 99)
        with patch.dict(builder.HELMET_LOD_SOURCE_HASHES, {source_id: hashlib.sha256(data).hexdigest()}):
            with self.assertRaises(ValueError):
                builder.repair_helmet_lod(source_id, data)


if __name__ == "__main__":
    unittest.main()
