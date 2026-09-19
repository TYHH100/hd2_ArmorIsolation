"""Build the fixed B-01 Xiafei blue-light experiment; never change the source or game."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct

import build_cm14_isolated as archive

TARGETS = (
    ("61b31723", "58e4bd4b2278d15c", 0),
    ("4f7fb2bd", "562a45e9bc984eb9", 0),
    ("6351a9aa", "6cd3d55c05d4eac1", 0),
    ("6d30f386", "519cc1ec2eb56e1d", 0),
    ("261c4a52", "fd109bfeeed36726", 1),
    ("45d80a38", "3b143cc283b7f707", 1),
    ("b4027b70", "f4880623d32bafa9", 1),
    ("df8e4ada", "8313c9a556b8ee85", 1),
)
SOURCE_COUNTS = {archive.UNIT: 106, archive.MATERIAL: 4, archive.TEXTURE: 26}
HELMET_LOD_SOURCE_HASHES = {
    0x781134771DD69FBE: "27299f6360bc4391ceeb65308ebae7156fe5ecc7e18097ea74a02d5da6d882b0",
    0xC96CB2E72D7A0525: "047259872481d57a96495bcf1644547b8c673151a04274cb8899740fd11322f1",
    0x7B23E3C0AB4CF618: "bd3ba21fca4e6983bea1923b5a46c7b93e2c424047b68955c651910560628c29",
}
HELMET_LOD_FIELDS = ((0xDC, 4, 14), (0xEC, 3, 13), (0xFC, 2, 12), (0x154, 1, 11))


def select_targets(kits):
    targets = []
    for kit_id, archive_id, kind in TARGETS:
        matches = [kit for kit in kits if kit["id"] == kit_id]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one B-01 Kit {kit_id}")
        target = matches[0]
        layout = [(body["type"], len(body["pieces"])) for body in target["bodies"]]
        expected = [(3, 7), (0, 8), (1, 8)] if kind == 0 else [(3, 1)]
        if (target["archive"] != archive_id or target["type"] != kind or
                target["passive"] != (1 if kind == 0 else 0) or layout != expected):
            raise ValueError(f"B-01 identity/layout mismatch: {kit_id}")
        if kind == 1 and target["bodies"][0]["pieces"][0]["slot"] != 0:
            raise ValueError(f"B-01 helmet slot mismatch: {kit_id}")
        targets.append(target)
    return targets


def target_pieces(target):
    return [piece for body in target["bodies"] for piece in body["pieces"] if piece["slot"] != 1]


def dependency_closure(target, data, entries):
    roots = set()
    for piece in target_pieces(target):
        unit = archive.UNIT, int(piece["resources"]["unit"], 16)
        if unit not in entries:
            raise ValueError(f"Source lacks target Unit {unit[1]:016x} for {target['id']}")
        roots.add(unit)
        roots.update((archive.TEXTURE, int(value, 16)) for field, value in piece["resources"].items()
                     if field != "unit" and (archive.TEXTURE, int(value, 16)) in entries)
    selected, external, pending = set(), set(), set(roots)
    while pending:
        key = pending.pop()
        if key in selected:
            continue
        selected.add(key)
        entry = entries[key]
        payload = data[entry.offsets[0]:entry.offsets[0] + entry.sizes[0]]
        for kind, offset in archive.reference_fields(key[0], payload):
            value = struct.unpack_from("<Q", payload, offset)[0]
            if not value:
                continue
            reference = kind, value
            if reference in entries:
                if reference not in selected:
                    pending.add(reference)
            else:
                external.add(reference)
    return selected, external


def range_hash(stream, offset, size):
    stream.seek(offset)
    digest = hashlib.sha256()
    while size:
        chunk = stream.read(min(size, 1024 * 1024))
        if not chunk:
            raise ValueError("Truncated resource during payload verification")
        digest.update(chunk)
        size -= len(chunk)
    return digest.digest()


def make_resource_mappings(plans, reserved):
    reserved = set(reserved)
    shared_keys = {key for _, selected in plans for key in selected if key[0] != archive.UNIT}
    shared, rows = archive.make_mapping(shared_keys, reserved, 0, "mods/b01_xiafei_blue/v1")
    reserved.update(shared.values())
    mappings = {}
    for target, selected in plans:
        units = {key for key in selected if key[0] == archive.UNIT}
        private, private_rows = archive.make_mapping(units, reserved, int(target["id"], 16), "mods/b01_isolation/v1")
        reserved.update(private.values())
        mappings[target["id"]] = {**shared, **private}
        rows.extend(private_rows)
    return shared, mappings, rows


def repair_helmet_lod(source_id, data):
    expected_hash = HELMET_LOD_SOURCE_HASHES.get(source_id)
    if expected_hash is None:
        return data, []
    if hashlib.sha256(data).hexdigest() != expected_hash:
        raise ValueError(f"Helmet source changed; revalidate LOD layout for {source_id:016x}")
    result, changes = bytearray(data), []
    for offset, expected, desired in HELMET_LOD_FIELDS:
        if offset + 4 > len(data) or struct.unpack_from("<I", data, offset)[0] != expected:
            raise ValueError(f"Helmet LOD field differs at {source_id:016x}+{offset:x}")
        struct.pack_into("<I", result, offset, desired)
        changes.append({"offset": offset, "source": expected, "target": desired})
    return bytes(result), changes


def verify_payloads(source, destination, source_entries, output_entries, rows, payloads):
    for lane, suffix in enumerate(archive.SUFFIXES):
        with Path(str(source) + suffix).open("rb") as before, Path(str(destination) + suffix).open("rb") as after:
            for row in rows:
                kind, source_id, target_id = (int(row[key], 16) for key in ("type", "source", "target"))
                original, result = source_entries[kind, source_id], output_entries[kind, target_id]
                if original.sizes != result.sizes:
                    raise ValueError("Resource sizes changed")
                actual = range_hash(after, result.offsets[lane], result.sizes[lane])
                expected = (hashlib.sha256(payloads[kind, target_id]).digest() if lane == 0 else
                            range_hash(before, original.offsets[lane], original.sizes[lane]))
                if actual != expected:
                    raise ValueError(f"Payload mismatch: {row['kit']} {target_id:016x} lane {lane}")


def build(args):
    source = args.source
    source_paths = [Path(str(source) + suffix) for suffix in archive.SUFFIXES]
    source_hashes = {path.name: archive.sha256_file(path) for path in source_paths}
    data = source.read_bytes()
    header, types, entries = archive.parse_toc(data)
    if Counter(entry.key[0] for entry in entries) != SOURCE_COUNTS:
        raise ValueError("Source is not the inspected B-01 blue-light resource layout")
    archive.validate_segments(entries, [path.stat().st_size for path in source_paths],
                              72 + len(types) * 32 + len(entries) * 80)
    source_entries = {entry.key: entry for entry in entries}
    kits = json.loads(args.kits.read_text(encoding="utf-8"))
    targets = select_targets(kits)
    plans, external, retained = [], set(), set()
    for target in targets:
        selected, references = dependency_closure(target, data, source_entries)
        expected = {archive.UNIT: 22 if target["type"] == 0 else 1, archive.MATERIAL: 1, archive.TEXTURE: 13}
        if Counter(kind for kind, _ in selected) != expected:
            raise ValueError(f"B-01 dependency closure changed: {target['id']}")
        plans.append((target, selected))
        external.update(references)
        retained.update(selected)
    reader = archive.VanillaReader(args.game, args.reader_tools)
    archives = list(dict.fromkeys([target["archive"] for target in targets] +
                                  ["9ba626afa44a3aa3", "18235e0c9ec0e636"]))
    dependency_check = archive.inspect_external(reader, archives, external,
                                                {value for kind, value in source_entries if kind == archive.TEXTURE})
    modified_materials = {value for kind, value in source_entries if kind == archive.MATERIAL}
    for checked in dependency_check["checked"]:
        checked["modified_base_overlap"] = [value for value in checked["base_materials"]
                                             if int(value, 16) in modified_materials]
    if not dependency_check["complete"] or any(row["modified_base_overlap"] for row in dependency_check["checked"]):
        raise ValueError("External dependency unresolved or needs a private clone; inspect before building")
    reserved = {int(value, 16) for kit in kits for body in kit["bodies"] for piece in body["pieces"]
                for value in piece["resources"].values()}
    reserved.update(entry.key[1] for entry in entries)
    reserved.update(key[1] for name in archives for key in reader.entries(name))
    coexist = []
    if args.cm14_manifest.exists():
        cm14 = json.loads(args.cm14_manifest.read_text(encoding="utf-8"))
        reserved.update(int(row["target"], 16) for row in cm14["mapping"])
        coexist.append({"path": str(args.cm14_manifest.resolve()),
                        "sha256": archive.sha256_file(args.cm14_manifest)})
    shared, mappings, rows = make_resource_mappings(plans, reserved)
    fields, expanded, payloads, changes, lod_adjustments = [], [], {}, {}, []
    for key in sorted(shared):
        entry = source_entries[key]
        before = data[entry.offsets[0]:entry.offsets[0] + entry.sizes[0]]
        after, rewritten, _ = archive.rewrite_references(key[0], before, shared)
        new_entry = archive.Entry((shared[key], *entry.values[1:]))
        expanded.append(new_entry)
        payloads[new_entry.key] = after
        changes[f"shared:{key[1]:016x}"] = rewritten
    for target, selected in plans:
        owner = int(target["id"], 16)
        mapping = mappings[target["id"]]
        for key in sorted(key for key in selected if key[0] == archive.UNIT):
            entry = source_entries[key]
            before = data[entry.offsets[0]:entry.offsets[0] + entry.sizes[0]]
            before, adjusted_lods = repair_helmet_lod(key[1], before)
            if adjusted_lods:
                lod_adjustments.append({"kit": target["id"], "source_unit": f"{key[1]:016x}",
                                        "source_main_sha256": HELMET_LOD_SOURCE_HASHES[key[1]],
                                        "fields": adjusted_lods, "game_runtime_verified": False})
            after, rewritten, _ = archive.rewrite_references(key[0], before, mapping)
            new_entry = archive.Entry((mapping[key], *entry.values[1:]))
            expanded.append(new_entry)
            payloads[new_entry.key] = after
            changes[f"{target['id']}:{key[1]:016x}"] = rewritten
        fields.extend(sorted({(owner, offset, int(piece["resources"][field], 16),
                               mapping[kind, int(piece["resources"][field], 16)])
                              for piece in target_pieces(target) for field, offset in archive.FIELD_OFFSETS.items()
                              for kind in [archive.UNIT if field == "unit" else archive.TEXTURE]
                              if (kind, int(piece["resources"][field], 16)) in mapping}))
    table, original, relocated, sizes = archive.plan_archive(
        header, types, expanded, {entry.key: entry.key[1] for entry in expanded})
    archive.validate_segments(relocated, sizes, len(table))
    if {entry.key for entry in relocated} & set(source_entries):
        raise ValueError("Private patch still overrides a source ID")
    destination = args.output / "patch" / "9ba626afa44a3aa3.patch_0"
    archive.write_archive(source, destination, table, original, relocated, payloads, sizes)
    output_files = [Path(str(destination) + suffix) for suffix in archive.SUFFIXES]
    parsed = archive.parse_toc(destination.read_bytes())[2]
    if parsed != relocated:
        raise ValueError("Output TOC did not round-trip")
    archive.validate_segments(parsed, [path.stat().st_size for path in output_files], len(table))
    verify_payloads(source, destination, source_entries, {entry.key: entry for entry in parsed}, rows, payloads)
    if any(archive.sha256_file(path) != source_hashes[path.name] for path in source_paths):
        raise ValueError("Source changed during build")
    args.header.parent.mkdir(parents=True, exist_ok=True)
    args.header.write_text(archive.make_header(rows, fields, targets, source_hashes[source.name],
                                              "b01_isolation"), encoding="ascii")
    affected = []
    for kit in kits:
        if kit["id"] in {target["id"] for target in targets}:
            continue
        units = sorted({piece["resources"]["unit"] for body in kit["bodies"] for piece in body["pieces"]
                        if (archive.UNIT, int(piece["resources"]["unit"], 16)) in source_entries})
        if units:
            affected.append({"kit": kit["id"], "archive": kit["archive"], "type": kit["type"], "shared_units": units})
    manifest = {
        "experiment": "B-01 Xiafei blue light, fixed eight targets", "revision": 4,
        "expected_game_version": "1.0.0.18930", "expected_game_dll_sha256": archive.DLL_SHA256,
        "source": str(source.resolve()), "source_sha256": source_hashes, "source_unchanged": True,
        "source_kits_sha256": archive.sha256_file(args.kits),
        "targets": [{"kit": target["id"], "archive": target["archive"], "type": target["type"],
                     "unit_references": len(target_pieces(target)), "resource_count": len(selected)}
                     for target, selected in plans],
        "shared_resource_owner": "00000000", "shared_resource_count": len(shared),
        "shared_resource_scope": "One private material/texture set shared only within this B-01 mod",
        "source_resources": [{"type": f"{entry.key[0]:016x}", "source": f"{entry.key[1]:016x}"} for entry in entries],
        "excluded_resources": [{"type": f"{entry.key[0]:016x}", "source": f"{entry.key[1]:016x}"}
                               for entry in entries if entry.key not in retained],
        "mapping": rows, "piece_fields": [{"kit": f"{owner:08x}", "offset": offset,
                                            "source": f"{before:016x}", "target": f"{after:016x}"}
                                           for owner, offset, before, after in fields],
        "rewritten_references": changes, "external_material_check": dependency_check,
        "helmet_lod_adjustments": lod_adjustments,
        "original_patch_other_kit_unit_overlaps": affected,
        "coexisting_manifests": coexist,
        "collision_scope": "Snapshot direct refs, source and inspected archive IDs, CM14 private IDs; 64 and high32",
        "preserved": ["default cape", "Piece scalar fields", "32-bit slot/usage hashes",
                      "mesh material/bone indices; the listed helmet LOD selectors are explicitly repaired"],
        "source_ids_in_output_toc": 0, "payloads_verified": True, "game_runtime_verified": False,
        "gpu_storage": {"mode": "shared_private_materials_and_textures", "previous_expanded_file_bytes": 2249516160,
                        "physical_file_bytes": sizes[2], "saved_disk_bytes": 2249516160 - sizes[2],
                        "resource_gpu_buffer_bytes": struct.unpack_from("<Q", table, 40)[0],
                        "shared_disk_ranges": False,
                        "note": "Private Unit IDs per Kit; one mod-private material and texture set, standard non-overlapping TOC"},
        "output": [{"name": path.name, "path": str(path.relative_to(args.output)),
                    "size": path.stat().st_size, "sha256": archive.sha256_file(path)} for path in output_files],
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"targets": len(targets), "private_resources": len(rows), "piece_fields": len(fields),
                      "excluded_source_resources": len(entries) - len(retained), "output_bytes": sum(sizes),
                      "gpu_storage": manifest["gpu_storage"],
                      "helmet_lod_adjustments": len(lod_adjustments),
                      "external_materials": len(dependency_check["checked"]),
                      "other_kit_unit_overlaps": len(affected)}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--reader-tools", type=Path, required=True)
    parser.add_argument("--kits", type=Path, default=Path("docs/armor-isolation-live-kits.json"))
    parser.add_argument("--cm14-manifest", type=Path, default=Path("dist/cm14-isolated/manifest.json"))
    parser.add_argument("--output", type=Path, default=Path("dist/b01-isolated"))
    parser.add_argument("--header", type=Path, default=Path("include/b01_resource_map.hpp"))
    build(parser.parse_args())


if __name__ == "__main__":
    main()
