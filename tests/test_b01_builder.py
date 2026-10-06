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


SELECTOR_BASE = 0xA8
VANILLA_MESHES = [0x11, 0x22, 0x33, 0x44, 0x55]
# A replacement Unit regularly inserts helper meshes in front of the vanilla ones, which shifts
# every MeshInfo index; the shift differs per Unit, so only an identifier match is safe.
PRIVATE_MESHES = [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF, 0x10, 0x20, 0x30, 0x40] + VANILLA_MESHES


def synthetic_unit(mesh_ids, selectors, size=0x600):
    """Minimal Unit payload: one LOD group with one entry holding every selector."""
    data = bytearray(size)
    struct.pack_into("<I", data, 0x30, 0x70)
    struct.pack_into("<I", data, 0x64, 0x100)
    struct.pack_into("<I", data, 0x70, 1)
    struct.pack_into("<I", data, 0x74, 0x0C)
    struct.pack_into("<I", data, 0x8C, 1)
    struct.pack_into("<I", data, 0x90, 0x20)
    struct.pack_into("<I", data, 0xA4, len(selectors))
    for index, value in enumerate(selectors):
        struct.pack_into("<I", data, SELECTOR_BASE + index * 4, value)
    struct.pack_into("<I", data, 0x100, len(mesh_ids))
    for index, mesh_id in enumerate(mesh_ids):
        at = 0x140 + index * 0x30
        struct.pack_into("<I", data, 0x104 + index * 4, at - 0x100)
        struct.pack_into("<I", data, at + 0x28, mesh_id)
    return data


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

    def test_lod_repair_matches_mesh_identity_and_preserves_other_bytes(self):
        vanilla = synthetic_unit(VANILLA_MESHES, [4, 3, 2, 1])
        source = synthetic_unit(PRIVATE_MESHES, [4, 3, 2, 1])
        fixed, changes = archive.repair_unit_lod(source, vanilla)
        self.assertEqual([row["before"] for row in changes], [4, 3, 2, 1])
        self.assertEqual([row["after"] for row in changes], [14, 13, 12, 11])
        allowed = {row["offset"] + index for row in changes for index in range(4)}
        for index in range(len(source)):
            if index not in allowed:
                self.assertEqual(source[index], fixed[index])
        # The same unit repaired twice must stay unchanged: the rule is idempotent.
        again, empty = archive.repair_unit_lod(fixed, vanilla)
        self.assertEqual(empty, [])
        self.assertEqual(again, fixed)

    def test_lod_repair_rejects_ambiguous_or_edited_sources(self):
        vanilla = synthetic_unit(VANILLA_MESHES, [4, 3, 2, 1])
        with self.assertRaises(ValueError):
            archive.repair_unit_lod(synthetic_unit(PRIVATE_MESHES, [4, 3, 2]), vanilla)
        # A selector the author edited on purpose is never overwritten.
        with self.assertRaises(ValueError):
            archive.repair_unit_lod(synthetic_unit(PRIVATE_MESHES, [9, 3, 2, 1]), vanilla)
        # A vanilla mesh the replacement dropped cannot be restored.
        dropped = [mesh for mesh in PRIVATE_MESHES if mesh != 0x44]
        with self.assertRaises(ValueError):
            archive.repair_unit_lod(synthetic_unit(dropped, [4, 3, 2, 1]), vanilla)
        # Duplicate MeshInfo identifiers make the target index ambiguous.
        duplicated = [0x11, 0x11, 0x33, 0x44, 0x55] + PRIVATE_MESHES[:10]
        with self.assertRaises(ValueError):
            archive.repair_unit_lod(synthetic_unit(duplicated, [4, 3, 2, 1]), vanilla)

    def test_lod_repair_preserves_fully_custom_mesh_set(self):
        vanilla = synthetic_unit(VANILLA_MESHES, [4, 3, 2, 1])
        custom_meshes = [0x101, 0x202, 0x303, 0x404, 0x505]
        source = synthetic_unit(custom_meshes, [4, 3, 2, 1])
        fixed, changes = archive.repair_unit_lod(source, vanilla)
        self.assertEqual(changes, [])
        self.assertEqual(fixed, source)

    def test_recorded_helmet_rule_still_agrees_with_the_generic_match(self):
        source_id = 0x781134771DD69FBE
        vanilla = synthetic_unit(VANILLA_MESHES, [4, 3, 2, 1])
        source = synthetic_unit(PRIVATE_MESHES, [4, 3, 2, 1])
        digest = hashlib.sha256(source).hexdigest()
        recorded = ((SELECTOR_BASE, 4, 14), (SELECTOR_BASE + 4, 3, 13),
                    (SELECTOR_BASE + 8, 2, 12), (SELECTOR_BASE + 12, 1, 11))
        with patch.dict(builder.HELMET_LOD_SOURCE_HASHES, {source_id: digest}):
            with patch.object(builder, "HELMET_LOD_FIELDS", recorded):
                fixed, changes = builder.repair_helmet_lod(source_id, source, vanilla)
        self.assertEqual(len(changes), 4)
        self.assertEqual(struct.unpack_from("<I", fixed, SELECTOR_BASE)[0], 14)
        # Drift between the generic rule and the verified baseline must stop the build.
        drifted = ((SELECTOR_BASE, 9, 14),) + recorded[1:]
        with patch.dict(builder.HELMET_LOD_SOURCE_HASHES, {source_id: digest}):
            with patch.object(builder, "HELMET_LOD_FIELDS", drifted):
                with self.assertRaises(ValueError):
                    builder.repair_helmet_lod(source_id, source, vanilla)
        # A source repaired outside the generator (the mod manager repairs LOD selectors) is
        # accepted: the generic rule finds nothing to change.
        repaired_source = synthetic_unit(PRIVATE_MESHES, [14, 13, 12, 11])
        with patch.dict(builder.HELMET_LOD_SOURCE_HASHES,
                        {source_id: hashlib.sha256(repaired_source).hexdigest()}):
            with patch.object(builder, "HELMET_LOD_FIELDS", recorded):
                untouched, changes = builder.repair_helmet_lod(source_id, repaired_source, vanilla)
        self.assertEqual(changes, [])
        self.assertEqual(untouched, repaired_source)
        # A selector that is neither the original nor the repaired value means the layout moved.
        moved = synthetic_unit(PRIVATE_MESHES, [7, 3, 2, 1])
        with patch.dict(builder.HELMET_LOD_SOURCE_HASHES, {source_id: hashlib.sha256(moved).hexdigest()}):
            with patch.object(builder, "HELMET_LOD_FIELDS", recorded):
                with self.assertRaises(ValueError):
                    builder.repair_helmet_lod(source_id, moved, vanilla)
        # A unit outside the baseline still gets the generic repair without a value guard.
        generic, changes = builder.repair_helmet_lod(0xBC20D0B4EFFF128C, source, vanilla)
        self.assertEqual(len(changes), 4)
        self.assertEqual(generic, fixed)


if __name__ == "__main__":
    unittest.main()
