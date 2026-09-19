"""Build a CM-14-only private resource patch; never modify the input or game."""

from __future__ import annotations

import argparse
import bisect
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import struct
import sys

MAGIC = 0xF0000011
UNIT = 0xE0A48D0BE9A7453F
MATERIAL = 0xEAC0B497876ADEDF
TEXTURE = 0xCD4238C6A0C69E32
KINDS = {UNIT: "unit", MATERIAL: "material", TEXTURE: "texture"}
KIT_ID = 0x38AA207D
ARCHIVE_ID = 0xB0DB7F4F0A11DEBD
HELMET_KIT_ID = 0x203F720C
HELMET_ARCHIVE_ID = 0x1BF281B613081B05
DLL_SHA256 = "cc75948d90fdfde259dcb519e9933db7ffa3ccb281ce4fb89e6b1b011557470c"
SUFFIXES = ("", ".stream", ".gpu_resources")
TOC = struct.Struct("<7Q6I")
TYPE = struct.Struct("<IIQIIII")
FIELD_OFFSETS = {"unit": 0, "material_lut": 0x18, "pattern_lut": 0x20,
                 "cape_lut": 0x28, "cape_gradient": 0x30, "cape_nac": 0x38,
                 "decal_scalar_fields": 0x40, "base_data": 0x48, "decal_sheet": 0x50}


def align(value, alignment):
    if alignment <= 0 or alignment & (alignment - 1) or alignment > 65536:
        raise ValueError(f"Invalid alignment: {alignment}")
    return (value + alignment - 1) & -alignment


def murmur64a(data):
    """MurmurHash64A, seed zero, as used by Stingray resource names."""
    mask, multiplier = (1 << 64) - 1, 0xC6A4A7935BD1E995
    value = len(data) * multiplier & mask
    end = len(data) // 8 * 8
    for (word,) in struct.iter_unpack("<Q", data[:end]):
        word = word * multiplier & mask
        word ^= word >> 47
        value = (value ^ (word * multiplier & mask)) * multiplier & mask
    if end != len(data):
        value ^= int.from_bytes(data[end:], "little")
        value = value * multiplier & mask
    value ^= value >> 47
    value = value * multiplier & mask
    return value ^ (value >> 47)


@dataclass(frozen=True)
class Entry:
    values: tuple

    @property
    def key(self):
        return self.values[1], self.values[0]

    @property
    def offsets(self):
        return self.values[2:5]

    @property
    def sizes(self):
        return self.values[7:10]


def parse_toc(data):
    if len(data) < 72:
        raise ValueError("Truncated archive header")
    magic, type_count, count = struct.unpack_from("<III", data)
    end = 72 + type_count * TYPE.size + count * TOC.size
    if magic != MAGIC or end > len(data) or count > 1000000:
        raise ValueError("Invalid archive table")
    types = [TYPE.unpack_from(data, 72 + i * TYPE.size) for i in range(type_count)]
    entries = [Entry(TOC.unpack_from(data, 72 + type_count * TYPE.size + i * TOC.size))
               for i in range(count)]
    if len({entry.key for entry in entries}) != count:
        raise ValueError("Duplicate archive resource IDs")
    if Counter(e.key[0] for e in entries) != Counter({t[2]: t[3] for t in types}):
        raise ValueError("Type counts do not match entries")
    return bytes(data[:72]), types, entries


def validate_segments(entries, lengths, toc_end=0):
    for lane in range(3):
        spans = []
        for entry in entries:
            offset, size = entry.offsets[lane], entry.sizes[lane]
            if size and (offset > lengths[lane] or size > lengths[lane] - offset):
                raise ValueError(f"Resource {entry.key} exceeds lane {lane}")
            if size:
                if lane == 0 and offset < toc_end:
                    raise ValueError("Resource overlaps archive table")
                spans.append((offset, offset + size))
        spans.sort()
        if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
            raise ValueError(f"Overlapping resource ranges in lane {lane}")


def reference_fields(kind, data):
    """Return typed 64-bit reference offsets, never slot hashes or indices."""
    if kind == UNIT:
        if len(data) < 0x74:
            raise ValueError("Truncated Unit")
        at = struct.unpack_from("<I", data, 0x70)[0]
        if not at:
            return []
        if at > len(data) - 4:
            raise ValueError("Invalid Unit material table")
        count = struct.unpack_from("<I", data, at)[0]
        if at + 4 + count * 12 > len(data):
            raise ValueError("Truncated Unit material references")
        return [(MATERIAL, at + 4 + count * 4 + i * 8) for i in range(count)]
    if kind == MATERIAL:
        if len(data) < 0x88:
            raise ValueError("Truncated Material")
        count = struct.unpack_from("<I", data, 0x40)[0]
        if 0x88 + count * 12 > len(data):
            raise ValueError("Truncated Material texture references")
        return [(MATERIAL, 0x18)] + [(TEXTURE, 0x88 + count * 4 + i * 8)
                                   for i in range(count)]
    return []


def rewrite_references(kind, data, mapping):
    result = bytearray(data)
    changes, external = [], set()
    for target_kind, offset in reference_fields(kind, data):
        source = struct.unpack_from("<Q", data, offset)[0]
        if not source:
            continue
        if (target_kind, source) in mapping:
            target = mapping[target_kind, source]
            struct.pack_into("<Q", result, offset, target)
            changes.append({"offset": offset, "kind": KINDS[target_kind],
                            "source": f"{source:016x}", "target": f"{target:016x}"})
        else:
            external.add((target_kind, source))
    return bytes(result), changes, external


def make_mapping(keys, reserved, kit_id=KIT_ID, namespace="mods/cm14_isolation/v1"):
    reserved = set(reserved)
    thin = {value >> 32 for value in reserved}
    mapping, rows = {}, []
    for kind, source in sorted(keys):
        base = f"{namespace}/kit_{kit_id:08x}/{KINDS[kind]}/{source:016x}"
        salt = 0
        while True:
            name = base if not salt else f"{base}_{salt}"
            target = murmur64a(name.encode("ascii"))
            if target and target not in reserved and target >> 32 not in thin:
                break
            salt += 1
        reserved.add(target)
        thin.add(target >> 32)
        mapping[kind, source] = target
        rows.append({"kit": f"{kit_id:08x}", "kind": KINDS[kind], "type": f"{kind:016x}",
                     "source": f"{source:016x}", "target": f"{target:016x}", "name": name})
    return mapping, rows


def plan_archive(header, types, entries, mapping):
    counts = Counter(e.key[0] for e in entries)
    new_types = [(*t[:3], counts[t[2]], *t[4:]) for t in sorted(types, key=lambda t: t[2])
                 if counts[t[2]]]
    ordered = sorted(entries, key=lambda e: (e.key[0], mapping[e.key]))
    positions = [72 + len(new_types) * 32 + len(ordered) * 80, 0, 0]
    buffers = [0, 0]
    relocated = []
    for index, entry in enumerate(ordered):
        values = list(entry.values)
        values[0] = mapping[entry.key]
        for lane in range(3):
            alignment = values[10] if lane == 0 else values[11]
            positions[lane] = align(positions[lane], alignment)
            values[2 + lane] = positions[lane]
            positions[lane] += values[7 + lane]
        # Stock archives use separate 256-byte-aligned in-memory buffer offsets.
        values[5:7] = buffers
        buffers = [buffers[0] + align(values[7], 256),
                   buffers[1] + align(values[9], 256)]
        values[12] = index
        relocated.append(Entry(tuple(values)))
    result = bytearray(header)
    struct.pack_into("<II", result, 4, len(new_types), len(relocated))
    struct.pack_into("<QQ", result, 32, *buffers)
    result.extend(b"".join(TYPE.pack(*t) for t in new_types))
    result.extend(b"".join(TOC.pack(*e.values) for e in relocated))
    return bytes(result), ordered, relocated, positions


def sha256_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def copy_range(source, target, source_offset, target_offset, length):
    source.seek(source_offset)
    target.seek(target_offset)
    while length:
        block = source.read(min(length, 1024 * 1024))
        if not block:
            raise ValueError("Source data changed or became truncated")
        target.write(block)
        length -= len(block)


def write_archive(source_path, output_path, table, old_entries, new_entries, payloads, sizes):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    for lane, suffix in enumerate(SUFFIXES):
        source_file = Path(str(source_path) + suffix)
        destination = Path(str(output_path) + suffix)
        if source_file.resolve() == destination.resolve():
            raise ValueError("Output must not overwrite input")
        with source_file.open("rb") as source, destination.open("wb") as output:
            if lane == 0:
                output.write(table)
            for before, after in zip(old_entries, new_entries):
                if lane == 0:
                    output.seek(after.offsets[0])
                    output.write(payloads[before.key])
                elif after.sizes[lane]:
                    copy_range(source, output, before.offsets[lane], after.offsets[lane], after.sizes[lane])
            output.truncate(sizes[lane])


class VanillaReader:
    def __init__(self, game, reader_tools):
        sys.path.insert(0, str(reader_tools))
        from archive import GameData

        self.game = GameData(game / "data")
        data = self.game.dsar("bundles.nxa", whole=True)
        self.mappings, self.tables = {}, {}
        for i in range(struct.unpack_from("<I", data, 16)[0]):
            _, name_at, count, entries_at = struct.unpack_from("<QIII4x", data, 24 + i * 24)
            name = data[name_at:data.index(b"\0", name_at)].decode()
            self.mappings[name] = list(struct.iter_unpack("<QI3xB", data[entries_at:entries_at + count * 16]))

    def read(self, name, offset, size=None):
        rows = self.mappings[name]
        i = bisect.bisect_right([r[0] for r in rows], offset) - 1
        if i < 0:
            raise ValueError("Unmapped vanilla archive offset")
        original, logical, bundle = rows[i]
        data = self.game.dsar(f"bundles.{bundle:02d}.nxa", logical + offset - original)
        if size is not None and len(data) < size:
            raise ValueError("Truncated vanilla resource")
        return data if size is None else data[:size]

    def entries(self, name):
        if name not in self.tables:
            self.tables[name] = {e.key: e for e in parse_toc(self.read(name, 0))[2]}
        return self.tables[name]


def inspect_external(reader, archives, references, texture_ids):
    pending = {value for kind, value in references if kind == MATERIAL}
    checked, missing, visited = [], [], set()
    while pending:
        material_id = pending.pop()
        if material_id in visited:
            continue
        visited.add(material_id)
        found = next(((name, reader.entries(name)[MATERIAL, material_id]) for name in archives
                      if (MATERIAL, material_id) in reader.entries(name)), None)
        if found is None:
            missing.append(f"{material_id:016x}")
            continue
        name, entry = found
        data = reader.read(name, entry.offsets[0], entry.sizes[0])
        textures, bases = [], []
        for kind, offset in reference_fields(MATERIAL, data):
            resource = struct.unpack_from("<Q", data, offset)[0]
            if resource:
                (textures if kind == TEXTURE else bases).append(resource)
        overlap = sorted(set(textures) & texture_ids)
        checked.append({"id": f"{material_id:016x}", "archive": name,
                        "base_materials": [f"{v:016x}" for v in bases],
                        "textures": [f"{v:016x}" for v in textures],
                        "modified_texture_overlap": [f"{v:016x}" for v in overlap],
                        "main_sha256": hashlib.sha256(data).hexdigest()})
        pending.update(set(bases) - visited)
    return {"checked": checked, "unresolved_materials": sorted(missing),
            "searched_archives": archives,
            "complete": not missing and not any(r["modified_texture_overlap"] for r in checked)}


def select_targets(kits, entries):
    plans = []
    for kit_id, archive_id, kit_type, passive, body_layout, unit_count, resource_count in (
        (KIT_ID, ARCHIVE_ID, 0, 7, [(3, 7), (0, 10), (1, 10)], 26, 38),
        (HELMET_KIT_ID, HELMET_ARCHIVE_ID, 1, 0, [(3, 1)], 1, 13),
    ):
        matches = [k for k in kits if k["id"] == f"{kit_id:08x}"]
        if len(matches) != 1:
            raise ValueError(f"Expected one CM-14 target {kit_id:08x}")
        target = matches[0]
        if (target["archive"] != f"{archive_id:016x}" or target["type"] != kit_type or
                target["passive"] != passive or
                [(b["type"], len(b["pieces"])) for b in target["bodies"]] != body_layout):
            raise ValueError(f"CM-14 target identity/layout mismatch: {kit_id:08x}")
        pieces = [p for body in target["bodies"] for p in body["pieces"]]
        target_units = {int(p["resources"]["unit"], 16) for p in pieces if p["slot"] != 1}
        selected = [e for e in entries if e.key[0] in (MATERIAL, TEXTURE)
                    or e.key[0] == UNIT and e.key[1] in target_units]
        if {e.key[1] for e in selected if e.key[0] == UNIT} != target_units:
            raise ValueError(f"Input does not cover every non-cape CM-14 Unit: {kit_id:08x}")
        if len(target_units) != unit_count or len(selected) != resource_count:
            raise ValueError(f"Unexpected CM-14/source shape: {kit_id:08x}")
        if kit_type == 1 and (target_units != {0xDB8AD4132CEBF885} or pieces[0]["slot"] != 0):
            raise ValueError("Unexpected CM-14 helmet Unit or slot")
        plans.append((target, pieces, selected))
    return plans


def make_header(mapping_rows, fields, targets, source_hash, namespace="cm14_isolation"):
    lines = ["#pragma once", "#include <cstddef>", "#include <cstdint>", "", f"namespace {namespace} {{",
             f'inline constexpr char expected_game_dll_sha256[] = "{DLL_SHA256}";',
             'inline constexpr char expected_game_version[] = "1.0.0.18930";',
             f'inline constexpr char source_main_sha256[] = "{source_hash}";',
             "struct ResourceMapping { std::uint32_t kit_id; std::uint64_t type, source, target; };",
             "inline constexpr ResourceMapping resources[] = {"]
    lines.extend(f'    {{0x{r["kit"]}U, 0x{r["type"]}ULL, 0x{r["source"]}ULL, 0x{r["target"]}ULL}},'
                 for r in mapping_rows)
    lines.extend(["};", "struct FieldMapping { std::uint32_t kit_id, field_offset; std::uint64_t source, target; };",
                  "inline constexpr FieldMapping piece_fields[] = {"])
    lines.extend(f'    {{0x{kit:08x}U, 0x{offset:02x}U, 0x{source:016x}ULL, 0x{destination:016x}ULL}},'
                 for kit, offset, source, destination in fields)
    lines.extend(["};", "struct ExpectedBody { std::uint32_t body_type, piece_count; };",
                  "struct ExpectedPiece {", "    std::uint32_t body_type, slot, piece_type, weight, tone_variations;",
                  "    std::uint64_t source_unit;", "};",
                  "struct TargetKit {", "    std::uint32_t id; std::uint64_t archive; std::uint32_t type, passive;",
                  "    const ExpectedBody *bodies; std::size_t body_count;",
                  "    const ExpectedPiece *pieces; std::size_t piece_count;",
                  "    std::size_t expected_unit_changes;", "};"])
    for target in targets:
        lines.append(f'inline constexpr ExpectedBody bodies_{target["id"]}[] = {{')
        lines.extend(f'    {{{b["type"]}U, {len(b["pieces"])}U}},' for b in target["bodies"])
        lines.extend(["};", f'inline constexpr ExpectedPiece pieces_{target["id"]}[] = {{'])
        for body in target["bodies"]:
            for piece in body["pieces"]:
                lines.append(f'    {{{body["type"]}U, {piece["slot"]}U, {piece["type"]}U, '
                             f'{piece["weight"]}U, {piece["tone_variations"]}U, '
                             f'0x{piece["resources"]["unit"]}ULL}},')
        lines.append("};")
    lines.append("inline constexpr TargetKit targets[] = {")
    for target in targets:
        pieces = [p for b in target["bodies"] for p in b["pieces"]]
        changes = sum(p["slot"] != 1 for p in pieces)
        lines.append(f'    {{0x{target["id"]}U, 0x{target["archive"]}ULL, {target["type"]}U, '
                     f'{target["passive"]}U, bodies_{target["id"]}, {len(target["bodies"])}U, '
                     f'pieces_{target["id"]}, {len(pieces)}U, {changes}U}},')
    lines.extend(["};", f"}} // namespace {namespace}", ""])
    return "\n".join(lines)


def build(args):
    source = args.source
    source_paths = [Path(str(source) + suffix) for suffix in SUFFIXES]
    source_hashes = {p.name: sha256_file(p) for p in source_paths}
    data = source.read_bytes()
    header, types, entries = parse_toc(data)
    validate_segments(entries, [p.stat().st_size for p in source_paths],
                      72 + len(types) * 32 + len(entries) * 80)
    kits = json.loads(args.kits.read_text(encoding="utf-8"))
    plans = select_targets(kits, entries)
    targets = [plan[0] for plan in plans]
    target_ids = {target["id"] for target in targets}
    retained_keys = {e.key for _, _, selected in plans for e in selected}
    removed = [f"{e.key[1]:016x}" for e in entries if e.key not in retained_keys]
    patch_keys = {e.key for e in entries}
    affected = []
    names = json.loads(args.names.read_text(encoding="utf-8-sig")) if args.names else {}
    for kit in kits:
        shared = {p["resources"]["unit"] for body in kit["bodies"] for p in body["pieces"]
                  if (UNIT, int(p["resources"]["unit"], 16)) in patch_keys}
        if shared and kit["id"] not in target_ids:
            affected.append({"kit": kit["id"], "archive": kit["archive"],
                             "name": names.get(kit["archive"]), "shared_units": sorted(shared)})
    reader = VanillaReader(args.game, args.reader_tools)
    archives = list(dict.fromkeys([target["archive"] for target in targets] + ["9ba626afa44a3aa3", "18235e0c9ec0e636"]
                                  + [k["archive"] for k in affected]))
    reserved = {int(value, 16) for kit in kits for body in kit["bodies"] for piece in body["pieces"]
                for value in piece["resources"].values()}
    reserved.update(e.key[1] for e in entries)
    reserved.update(key[1] for archive in archives for key in reader.entries(archive))
    rows, fields, expanded_entries = [], [], []
    payloads, changes, external = {}, {}, set()
    for target, pieces, selected in plans:
        kit_id = int(target["id"], 16)
        mapping, target_rows = make_mapping([e.key for e in selected], reserved, kit_id)
        reserved.update(mapping.values())
        rows.extend(target_rows)
        for entry in selected:
            before = data[entry.offsets[0]:entry.offsets[0] + entry.sizes[0]]
            after, rewritten, references = rewrite_references(entry.key[0], before, mapping)
            # Keep source lane offsets while giving each owner's duplicate its own packing key.
            expanded = Entry((mapping[entry.key], *entry.values[1:]))
            expanded_entries.append(expanded)
            payloads[expanded.key] = after
            changes[f'{target["id"]}:{entry.key[1]:016x}'] = rewritten
            external.update(references)
        fields.extend(sorted({(kit_id, offset, int(piece["resources"][field], 16),
                               mapping[kind, int(piece["resources"][field], 16)])
                              for piece in pieces if piece["slot"] != 1
                              for field, offset in FIELD_OFFSETS.items()
                              for kind in [UNIT if field == "unit" else TEXTURE]
                              if (kind, int(piece["resources"][field], 16)) in mapping}))
    dependency_check = inspect_external(reader, archives, external,
                                        {int(r["source"], 16) for r in rows if r["kind"] == "texture"})
    if not dependency_check["complete"]:
        raise ValueError("External materials are unresolved or need private texture references")
    table, old_entries, new_entries, sizes = plan_archive(
        header, types, expanded_entries, {e.key: e.key[1] for e in expanded_entries})
    if {entry.key[1] for entry in new_entries} & {entry.key[1] for entry in entries}:
        raise ValueError("Private output still overrides an input resource")
    validate_segments(new_entries, sizes, len(table))
    destination = args.output / "patch" / "9ba626afa44a3aa3.patch_0"
    write_archive(source, destination, table, old_entries, new_entries, payloads, sizes)
    output_files = [Path(str(destination) + suffix) for suffix in SUFFIXES]
    parsed = parse_toc(destination.read_bytes())[2]
    validate_segments(parsed, [p.stat().st_size for p in output_files], len(table))
    if parsed != new_entries:
        raise ValueError("Output TOC did not round-trip")
    for path in source_paths:
        if sha256_file(path) != source_hashes[path.name]:
            raise ValueError("Input was changed during build")
    args.header.parent.mkdir(parents=True, exist_ok=True)
    args.header.write_text(make_header(rows, fields, targets, source_hashes[source.name]), encoding="ascii")
    manifest = {"revision": "armor-and-helmet", "targets": [
                    {"kit": t["id"], "archive": t["archive"], "type": t["type"],
                     "unit_references": sum(p["slot"] != 1 for b in t["bodies"] for p in b["pieces"]),
                     "resource_count": sum(r["kit"] == t["id"] for r in rows)} for t in targets],
                "expected_game_version": "1.0.0.18930", "expected_game_dll_sha256": DLL_SHA256,
                "source": str(source.resolve()), "source_sha256": source_hashes,
                "source_resources": [{"type": f"{e.key[0]:016x}", "source": f"{e.key[1]:016x}"}
                                     for e in entries],
                "source_kits_sha256": sha256_file(args.kits), "source_unchanged": True,
                "mapping": rows, "removed_units": removed, "piece_fields": [
                    {"kit": f"{kit:08x}", "offset": offset, "source": f"{a:016x}", "target": f"{b:016x}"}
                    for kit, offset, a, b in fields],
                "rewritten_references": changes, "external_material_check": dependency_check,
                "original_patch_other_kit_unit_overlaps": affected,
                "collision_scope": "Snapshot direct resources, source patch and inspected archive TOCs (64 and high32)",
                "preserved": ["32-bit material/texture slot keys", "mesh/bone indices", "Piece scalar fields", "default cape"],
                "source_ids_in_output_toc": 0, "game_runtime_verified": False,
                "output": [{"name": p.name, "path": str(p.relative_to(args.output)),
                            "size": p.stat().st_size, "sha256": sha256_file(p)} for p in output_files],
                "header_size_fields": "Sum of resource sizes rounded up to 256; matches current stock archive buffer offsets"}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"private_resources": len(rows), "removed_units": len(removed),
                      "other_kit_unit_overlaps": len(affected), "output_bytes": sum(sizes),
                      "external_materials_checked": len(dependency_check["checked"]),
                      "unresolved_materials": dependency_check["unresolved_materials"],
                      "manifest": str(args.output / "manifest.json")}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--kits", type=Path, default=Path("docs/armor-isolation-live-kits.json"))
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--reader-tools", type=Path, required=True)
    parser.add_argument("--names", type=Path)
    parser.add_argument("--output", type=Path, default=Path("dist/cm14-isolated"))
    parser.add_argument("--header", type=Path, default=Path("include/cm14_resource_map.hpp"))
    build(parser.parse_args())


if __name__ == "__main__":
    main()
