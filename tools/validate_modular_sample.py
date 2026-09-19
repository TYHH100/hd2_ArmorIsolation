"""Validate preserved TG-122 options offline and remove the generated test package."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
from itertools import product
import json
from pathlib import Path
import re
import struct
import tempfile

import armor_isolation_tool as tool
import build_b01_isolated as b01
import build_cm14_isolated as archive


PATCH = re.compile(r"[0-9a-fA-F]{16}\.patch_\d+")
TARGETS = ["a45385cd", "c1611ac9"]
DEFAULT_SOURCE = tool.ROOT / "1" / "milltina \u4fee\u5973 \u66ff\u6362tg-122"
RESOLUTION_SOURCE = Path("G:/Temp/HD2ModManager/Mods/Mods/shinano Chromium\u66ff\u6362CM-21"
                         "\u6218\u58d5\u62a4\u7406\u5458 CE-07\u62c6\u9664\u4e13\u5bb6_5dc4aef9")
RESOLUTION_TARGETS = ["d52bb413", "bd1e5e84", "5a17d6d6", "65c07df2"]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def tree(root):
    paths = list(root.rglob("*"))
    files = {path.relative_to(root).as_posix(): path for path in paths if path.is_file()}
    directories = {path.relative_to(root).as_posix() for path in paths if path.is_dir()}
    return files, directories


def read_patches(root, files, expected_count=9):
    result = {}
    for relative, path in sorted(files.items()):
        if not PATCH.fullmatch(path.name):
            continue
        data = path.read_bytes()
        _, types, entries = archive.parse_toc(data)
        sizes = [Path(str(path) + suffix).stat().st_size for suffix in archive.SUFFIXES]
        archive.validate_segments(entries, sizes, 72 + len(types) * 32 + len(entries) * 80)
        result[relative] = {"path": path, "main": data, "entries": {entry.key: entry for entry in entries},
                            "sizes": sizes}
    require(len(result) == expected_count, f"Expected {expected_count} patch triplets")
    return result


def included_patches(option, patches):
    # The manager collects only files directly in each Include directory.
    included = [Path(value.replace("\\", "/")).as_posix().rstrip("/")
                for value in option.get("Include", [])]
    return [relative for directory in included for relative in patches
            if Path(relative).parent.as_posix() == directory]


def option_combinations(document, patches):
    groups = []
    binary_count = 0
    head_count = 0
    for option in document["Options"]:
        parent = included_patches(option, patches)
        children = option.get("SubOptions", [])
        if children:
            require(not parent and len(children) == 3, "Expected three mutually exclusive head variants")
            alternatives = [included_patches(child, patches) for child in children]
            require(sorted(map(len, alternatives)) == [0, 1, 1], "Unexpected TG-122 head patch selection")
            groups.append(alternatives)
            head_count += len(alternatives)
        else:
            require(len(parent) == 1, "Expected one patch per TG-122 top-level component")
            kinds = Counter(key[0] for key in patches[parent[0]]["entries"])
            if kinds == {archive.UNIT: 2}:
                groups.append([[], parent])
                binary_count += 1
            else:
                groups.append([parent])
    require(binary_count == 5 and head_count == 3, "Unexpected accessory or head option count")
    combinations = [list(dict.fromkeys(relative for group in selection for relative in group))
                    for selection in product(*groups)]
    require(len(combinations) == 96, "Expected 96 legal TG-122 option combinations")
    return combinations


def composite(patches, selected, first_wins):
    effective = {}
    for relative in selected:
        for key in patches[relative]["entries"]:
            if first_wins:
                effective.setdefault(key, relative)
            else:
                effective[key] = relative
    return effective


def verify_patch_payloads(before, after, mapping):
    expected = {(kind, mapping[kind, source]) for kind, source in before["entries"]}
    require(set(after["entries"]) == expected, "A component lost a resource or gained an unplanned resource")
    signatures = {}
    for key, source in before["entries"].items():
        private_key = key[0], mapping[key]
        target = after["entries"][private_key]
        require(source.sizes == target.sizes, "Resource lane sizes changed")
        source_main = before["main"][source.offsets[0]:source.offsets[0] + source.sizes[0]]
        target_main = after["main"][target.offsets[0]:target.offsets[0] + target.sizes[0]]
        expected_main, _, _ = archive.rewrite_references(key[0], source_main, mapping)
        require(target_main == expected_main, "Unexpected main payload change")
        signatures[key] = [hashlib.sha256(source_main).hexdigest()]
    for lane in (1, 2):
        suffix = archive.SUFFIXES[lane]
        with Path(str(before["path"]) + suffix).open("rb") as source_stream, \
                Path(str(after["path"]) + suffix).open("rb") as target_stream:
            for key, source in before["entries"].items():
                target = after["entries"][key[0], mapping[key]]
                source_hash = b01.range_hash(source_stream, source.offsets[lane], source.sizes[lane])
                target_hash = b01.range_hash(target_stream, target.offsets[lane], target.sizes[lane])
                require(source_hash == target_hash, "Stream or GPU payload changed")
                signatures[key].append(source_hash.hex())
    return signatures


def validate(source, defaults, report_path):
    source = source.resolve()
    files, directories = tree(source)
    baseline = {relative: archive.sha256_file(path) for relative, path in files.items()}
    patches = read_patches(source, files)
    source_document = json.loads((source / "manifest.json").read_text(encoding="utf-8-sig"))
    combinations = option_combinations(source_document, patches)
    report = {"sample": source.name, "source": str(source), "targets": TARGETS,
              "game_runtime_verified": False, "temporary_packages_removed": False,
              "runtime_mode": "universal_runtime", "source_patch_count": len(patches),
              "binary_accessory_count": 5, "head_variant_count": 3,
              "option_combination_count": len(combinations)}
    build_root = tool.ROOT / "build"
    build_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="modular-validation-", dir=build_root) as temporary:
        temporary_root = Path(temporary)
        package = tool.generate_package(source, Path(defaults["game"]), Path(defaults["reader_tools"]),
                                        Path(defaults["kits"]), TARGETS, temporary_root)
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        result_root = (package / manifest["modular"]["mod_directory"]).resolve()
        require(result_root == (package / "mod" / source.name).resolve(), "Unexpected preserved mod location")
        require(result_root.is_relative_to(package.resolve()), "Preserved mod escaped its package")
        output_files, output_directories = tree(result_root)
        require(set(files) == set(output_files), "Preserved mod file set differs")
        require(directories == output_directories, "Preserved mod directory set differs")
        patch_files = {relative + suffix for relative in patches for suffix in archive.SUFFIXES}
        for relative, path in output_files.items():
            if relative not in patch_files:
                require(archive.sha256_file(path) == baseline[relative], f"Attached file changed: {relative}")
        require((source / "manifest.json").read_bytes() == (result_root / "manifest.json").read_bytes(),
                "Original options manifest was changed")
        output_patches = read_patches(result_root, output_files)
        mapping = {}
        for row in manifest["mapping"]:
            key = int(row["type"], 16), int(row["source"], 16)
            require(key not in mapping, "TG-122 sample unexpectedly maps one source to multiple Kits")
            mapping[key] = int(row["target"], 16)
        source_keys = set().union(*(set(patch["entries"]) for patch in patches.values()))
        require(set(mapping) == source_keys, "Expected all sample resources to have private mappings")
        require(len(set(mapping.values())) == len(mapping), "Private resource IDs collide")
        require(not set(mapping.values()) & {key[1] for key in source_keys}, "An output still uses a source ID")
        signatures = {relative: verify_patch_payloads(before, output_patches[relative], mapping)
                      for relative, before in patches.items()}
        base = [relative for relative, patch in patches.items()
                if Counter(key[0] for key in patch["entries"]) == {archive.UNIT: 23}]
        shared = [relative for relative, patch in patches.items()
                  if Counter(key[0] for key in patch["entries"]) == {archive.MATERIAL: 8, archive.TEXTURE: 28}]
        require(len(base) == 1 and len(shared) == 1, "Unexpected base model or shared data layout")
        base_keys = set(patches[base[0]]["entries"])
        variants = []
        for relative, patch in patches.items():
            if relative in base + shared:
                continue
            require(set(patch["entries"]) <= base_keys, "Optional patch adds a new Unit instead of overriding it")
            for key in patch["entries"]:
                before = signatures[base[0]][key]
                changed = signatures[relative][key]
                require(before[0] != changed[0] and before[2] != changed[2], "Expected distinct main and GPU variant")
            variants.append({"patch": relative, "unit_count": len(patch["entries"]),
                             "same_private_ids_as_base": True, "distinct_main_and_gpu_preserved": True})
        required = {(int(row["type"], 16), int(row["target"], 16)) for row in manifest["required_resources"]}
        baseline_private = set().union(*(set(output_patches[relative]["entries"]) for relative in base + shared))
        require(required <= baseline_private, "Runtime requires resources absent from the base/shared packages")
        for first_wins in (True, False):
            for selection in combinations:
                original = composite(patches, selection, first_wins)
                isolated = composite(output_patches, selection, first_wins)
                expected = {(kind, mapping[kind, value]): relative
                            for (kind, value), relative in original.items()}
                require(isolated == expected, "Option combination changed effective resource provenance")
                require(required <= set(isolated), "A supported combination cannot satisfy runtime readiness")
        expected_output = {(result_root / relative).relative_to(package).as_posix() for relative in patch_files}
        require({Path(row["path"]).as_posix() for row in manifest["output"]} == expected_output,
                "Outer manifest does not cover every preserved patch lane")
        for row in manifest["output"]:
            require(archive.sha256_file(package / row["path"]) == row["sha256"], "Patch manifest hash mismatch")
        runtime_dir, release = tool.runtime_release()
        addon_hash = archive.sha256_file(package / "runtime/ArmorIsolation.addon64")
        require(addon_hash == archive.sha256_file(runtime_dir / "ArmorIsolation.addon64"), "Fixed DLL differs")
        require(addon_hash == next(row["sha256"] for row in release["files"]
                                   if row["name"] == "ArmorIsolation.addon64"), "Fixed DLL release hash differs")
        require(manifest["package_status"] == "built_and_runtime_configuration_validated", "Runtime not validated")
        require(manifest["game_runtime_verified"] is False, "Offline validation must not claim game acceptance")
        report.update({"package_id": manifest["package_id"], "source_file_count": len(files),
                       "source_directory_count": len(directories), "all_relative_paths_preserved": True,
                       "all_non_patch_bytes_preserved": True, "original_manifest_bytes_preserved": True,
                       "private_resource_counts": dict(Counter(row["kind"] for row in manifest["mapping"])),
                       "component_variants": variants, "shared_material_patch_count": len(shared),
                       "source_gpu_file_bytes": sum(patch["sizes"][2] for patch in patches.values()),
                       "output_gpu_file_bytes": sum(patch["sizes"][2] for patch in output_patches.values()),
                       "all_stream_gpu_resource_payloads_equal": True,
                       "required_resources_available_from_base_and_shared": True,
                       "equivalent_compositions_checked": len(combinations) * 2,
                       "simulated_precedence": ["first_selected_patch_wins", "last_selected_patch_wins"],
                       "actual_game_precedence_verified": False,
                       "runtime_configuration_validated": True, "addon_sha256": addon_hash})
    require(not temporary_root.exists(), "Temporary test package was not removed")
    require(all(archive.sha256_file(path) == baseline[relative] for relative, path in files.items()),
            "Source mod changed during validation")
    report["temporary_packages_removed"] = True
    report["source_unchanged"] = True
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("MODULAR_SAMPLE_OK", report_path)
    return report


def verify_mapped_payloads(before, after, rows, shared_mapping):
    expected = {(int(row["type"], 16), int(row["target"], 16)) for row in rows}
    require(set(after["entries"]) == expected, "Component TOC differs from its private mapping")
    source_keys = {(int(row["type"], 16), int(row["source"], 16)) for row in rows}
    require(source_keys == set(before["entries"]), "A source resource was dropped")
    for row in rows:
        kind, original_id, private_id = (int(row[key], 16) for key in ("type", "source", "target"))
        original, private = before["entries"][kind, original_id], after["entries"][kind, private_id]
        require(original.sizes == private.sizes, "A resource lane size changed")
        original_main = before["main"][original.offsets[0]:original.offsets[0] + original.sizes[0]]
        private_main = after["main"][private.offsets[0]:private.offsets[0] + private.sizes[0]]
        expected_main, _, _ = archive.rewrite_references(kind, original_main, shared_mapping)
        require(private_main == expected_main, "Unexpected resolution sample main payload change")
    for lane in (1, 2):
        suffix = archive.SUFFIXES[lane]
        with Path(str(before["path"]) + suffix).open("rb") as source_stream, \
                Path(str(after["path"]) + suffix).open("rb") as target_stream:
            for row in rows:
                kind, original_id, private_id = (int(row[key], 16) for key in ("type", "source", "target"))
                original, private = before["entries"][kind, original_id], after["entries"][kind, private_id]
                require(b01.range_hash(source_stream, original.offsets[lane], original.sizes[lane]) ==
                        b01.range_hash(target_stream, private.offsets[lane], private.sizes[lane]),
                        "Resolution sample stream or GPU payload changed")


def material_slots(patch, key):
    entry = patch["entries"][key]
    data = patch["main"][entry.offsets[0]:entry.offsets[0] + entry.sizes[0]]
    count = struct.unpack_from("<I", data, 0x40)[0]
    slots = struct.unpack_from(f"<{count}I", data, 0x88)
    values = struct.unpack_from(f"<{count}Q", data, 0x88 + count * 4)
    return dict(zip(slots, values))


def validate_resolution(source, defaults, report_path):
    source = source.resolve()
    files, directories = tree(source)
    baseline = {relative: archive.sha256_file(path) for relative, path in files.items()}
    patches = read_patches(source, files, 3)
    document = json.loads((source / "manifest.json").read_text(encoding="utf-8-sig"))
    options = document["Options"]
    require(len(options) == 2, "Expected the inspected model and resolution option groups")
    model_option = next(option for option in options if not option.get("SubOptions"))
    texture_option = next(option for option in options if option.get("SubOptions"))
    model_paths = included_patches(model_option, patches)
    require(len(model_paths) == 1 and not included_patches(texture_option, patches), "Unexpected parent patch layout")
    branches = [(child["Name"], included_patches(child, patches)) for child in texture_option["SubOptions"]]
    require({name for name, _ in branches} == {"4K", "8K"} and all(len(paths) == 1 for _, paths in branches),
            "Expected two single-selection resolution branches")
    report = {"sample": source.name, "source": str(source), "targets": RESOLUTION_TARGETS,
              "game_runtime_verified": False, "temporary_packages_removed": False,
              "runtime_mode": "universal_runtime", "source_patch_count": 3,
              "mutually_exclusive_resolution_branches": [name for name, _ in branches]}
    build_root = tool.ROOT / "build"
    build_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="resolution-validation-", dir=build_root) as temporary:
        temporary_root = Path(temporary)
        package = tool.generate_package(source, Path(defaults["game"]), Path(defaults["reader_tools"]),
                                        Path(defaults["kits"]), RESOLUTION_TARGETS, temporary_root)
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        result_root = (package / manifest["modular"]["mod_directory"]).resolve()
        require(result_root == (package / "mod" / source.name).resolve(), "Unexpected preserved mod location")
        output_files, output_directories = tree(result_root)
        require(set(files) == set(output_files) and directories == output_directories, "Mod directory structure changed")
        patch_files = {relative + suffix for relative in patches for suffix in archive.SUFFIXES}
        for relative, path in output_files.items():
            if relative not in patch_files:
                require(archive.sha256_file(path) == baseline[relative], f"Attached file changed: {relative}")
        require((source / "manifest.json").read_bytes() == (result_root / "manifest.json").read_bytes(),
                "Original resolution options manifest changed")
        output_patches = read_patches(result_root, output_files, 3)
        patch_rows = {row["path"]: row["mapping"] for row in manifest["modular"]["patches"]}
        require(set(patch_rows) == set(patches), "Patch mapping provenance is incomplete")
        shared_mapping = {(int(row["type"], 16), int(row["source"], 16)): int(row["target"], 16)
                          for rows in patch_rows.values() for row in rows if int(row["type"], 16) != archive.UNIT}
        for relative, before in patches.items():
            verify_mapped_payloads(before, output_patches[relative], patch_rows[relative], shared_mapping)
        source_ids = {key[1] for patch in patches.values() for key in patch["entries"]}
        require(not source_ids & {key[1] for patch in output_patches.values() for key in patch["entries"]},
                "An output TOC still uses a source ID")
        first_path, second_path = branches[0][1][0], branches[1][1][0]
        first, second = patches[first_path], patches[second_path]
        common_materials = set(first["entries"]) & set(second["entries"])
        require(len(common_materials) == 1 and next(iter(common_materials))[0] == archive.MATERIAL,
                "Unexpected resolution material correspondence")
        material = next(iter(common_materials))
        first_slots, second_slots = material_slots(first, material), material_slots(second, material)
        require(first_slots.keys() == second_slots.keys(), "Material texture slots differ")
        alias_evidence = []
        for slot in first_slots:
            left, right = first_slots[slot], second_slots[slot]
            if left == right:
                continue
            left_key, right_key = (archive.TEXTURE, left), (archive.TEXTURE, right)
            require(left_key in first["entries"] and right_key in second["entries"], "Variant slot lacks its local texture")
            require(shared_mapping[left_key] == shared_mapping[right_key], "Equivalent resolution slot has different private IDs")
            alias_evidence.append({"slot": f"{slot:08x}", "source_variants": [f"{left:016x}", f"{right:016x}"],
                                   "private_id": f"{shared_mapping[left_key]:016x}",
                                   "gpu_bytes": [first["entries"][left_key].sizes[2], second["entries"][right_key].sizes[2]]})
        require(len(alias_evidence) == 3, "Expected three resolution texture aliases")
        require(sum(row["gpu_bytes"][0] != row["gpu_bytes"][1] for row in alias_evidence) == 2,
                "Expected two resolution-dependent images and one same-sized image")
        required = {(int(row["type"], 16), int(row["target"], 16)) for row in manifest["required_resources"]}
        selections = []
        for name, branch_paths in branches:
            selected = model_paths + branch_paths
            require(len(selected) == 2, "Resolution check enabled more than one texture branch")
            for first_wins in (True, False):
                source_effective = composite(patches, selected, first_wins)
                isolated = composite(output_patches, selected, first_wins)
                expected = {}
                for key, relative in source_effective.items():
                    rows = [row for row in patch_rows[relative]
                            if (int(row["type"], 16), int(row["source"], 16)) == key]
                    require(rows, "Effective source resource lacks its private mapping")
                    expected.update({(key[0], int(row["target"], 16)): relative for row in rows})
                require(isolated == expected, "Resolution selection changed resource provenance")
                require(required <= set(isolated), "Selected resolution cannot satisfy static runtime readiness")
            selections.append({"resolution": name, "selected_patches": selected,
                               "selected_gpu_file_bytes": sum(output_patches[relative]["sizes"][2] for relative in selected),
                               "runtime_required_satisfied": True})
        expected_output = {(result_root / relative).relative_to(package).as_posix() for relative in patch_files}
        require({Path(row["path"]).as_posix() for row in manifest["output"]} == expected_output,
                "Output report omits a preserved patch lane")
        for row in manifest["output"]:
            require(archive.sha256_file(package / row["path"]) == row["sha256"], "Output report hash mismatch")
        runtime_dir, release = tool.runtime_release()
        addon_hash = archive.sha256_file(package / "runtime/ArmorIsolation.addon64")
        require(addon_hash == archive.sha256_file(runtime_dir / "ArmorIsolation.addon64"), "Fixed runtime DLL differs")
        require(addon_hash == next(row["sha256"] for row in release["files"]
                                   if row["name"] == "ArmorIsolation.addon64"), "Fixed DLL release hash differs")
        require(manifest["package_status"] == "built_and_runtime_configuration_validated", "Runtime not validated")
        require(manifest["game_runtime_verified"] is False, "Offline validation must not claim game acceptance")
        report.update({"package_id": manifest["package_id"], "source_file_count": len(files),
                       "source_directory_count": len(directories), "all_relative_paths_preserved": True,
                       "all_non_patch_bytes_preserved": True, "original_manifest_bytes_preserved": True,
                       "private_resource_counts": dict(Counter(row["kind"] for row in manifest["mapping"])),
                       "texture_slot_aliases": alias_evidence, "resolution_selections": selections,
                       "source_gpu_file_bytes": sum(patch["sizes"][2] for patch in patches.values()),
                       "output_gpu_file_bytes": sum(patch["sizes"][2] for patch in output_patches.values()),
                       "all_stream_gpu_resource_payloads_equal": True,
                       "equivalent_compositions_checked": len(branches) * 2,
                       "simulated_precedence": ["first_selected_patch_wins", "last_selected_patch_wins"],
                       "actual_game_precedence_verified": False,
                       "runtime_configuration_validated": True, "addon_sha256": addon_hash})
    require(not temporary_root.exists(), "Temporary resolution test package was not removed")
    require(all(archive.sha256_file(path) == baseline[relative] for relative, path in files.items()),
            "Source mod changed during validation")
    report["temporary_packages_removed"] = True
    report["source_unchanged"] = True
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("RESOLUTION_SAMPLE_OK", report_path)
    return report


def main():
    defaults = tool.discover_defaults()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", choices=("tg122", "resolution"), default="tg122")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    resolution = args.sample == "resolution"
    source = args.source or (RESOLUTION_SOURCE if resolution else DEFAULT_SOURCE)
    report = args.report or tool.ROOT / "docs" / ("resolution-sample-validation.json" if resolution else
                                                 "modular-sample-validation.json")
    (validate_resolution if resolution else validate)(source, defaults, report)


if __name__ == "__main__":
    main()
