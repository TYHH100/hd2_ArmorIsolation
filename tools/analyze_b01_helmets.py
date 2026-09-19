"""Read B-01 helmet topology and compare LOD references against vanilla."""

import hashlib
import json
from pathlib import Path
import struct

import build_cm14_isolated as resource


def u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def parse_unit(data):
    meshes, lods = [], []
    joint_at = u32(data, 0x34)
    joint_count = u32(data, joint_at)
    joint_names = struct.unpack_from(f"<{joint_count}I", data, joint_at + 16 + joint_count * 132)
    mesh_at = u32(data, 0x64)
    skeleton_at = u32(data, 0x58)
    material_at = u32(data, 0x70)
    material_count = u32(data, material_at)
    for index in range(u32(data, mesh_at)):
        at = mesh_at + u32(data, mesh_at + 4 + index * 4)
        nmat, matoff = struct.unpack_from("<II", data, at + 0x68)
        ngroup, groupoff = struct.unpack_from("<II", data, at + 0x78)
        skeleton, layout = struct.unpack_from("<ii", data, at + 0x38)
        mesh = {
            "index": index, "offset": at, "mesh_id": f"{u32(data, at + 0x28):08x}",
            "type": u32(data, at + 0x24), "transform": u32(data, at + 0x30),
            "skeleton_map": skeleton, "layout": layout,
            "material_slots": [f"{u32(data, at + matoff + j * 4):08x}" for j in range(nmat)],
            "groups": [list(struct.unpack_from("<6I", data, at + groupoff + j * 24)) for j in range(ngroup)],
        }
        if skeleton >= 0:
            skel = skeleton_at + u32(data, skeleton_at + 4 + skeleton * 4)
            count, matrices, indices, remaps = struct.unpack_from("<4I", data, skel)
            remap_offset, remap_count = struct.unpack_from("<II", data, skel + remaps + 4)
            remap_zero = u32(data, skel + remaps + remap_offset)
            bone_index = u32(data, skel + indices + remap_zero * 4)
            mesh["skin_vertex_index_zero"] = {
                "remap": remap_zero, "joint_index": bone_index,
                "joint_name_hash": f"{joint_names[bone_index]:08x}",
                "matrix_sha256": digest(data[skel + matrices + remap_zero * 64:skel + matrices + (remap_zero + 1) * 64]),
            }
        meshes.append(mesh)
    lod_at = u32(data, 0x30)
    for group in range(u32(data, lod_at)):
        at = lod_at + u32(data, lod_at + 4 + group * 4)
        for entry in range(u32(data, at + 16)):
            entry_at = at + u32(data, at + 20 + entry * 4)
            for index in range(u32(data, entry_at + 8)):
                field_at = entry_at + 12 + index * 4
                value = u32(data, field_at)
                lods.append({"group": group, "entry": entry, "offset": field_at, "value": value,
                             "mesh_id_if_array_index": meshes[value]["mesh_id"],
                             "mesh_type_if_array_index": meshes[value]["type"]})
    return {
        "main_size": len(data), "main_sha256": digest(data),
        "bones_resource": f"{struct.unpack_from('<Q', data, 8)[0]:016x}",
        "geometry_group": f"{struct.unpack_from('<Q', data, 16)[0]:016x}",
        "state_machine": f"{struct.unpack_from('<Q', data, 32)[0]:016x}",
        "joint_count": joint_count, "joints_sha256": digest(data[joint_at:joint_at + 16 + joint_count * 136]),
        "materials": [{"slot": f"{u32(data, material_at + 4 + i * 4):08x}",
                       "resource": f"{struct.unpack_from('<Q', data, material_at + 4 + material_count * 4 + i * 8)[0]:016x}"}
                      for i in range(material_count)],
        "mesh_count": len(meshes), "meshes": meshes, "lod_references": lods,
    }


def main():
    root = Path(__file__).resolve().parents[1]
    prior = json.loads((root / "docs/b01-source-analysis.json").read_text(encoding="utf-8"))
    source_path = Path(prior["source"])
    source = source_path.read_bytes()
    entries = {entry.key: entry for entry in resource.parse_toc(source)[2]}
    reader = resource.VanillaReader(Path(r"G:\AppData\SteamLibrary\steamapps\common\Helldivers 2"),
                                    Path(r"G:\Temp\Githud\hd2-lua_mods_test\tools"))
    kits = json.loads((root / "docs/armor-isolation-live-kits.json").read_text(encoding="utf-8"))
    rows = []
    for target in prior["targets"]:
        if target["type"] != 1:
            continue
        unit_id = int(next(row["id"] for row in target["private_closure"] if row["kind"] == "unit"), 16)
        entry = entries[resource.UNIT, unit_id]
        vanilla_entry = reader.entries(target["archive"])[resource.UNIT, unit_id]
        source_info = parse_unit(source[entry.offsets[0]:entry.offsets[0] + entry.sizes[0]])
        vanilla_info = parse_unit(reader.read(target["archive"], vanilla_entry.offsets[0], vanilla_entry.sizes[0]))
        source_mesh_by_id = {mesh["mesh_id"]: mesh for mesh in source_info["meshes"]}
        corrections = []
        for actual, stock in zip(source_info["lod_references"], vanilla_info["lod_references"]):
            expected = source_mesh_by_id[stock["mesh_id_if_array_index"]]
            if actual["value"] != expected["index"]:
                corrections.append({"offset": actual["offset"], "offset_hex": f"0x{actual['offset']:x}",
                                    "before": actual["value"], "after": expected["index"],
                                    "expected_mesh_id": expected["mesh_id"],
                                    "current_mesh_id": actual["mesh_id_if_array_index"]})
        rows.append({"kit": target["kit"], "archive": target["archive"], "unit": f"{unit_id:016x}",
                     "source_sizes": list(entry.sizes), "vanilla_sizes": list(vanilla_entry.sizes),
                     "source": source_info, "vanilla": vanilla_info,
                     "joints_identical": source_info["joints_sha256"] == vanilla_info["joints_sha256"],
                     "piece": next(kit for kit in kits if kit["id"] == target["kit"])["bodies"][0]["pieces"][0],
                     "candidate_corrections": corrections})
    output = root / "docs/b01-helmet-lod-evidence.json"
    output.write_text(json.dumps({
        "source": str(source_path), "source_main_sha256": digest(source),
        "method": "Match vanilla selected MeshInfo GroupBoneHash/MeshID to unique source MeshInfo index",
        "native_lod_execution_verified": False, "game_visual_fix_verified": False,
        "caution": "Candidate repair, not a proven native LOD execution trace. Do not rename Bones or replace alternate helmets with first helmet.",
        "helmets": rows,
    }, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(output), "helmets": len(rows),
                      "candidate_fields": sum(len(row["candidate_corrections"]) for row in rows)}, indent=2))


if __name__ == "__main__":
    main()
