"""Isolate a legacy or V1 mod while preserving its folders and option variants."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import shutil
import struct

import build_generic_isolated as generic
from modular_source import load_catalog, manifest_options
from modular_texture_aliases import discover_texture_aliases

archive = generic.archive
b01 = generic.b01
SCHEMA = "hd2-modular-isolation/1"


def load_family(path, kits=()):
    catalog = load_catalog(path)
    sources = {relative: generic.load_source(catalog.root / relative) for relative in catalog.patch_paths}
    aliases, alias_evidence = discover_texture_aliases(catalog, sources, kits)
    variants = defaultdict(list)
    for relative, source in sources.items():
        for key, entry in source.entries.items():
            variants[aliases.get(key, key)].append((relative, source, entry))
    if not variants:
        raise ValueError("Mod contains no supported patch resources")
    return catalog, sources, variants, aliases, alias_evidence


def references(kind, source, entry):
    payload = source.data[entry.offsets[0]:entry.offsets[0] + entry.sizes[0]]
    return {(reference_kind, struct.unpack_from("<Q", payload, offset)[0])
            for reference_kind, offset in archive.reference_fields(kind, payload)
            if struct.unpack_from("<Q", payload, offset)[0]}


def dependency_closure(target, variants, aliases=None):
    aliases = aliases or {}
    roots = {(archive.UNIT, int(piece["resources"]["unit"], 16)) for piece in b01.target_pieces(target)}
    missing = roots - variants.keys()
    if missing:
        raise ValueError("Source does not contain every non-cape Unit; partial replacements are unsupported")
    roots.update((archive.TEXTURE, int(value, 16)) for piece in b01.target_pieces(target)
                 for name, value in piece["resources"].items()
                 if name != "unit" and (archive.TEXTURE, int(value, 16)) in variants)
    selected, external, pending = set(), set(), set(roots)
    while pending:
        key = pending.pop()
        if key in selected:
            continue
        selected.add(key)
        # All versions share an identity, but their references can differ.
        for _, source, entry in variants[key]:
            for reference in references(key[0], source, entry):
                reference = aliases.get(reference, reference)
                if reference in variants:
                    if reference not in selected:
                        pending.add(reference)
                else:
                    external.add(reference)
    return selected, external


def candidates(kits, variants, aliases=None):
    result = []
    for kit in kits:
        units = {(archive.UNIT, int(piece["resources"]["unit"], 16)) for piece in b01.target_pieces(kit)}
        matched = units & variants.keys()
        if not matched:
            continue
        reasons = []
        if kit["type"] not in (0, 1):
            reasons.append("Only armor and helmet Kits are supported")
        elif units != matched:
            reasons.append("Source does not contain every non-cape Unit; partial replacements are unsupported")
        else:
            try:
                dependency_closure(kit, variants, aliases)
            except (ValueError, struct.error) as error:
                reasons.append(str(error))
        result.append({"id": kit["id"], "archive": kit["archive"], "type": kit["type"],
                       "unit_matched": len(matched), "unit_total": len(units),
                       "supported": not reasons, "reasons": reasons, "selection": "explicit_required"})
    return result


def select_targets(kits, variants, requested, aliases=None):
    if not requested:
        raise ValueError("Explicit target Kit IDs are required")
    normalized = []
    for value in requested:
        text = str(value).lower().removeprefix("0x")
        if not generic.re.fullmatch(r"[0-9a-f]{1,8}", text) or int(text, 16) == 0:
            raise ValueError(f"Invalid target Kit ID: {value}")
        normalized.append(f"{int(text, 16):08x}")
    if len(normalized) != len(set(normalized)):
        raise ValueError("Duplicate target Kit IDs")
    choices = {row["id"]: row for row in candidates(kits, variants, aliases)}
    targets = []
    for identity in sorted(normalized):
        candidate = choices.get(identity)
        if candidate is None or not candidate["supported"]:
            raise ValueError(f"Unsupported target {identity}: {candidate['reasons'] if candidate else 'no Unit match'}")
        matches = [kit for kit in kits if kit["id"] == identity]
        if len(matches) != 1:
            raise ValueError(f"Ambiguous target Kit {identity}")
        targets.append(matches[0])
    return targets


def include_patches(catalog, includes):
    directories = {(catalog.root / value.replace("\\", "/")).resolve() for value in includes or []}
    return {relative for relative in catalog.patch_paths if (catalog.root / relative).parent in directories}


def option_providers(catalog, sources, aliases=None):
    aliases = aliases or {}
    def keys(paths):
        return {aliases.get(key, key) for path in paths for key in sources[path].entries}

    result = []
    options = manifest_options(catalog.manifest)
    if not options:
        paths = {path for path in sources if path.parent == Path(".")}
        return [{"id": "root", "name": "root", "paths": paths, "guaranteed": keys(paths), "all_keys": keys(paths)}]
    for index, option in enumerate(options):
        parents = include_patches(catalog, option.get("Include"))
        branches = [parents | include_patches(catalog, child.get("Include")) for child in option.get("SubOptions") or []]
        branches = branches or [parents]
        guarantee = set.intersection(*(keys(paths) for paths in branches))
        all_paths = set.union(*branches)
        result.append({"id": str(index), "name": option["Name"], "paths": all_paths,
                       "guaranteed": guarantee, "all_keys": keys(all_paths)})
    return result


def common_suppliers(catalog, sources, required, aliases=None):
    providers = option_providers(catalog, sources, aliases)
    reachable = set().union(*(row["paths"] for row in providers))
    if reachable != sources.keys():
        missing = sorted(path.as_posix() for path in sources.keys() - reachable)
        raise ValueError("Patch has no manifest Include: " + ", ".join(missing))
    units = {key for key in required if key[0] == archive.UNIT}
    bases = [row for row in providers if units <= row["guaranteed"]]
    if not bases:
        raise ValueError("No base model option guarantees all target Units across its suboptions")
    base = min(bases, key=lambda row: (-sum(key[0] == archive.UNIT for key in row["guaranteed"]),
                                     int(row["id"]) if row["id"] != "root" else -1))
    chosen, available = [base], set(base["guaranteed"])
    # Data-only alternatives (for example 4K/8K) must each supply the needed IDs.
    data = [row for row in providers if row is not base and
            not any(key[0] == archive.UNIT for key in row["all_keys"])]
    while required - available:
        useful = [row for row in data if row["guaranteed"] & (required - available)]
        if not useful:
            raise ValueError("Optional variants need resources without a common supplier; "
                             "every resolution must provide the required IDs. Selection-specific profiles are unsupported")
        best = min(useful, key=lambda row: (-len(row["guaranteed"] & (required - available)), row["id"]))
        chosen.append(best)
        available.update(best["guaranteed"])
        data.remove(best)
    return chosen


def analyze(args):
    kits = generic.validate_version(args.game, args.kits)
    catalog, sources, variants, aliases, alias_evidence = load_family(args.source, kits)
    return {"schema": generic.SCHEMA, "source_kind": "modular", "source": str(catalog.root),
            "expected_game_version": "1.0.0.18930", "auto_selected": [],
            "source_counts": dict(Counter(archive.KINDS[key[0]] for key in variants)),
            "candidates": candidates(kits, variants, aliases),
            "modular": {"manifest_format": "v1" if "Version" in catalog.manifest else "legacy",
                        "option_count": len(catalog.manifest.get("Options") or []),
                        "patches": [{"path": path.as_posix(), "resources": len(source.entries)}
                                    for path, source in sources.items()],
                        "missing_includes": list(catalog.missing_includes), "texture_aliases": alias_evidence},
            "notes": ["All folders and options are preserved; targets must be selected explicitly.",
                      "Common suppliers for every variant are verified during generation."]}


def package_identity(catalog, targets, coexist):
    lanes = [{"suffix": path.as_posix(), "sha256": row["sha256"]}
             for path, row in catalog.inventory.items()]
    base = generic.package_identity(lanes, targets, coexist)
    return hashlib.sha256((SCHEMA + ":" + base).encode("ascii")).hexdigest()[:24]


def validate_output(path, catalog, game):
    output = Path(path).resolve()
    for protected in (catalog.root, Path(game).resolve()):
        if output == protected or output.is_relative_to(protected) or protected.is_relative_to(output):
            raise ValueError("Output must be outside the source mod and game directory")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Output must be a new directory or an empty staging directory")
    return output


def build(args):
    kits = generic.validate_version(args.game, args.kits)
    catalog, sources, variants, aliases, alias_evidence = load_family(args.source, kits)
    output = validate_output(args.output, catalog, args.game)
    targets = select_targets(kits, variants, getattr(args, "target", []), aliases)
    plans, external, retained = [], set(), set()
    for target in targets:
        selected, references_outside = dependency_closure(target, variants, aliases)
        plans.append((target, selected))
        retained.update(selected)
        external.update(references_outside)
    suppliers = common_suppliers(catalog, sources, retained, aliases)
    coexist_reserved, coexist = generic.read_coexist(getattr(args, "coexist_manifest", []) or [], targets)
    identity = package_identity(catalog, targets, coexist)
    reader = archive.VanillaReader(Path(args.game), Path(args.reader_tools))
    archives = list(dict.fromkeys([target["archive"] for target in targets] +
                                  ["9ba626afa44a3aa3", "18235e0c9ec0e636"]))
    raw_keys = {key for source in sources.values() for key in source.entries}
    external_check = generic.inspect_external(reader, archives, external, raw_keys)
    reserved = {int(value, 16) for kit in kits for body in kit["bodies"] for piece in body["pieces"]
                for value in piece["resources"].values()}
    reserved.update(value for _, value in raw_keys)
    reserved.update(value for name in archives for _, value in reader.entries(name))
    reserved.update(coexist_reserved)
    shared, mappings, rows, required = generic.make_resource_mappings(plans, reserved, identity)
    used_private = {int(row["target"], 16) for row in rows}
    unused, unused_rows = archive.make_mapping(variants.keys() - retained, reserved | used_private, 0,
                                              f"mods/armor_isolation/v1/{identity}/unbound")
    all_shared = {**shared, **{key: value for key, value in unused.items() if key[0] != archive.UNIT}}
    all_shared.update({key: all_shared[canonical] for key, canonical in aliases.items()})
    storage_rows = [*rows, *unused_rows]
    by_source = defaultdict(list)
    for row in storage_rows:
        by_source[int(row["type"], 16), int(row["source"], 16)].append(row)
    fields = set()
    for target, _ in plans:
        mapping = mappings[target["id"]]
        for piece in b01.target_pieces(target):
            for name, offset in archive.FIELD_OFFSETS.items():
                key = archive.UNIT if name == "unit" else archive.TEXTURE, int(piece["resources"][name], 16)
                if key in mapping:
                    fields.add((int(target["id"], 16), offset, key[1], mapping[key]))
    mod_relative = Path("mod") / catalog.root.name
    mod_output = output / mod_relative
    created_root = not output.exists()
    output.mkdir(parents=True, exist_ok=True)
    output_rows, patch_records, adjustments = [], [], []
    try:
        catalog.copy_passthrough(mod_output)
        for relative, source in sources.items():
            expanded, payloads, patch_mapping, rewritten = [], {}, [], []
            for key, entry in source.entries.items():
                before = source.data[entry.offsets[0]:entry.offsets[0] + entry.sizes[0]]
                if key[0] == archive.UNIT and key in retained:
                    before, changes = generic.repair_known_helmet(key[1], before)
                    if changes:
                        adjustments.append({"patch": relative.as_posix(), "source_unit": f"{key[1]:016x}",
                                            "rule": generic.REPAIR_CATALOG, "fields": changes})
                after, changed, _ = archive.rewrite_references(key[0], before, all_shared)
                for canonical_row in by_source[aliases.get(key, key)]:
                    row = {**canonical_row, "source": f"{key[1]:016x}"}
                    target_id = int(row["target"], 16)
                    expanded.append(archive.Entry((target_id, *entry.values[1:])))
                    payloads[key[0], target_id] = after
                    patch_mapping.append(row)
                    rewritten.append({"source": row["source"], "target": row["target"], "fields": changed})
            table, original, relocated, sizes = archive.plan_archive(
                source.header, source.types, expanded, {entry.key: entry.key[1] for entry in expanded})
            archive.validate_segments(relocated, sizes, len(table))
            destination = mod_output / relative
            generic.write_archive(source, destination, table, original, relocated, payloads, sizes)
            parsed = archive.parse_toc(destination.read_bytes())[2]
            if parsed != relocated:
                raise ValueError("Generated modular TOC did not round-trip")
            generic.verify_payloads(source, destination, {entry.key: entry for entry in parsed}, patch_mapping, payloads)
            for lane, suffix in enumerate(archive.SUFFIXES):
                path = Path(str(destination) + suffix)
                if not source.lanes[lane]["exists"]:
                    if path.stat().st_size:
                        raise ValueError("Originally absent lane unexpectedly contains output data")
                    path.unlink()
                    continue
                output_rows.append({"name": path.name, "path": path.relative_to(output).as_posix(),
                                    "size": path.stat().st_size, "sha256": archive.sha256_file(path)})
            patch_records.append({"path": relative.as_posix(), "source_resources": len(source.entries),
                                  "output_resources": len(parsed), "mapping": patch_mapping,
                                  "rewritten_references": rewritten, "gpu_bytes": sizes[2]})
        actual_files = {path.relative_to(mod_output) for path in mod_output.rglob("*") if path.is_file()}
        actual_dirs = {path.relative_to(mod_output) for path in mod_output.rglob("*") if path.is_dir()}
        if actual_files != set(catalog.files) or actual_dirs != set(catalog.directories):
            raise ValueError("Mod folder structure changed")
        catalog.verify_unchanged()
        manifest = {
            "schema": generic.SCHEMA, "revision": 1, "package_id": identity, "source_kind": "modular",
            "expected_game_version": "1.0.0.18930", "expected_game_dll_sha256": archive.DLL_SHA256,
            "source": str(catalog.root), "source_unchanged": True, "source_kits_sha256": generic.KITS_SHA256,
            "source_inventory": catalog.serializable_inventory(),
            "targets": [{"kit": target["id"], "archive": target["archive"], "type": target["type"],
                         "unit_references": len(b01.target_pieces(target)), "resource_count": len(selected)}
                        for target, selected in plans],
            "selected_kit_metadata": targets, "mapping": rows, "preserved_unbound_mapping": unused_rows,
            "required_resources": required, "shared_resource_owner": "00000000",
            "shared_resource_count": len(shared),
            "piece_fields": [{"kit": f"{owner:08x}", "offset": offset, "source": f"{source:016x}",
                              "target": f"{destination:016x}"} for owner, offset, source, destination in sorted(fields)],
            "external_material_check": external_check, "coexisting_manifests": coexist,
            "helmet_lod_adjustments": adjustments, "payloads_verified": True, "source_ids_in_output_toc": 0,
            "game_runtime_verified": False, "output": output_rows,
            "modular": {"schema": SCHEMA, "mod_directory": mod_relative.as_posix(),
                        "manifest_format": "v1" if "Version" in catalog.manifest else "legacy",
                        "option_count": len(catalog.manifest.get("Options") or []),
                        "manifest_bytes_preserved": True, "folder_structure_preserved": True,
                        "texture_aliases": alias_evidence,
                        "source_resource_aliases": [{"type": f"{key[0]:016x}", "source": f"{key[1]:016x}",
                                                     "canonical": f"{canonical[1]:016x}"}
                                                    for key, canonical in sorted(aliases.items())],
                        "missing_includes": list(catalog.missing_includes), "patches": patch_records,
                        "required_options": [{"id": row["id"], "name": row["name"],
                                              "patches": sorted(path.as_posix() for path in row["paths"])}
                                             for row in suppliers],
                        "base_model_patch": sorted(path.as_posix() for path in suppliers[0]["paths"]),
                        "shared_data_patches": sorted({path.as_posix() for row in suppliers[1:] for path in row["paths"]}),
                        "runtime_requirements_mode": "all_variants_common_suppliers",
                        "selection_preserved": "Original Include/SubOptions and patch names; no overlay flattening",
                        "unbound_resources": "Privately renamed and preserved; not redirected to unselected Kits"},
            "gpu_storage": {"mode": "preserved_component_and_resolution_variants",
                            "physical_file_bytes": sum(row["size"] for row in output_rows if row["path"].endswith(".gpu_resources")),
                            "shared_disk_ranges": False},
        }
        (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return manifest
    except BaseException:
        if mod_output.exists() and mod_output.parent == output / "mod":
            shutil.rmtree(mod_output)
        (output / "manifest.json").unlink(missing_ok=True)
        if mod_output.parent.exists() and not any(mod_output.parent.iterdir()):
            mod_output.parent.rmdir()
        if created_root and output.exists() and not any(output.iterdir()):
            output.rmdir()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("analyze", "build"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--reader-tools", type=Path, required=True)
    parser.add_argument("--kits", type=Path, default=generic.ROOT / "docs/armor-isolation-live-kits.json")
    parser.add_argument("--target", action="append", default=[])
    parser.add_argument("--coexist-manifest", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.action == "build" and args.output is None:
        parser.error("build requires --output")
    print(json.dumps(analyze(args) if args.action == "analyze" else build(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
