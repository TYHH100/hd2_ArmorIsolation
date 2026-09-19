"""Read-only HD2 appearance inspection; never execute or alter game code."""

import argparse
import bisect
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

sys.dont_write_bytecode = True


def read_module(pid, name):
    kernel = c.WinDLL("kernel32", use_last_error=True)
    psapi = c.WinDLL("psapi", use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.ReadProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p,
                                        c.c_size_t, c.POINTER(c.c_size_t)]
    psapi.EnumProcessModulesEx.argtypes = [w.HANDLE, c.c_void_p, w.DWORD,
                                          c.POINTER(w.DWORD), w.DWORD]
    psapi.GetModuleBaseNameW.argtypes = [w.HANDLE, c.c_void_p, w.LPWSTR, w.DWORD]
    handle = kernel.OpenProcess(0x410, False, pid)
    if not handle:
        raise c.WinError(c.get_last_error())
    try:
        modules = (c.c_void_p * 2048)()
        needed = w.DWORD()
        if not psapi.EnumProcessModulesEx(handle, modules, c.sizeof(modules),
                                          c.byref(needed), 3):
            raise c.WinError(c.get_last_error())
        if needed.value > c.sizeof(modules):
            raise ValueError("Module list exceeded buffer")
        names = {}
        for base in modules[:needed.value // c.sizeof(c.c_void_p)]:
            text = c.create_unicode_buffer(512)
            if psapi.GetModuleBaseNameW(handle, base, text, len(text)):
                names[text.value.lower()] = base
        if "helldivers2.exe" not in names or name not in names:
            raise ValueError("Requested HD2 module was not found")
        base = names[name]

        def read(offset, size):
            buffer = c.create_string_buffer(size)
            count = c.c_size_t()
            if not kernel.ReadProcessMemory(handle, base + offset, buffer, size,
                                            c.byref(count)) or count.value != size:
                raise c.WinError(c.get_last_error())
            return buffer.raw

        header = read(0, 4096)
        pe = struct.unpack_from("<I", header, 0x3C)[0]
        if header[:2] != b"MZ" or header[pe:pe + 4] != b"PE\0\0":
            raise ValueError("Invalid PE header")
        size = struct.unpack_from("<I", header, pe + 24 + 56)[0]
        if not 0 < size <= 256 * 1024 * 1024:
            raise ValueError("Unexpected image size")
        return base, read(0, size)
    finally:
        kernel.CloseHandle(handle)


def inspect_runtime(args):
    import capstone as cs

    base, image = read_module(args.pid, args.module)
    pe = struct.unpack_from("<I", image, 0x3C)[0]
    stamp = struct.unpack_from("<I", image, pe + 8)[0]
    rva, size = struct.unpack_from("<II", image, pe + 24 + 112 + 8 * 3)
    if rva + size > len(image) or size % 12:
        raise ValueError("Invalid exception table")
    ranges = sorted((s, e) for s, e, _ in struct.iter_unpack(
        "<III", image[rva:rva + size]) if 0 < s < e <= len(image))
    starts = [item[0] for item in ranges]

    def containing(address):
        i = bisect.bisect_right(starts, address) - 1
        return ranges[i] if i >= 0 and address < ranges[i][1] else None

    print(json.dumps({"module": args.module, "pid": args.pid, "base": hex(base),
                      "timestamp": hex(stamp), "image_size": hex(len(image)),
                      "function_entries": len(ranges)}))
    if args.strings:
        pattern = re.compile(args.strings, re.I)
        for match in re.finditer(rb"[ -~]{4,}", image):
            text = match.group().decode("ascii")
            if pattern.search(text):
                print(f"STRING {match.start():#x} {text[:600]}")

    disasm = cs.Cs(cs.CS_ARCH_X86, cs.CS_MODE_64)
    if args.calls_to:
        targets = set(args.calls_to)
        for match in re.finditer(rb"\xe8", image):
            offset = match.start()
            if offset + 5 > len(image) or containing(offset) is None:
                continue
            target = offset + 5 + struct.unpack_from("<i", image, offset + 1)[0]
            if target in targets:
                print("CALL_CANDIDATE", hex(offset), "->", hex(target),
                      "unwind_range", containing(offset))
    if args.xref:
        targets = set(args.xref)
        # Byte-pattern candidates are instruction-validated before reporting.
        for match in re.finditer(rb"[\x40-\x4f][\x8d\x8b][\x05\x0d\x15\x1d\x25\x2d\x35\x3d]", image):
            offset = match.start()
            if offset + 7 > len(image):
                continue
            target = offset + 7 + struct.unpack_from("<i", image, offset + 3)[0]
            if target in targets:
                ins = next(disasm.disasm(image[offset:offset + 7], offset), None)
                if ins and ins.size == 7:
                    print("XREF_CANDIDATE", hex(offset), "->", hex(target),
                          "function", containing(offset), ins.mnemonic, ins.op_str)
        for target in targets:
            needle = struct.pack("<Q", base + target)
            for match in re.finditer(re.escape(needle), image):
                print("POINTER", hex(match.start()), "->", hex(target))

    spans = []
    for address in args.function:
        span = containing(address)
        if span is None:
            print("NO_FUNCTION_BOUNDARY", hex(address))
            continue
        spans.append(span)
    for value in args.range:
        start, length = [int(x, 0) for x in value.split(":")]
        if start < 0 or length <= 0 or start + length > len(image):
            raise ValueError("Disassembly range outside image")
        spans.append((start, start + length))
    for start, end in spans:
        print(f"CODE_RANGE {start:#x}..{end:#x}")
        for ins in disasm.disasm(image[start:end], start):
            annotation = ""
            match = re.search(r"\[rip ([+-]) (0x[0-9a-f]+)\]", ins.op_str)
            if match:
                delta = int(match[2], 16) * (1 if match[1] == "+" else -1)
                target = ins.address + ins.size + delta
                if 0 <= target < len(image):
                    annotation = f" ; RVA {target:#x}"
                    raw = image[target:target + 160].split(b"\0", 1)[0]
                    if len(raw) >= 4 and all(32 <= b < 127 for b in raw):
                        annotation += " " + repr(raw.decode("ascii"))
            print(f"{ins.address:08x} {ins.bytes.hex():24s} {ins.mnemonic} {ins.op_str}{annotation}")
    for address in args.bytes:
        if not 0 <= address < len(image):
            raise ValueError("Requested byte RVA is outside image")
        print(f"BYTES {address:#x} {image[address:address + 256].hex(' ')}")


def inspect_asset(args):
    sys.path.insert(0, str(args.reader_tools))
    sys.path.insert(0, str(args.unit_tools))
    from archive import GameData
    import unit_census as unit

    game = GameData(args.game / "data")
    index = game.dsar("bundles.nxa", whole=True)
    count = struct.unpack_from("<I", index, 16)[0]
    mappings = {}
    for i in range(count):
        _, name_at, entries, entries_at = struct.unpack_from("<QIII4x", index, 24 + i * 24)
        end = index.index(b"\0", name_at)
        name = index[name_at:end].decode()
        mappings[name] = list(struct.iter_unpack(
            "<QI3xB", index[entries_at:entries_at + entries * 16]))

    def resource(name, offset, length=None):
        entries = mappings[name]
        i = bisect.bisect_right([e[0] for e in entries], offset) - 1
        if i < 0:
            raise ValueError("Unmapped resource offset")
        original, logical, bundle = entries[i]
        data = game.dsar(f"bundles.{bundle:02d}.nxa", logical + offset - original)
        if length is not None and len(data) < length:
            raise ValueError("Truncated resource")
        return data if length is None else data[:length]

    toc = resource(args.archive, 0)
    entries = unit.bundle_entries(toc)
    names = unit.load_names()
    records = []
    for entry in entries:
        if entry["type_id"] != unit.UNIT_TYPE or entry["file_id"] not in args.unit:
            continue
        blob = resource(args.archive, entry["data_off"], entry["data_sz"])
        hdr = unit.unit_hdr(blob)
        sg = unit.parse_sg(blob, hdr["TransformInfoOffset"])
        bones = unit.parse_boneinfo(blob, hdr["BoneInfoOffset"])
        streams = unit.parse_streaminfo(blob, hdr["StreamInfoOffset"])
        meshes = unit.parse_meshinfo(blob, hdr["MeshInfoOffset"])
        if not all(all(i < sg["n"] for i in b["real"]) for b in bones):
            raise ValueError("Bone scene-node index out of bounds")
        if not all(all(all(i < b["num_bones"] for i in remap)
                       for remap in b["remaps"]) for b in bones):
            raise ValueError("Bone remap index out of bounds")
        records.append({"unit": f'{entry["file_id"]:016x}', "archive": args.archive,
                        "main_size": len(blob), "main_sha256": hashlib.sha256(blob).hexdigest(),
                        "gpu_size": entry["gpu_sz"], "header": hdr,
                        "nodes": [{"index": i, "hash": f'{h:08x}',
                                   "name": names.get(h), "parent_record": sg["parents"][i]}
                                  for i, h in enumerate(sg["hashes"])],
                        "bone_lods": bones, "streams": streams, "meshes": meshes})
    if len(records) != len(set(args.unit)):
        raise ValueError("Requested Unit was not found")
    result = json.dumps(records, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result + "\n", encoding="utf-8")
    else:
        print(result)
    for r in records:
        print("ASSET", r["unit"], "nodes", len(r["nodes"]), "bone_lods", len(r["bone_lods"]),
              "streams", len(r["streams"]), "meshes", len(r["meshes"]), "gpu_bytes", r["gpu_size"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    runtime = modes.add_parser("runtime")
    runtime.add_argument("--pid", required=True, type=int)
    runtime.add_argument("--module", choices=["game.dll", "helldivers2.exe"], default="game.dll")
    runtime.add_argument("--strings")
    for flag in ["xref", "function", "bytes"]:
        runtime.add_argument("--" + flag, type=lambda x: int(x, 0), action="append", default=[])
    runtime.add_argument("--calls-to", type=lambda x: int(x, 0), action="append", default=[])
    runtime.add_argument("--range", action="append", default=[])
    asset = modes.add_parser("asset")
    asset.add_argument("--game", required=True, type=Path)
    asset.add_argument("--reader-tools", required=True, type=Path)
    asset.add_argument("--unit-tools", required=True, type=Path)
    asset.add_argument("--archive", required=True)
    asset.add_argument("--unit", required=True, action="append", type=lambda x: int(x, 16))
    asset.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "runtime":
        inspect_runtime(args)
    else:
        inspect_asset(args)


if __name__ == "__main__":
    main()
