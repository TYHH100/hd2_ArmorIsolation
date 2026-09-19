"""Read-only B-01 source coverage/dependency analysis; write a local report."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import struct

import build_cm14_isolated as resource


TARGET_IDS = {"61b31723", "4f7fb2bd", "6351a9aa", "6d30f386",
              "261c4a52", "45d80a38", "b4027b70", "df8e4ada"}


def key_row(key):
    kind, value = key
    return {"kind": resource.KINDS[kind], "type": f"{kind:016x}", "id": f"{value:016x}"}


def analyze(args):
    source = args.source.read_bytes()
    header, types, entries = resource.parse_toc(source)
    source_files = [Path(str(args.source) + suffix) for suffix in resource.SUFFIXES]
    resource.validate_segments(entries, [path.stat().st_size for path in source_files],
                               72 + len(types) * 32 + len(entries) * 80)
    by_key = {entry.key: entry for entry in entries}
    kits = json.loads(args.kits.read_text(encoding="utf-8"))
    targets = [kit for kit in kits if kit["id"] in TARGET_IDS]
    if len(targets) != len(TARGET_IDS):
        raise ValueError("B-01 target snapshot incomplete")
    names = {}
    for filename in ("armor-names.json", "helmet-names.json"):
        path = args.names / filename
        if path.exists():
            names.update(json.loads(path.read_text(encoding="utf-8-sig")))
    target_rows, all_local, all_external, all_units = [], set(), set(), set()
    for kit in targets:
        pieces = [piece for body in kit["bodies"] for piece in body["pieces"] if piece["slot"] != 1]
        units = {(resource.UNIT, int(piece["resources"]["unit"], 16)) for piece in pieces}
        all_units.update(units)
        direct = {(resource.TEXTURE, int(value, 16))
                  for piece in pieces for field, value in piece["resources"].items()
                  if field != "unit" and (resource.TEXTURE, int(value, 16)) in by_key}
        pending, visited, external = set(units | direct), set(), set()
        while pending:
            key = pending.pop()
            if key in visited:
                continue
            if key not in by_key:
                external.add(key)
                continue
            visited.add(key)
            entry = by_key[key]
            data = source[entry.offsets[0]:entry.offsets[0] + entry.sizes[0]]
            pending.update((kind, value) for kind, offset in resource.reference_fields(key[0], data)
                           if (value := struct.unpack_from("<Q", data, offset)[0]))
        all_local.update(visited)
        all_external.update(external)
        target_rows.append({
            "kit": kit["id"], "archive": kit["archive"], "name": names.get(kit["archive"]),
            "type": kit["type"], "passive": kit["passive"],
            "body_layout": [[body["type"], len(body["pieces"])] for body in kit["bodies"]],
            "non_cape_piece_count": len(pieces), "non_cape_unique_unit_count": len(units),
            "missing_source_units": [key_row(key) for key in sorted(units - by_key.keys())],
            "direct_modified_textures": [key_row(key) for key in sorted(direct)],
            "private_closure_counts": dict(Counter(resource.KINDS[kind] for kind, _ in visited)),
            "private_closure": [key_row(key) for key in sorted(visited)],
            "external_references": [key_row(key) for key in sorted(external)],
        })
    affected = []
    for kit in kits:
        if kit["id"] in TARGET_IDS:
            continue
        shared = {piece["resources"]["unit"] for body in kit["bodies"] for piece in body["pieces"]
                  if (resource.UNIT, int(piece["resources"]["unit"], 16)) in by_key}
        if shared:
            affected.append({"kit": kit["id"], "archive": kit["archive"], "type": kit["type"],
                             "name": names.get(kit["archive"]), "shared_units": sorted(shared)})
    reader = resource.VanillaReader(args.game, args.reader_tools)
    archives = [kit["archive"] for kit in targets] + ["9ba626afa44a3aa3", "18235e0c9ec0e636"]
    check = resource.inspect_external(reader, archives, all_external,
                                      {name for kind, name in by_key if kind == resource.TEXTURE})
    source_materials = {f"{name:016x}" for kind, name in by_key if kind == resource.MATERIAL}
    base_overlap = [{"external_material": row["id"], "source_base_material": base}
                    for row in check["checked"] for base in row["base_materials"]
                    if base in source_materials]
    report = {
        "source": str(args.source.resolve()),
        "source_files": [{"name": path.name, "size": path.stat().st_size,
                          "sha256": resource.sha256_file(path)} for path in source_files],
        "snapshot": str(args.kits), "snapshot_sha256": resource.sha256_file(args.kits),
        "expected_game_version": "1.0.0.18930", "expected_game_dll_sha256": resource.DLL_SHA256,
        "source_counts": dict(Counter(resource.KINDS[kind] for kind, _ in by_key)),
        "zero_length_lane_validation": "Validate bounds only for non-empty data; zero-length lanes may use EOF alignment offset",
        "targets": target_rows,
        "target_unique_unit_count": len(all_units),
        "excluded_source_resources": [key_row(key) for key in sorted(by_key.keys() - all_local)],
        "private_resource_count_if_per_kit": sum(sum(row["private_closure_counts"].values()) for row in target_rows),
        "other_kit_direct_unit_overlap_count": len(affected),
        "other_kit_direct_unit_overlaps": affected,
        "external_material_check": check,
        "external_base_material_source_overlap": base_overlap,
        "additional_vanilla_unit_or_material_cloning_required": not check["complete"] or bool(base_overlap) or any(
            row["missing_source_units"] for row in target_rows),
        "scope": "Eight B-01 armor/helmet Kits; default cape excluded. Overlap is potential impact, not visual proof.",
        "external_references": [
            "https://github.com/xypwn/filediver",
            "https://github.com/crosire/reshade/tree/v6.5.1/include",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(args.output), "targets": len(target_rows),
                      "source_counts": report["source_counts"],
                      "private_resources": report["private_resource_count_if_per_kit"],
                      "other_kits": len(affected), "external_materials": len(check["checked"]),
                      "dependency_check_complete": check["complete"]}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--reader-tools", type=Path, required=True)
    parser.add_argument("--kits", type=Path, default=Path("docs/armor-isolation-live-kits.json"))
    parser.add_argument("--names", type=Path, default=Path(r"D:\TYHH10-git\Helldivers2ModManager\src\Helldivers2ModManager\Resources\Data"))
    parser.add_argument("--output", type=Path, default=Path("docs/b01-source-analysis.json"))
    analyze(parser.parse_args())


if __name__ == "__main__":
    main()
