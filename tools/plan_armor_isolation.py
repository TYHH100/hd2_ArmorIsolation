"""Read current HD2 kit records and plan namespaced resource IDs without applying them."""

import argparse
from collections import defaultdict
import ctypes as c
import hashlib
import json
from pathlib import Path
import struct
import sys

sys.dont_write_bytecode = True
from inspect_appearance import read_module


EXPECTED_DLL_SHA256 = "cc75948d90fdfde259dcb519e9933db7ffa3ccb281ce4fb89e6b1b011557470c"
RESOURCE_FIELDS = ["unit", "material_lut", "pattern_lut", "cape_lut",
                   "cape_gradient", "cape_nac", "decal_scalar_fields", "base_data", "decal_sheet"]


class Reader:
    def __init__(self, pid):
        self.api = c.WinDLL("kernel32", use_last_error=True)
        self.api.OpenProcess.argtypes = [c.c_ulong, c.c_int, c.c_ulong]
        self.api.OpenProcess.restype = c.c_void_p
        self.api.ReadProcessMemory.argtypes = [c.c_void_p, c.c_void_p, c.c_void_p,
                                               c.c_size_t, c.POINTER(c.c_size_t)]
        self.api.CloseHandle.argtypes = [c.c_void_p]
        self.handle = self.api.OpenProcess(0x10, False, pid)
        if not self.handle:
            raise c.WinError(c.get_last_error())

    def read(self, address, length):
        if not 0x10000 < address < 0x800000000000 or not 0 < length <= 1048576:
            raise ValueError("Read outside bounded address/length limits")
        data = c.create_string_buffer(length)
        done = c.c_size_t()
        if not self.api.ReadProcessMemory(self.handle, address, data, length, c.byref(done)):
            raise c.WinError(c.get_last_error())
        if done.value != length:
            raise ValueError("Partial process read")
        return data.raw

    def close(self):
        self.api.CloseHandle(self.handle)


def read_kits(pid, game):
    dll = game / "data" / "game" / "game.dll"
    with dll.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    if sha != EXPECTED_DLL_SHA256:
        raise ValueError("Unverified DLL version; offsets must be revalidated")
    base, image = read_module(pid, "game.dll")
    pe = struct.unpack_from("<I", image, 0x3c)[0]
    if struct.unpack_from("<I", image, pe + 8)[0] != 0x6a86132e or len(image) != 0x3a6b000:
        raise ValueError("Loaded DLL version mismatch")
    reader = Reader(pid)
    try:
        store = struct.unpack_from("<Q", image, 0x276c220)[0]
        header = reader.read(store, 16)
        pointer, count = struct.unpack_from("<QI", header)
        if not 0 < count < 4096:
            raise ValueError("Invalid kit count")
        pointers = struct.unpack(f"<{count}Q", reader.read(pointer, count * 8))
        kits = []
        for address in pointers:
            k = struct.unpack("<8IQIIQI4x", reader.read(address, 64))
            if not 0 < k[12] <= 16:
                raise ValueError("Unexpected body count")
            kit = {"id": f"{k[0]:08x}", "archive": f"{k[8]:016x}",
                   "type": k[9], "passive": k[7], "bodies": []}
            bodies = reader.read(k[11], k[12] * 24)
            for j in range(k[12]):
                body_type, _, pieces, piece_count = struct.unpack_from("<IIQI4x", bodies, j * 24)
                if not 0 <= piece_count <= 128:
                    raise ValueError("Unexpected piece count")
                body = {"type": body_type, "pieces": []}
                data = reader.read(pieces, piece_count * 96) if piece_count else b""
                for n in range(piece_count):
                    p = struct.unpack_from("<QIIII8QB7x", data, n * 96)
                    resources = dict(zip(RESOURCE_FIELDS, [f"{v:016x}" for v in [p[0], *p[5:13]]]))
                    body["pieces"].append({"slot": p[1], "type": p[2], "weight": p[3],
                                           "tone_variations": p[13], "resources": resources})
                kit["bodies"].append(body)
            kits.append(kit)
        if reader.read(store, 16) != header:
            raise ValueError("Kit table changed during inspection")
        return kits, {"pid": pid, "module_base": hex(base), "dll_sha256": sha,
                      "pe_timestamp": "0x6a86132e", "size_of_image": "0x3a6b000"}
    finally:
        reader.close()


def owners_for(kits):
    owners = defaultdict(set)
    for kit in kits:
        for body in kit["bodies"]:
            for piece in body["pieces"]:
                for field, value in piece["resources"].items():
                    if value != "0000000000000000":
                        owners[("unit" if field == "unit" else "texture", value)].add(kit["id"])
    return owners


def statistics(kits):
    owners = owners_for(kits)
    counts = {}
    for kind in ["unit", "texture"]:
        entries = [v for (t, _), v in owners.items() if t == kind]
        affected = set().union(*(v for v in entries if len(v) > 1)) if entries else set()
        counts[kind] = {"unique_direct_ids": len(entries),
                        "shared_ids": sum(len(v) > 1 for v in entries),
                        "affected_kits": len(affected),
                        "private_ids_for_all_kit_resource_pairs": sum(map(len, entries)),
                        "extra_ids_vs_unique": sum(len(v) - 1 for v in entries)}
    return {"kit_count": len(kits), "distinct_archives": len({k["archive"] for k in kits}),
            "direct_resources": counts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--hash-tools", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.hash_tools))
    from hashes import murmur64a

    kits, version = read_kits(args.pid, args.game)
    if len({k["id"] for k in kits}) != len(kits):
        raise ValueError("Duplicate kit IDs require an expanded ownership key")
    existing = owners_for(kits)
    existing_names = {int(resource, 16) for _, resource in existing}
    reserved = set(existing_names)
    reserved_thin = {v >> 32 for v in existing_names}
    mapping = []
    keys = set()
    for kit in sorted(kits, key=lambda k: k["id"]):
        for kind, source in sorted(owners_for([kit])):
            path = f"mods/hd2_armor_isolation/v1/kit_{kit['id']}/{kind}/{source}"
            salt = 0
            while True:
                candidate_path = path if salt == 0 else f"{path}_{salt}"
                target = murmur64a(candidate_path.encode("ascii"), 0)
                if target and target not in reserved and target >> 32 not in reserved_thin:
                    break
                salt += 1
            reserved.add(target)
            reserved_thin.add(target >> 32)
            keys.add((kit["id"], kind, source))
            mapping.append({"kit": kit["id"], "archive": kit["archive"], "kind": kind,
                            "source": source, "candidate": f"{target:016x}",
                            "namespace": candidate_path})
    target_owners = defaultdict(set)
    for m in mapping:
        target_owners[(m["kind"], m["candidate"])].add(m["kit"])
    shared_after = sum(len(v) > 1 for v in target_owners.values())
    expected = sum(len(v) for v in existing.values())
    if len(mapping) != expected or len(keys) != expected or shared_after:
        raise ValueError("Dry-run mapping coverage/independence check failed")
    remap = {(m["kit"], m["kind"], m["source"]): m["candidate"] for m in mapping}
    planned = json.loads(json.dumps(kits))
    changed_references = 0
    for kit in planned:
        for body in kit["bodies"]:
            for piece in body["pieces"]:
                for field, source in piece["resources"].items():
                    if source == "0000000000000000":
                        continue
                    kind = "unit" if field == "unit" else "texture"
                    piece["resources"][field] = remap[(kit["id"], kind, source)]
                    changed_references += 1
    if any(len(v) > 1 for v in owners_for(planned).values()):
        raise ValueError("Rewritten direct reference graph still shares resources")
    body_without_cape = [
        {**kit, "bodies": [{**b, "pieces": [p for p in b["pieces"] if p["slot"] != 1]}
                           for b in kit["bodies"]]}
        for kit in kits if kit["type"] == 0]
    summary = {"version": version, "scope": "Direct Kit/Piece references only; no changes applied",
               "all_equipment": statistics(kits),
               "body_armor": statistics([k for k in kits if k["type"] == 0]),
               "body_armor_excluding_cape_slot": statistics(body_without_cape),
               "helmets": statistics([k for k in kits if k["type"] == 1]),
               "capes": statistics([k for k in kits if k["type"] == 2]),
               "dry_run": {"mapping_rows": len(mapping), "shared_direct_ids_after": shared_after,
                           "direct_reference_fields_rewritten_in_local_memory": changed_references,
                           "same_source_repeated_within_one_kit_reuses_one_private_id": True,
                           "collision_scope": "Current direct kit resources and generated candidates, including high32; NOT whole game",
                           "nested_unit_material_texture_dependencies": "Not included",
                           "engine_load_test": "Not performed"},
               "most_shared_units": [{"unit": res, "kit_count": len(owners), "kits": sorted(owners)}
                                     for (kind, res), owners in sorted(existing.items(), key=lambda x: -len(x[1]))
                                     if kind == "unit" and len(owners) > 1][:12]}
    args.output.mkdir(parents=True, exist_ok=True)
    for name, data in [("armor-isolation-live-kits.json", kits),
                       ("armor-isolation-id-plan.json", mapping),
                       ("armor-isolation-summary.json", summary)]:
        (args.output / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
