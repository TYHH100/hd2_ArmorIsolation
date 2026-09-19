"""Export a package manifest for the shared ArmorIsolation ReShade runtime."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys

import build_cm14_isolated as archive
from isolation_paths import resource_root

SCHEMA = "hd2-armor-runtime/1"
GAME_VERSION = "1.0.0.18930"
KITS_SHA256 = "e68b82eb7dacde3219f7d049b692dfb418f7f2a35516d98c3dab7515eb0409c1"
DEFAULT_KITS = resource_root() / "docs/armor-isolation-live-kits.json"
MAX_RESOURCES = 16384
MAX_FIELDS = 32768
MAX_REQUIREMENTS = 131072
MAX_PROFILE_BYTES = 8 * 1024 * 1024
ZERO_OWNER = "00000000"


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"Invalid JSON number: {value}")))


def _hex(value, width, label, *, nonzero=False):
    if not isinstance(value, str) or re.fullmatch(rf"[0-9a-f]{{{width}}}", value) is None:
        raise ValueError(f"{label} must be {width} lowercase hexadecimal characters")
    if nonzero and int(value, 16) == 0:
        raise ValueError(f"{label} must be nonzero")
    return value


def _uint(value, label):
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(f"{label} must be uint32")
    return value


def _rows(value, label, maximum=MAX_RESOURCES):
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise ValueError(f"{label} must contain 1..{maximum} rows")
    if any(not isinstance(row, dict) for row in value):
        raise ValueError(f"{label} rows must be objects")
    return value


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _selected_metadata(manifest, kits_path):
    if manifest.get("source_kits_sha256") != KITS_SHA256:
        raise ValueError("Manifest source_kits_sha256 is not the verified snapshot")
    if archive.sha256_file(Path(kits_path)) != KITS_SHA256:
        raise ValueError("Kit snapshot SHA256 does not match the verified version")
    snapshot = {kit["id"]: kit for kit in _load_json(kits_path)}
    selected, seen = [], set()
    for row in _rows(manifest.get("targets"), "targets", 402):
        owner = _hex(row.get("kit"), 8, "target kit", nonzero=True)
        if owner in seen or owner not in snapshot:
            raise ValueError(f"Duplicate or unknown target kit: {owner}")
        expected = snapshot[owner]
        if (_hex(row.get("archive"), 16, "target archive", nonzero=True) != expected["archive"]
                or _uint(row.get("type"), "target type") != expected["type"]
                or expected["type"] not in (0, 1)):
            raise ValueError(f"Target metadata differs from snapshot: {owner}")
        selected.append(copy.deepcopy(expected))
        seen.add(owner)
    if "selected_kit_metadata" in manifest:
        supplied = _rows(manifest["selected_kit_metadata"], "selected_kit_metadata", 402)
        by_id = {_hex(row.get("id"), 8, "metadata id", nonzero=True): row for row in supplied}
        if len(by_id) != len(supplied) or set(by_id) != seen:
            raise ValueError("Selected metadata does not match target kits")
        for kit in selected:
            if _canonical(by_id[kit["id"]]) != _canonical(kit):
                raise ValueError(f"Selected metadata differs from snapshot: {kit['id']}")
        selected = copy.deepcopy(supplied)
    return selected


def make_runtime_profile(manifest: dict, kits_path: Path = DEFAULT_KITS) -> dict:
    if not isinstance(manifest, dict):
        raise ValueError("Manifest must be an object")
    if (manifest.get("expected_game_version") != GAME_VERSION
            or manifest.get("expected_game_dll_sha256") != archive.DLL_SHA256):
        raise ValueError("Manifest game version or DLL SHA256 is unsupported")
    metadata = _selected_metadata(manifest, kits_path)
    owners = {kit["id"] for kit in metadata}
    mapping, by_source, by_target = [], {}, {}
    for row in _rows(manifest.get("mapping"), "mapping"):
        clean = {key: _hex(row.get(key), 8 if key == "kit" else 16, f"mapping {key}",
                          nonzero=key != "kit") for key in ("kit", "type", "source", "target")}
        owner, kind = clean["kit"], int(clean["type"], 16)
        if kind not in archive.KINDS or owner not in owners | {ZERO_OWNER}:
            raise ValueError("Mapping resource type or owner is unsupported")
        if owner == ZERO_OWNER and kind == archive.UNIT:
            raise ValueError("Shared Unit mappings are not allowed")
        key = (owner, clean["type"], clean["source"])
        target = (clean["type"], clean["target"])
        if key in by_source or target in by_target or clean["source"] == clean["target"]:
            raise ValueError("Duplicate or unchanged resource mapping")
        by_source[key], by_target[target] = clean, clean
        mapping.append(clean)

    available_fields = set()
    for kit in metadata:
        for body in kit["bodies"]:
            for piece in body["pieces"]:
                if piece["slot"] != 1:
                    available_fields.update((kit["id"], offset, piece["resources"][name])
                                            for name, offset in archive.FIELD_OFFSETS.items())
    fields, field_keys = [], set()
    for row in _rows(manifest.get("piece_fields"), "piece_fields", MAX_FIELDS):
        clean = {key: _hex(row.get(key), 8 if key == "kit" else 16, f"field {key}", nonzero=True)
                 for key in ("kit", "source", "target")}
        clean["offset"] = _uint(row.get("offset"), "field offset")
        key = (clean["kit"], clean["offset"], clean["source"])
        if key in field_keys or key not in available_fields:
            raise ValueError("Duplicate or invalid Piece field")
        kind = archive.UNIT if clean["offset"] == 0 else archive.TEXTURE
        candidates = [by_source.get((owner, f"{kind:016x}", clean["source"]))
                      for owner in (clean["kit"], ZERO_OWNER)]
        matches = [entry for entry in candidates if entry is not None]
        if len(matches) != 1 or matches[0]["target"] != clean["target"]:
            raise ValueError("Piece field has no unique matching resource mapping")
        fields.append(clean)
        field_keys.add(key)

    # Older fixed-profile manifests lacked dependency rows; their runtimes waited
    # for all resources owned by each Kit and, for B-01, the shared mod set.
    required_input = manifest.get("required_resources")
    if "required_resources" not in manifest:
        required_input = [{"kit": kit["id"], "type": row["type"], "target": row["target"]}
                          for kit in metadata for row in mapping if row["kit"] in (ZERO_OWNER, kit["id"])]
    required, required_keys, used_targets = [], set(), set()
    for row in _rows(required_input, "required_resources", MAX_REQUIREMENTS):
        clean = {key: _hex(row.get(key), 8 if key == "kit" else 16, f"required {key}", nonzero=True)
                 for key in ("kit", "type", "target")}
        target = (clean["type"], clean["target"])
        key = (clean["kit"], *target)
        resource = by_target.get(target)
        if (clean["kit"] not in owners or key in required_keys or resource is None
                or resource["kit"] not in (ZERO_OWNER, clean["kit"])):
            raise ValueError("Duplicate, unknown, or wrongly owned required resource")
        required.append(clean)
        required_keys.add(key)
        used_targets.add(target)
    if used_targets != set(by_target):
        raise ValueError("Every mapped resource must be required by a target")
    for row in mapping:
        if row["kit"] != ZERO_OWNER and (row["kit"], row["type"], row["target"]) not in required_keys:
            raise ValueError("Owned resource is missing from its Kit requirements")
    for field in fields:
        kind = archive.UNIT if field["offset"] == 0 else archive.TEXTURE
        if (field["kit"], f"{kind:016x}", field["target"]) not in required_keys:
            raise ValueError("Piece field resource is missing from its Kit requirements")

    if "package_id" in manifest:
        package_id = _hex(manifest["package_id"], 24, "package_id", nonzero=True)
    else:
        identity = {"targets": sorted(metadata, key=lambda row: row["id"]),
                    "mapping": sorted(mapping, key=_canonical), "piece_fields": sorted(fields, key=_canonical)}
        package_id = hashlib.sha256(_canonical(identity).encode("ascii")).hexdigest()[:24]
    return {"schema": SCHEMA, "package_id": package_id,
            "expected_game_version": GAME_VERSION, "expected_game_dll_sha256": archive.DLL_SHA256,
            "selected_kit_metadata": metadata, "mapping": mapping,
            "piece_fields": fields, "required_resources": required}


def write_profile(profile: dict, output_file: Path) -> None:
    output_file = Path(output_file)
    package_id = _hex(profile.get("package_id"), 24, "package_id", nonzero=True)
    if output_file.name != f"{package_id}.json":
        raise ValueError("Runtime profile filename must be <package_id>.json")
    payload = json.dumps(profile, ensure_ascii=True, indent=2, allow_nan=False) + "\n"
    if len(payload.encode("utf-8")) > MAX_PROFILE_BYTES:
        raise ValueError("Runtime profile exceeds the 8 MiB size limit")
    created = False
    try:
        with output_file.open("x", encoding="utf-8", newline="\n") as stream:
            created = True
            stream.write(payload)
    except BaseException:
        if created:
            output_file.unlink(missing_ok=True)
        raise


def export_manifest(manifest_path: Path, output_file: Path, kits_path: Path = DEFAULT_KITS) -> dict:
    profile = make_runtime_profile(_load_json(manifest_path), kits_path)
    output_file = Path(output_file)
    if output_file.is_dir():
        output_file /= f"{profile['package_id']}.json"
    write_profile(profile, output_file)
    return profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Existing directory or <package_id>.json path")
    parser.add_argument("--kits", type=Path, default=DEFAULT_KITS)
    args = parser.parse_args()
    try:
        profile = export_manifest(args.manifest, args.output, args.kits)
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"package_id": profile["package_id"], "targets": len(profile["selected_kit_metadata"]),
                      "resources": len(profile["mapping"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
