"""Build an explicitly selected armor/head isolation package for the verified game version."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import nullcontext
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import re
import struct

import build_b01_isolated as b01
import build_cm14_isolated as archive

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "hd2-armor-isolation/1"
KITS_SHA256 = "e68b82eb7dacde3219f7d049b692dfb418f7f2a35516d98c3dab7515eb0409c1"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
PATCH_NAME = "9ba626afa44a3aa3.patch_0"
REPAIR_CATALOG = "b01-helmet-lod/exact-main-sha256/1"


@dataclass
class Source:
    path: Path
    data: bytes
    header: bytes
    types: list
    entries: dict
    lanes: list


def validate_version(game, kits_path):
    dll = Path(game) / "data/game/game.dll"
    if not dll.is_file() or archive.sha256_file(dll) != archive.DLL_SHA256:
        raise ValueError("Unsupported game.dll: this tool requires the verified 1.0.0.18930 build")
    if archive.sha256_file(Path(kits_path)) != KITS_SHA256:
        raise ValueError("Kit snapshot differs from the verified game version; a new snapshot needs validation")
    return json.loads(Path(kits_path).read_text(encoding="utf-8"))


def resolve_source(path):
    path = Path(path).resolve()
    if path.is_dir():
        matches = [item for item in path.iterdir() if item.is_file()
                   and re.fullmatch(r"[0-9a-fA-F]{16}\.patch_\d+", item.name)]
        if len(matches) != 1:
            raise ValueError(f"Select one patch main file; this directory contains {len(matches)} patches")
        path = matches[0]
    if not path.is_file() or not re.fullmatch(r"[0-9a-fA-F]{16}\.patch_\d+", path.name):
        raise ValueError("Source must be one patch main file, or a directory containing exactly one patch")
    return path


def load_source(path):
    path = resolve_source(path)
    data = path.read_bytes()
    header, types, entries = archive.parse_toc(data)
    unknown = sorted({entry.key[0] for entry in entries} - set(archive.KINDS))
    if unknown:
        raise ValueError("Unsupported source resource types: " + ", ".join(f"{v:016x}" for v in unknown))
    if not entries:
        raise ValueError("Source patch contains no resources")
    lanes = []
    for lane, suffix in enumerate(archive.SUFFIXES):
        lane_path = Path(str(path) + suffix)
        exists = lane_path.is_file()
        if not exists and any(entry.sizes[lane] for entry in entries):
            raise ValueError(f"Missing nonempty source lane: {lane_path.name}")
        lanes.append({"suffix": suffix, "name": lane_path.name, "exists": exists,
                      "size": lane_path.stat().st_size if exists else 0,
                      "sha256": archive.sha256_file(lane_path) if exists else EMPTY_SHA256})
    if hashlib.sha256(data).hexdigest() != lanes[0]["sha256"]:
        raise ValueError("Source changed while reading its table")
    archive.validate_segments(entries, [lane["size"] for lane in lanes],
                              72 + len(types) * 32 + len(entries) * 80)
    return Source(path, data, header, types, {entry.key: entry for entry in entries}, lanes)


def candidates(kits, source):
    result = []
    for kit in kits:
        pieces = b01.target_pieces(kit)
        units = {(archive.UNIT, int(piece["resources"]["unit"], 16)) for piece in pieces}
        matched = units & source.entries.keys()
        if not matched:
            continue
        reasons = []
        if kit["type"] not in (0, 1):
            reasons.append("Only armor (type 0) and helmet (type 1) Kits are supported")
        if units != matched:
            reasons.append("Source does not contain every non-cape Unit; partial replacements are unsupported")
        if not reasons:
            try:
                b01.dependency_closure(kit, source.data, source.entries)
            except (ValueError, struct.error) as error:
                reasons.append(str(error))
        result.append({"id": kit["id"], "archive": kit["archive"], "type": kit["type"],
                       "unit_matched": len(matched), "unit_total": len(units),
                       "supported": not reasons, "reasons": reasons,
                       "selection": "explicit_required"})
    return result


def select_targets(kits, source, requested):
    if not requested:
        raise ValueError("Explicit target Kit IDs are required; resource sharing cannot infer author intent")
    ids = []
    for value in requested:
        text = str(value).lower().removeprefix("0x")
        if not re.fullmatch(r"[0-9a-f]{1,8}", text) or int(text, 16) == 0:
            raise ValueError(f"Invalid target Kit ID: {value}")
        ids.append(f"{int(text, 16):08x}")
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate target Kit IDs")
    choices = {item["id"]: item for item in candidates(kits, source)}
    targets = []
    for target_id in sorted(ids):
        matches = [kit for kit in kits if kit["id"] == target_id]
        if len(matches) != 1:
            raise ValueError(f"Unknown or ambiguous target Kit: {target_id}")
        candidate = choices.get(target_id)
        if candidate is None or not candidate["supported"]:
            reasons = candidate["reasons"] if candidate else ["No source Unit matches this Kit"]
            raise ValueError(f"Unsupported target {target_id}: {'; '.join(reasons)}")
        targets.append(matches[0])
    return targets


def analyze(args):
    kits_path = Path(getattr(args, "kits", ROOT / "docs/armor-isolation-live-kits.json"))
    kits = validate_version(args.game, kits_path)
    source = load_source(args.source)
    choices = candidates(kits, source)
    return {"schema": SCHEMA, "expected_game_version": "1.0.0.18930",
            "source": str(source.path), "source_lanes": source.lanes,
            "source_counts": {archive.KINDS[kind]: count for kind, count in
                              Counter(key[0] for key in source.entries).items()},
            "candidates": choices, "auto_selected": [],
            "notes": ["Candidates indicate shared source Units, not intended targets.",
                      "External dependencies are verified after explicit target selection."] +
                     ([] if choices else ["No target has source Units; texture-only replacements are unsupported."])}


def read_coexist(paths, targets):
    selected_ids = {target["id"] for target in targets}
    reserved, records = set(), []
    for path in paths:
        path = Path(path).resolve()
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("expected_game_dll_sha256") != archive.DLL_SHA256:
            raise ValueError(f"Coexisting manifest has an incompatible game version: {path}")
        existing_ids = {f"{int(row['kit'], 16):08x}" for row in manifest["targets"]}
        overlap = selected_ids & existing_ids
        if overlap:
            raise ValueError("Coexisting package selects the same Kit: " + ", ".join(sorted(overlap)))
        for row in [*manifest["mapping"], *manifest.get("preserved_unbound_mapping", [])]:
            value, kind = int(row["target"], 16), int(row["type"], 16)
            if kind not in archive.KINDS or not 0 < value < (1 << 64):
                raise ValueError(f"Invalid coexisting resource mapping: {path}")
            reserved.add(value)
        records.append({"path": str(path), "sha256": archive.sha256_file(path),
                        "targets": sorted(existing_ids), "package_id": manifest.get("package_id")})
    return reserved, records


def package_identity(lanes, targets, coexist=()):
    content = {"schema": SCHEMA, "repair_catalog": REPAIR_CATALOG,
               "repair_rules": [{"unit": f"{key:016x}", "sha256": value,
                                 "fields": b01.HELMET_LOD_FIELDS}
                                for key, value in sorted(b01.HELMET_LOD_SOURCE_HASHES.items())],
               "source_lanes": [{"suffix": row["suffix"], "sha256": row["sha256"]} for row in lanes],
               "targets": sorted(target["id"] for target in targets),
               "coexisting_sha256": sorted(row["sha256"] for row in coexist)}
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()[:24]


def make_resource_mappings(plans, reserved, package_id):
    reserved = set(reserved)
    namespace = f"mods/armor_isolation/v1/{package_id}"
    shared_keys = {key for _, selected in plans for key in selected if key[0] != archive.UNIT}
    shared, rows = archive.make_mapping(shared_keys, reserved, 0, namespace)
    reserved.update(shared.values())
    mappings, required = {}, []
    for target, selected in plans:
        owner = int(target["id"], 16)
        units = {key for key in selected if key[0] == archive.UNIT}
        private, new_rows = archive.make_mapping(units, reserved, owner, namespace)
        reserved.update(private.values())
        mapping = {**shared, **private}
        mappings[target["id"]] = mapping
        rows.extend(new_rows)
        required.extend({"kit": target["id"], "type": f"{kind:016x}", "target": f"{mapping[kind, value]:016x}"}
                        for kind, value in sorted(selected))
    return shared, mappings, rows, required


def repair_known_helmet(source_id, data):
    expected = b01.HELMET_LOD_SOURCE_HASHES.get(source_id)
    if expected is None or hashlib.sha256(data).hexdigest() != expected:
        return data, []
    return b01.repair_helmet_lod(source_id, data)


def inspect_external(reader, archives, external, source_entries):
    textures = {value for kind, value in source_entries if kind == archive.TEXTURE}
    materials = {value for kind, value in source_entries if kind == archive.MATERIAL}
    result = archive.inspect_external(reader, archives, external, textures)
    for row in result["checked"]:
        row["modified_base_overlap"] = [value for value in row["base_materials"] if int(value, 16) in materials]
    if not result["complete"] or any(row["modified_base_overlap"] for row in result["checked"]):
        raise ValueError("External Material is unresolved or references a modified Texture/BaseMaterial; private cloning is unsupported")
    return result


def make_header(rows, fields, targets, source_hash, required, package_id):
    text = archive.make_header(rows, fields, targets, source_hash, "generic_isolation")
    extra = [f'inline constexpr char package_id[] = "{package_id}";',
             "struct RequiredResource { std::uint32_t kit_id; std::uint64_t type, target; };",
             "inline constexpr RequiredResource required_resources[] = {"]
    extra.extend(f'    {{0x{row["kit"]}U, 0x{row["type"]}ULL, 0x{row["target"]}ULL}},' for row in required)
    extra.append("};")
    return text.replace("} // namespace generic_isolation", "\n".join(extra) + "\n} // namespace generic_isolation")


def open_lane(source, lane):
    path = Path(str(source.path) + archive.SUFFIXES[lane])
    return path.open("rb") if source.lanes[lane]["exists"] else nullcontext(io.BytesIO())


def write_archive(source, destination, table, original, relocated, payloads, sizes):
    destination.parent.mkdir(parents=True, exist_ok=True)
    for lane, suffix in enumerate(archive.SUFFIXES):
        with open_lane(source, lane) as before, Path(str(destination) + suffix).open("xb") as after:
            if lane == 0:
                after.write(table)
            for entry, result in zip(original, relocated):
                if lane == 0:
                    after.seek(result.offsets[0])
                    after.write(payloads[entry.key])
                elif result.sizes[lane]:
                    archive.copy_range(before, after, entry.offsets[lane], result.offsets[lane], result.sizes[lane])
            after.truncate(sizes[lane])


def verify_payloads(source, destination, output_entries, rows, payloads):
    for lane, suffix in enumerate(archive.SUFFIXES):
        with open_lane(source, lane) as before, Path(str(destination) + suffix).open("rb") as after:
            for row in rows:
                kind, source_id, target_id = (int(row[key], 16) for key in ("type", "source", "target"))
                original, result = source.entries[kind, source_id], output_entries[kind, target_id]
                if original.sizes != result.sizes:
                    raise ValueError("Resource sizes changed")
                expected = (hashlib.sha256(payloads[kind, target_id]).digest() if lane == 0 else
                            b01.range_hash(before, original.offsets[lane], original.sizes[lane]))
                if b01.range_hash(after, result.offsets[lane], result.sizes[lane]) != expected:
                    raise ValueError(f"Output payload mismatch: {target_id:016x}, lane {lane}")


def verify_source_unchanged(source):
    for row in source.lanes:
        path = Path(str(source.path) + row["suffix"])
        if path.is_file() != row["exists"] or (row["exists"] and archive.sha256_file(path) != row["sha256"]):
            raise ValueError("Source changed during build")


def validate_output(output, source, game):
    output, game = Path(output).resolve(), Path(game).resolve()
    if output == source.path.parent or output.is_relative_to(source.path.parent):
        raise ValueError("Output must be outside the source mod directory")
    if output == game or output.is_relative_to(game):
        raise ValueError("Generating directly inside the game directory is not supported")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Output must be a new directory or an empty staging directory")
    return output


def build(args):
    kits_path = Path(getattr(args, "kits", ROOT / "docs/armor-isolation-live-kits.json"))
    kits = validate_version(args.game, kits_path)
    source = load_source(args.source)
    output = validate_output(args.output, source, args.game)
    targets = select_targets(kits, source, getattr(args, "target", []))
    coexist_reserved, coexist = read_coexist(getattr(args, "coexist_manifest", []) or [], targets)
    package_id = package_identity(source.lanes, targets, coexist)
    plans, external, retained = [], set(), set()
    for target in targets:
        selected, references = b01.dependency_closure(target, source.data, source.entries)
        plans.append((target, selected))
        external.update(references)
        retained.update(selected)
    reader = archive.VanillaReader(Path(args.game), Path(args.reader_tools))
    archives = list(dict.fromkeys([target["archive"] for target in targets] +
                                  ["9ba626afa44a3aa3", "18235e0c9ec0e636"]))
    external_check = inspect_external(reader, archives, external, source.entries)
    reserved = {int(value, 16) for kit in kits for body in kit["bodies"] for piece in body["pieces"]
                for value in piece["resources"].values()}
    reserved.update(value for _, value in source.entries)
    reserved.update(value for name in archives for _, value in reader.entries(name))
    reserved.update(coexist_reserved)
    shared, mappings, rows, required = make_resource_mappings(plans, reserved, package_id)
    fields, expanded, payloads, changes, adjustments = [], [], {}, {}, []
    for owner, selected, mapping in [("00000000", shared, shared)] + [
            (target["id"], {key for key in selected if key[0] == archive.UNIT}, mappings[target["id"]])
            for target, selected in plans]:
        for key in sorted(selected):
            entry = source.entries[key]
            before = source.data[entry.offsets[0]:entry.offsets[0] + entry.sizes[0]]
            if key[0] == archive.UNIT:
                before, adjusted = repair_known_helmet(key[1], before)
                if adjusted:
                    adjustments.append({"kit": owner, "source_unit": f"{key[1]:016x}",
                                        "source_main_sha256": b01.HELMET_LOD_SOURCE_HASHES[key[1]],
                                        "rule": REPAIR_CATALOG, "fields": adjusted,
                                        "catalog_rule_game_verified": True, "generated_package_game_verified": False})
            after, rewritten, _ = archive.rewrite_references(key[0], before, mapping)
            result = archive.Entry((mapping[key], *entry.values[1:]))
            expanded.append(result)
            payloads[result.key] = after
            changes[f"{owner}:{key[1]:016x}"] = rewritten
    for target, _ in plans:
        owner, mapping = int(target["id"], 16), mappings[target["id"]]
        fields.extend(sorted({(owner, offset, int(piece["resources"][field], 16),
                               mapping[kind, int(piece["resources"][field], 16)])
                              for piece in b01.target_pieces(target) for field, offset in archive.FIELD_OFFSETS.items()
                              for kind in [archive.UNIT if field == "unit" else archive.TEXTURE]
                              if (kind, int(piece["resources"][field], 16)) in mapping}))
    table, original, relocated, sizes = archive.plan_archive(
        source.header, source.types, expanded, {entry.key: entry.key[1] for entry in expanded})
    archive.validate_segments(relocated, sizes, len(table))
    if {entry.key[1] for entry in relocated} & reserved:
        raise ValueError("Generated resource collides with a reserved source or installed package ID")
    if {entry.key[1] >> 32 for entry in relocated} & {value >> 32 for value in reserved}:
        raise ValueError("Generated resource high32 collides with a reserved resource")
    destination = output / "patch" / PATCH_NAME
    output_files = [Path(str(destination) + suffix) for suffix in archive.SUFFIXES]
    header_path = output / "generated/generic_resource_map.hpp"
    manifest_path = output / "manifest.json"
    created_root = not output.exists()
    output.mkdir(parents=True, exist_ok=True)
    try:
        write_archive(source, destination, table, original, relocated, payloads, sizes)
        parsed = archive.parse_toc(destination.read_bytes())[2]
        if parsed != relocated:
            raise ValueError("Generated TOC did not round-trip")
        archive.validate_segments(parsed, [path.stat().st_size for path in output_files], len(table))
        verify_payloads(source, destination, {entry.key: entry for entry in parsed}, rows, payloads)
        verify_source_unchanged(source)
        header_path.parent.mkdir()
        with header_path.open("x", encoding="ascii", newline="\n") as stream:
            stream.write(make_header(rows, fields, targets, source.lanes[0]["sha256"], required, package_id))
        target_ids = {target["id"] for target in targets}
        affected = [row for row in candidates(kits, source) if row["id"] not in target_ids]
        manifest = {
            "schema": SCHEMA, "revision": 1, "package_id": package_id,
            "expected_game_version": "1.0.0.18930", "expected_game_dll_sha256": archive.DLL_SHA256,
            "source": str(source.path), "source_sha256": {row["name"]: row["sha256"] for row in source.lanes},
            "source_lanes": source.lanes, "source_unchanged": True, "source_kits_sha256": KITS_SHA256,
            "targets": [{"kit": target["id"], "archive": target["archive"], "type": target["type"],
                         "unit_references": len(b01.target_pieces(target)), "resource_count": len(selected)}
                        for target, selected in plans],
            "selected_kit_metadata": targets,
            "shared_resource_owner": "00000000", "shared_resource_count": len(shared),
            "shared_resource_scope": "One private Material/Texture set shared only inside this package",
            "source_resources": [{"type": f"{kind:016x}", "source": f"{value:016x}"} for kind, value in source.entries],
            "excluded_resources": [{"type": f"{kind:016x}", "source": f"{value:016x}"}
                                   for kind, value in source.entries if (kind, value) not in retained],
            "mapping": rows, "required_resources": required,
            "piece_fields": [{"kit": f"{owner:08x}", "offset": offset, "source": f"{before:016x}",
                              "target": f"{after:016x}"} for owner, offset, before, after in fields],
            "rewritten_references": changes, "external_material_check": external_check,
            "helmet_lod_adjustments": adjustments, "coexisting_manifests": coexist,
            "original_patch_other_kit_unit_overlaps": affected,
            "collision_scope": "Snapshot direct refs, source and selected/shared archive IDs, explicitly supplied coexisting private IDs; 64 and high32",
            "preserved": ["default cape", "Piece scalars", "32-bit material/texture slot keys",
                          "bones and mesh data except exact-hash catalog LOD selectors"],
            "source_ids_in_output_toc": 0, "payloads_verified": True, "game_runtime_verified": False,
            "gpu_storage": {"mode": "shared_private_materials_and_textures", "physical_file_bytes": sizes[2],
                            "resource_gpu_buffer_bytes": struct.unpack_from("<Q", table, 40)[0],
                            "shared_disk_ranges": False},
            "generated_header": {"path": str(header_path.relative_to(output)), "sha256": archive.sha256_file(header_path)},
            "output": [{"name": path.name, "path": str(path.relative_to(output)), "size": path.stat().st_size,
                        "sha256": archive.sha256_file(path)} for path in output_files],
        }
        with manifest_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(manifest, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        return manifest
    except BaseException:
        for path in [*output_files, header_path, manifest_path]:
            path.unlink(missing_ok=True)
        for path in (header_path.parent, destination.parent):
            if path.exists() and not any(path.iterdir()):
                path.rmdir()
        if created_root and output.exists() and not any(output.iterdir()):
            output.rmdir()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("analyze", "build"), nargs="?", default="build")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--reader-tools", type=Path, required=True)
    parser.add_argument("--kits", type=Path, default=ROOT / "docs/armor-isolation-live-kits.json")
    parser.add_argument("--target", action="append", default=[])
    parser.add_argument("--coexist-manifest", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.action == "build" and args.output is None:
        parser.error("build requires --output")
    result = analyze(args) if args.action == "analyze" else build(args)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
