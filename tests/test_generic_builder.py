import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import build_generic_isolated as builder

archive = builder.archive


def unit(material_id):
    data = bytearray(0x90)
    struct.pack_into("<I", data, 0x70, 0x80)
    struct.pack_into("<IIQ", data, 0x80, 1, 0x12345678, material_id)
    return bytes(data)


def material(texture_id, base=0):
    data = bytearray(0x94)
    struct.pack_into("<Q", data, 0x18, base)
    struct.pack_into("<I", data, 0x40, 1)
    struct.pack_into("<IQ", data, 0x88, 0x11223344, texture_id)
    return bytes(data)


def kit(value, unit_id, kind=1):
    return {"id": f"{value:08x}", "archive": f"{value + 100:016x}", "type": kind, "passive": 0,
            "bodies": [{"type": 3, "pieces": [
                {"slot": 0, "type": 0, "weight": 0, "tone_variations": 0,
                 "resources": {key: f"{unit_id if key == 'unit' else 0:016x}" for key in archive.FIELD_OFFSETS}}
            ]}]}


def fixture(root, resources=None, gpu=b"", create_empty_lanes=True):
    if resources is None:
        resources = {(archive.UNIT, 10): unit(20), (archive.MATERIAL, 20): material(30),
                     (archive.TEXTURE, 30): b"texture"}
    path = root / "source/0123456789abcdef.patch_1"
    path.parent.mkdir(parents=True)
    entries, types = [], []
    for index, (key, payload) in enumerate(resources.items()):
        entries.append(archive.Entry((key[1], key[0], 0, 0, 0, 0, 0, len(payload), 0,
                                      len(gpu) if index == 0 else 0, 16, 16, index)))
    for kind in sorted({key[0] for key in resources}):
        types.append((0, 0, kind, sum(key[0] == kind for key in resources), 0, 0, 0))
    header = bytearray(72)
    struct.pack_into("<III", header, 0, archive.MAGIC, len(types), len(entries))
    table, original, relocated, sizes = archive.plan_archive(header, types, entries,
                                                           {entry.key: entry.key[1] for entry in entries})
    main = bytearray(sizes[0])
    main[:len(table)] = table
    gpu_data = bytearray(sizes[2])
    for before, after in zip(original, relocated):
        main[after.offsets[0]:after.offsets[0] + after.sizes[0]] = resources[before.key]
        if after.sizes[2]:
            gpu_data[after.offsets[2]:after.offsets[2] + after.sizes[2]] = gpu
    path.write_bytes(main)
    if create_empty_lanes:
        Path(str(path) + ".stream").write_bytes(b"")
    if gpu_data or create_empty_lanes:
        Path(str(path) + ".gpu_resources").write_bytes(gpu_data)
    return path


class FakeReader:
    def __init__(self, *args):
        pass

    def entries(self, name):
        return {}


class GenericBuilderTests(unittest.TestCase):
    def test_shared_unit_candidates_never_auto_select(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = builder.load_source(fixture(Path(temporary)))
            kits = [kit(1, 10), kit(2, 10)]
            choices = builder.candidates(kits, source)
            self.assertEqual([row["id"] for row in choices], ["00000001", "00000002"])
            self.assertTrue(all(row["supported"] for row in choices))
            with self.assertRaisesRegex(ValueError, "Explicit"):
                builder.select_targets(kits, source, [])
            self.assertEqual(builder.select_targets(kits, source, ["1"]), kits[:1])
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                builder.select_targets(kits, source, ["1", "00000001"])

    def test_partial_unit_and_unsupported_kit_are_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = builder.load_source(fixture(Path(temporary)))
            partial = kit(1, 10)
            partial["bodies"][0]["pieces"].append(kit(9, 99)["bodies"][0]["pieces"][0])
            choices = builder.candidates([partial, kit(2, 10, 2)], source)
            self.assertEqual((choices[0]["unit_matched"], choices[0]["unit_total"]), (1, 2))
            self.assertFalse(any(row["supported"] for row in choices))
            with self.assertRaisesRegex(ValueError, "partial replacements"):
                builder.select_targets([partial], source, ["1"])

    def test_missing_empty_lanes_allowed_nonempty_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = fixture(Path(temporary), create_empty_lanes=False)
            source = builder.load_source(path)
            self.assertEqual([row["exists"] for row in source.lanes], [True, False, False])
            self.assertEqual(source.lanes[1]["sha256"], builder.EMPTY_SHA256)
        with tempfile.TemporaryDirectory() as temporary:
            path = fixture(Path(temporary), gpu=b"geometry")
            Path(str(path) + ".gpu_resources").unlink()
            with self.assertRaisesRegex(ValueError, "Missing nonempty"):
                builder.load_source(path)

    def test_unknown_source_type_and_ambiguous_source_directory_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = fixture(Path(temporary), {(123, 456): b"unknown"})
            with self.assertRaisesRegex(ValueError, "Unsupported source resource"):
                builder.load_source(path)
            path.with_name("fedcba9876543210.patch_2").write_bytes(path.read_bytes())
            with self.assertRaisesRegex(ValueError, "contains 2"):
                builder.resolve_source(path.parent)

    def test_namespace_tracks_all_lane_hashes_targets_and_repair_rules(self):
        lanes = [{"suffix": suffix, "sha256": builder.EMPTY_SHA256} for suffix in archive.SUFFIXES]
        identity = builder.package_identity(lanes, [kit(1, 10)])
        self.assertEqual(len(identity), 24)
        other = [dict(row) for row in lanes]
        other[2]["sha256"] = "1" * 64
        self.assertNotEqual(identity, builder.package_identity(other, [kit(1, 10)]))
        self.assertNotEqual(identity, builder.package_identity(lanes, [kit(2, 10)]))
        with patch.object(builder, "REPAIR_CATALOG", "new-rule"):
            self.assertNotEqual(identity, builder.package_identity(lanes, [kit(1, 10)]))
        self.assertEqual(builder.package_identity(lanes, [kit(1, 10), kit(2, 10)]),
                         builder.package_identity(lanes, [kit(2, 10), kit(1, 10)]))

    def test_shared_scope_and_required_resources_follow_each_closure(self):
        plans = [(kit(1, 10), {(archive.UNIT, 10), (archive.MATERIAL, 20), (archive.TEXTURE, 30)}),
                 (kit(2, 10), {(archive.UNIT, 10), (archive.MATERIAL, 20), (archive.TEXTURE, 31)})]
        shared, mappings, rows, required = builder.make_resource_mappings(plans, {10, 20, 30, 31}, "package_a")
        self.assertEqual(len(rows), 5)
        self.assertNotEqual(mappings["00000001"][archive.UNIT, 10], mappings["00000002"][archive.UNIT, 10])
        self.assertEqual(mappings["00000001"][archive.MATERIAL, 20], mappings["00000002"][archive.MATERIAL, 20])
        self.assertEqual(len(required), 6)
        first = {row["target"] for row in required if row["kit"] == "00000001"}
        self.assertNotIn(f"{shared[archive.TEXTURE, 31]:016x}", first)
        other_rows = builder.make_resource_mappings(plans, {10, 20, 30, 31}, "package_b")[2]
        self.assertFalse({row["target"] for row in rows} & {row["target"] for row in other_rows})
        self.assertEqual(len({int(row["target"], 16) >> 32 for row in rows}), len(rows))

    def test_coexisting_targets_conflict_and_high32_are_reserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            value = {"expected_game_dll_sha256": archive.DLL_SHA256,
                     "targets": [{"kit": "00000001"}],
                     "mapping": [{"target": "1234567800000001", "type": f"{archive.UNIT:016x}"}]}
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "same Kit"):
                builder.read_coexist([path], [kit(1, 10)])
            reserved, records = builder.read_coexist([path], [kit(2, 10)])
            self.assertEqual(reserved, {0x1234567800000001})
            self.assertEqual(len(records), 1)
            with patch.object(archive, "murmur64a", side_effect=[0x1234567800000002, 0x8765432100000001]):
                _, _, rows, _ = builder.make_resource_mappings([(kit(2, 10), {(archive.UNIT, 10)})], reserved, "abc")
            self.assertEqual(rows[0]["target"], "8765432100000001")

    def test_unknown_game_or_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dll = root / "data/game/game.dll"
            dll.parent.mkdir(parents=True)
            dll.write_bytes(b"unsupported")
            snapshot = root / "kits.json"
            snapshot.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unsupported game.dll"):
                builder.validate_version(root, snapshot)
            with patch.object(archive, "sha256_file", side_effect=[archive.DLL_SHA256, "other"]):
                with self.assertRaisesRegex(ValueError, "snapshot differs"):
                    builder.validate_version(root, snapshot)

    def test_external_dependencies_reject_modified_texture_or_base(self):
        checked = {"checked": [{"base_materials": ["0000000000000014"],
                                "modified_texture_overlap": []}], "complete": True}
        with patch.object(archive, "inspect_external", return_value=checked):
            with self.assertRaisesRegex(ValueError, "BaseMaterial"):
                builder.inspect_external(None, [], set(), {(archive.MATERIAL, 20): None})
        with patch.object(archive, "inspect_external", return_value={"checked": [], "complete": False}):
            with self.assertRaisesRegex(ValueError, "unresolved"):
                builder.inspect_external(None, [], set(), {})

    def test_lod_repair_applies_only_to_exact_catalog_source(self):
        source_id = 0x781134771DD69FBE
        data = bytearray(0x160)
        for offset, old, _ in builder.b01.HELMET_LOD_FIELDS:
            struct.pack_into("<I", data, offset, old)
        self.assertEqual(builder.repair_known_helmet(source_id, data), (data, []))
        with patch.dict(builder.b01.HELMET_LOD_SOURCE_HASHES, {source_id: hashlib.sha256(data).hexdigest()}):
            result, changes = builder.repair_known_helmet(source_id, data)
        self.assertEqual(len(changes), 4)
        self.assertEqual(struct.unpack_from("<I", result, 0xDC)[0], 14)
        self.assertEqual(builder.repair_known_helmet(999, data), (data, []))

    def test_complete_build_roundtrip_empty_lanes_and_per_kit_closure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            resources = {(archive.UNIT, 10): unit(20), (archive.UNIT, 11): unit(21),
                         (archive.MATERIAL, 20): material(30), (archive.MATERIAL, 21): material(31),
                         (archive.TEXTURE, 30): b"first", (archive.TEXTURE, 31): b"second",
                         (archive.TEXTURE, 40): b"unused"}
            source = fixture(root, resources, create_empty_lanes=False)
            before = source.read_bytes()
            args = SimpleNamespace(source=source, game=root / "game", reader_tools=root / "reader",
                                   kits=root / "kits.json", target=["1", "2"], output=root / "output",
                                   coexist_manifest=[])
            with patch.object(builder, "validate_version", return_value=[kit(1, 10), kit(2, 11)]), \
                    patch.object(archive, "VanillaReader", FakeReader):
                manifest = builder.build(args)
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(len(manifest["mapping"]), 6)
            self.assertEqual(len(manifest["excluded_resources"]), 1)
            self.assertEqual(len(manifest["required_resources"]), 6)
            self.assertTrue(manifest["payloads_verified"])
            self.assertFalse(manifest["game_runtime_verified"])
            self.assertEqual([row["size"] for row in manifest["output"]][1:], [0, 0])
            header = (args.output / "generated/generic_resource_map.hpp").read_text(encoding="ascii")
            self.assertIn("RequiredResource required_resources[]", header)
            self.assertIn("namespace generic_isolation", header)
            with self.assertRaisesRegex(ValueError, "empty staging"):
                builder.validate_output(args.output, builder.load_source(source), args.game)

    def test_failed_write_cleans_only_own_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = fixture(root)
            before = source.read_bytes()
            args = SimpleNamespace(source=source, game=root / "game", reader_tools=root / "reader",
                                   kits=root / "kits.json", target=["1"], output=root / "output",
                                   coexist_manifest=[])
            def fail(source, destination, *args):
                destination.parent.mkdir(parents=True)
                destination.write_bytes(b"partial")
                raise OSError("test write failure")
            with patch.object(builder, "validate_version", return_value=[kit(1, 10)]), \
                    patch.object(archive, "VanillaReader", FakeReader), \
                    patch.object(builder, "write_archive", side_effect=fail):
                with self.assertRaisesRegex(OSError, "test write failure"):
                    builder.build(args)
            self.assertFalse(args.output.exists())
            self.assertEqual(source.read_bytes(), before)
            with self.assertRaisesRegex(ValueError, "source mod"):
                builder.validate_output(source.parent / "nested", builder.load_source(source), args.game)
            with self.assertRaisesRegex(ValueError, "game directory"):
                builder.validate_output(args.game / "data/new", builder.load_source(source), args.game)


if __name__ == "__main__":
    unittest.main()
