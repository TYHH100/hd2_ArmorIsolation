"""Append a bounded runtime profile outside the archive's resource ranges."""

import json
from pathlib import Path
import struct
import zlib

MAGIC = b"HD2ARMORPROFILE\0"
VERSION = 1
FOOTER = struct.Struct("<16sIIQQI20s")
MAX_BYTES = 8 * 1024 * 1024
TRANSPORT = "hd2-armor-patch-footer/1"


def read_payload(path):
    with Path(path).open("rb") as stream:
        stream.seek(0, 2)
        length = stream.tell()
        if length < FOOTER.size:
            return None
        stream.seek(-FOOTER.size, 2)
        magic, version, footer_size, offset, size, checksum, reserved = FOOTER.unpack(stream.read(FOOTER.size))
        if magic != MAGIC:
            return None
        if (version != VERSION or footer_size != FOOTER.size or reserved != bytes(20)
                or not 0 < size <= MAX_BYTES or offset < 72
                or offset + size + FOOTER.size != length):
            raise ValueError(f"Invalid embedded profile footer: {path}")
        stream.seek(offset)
        payload = stream.read(size)
        if zlib.crc32(payload) != checksum:
            raise ValueError(f"Embedded profile checksum mismatch: {path}")
        return payload


def append_profile(path, profile):
    path = Path(path)
    if read_payload(path) is not None:
        raise ValueError(f"Patch already contains an embedded profile: {path}")
    payload = (json.dumps(profile, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                          allow_nan=False) + "\n").encode("utf-8")
    if not 0 < len(payload) <= MAX_BYTES:
        raise ValueError("Embedded profile exceeds the 8 MiB size limit")
    with path.open("r+b") as stream:
        if stream.read(4) != struct.pack("<I", 0xF0000011):
            raise ValueError(f"Not an uncompressed game patch: {path}")
        stream.seek(0, 2)
        offset = stream.tell()
        if offset < 72:
            raise ValueError(f"Truncated game patch: {path}")
        stream.write(payload)
        stream.write(FOOTER.pack(MAGIC, VERSION, FOOTER.size, offset, len(payload),
                                 zlib.crc32(payload), bytes(20)))
    if read_payload(path) != payload:
        raise ValueError(f"Embedded profile did not round-trip: {path}")
    return {"path": path.name, "archive_bytes": offset, "profile_bytes": len(payload)}
