"""Find strictly equivalent Unit IDs across mutually exclusive mod options."""

from collections import defaultdict
from pathlib import Path, PureWindowsPath
import hashlib
import struct

import build_cm14_isolated as archive
from modular_source import manifest_options


def _payload(source, key):
    entry = source.entries[key]
    start, size = entry.offsets[0], entry.sizes[0]
    result = source.data[start:start + size]
    if len(result) != size:
        raise ValueError("Truncated Unit payload during alias analysis")
    return result


def _normalized_payload(payload):
    """Ignore material slot bindings while retaining all Unit structure."""
    result = bytearray(payload)
    if len(result) < 0x74:
        raise ValueError("Unit payload is too small for alias analysis")
    table = struct.unpack_from("<I", result, 0x70)[0]
    if table:
        if table > len(result) - 4:
            raise ValueError("Invalid Unit material table")
        count = struct.unpack_from("<I", result, table)[0]
        end = table + 4 + count * 12
        if end > len(result):
            raise ValueError("Truncated Unit material table")
        result[table + 4:end] = b"\0" * (count * 12)
    for _, offset in archive.reference_fields(archive.UNIT, bytes(result)):
        result[offset:offset + 8] = b"\0" * 8
    return bytes(result)


def _mesh_signature(payload):
    meshes, references = archive.parse_unit_meshes(payload)
    return tuple(meshes), tuple(meshes[index] for _, index in references)


def _branch(paths, sources):
    resources = {}
    for path in sorted(paths):
        source = sources[path]
        for key in source.entries:
            if key[0] not in (archive.UNIT, archive.MATERIAL, archive.TEXTURE):
                raise ValueError("branch contains unsupported resource type")
            if key in resources:
                raise ValueError("branch has ambiguous duplicate resource providers")
            resources[key] = source
    if not resources:
        raise ValueError("branch contains no resources")
    return resources


def _included_paths(option, patches):
    includes = {Path(*PureWindowsPath(value).parts) for value in option.get("Include", [])}
    return {path for path in patches if path.parent in includes}


def _unit_aliases(branches, canonical_ids=frozenset()):
    """Return aliases only when every alias has a one-to-one structural match.

    Exact normalized bytes are preferred. MeshInfo plus selected mesh IDs is a
    fallback for variants that changed material-dependent Unit fields as well.
    """
    source_units = [{key for key in branch if key[0] == archive.UNIT} for branch in branches]
    if not any(source_units):
        return {}, []
    canonical_index = max(range(len(branches)), key=lambda index: (
        len(source_units[index] & canonical_ids), len(branches[index]), -index))
    canonical = source_units[canonical_index]
    canonical_branch = branches[canonical_index]
    eligible = canonical & set(canonical_ids) if canonical_ids else set(canonical)
    if not canonical:
        return {}, []

    exact = defaultdict(list)
    mesh = defaultdict(list)
    for key in eligible:
        payload = _payload(canonical_branch[key], key)
        exact[_normalized_payload(payload)].append(key)
        try:
            mesh[_mesh_signature(payload)].append(key)
        except (ValueError, struct.error):
            pass

    aliases = {}
    claimed = set()
    evidence = []
    for branch_index, branch in enumerate(branches):
        if branch is canonical_branch:
            continue
        for key in sorted(key for key in branch if key[0] == archive.UNIT):
            payload = _payload(branch[key], key)
            matches = [candidate for candidate in exact.get(_normalized_payload(payload), [])
                       if candidate not in claimed and candidate != key]
            method = "normalized"
            if len(matches) != 1:
                try:
                    matches = [candidate for candidate in mesh.get(_mesh_signature(payload), [])
                               if candidate not in claimed and candidate != key and candidate not in branch]
                except (ValueError, struct.error):
                    matches = []
                method = "mesh"
            if len(matches) != 1:
                continue
            target = matches[0]
            aliases[key] = target
            claimed.add(target)
            evidence.append({"source": f"{key[1]:016x}", "canonical": f"{target[1]:016x}",
                             "method": method, "branch": branch_index,
                             "normalized_sha256": hashlib.sha256(_normalized_payload(payload)).hexdigest()})
    return aliases, evidence


def discover_unit_aliases(catalog, sources, kits=()):
    """Return typed Unit aliases and diagnostics for exclusive option groups."""
    patches = tuple(Path(path) for path in catalog.patch_paths)
    sources = {Path(path): source for path, source in sources.items()}
    aliases, evidence = {}, []

    def visit(options, prefix="", inherited=frozenset()):
        for index, option in enumerate(options):
            option_id = f"{prefix}/{index}" if prefix else str(index)
            parent_paths = set(inherited) | _included_paths(option, patches)
            children = option.get("SubOptions") or []
            if len(children) > 1:
                record = {"option": option_id, "name": option.get("Name", "")}
                try:
                    if any(child.get("SubOptions") for child in children):
                        raise ValueError("nested branch choices need a separate effective-source analysis")
                    branch_paths = [parent_paths | _included_paths(child, patches) for child in children]
                    branches = [_branch(paths, sources) for paths in branch_paths]
                    canonical_ids = frozenset(
                        (archive.UNIT, int(piece["resources"]["unit"], 16))
                        for kit in kits for body in kit.get("bodies", [])
                        for piece in body.get("pieces", []) if piece.get("slot") != 1)
                    discovered, rows = _unit_aliases(branches, canonical_ids)
                except ValueError as error:
                    record.update(status="skipped", reason=str(error))
                else:
                    if set(discovered) & set(aliases):
                        raise ValueError("Unit belongs to more than one alias group")
                    aliases.update(discovered)
                    evidence.extend({**row, "option": option_id} for row in rows)
                    record.update(status="aliased" if discovered else "unchanged",
                                  aliases=[{"type": f"{kind:016x}", "source": f"{value:016x}",
                                            "canonical": f"{target[1]:016x}"}
                                           for (kind, value), target in sorted(discovered.items())])
                evidence.append(record)
            visit(children, option_id, parent_paths)

    visit(manifest_options(catalog.manifest))
    return aliases, evidence
