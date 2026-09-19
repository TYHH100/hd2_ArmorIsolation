"""Match texture alternatives only inside structurally equivalent exclusive choices."""

import hashlib
from pathlib import Path, PureWindowsPath
import struct

import build_cm14_isolated as archive
from modular_source import manifest_options


def _payload(source, key):
    entry = source.entries[key]
    start, size = entry.offsets[0], entry.sizes[0]
    result = source.data[start:start + size]
    if len(result) != size:
        raise ValueError("Truncated material payload during alias analysis")
    return result


def _material_shape(payload):
    fields = [offset for kind, offset in archive.reference_fields(archive.MATERIAL, payload)
              if kind == archive.TEXTURE]
    slots = [struct.unpack_from("<I", payload, 0x88 + index * 4)[0] for index in range(len(fields))]
    if len(slots) != len(set(slots)):
        raise ValueError("duplicate texture slot hashes")
    normalized = bytearray(payload)
    references = {}
    for slot, offset in zip(slots, fields):
        references[slot] = struct.unpack_from("<Q", payload, offset)[0]
        normalized[offset:offset + 8] = b"\0" * 8
    return bytes(normalized), references


def _included_paths(option, patches):
    includes = {Path(*PureWindowsPath(value).parts) for value in option.get("Include", [])}
    return {path for path in patches if path.parent in includes}


def _branch(paths, sources):
    resources = {}
    for path in sorted(paths):
        source = sources[path]
        for key in source.entries:
            if key[0] not in (archive.MATERIAL, archive.TEXTURE):
                raise ValueError("branch contains resources other than Material/Texture")
            if key in resources:
                raise ValueError("branch has ambiguous duplicate resource providers")
            resources[key] = source
    if not resources:
        raise ValueError("branch contains no resources")
    return resources


def _group_aliases(branches):
    materials = [{key for key in branch if key[0] == archive.MATERIAL} for branch in branches]
    if not materials[0] or any(keys != materials[0] for keys in materials[1:]):
        raise ValueError("branches have different or empty Material key sets")
    parents = {}

    def find(value):
        parents.setdefault(value, value)
        if parents[value] != value:
            parents[value] = find(parents[value])
        return parents[value]

    def unite(values):
        roots = {find(value) for value in values}
        canonical = min(roots)
        for value in roots:
            parents[value] = canonical

    material_evidence = []
    for key in sorted(materials[0]):
        shapes = [_material_shape(_payload(branch[key], key)) for branch in branches]
        if any(shape[0] != shapes[0][0] for shape in shapes[1:]):
            raise ValueError("Material bytes differ outside Texture64 references")
        slots = []
        for slot in shapes[0][1]:
            values = [shape[1][slot] for shape in shapes]
            local = [(archive.TEXTURE, value) in branch for value, branch in zip(values, branches)]
            if all(local):
                unite(values)
            elif any(local) or len(set(values)) != 1:
                raise ValueError("texture slot mixes missing or external branch resources")
            slots.append({"slot": f"{slot:08x}", "textures": [f"{value:016x}" for value in values],
                          "local": all(local)})
        material_evidence.append({"material": f"{key[1]:016x}",
                                  "normalized_sha256": hashlib.sha256(shapes[0][0]).hexdigest(),
                                  "slots": slots})
    groups = {}
    for value in parents:
        groups.setdefault(find(value), set()).add(value)
    groups = {canonical: values for canonical, values in groups.items() if len(values) > 1}
    for values in groups.values():
        for branch in branches:
            if sum((archive.TEXTURE, value) in branch for value in values) != 1:
                raise ValueError("texture aliases would collide within one branch")
    aliases = {(archive.TEXTURE, value): (archive.TEXTURE, canonical)
               for canonical, values in groups.items() for value in sorted(values) if value != canonical}
    return aliases, groups, material_evidence


def _check_exclusive_ownership(groups, paths, sources, kits):
    members = {value for values in groups.values() for value in values}
    if not members:
        return
    for path, source in sources.items():
        if path in paths:
            continue
        for key in source.entries:
            if key[0] == archive.TEXTURE and key[1] in members:
                raise ValueError(f"Texture alias resource also exists outside its exclusive group: {path}")
            if key[0] == archive.MATERIAL:
                payload = _payload(source, key)
                for kind, offset in archive.reference_fields(archive.MATERIAL, payload):
                    if kind == archive.TEXTURE and struct.unpack_from("<Q", payload, offset)[0] in members:
                        raise ValueError(f"Material outside an exclusive group references its texture alias: {path}")
    for kit in kits:
        for body in kit["bodies"]:
            for piece in body["pieces"]:
                if piece["slot"] == 1:
                    continue
                if any(int(value, 16) in members for field, value in piece["resources"].items() if field != "unit"):
                    raise ValueError(f"Kit {kit['id']} directly references an exclusive texture alias")


def discover_texture_aliases(catalog, sources, kits=()):
    """Return typed nonidentity aliases plus evidence, without changing any source payload."""
    patches = tuple(Path(path) for path in catalog.patch_paths)
    sources = {Path(path): source for path, source in sources.items()}
    if set(patches) != set(sources):
        raise ValueError("Texture alias analysis requires the complete catalog source set")
    kits = tuple(kits)
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
                    discovered, groups, materials = _group_aliases(branches)
                except ValueError as error:
                    record.update(status="skipped", reason=str(error))
                else:
                    all_paths = set().union(*branch_paths)
                    _check_exclusive_ownership(groups, all_paths, sources, kits)
                    if set(discovered) & set(aliases):
                        raise ValueError("Texture belongs to more than one alias group")
                    aliases.update(discovered)
                    record.update(status="aliased" if discovered else "unchanged", materials=materials,
                                  branches=[{"option": f"{option_id}/{i}",
                                             "patches": [path.as_posix() for path in sorted(paths)]}
                                            for i, paths in enumerate(branch_paths)],
                                  aliases=[{"type": f"{kind:016x}", "source": f"{value:016x}",
                                            "canonical": f"{target[1]:016x}"}
                                           for (kind, value), target in sorted(discovered.items())])
                evidence.append(record)
            visit(children, option_id, parent_paths)

    visit(manifest_options(catalog.manifest))
    return aliases, evidence
