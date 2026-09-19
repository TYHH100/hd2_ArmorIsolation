import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("cm14_builder", Path(__file__).parents[1] / "tools/build_cm14_isolated.py")
builder = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = builder
spec.loader.exec_module(builder)


class Cm14BuilderTests(unittest.TestCase):
    def test_rewrite_changes_only_typed_reference_values(self):
        unit = bytearray(0xA0)
        struct.pack_into("<I", unit, 0x70, 0x80)
        struct.pack_into("<IIIQQ", unit, 0x80, 2, 0x76543210, 0x11223344, 11, 12)
        mapped, changes, external = builder.rewrite_references(builder.UNIT, unit, {(builder.MATERIAL, 11): 99})
        self.assertEqual(mapped[:0x8C], unit[:0x8C])
        self.assertEqual(struct.unpack_from("<QQ", mapped, 0x8C), (99, 12))
        self.assertEqual(external, {(builder.MATERIAL, 12)})
        self.assertEqual(len(changes), 1)
        material = bytearray(0xA0)
        struct.pack_into("<Q", material, 0x18, 77)
        struct.pack_into("<I", material, 0x40, 2)
        struct.pack_into("<IIQQ", material, 0x88, 0xABCD, 0xFEDC, 11, 12)
        mapped, _, _ = builder.rewrite_references(builder.MATERIAL, material, {(builder.TEXTURE, 11): 99})
        self.assertEqual(mapped[:0x90], material[:0x90])
        self.assertEqual(struct.unpack_from("<QQ", mapped, 0x90), (99, 12))

    def test_namespaced_ids_cannot_reuse_source_or_thin_id(self):
        key = builder.UNIT, 0x7CBC9209D9736A6B
        mapping, _ = builder.make_mapping([key], [key[1]])
        self.assertEqual(mapping[key], 0x6234440435142775)
        salted, _ = builder.make_mapping([key], [key[1], mapping[key]])
        self.assertNotEqual(salted[key] >> 32, mapping[key] >> 32)
        self.assertNotEqual(salted[key], key[1])

    def test_armor_and_helmet_never_share_private_dependencies(self):
        keys = [(builder.MATERIAL, 0xE61E4053C9BA5788), (builder.TEXTURE, 11)]
        armor, _ = builder.make_mapping(keys, [key[1] for key in keys], builder.KIT_ID)
        helmet, rows = builder.make_mapping(keys, list(armor.values()), builder.HELMET_KIT_ID)
        self.assertFalse(set(armor.values()) & set(helmet.values()))
        self.assertFalse({v >> 32 for v in armor.values()} & {v >> 32 for v in helmet.values()})
        self.assertTrue(all(row["kit"] == "203f720c" for row in rows))
        self.assertTrue(all("kit_203f720c/" in row["name"] for row in rows))

    def test_selection_includes_helmet_but_not_shared_kit_owners(self):
        kits = json.loads((Path(__file__).parents[1] / "docs/armor-isolation-live-kits.json").read_text(encoding="utf-8"))
        target_ids = {f"{builder.KIT_ID:08x}", f"{builder.HELMET_KIT_ID:08x}"}
        units = {int(p["resources"]["unit"], 16) for k in kits if k["id"] in target_ids
                 for b in k["bodies"] for p in b["pieces"] if p["slot"] != 1}
        keys = [(builder.UNIT, u) for u in units | set(range(1, 10))]
        keys += [(builder.MATERIAL, 99)] + [(builder.TEXTURE, i) for i in range(11)]
        entries = [builder.Entry((value, kind) + (0,) * 11) for kind, value in keys]
        plans = builder.select_targets(kits, entries)
        self.assertEqual([plan[0]["id"] for plan in plans], ["38aa207d", "203f720c"])
        self.assertEqual([len(plan[2]) for plan in plans], [38, 13])
        helmet_units = {entry.key[1] for entry in plans[1][2] if entry.key[0] == builder.UNIT}
        self.assertEqual(helmet_units, {0xDB8AD4132CEBF885})
        retained = {entry.key for _, _, selected in plans for entry in selected}
        self.assertEqual(len(set(keys) - retained), 9)
        with self.assertRaises(ValueError):
            builder.select_targets(kits, [e for e in entries if e.key[1] != 0xDB8AD4132CEBF885])

    def test_repack_three_lanes_and_buffer_sizes(self):
        header = bytearray(72)
        struct.pack_into("<III", header, 0, builder.MAGIC, 1, 2)
        struct.pack_into("<QQ", header, 32, 0xDEADBEEF, 0xDEADBEEF)
        types = [(0, 0, builder.TEXTURE, 2, 0, 16, 64)]
        entries = [builder.Entry((11, builder.TEXTURE, 272, 0, 0, 777, 888, 3, 4, 5, 16, 64, 9)),
                   builder.Entry((12, builder.TEXTURE, 288, 64, 64, 777, 888, 2, 2, 3, 16, 64, 10))]
        mapping = {(builder.TEXTURE, 11): 101, (builder.TEXTURE, 12): 102}
        table, old, new, sizes = builder.plan_archive(header, types, entries, mapping)
        self.assertEqual(struct.unpack_from("<QQ", table, 32), (512, 512))
        self.assertEqual(new[1].values[5:7], (256, 256))
        self.assertEqual([e.values[12] for e in new], [0, 1])
        builder.validate_segments(new, sizes, len(table))
        with tempfile.TemporaryDirectory() as temporary:
            source, target = Path(temporary) / "source", Path(temporary) / "target"
            for lane, suffix in enumerate(builder.SUFFIXES):
                original = bytearray(max(e.offsets[lane] + e.sizes[lane] for e in entries))
                for i, entry in enumerate(entries):
                    at, size = entry.offsets[lane], entry.sizes[lane]
                    original[at:at + size] = bytes([65 + lane + i]) * size
                Path(str(source) + suffix).write_bytes(original)
            payloads = {entry.key: bytes([65 + i]) * entry.sizes[0] for i, entry in enumerate(entries)}
            builder.write_archive(source, target, table, old, new, payloads, sizes)
            self.assertEqual(builder.parse_toc(target.read_bytes())[2], new)
            for lane, suffix in enumerate(builder.SUFFIXES):
                actual = Path(str(target) + suffix).read_bytes()
                self.assertEqual(len(actual), sizes[lane])
                for i, entry in enumerate(new):
                    at, size = entry.offsets[lane], entry.sizes[lane]
                    self.assertEqual(actual[at:at + size], bytes([65 + lane + i]) * size)

    def test_rejects_truncation_overlap_and_invalid_reference_table(self):
        entry = builder.Entry((11, builder.TEXTURE, 80, 0, 0, 0, 0, 8, 0, 0, 16, 64, 0))
        with self.assertRaises(ValueError):
            builder.validate_segments([entry], [87, 0, 0])
        with self.assertRaises(ValueError):
            builder.validate_segments([entry, entry], [100, 0, 0])
        bad_unit = bytearray(0x74)
        struct.pack_into("<I", bad_unit, 0x70, 0x1000)
        with self.assertRaises(ValueError):
            builder.reference_fields(builder.UNIT, bad_unit)

    def test_empty_lanes_may_point_past_eof_alignment(self):
        entry = builder.Entry((11, builder.TEXTURE, 80, 16, 16, 0, 0, 8, 0, 0, 16, 64, 0))
        builder.validate_segments([entry], [88, 8, 8])
        values = list(entry.values)
        values[8] = 1
        with self.assertRaises(ValueError):
            builder.validate_segments([builder.Entry(tuple(values))], [88, 8, 8])


if __name__ == "__main__":
    unittest.main()
