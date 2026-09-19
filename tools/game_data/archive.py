"""Read the needed Lua resource from legacy or Slim game data; write one override."""

import bisect
from pathlib import Path
import struct

from lz4.block import decompress

ARCHIVE = "9ba626afa44a3aa3"
CALLBACK = 0x7251FDD9BB62480A
LUA_TYPE = 0xA14E8DFA2CD117E2
MAGIC = 0xF0000011


class GameData:
    def __init__(self, root: Path):
        self.root = root
        self.tables = {}
        self.mapping = None

    def dsar(self, name, offset=0, whole=False):
        path = self.root / name
        with path.open("rb") as stream:
            if name not in self.tables:
                header = stream.read(32)
                if header[:4] != b"DSAR":
                    raise ValueError(f"Not DSAR: {name}")
                count = struct.unpack_from("<I", header, 8)[0]
                if not 0 < count < 2_000_000:
                    raise ValueError("Invalid DSAR table size")
                self.tables[name] = list(struct.iter_unpack("<QQIIBB6x", stream.read(count * 32)))
            table = self.tables[name]
            index = bisect.bisect_left([entry[0] for entry in table], offset)
            if index == len(table) or table[index][0] != offset:
                raise ValueError(f"Resource is not at a DSAR boundary: {name} {offset:#x}")
            blocks = []
            for entry in table[index:]:
                logical, physical, raw_size, size, compression, flags = entry
                if blocks and flags & 2 and not whole:
                    break
                stream.seek(physical)
                data = stream.read(size)
                if len(data) != size:
                    raise ValueError("Truncated DSAR block")
                if compression == 3:
                    data = decompress(data, uncompressed_size=raw_size)
                elif compression != 0:
                    raise ValueError(f"Unsupported DSAR compression: {compression}")
                if len(data) != raw_size:
                    raise ValueError("DSAR length mismatch")
                blocks.append(data)
            return b"".join(blocks)

    def resource(self, offset, size=None):
        path = self.root / ARCHIVE
        if path.exists():
            with path.open("rb") as stream:
                magic = stream.read(4)
                if magic == struct.pack("<I", MAGIC):
                    if size is None:
                        stream.seek(4)
                        types, files = struct.unpack("<II", stream.read(8))
                        size = 72 + types * 32 + files * 80
                    stream.seek(offset)
                    result = stream.read(size)
                elif magic == b"DSAR":
                    result = self.dsar(ARCHIVE, offset)
                else:
                    raise ValueError("Unsupported game archive")
        else:
            if self.mapping is None:
                index = self.dsar("bundles.nxa", whole=True)
                count = struct.unpack_from("<I", index, 16)[0]
                for i in range(count):
                    _, name_at, entries, entries_at = struct.unpack_from("<QIII4x", index, 24 + i * 24)
                    end = index.index(b"\0", name_at)
                    if index[name_at:end].decode() == ARCHIVE:
                        self.mapping = list(struct.iter_unpack("<QI3xB", index[entries_at:entries_at + entries * 16]))
                        break
                if self.mapping is None:
                    raise ValueError("Startup archive missing from Slim mapping")
            item = bisect.bisect_right([entry[0] for entry in self.mapping], offset) - 1
            if item < 0:
                raise ValueError("Archive offset not mapped")
            original, logical, bundle = self.mapping[item]
            result = self.dsar(f"bundles.{bundle:02d}.nxa", logical + offset - original)
        if size is not None:
            if len(result) < size:
                raise ValueError("Truncated game resource")
            result = result[:size]
        return result

    def callbacks(self):
        table = self.resource(0)
        magic, types, files = struct.unpack_from("<III", table)
        if magic != MAGIC or 72 + types * 32 + files * 80 > len(table):
            raise ValueError("Invalid archive table")
        for i in range(files):
            entry = struct.unpack_from("<7Q6I", table, 72 + 32 * types + 80 * i)
            if entry[:2] == (CALLBACK, LUA_TYPE):
                return self.resource(entry[2], entry[7])
        raise ValueError("Wwise callback Lua resource not found")


def make_archive(bytecode):
    resource = struct.pack("<II", len(bytecode), 2) + bytecode
    end = (192 + len(resource) + 15) & ~15
    header = struct.pack("<III20sQQ24s", MAGIC, 1, 1, b"", end, 0, b"")
    types = struct.pack("<IIQIIII", 0, 0, LUA_TYPE, 1, 0, 16, 16)
    entry = struct.pack("<7Q6I", CALLBACK, LUA_TYPE, 192, 0, 0, 0, 0,
                        len(resource), 0, 0, 16, 16, 0)
    data = header + types + entry + bytes(8) + resource
    return data + bytes(end - len(data))


def unpack_archive(data):
    if struct.unpack_from("<III", data) != (MAGIC, 1, 1):
        raise ValueError("Expected a single-resource archive")
    entry = struct.unpack_from("<7Q6I", data, 104)
    if entry[:2] != (CALLBACK, LUA_TYPE) or entry[2] + entry[7] > len(data):
        raise ValueError("Invalid Lua resource entry")
    resource = data[entry[2]:entry[2] + entry[7]]
    length, version = struct.unpack_from("<II", resource)
    if version != 2 or length != len(resource) - 8:
        raise ValueError("Invalid Lua resource header")
    return resource[8:]
