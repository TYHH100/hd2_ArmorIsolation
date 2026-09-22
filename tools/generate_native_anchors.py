"""Maintainer-only: capture relocation-normalized anchors from the verified build."""
import argparse
import hashlib
from pathlib import Path
import struct
import capstone as cs
from inspect_appearance import read_module

ROOT = Path(__file__).resolve().parents[1]
SPANS = {
    "game.dll": [("armor_assembly", 0x8164B0, 0x817323)],
    "helldivers2.exe": [("material_texture", 0x30E350, 0x30E44E),
                        ("resource_lookup", 0x5F0040, 0x5F02B7),
                        ("resource_redirect", 0x5F0C30, 0x5F0E07),
                        ("resource_online", 0x5F0FC0, 0x5F10D6),
                        ("type_find", 0x5FC030, 0x5FC098)]}

# Manually reviewed on 2026-09-22, including every chained unwind fragment.
# This is a closed fixture, not automatic anchor learning from an unknown build.
REVIEWED_DLL = "73374bd4e38386beb9a23bef480082b67d457ebc77485fbec5f488b4e95e201f"
REVIEWED_CODE = "809ad3d4b02ff628528e1bddc1b43dada0d6418791dc58f041d22e82fdd45f6c"


def normalized_mask(data, start):
    disassembler = cs.Cs(cs.CS_ARCH_X86, cs.CS_MODE_64)
    disassembler.detail = True
    instructions = list(disassembler.disasm(data, start))
    if sum(i.size for i in instructions) != len(data):
        raise ValueError("incomplete function decoding")
    mask = bytearray([255] * len(data))
    for instruction in instructions:
        position = instruction.address - start
        if instruction.bytes[0] in (0xe8, 0xe9):
            if not start <= instruction.operands[0].imm < start + len(data):
                offset = position + instruction.imm_offset
                mask[offset:offset + instruction.imm_size] = bytes(instruction.imm_size)
        for operand in instruction.operands:
            if operand.type == cs.x86.X86_OP_MEM and operand.mem.base == cs.x86.X86_REG_RIP:
                offset = position + instruction.disp_offset
                mask[offset:offset + instruction.disp_size] = bytes(instruction.disp_size)
    return mask


def generate_reviewed_assembly(pid, game):
    dll = game / "data/game/game.dll"
    if hashlib.sha256(dll.read_bytes()).hexdigest() != REVIEWED_DLL:
        raise ValueError("reviewed assembly requires the exact 1.0.0.19099 DLL")
    base, image = read_module(pid, "game.dll")
    pe = struct.unpack_from("<I", image, 0x3c)[0]
    if struct.unpack_from("<I", image, pe + 8)[0] != 0x6aa96b14 or len(image) != 0x4770000:
        raise ValueError("loaded game identity differs from the reviewed build")
    start, end = 0x81f470, 0x8202c3
    data = image[start:end]
    if hashlib.sha256(data).hexdigest() != REVIEWED_CODE:
        raise ValueError("loaded assembly differs from the manually reviewed code")
    second_base, second = read_module(pid, "game.dll")
    if base != second_base or data != second[start:end] or hashlib.sha256(dll.read_bytes()).hexdigest() != REVIEWED_DLL:
        raise ValueError("game changed during capture")
    mask = normalized_mask(data, start)
    lines = ["#pragma once", '#include "armor_native_anchors.hpp"', "",
             "// Reviewed 1.0.0.19099 assembly. See docs/native-19099-validation.md.",
             "// SHA records the fixture source; compatibility checks reviewed instruction families.",
             "namespace armor_native {",
             f'inline constexpr char reviewed_assembly_dll_sha256[] = "{REVIEWED_DLL}";',
             f'inline const Anchor reviewed_assembly{{"armor_assembly", 0x{start:x}, {{']
    for offset in range(0, len(data), 24):
        lines.append("    " + ",".join(f"0x{x:02x}" for x in data[offset:offset+24]) + ",")
    lines.append("}, {")
    for offset in range(0, len(mask), 32):
        lines.append("    " + ",".join(str(x) for x in mask[offset:offset+32]) + ",")
    lines.extend(["}};", "} // namespace armor_native", ""])
    (ROOT / "include/armor_reviewed_assembly.hpp").write_text("\n".join(lines), encoding="ascii")
    print("reviewed assembly", len(data), "masked", mask.count(0))


def generate(pid, game):
    dll = game / "data/game/game.dll"
    assert hashlib.sha256(dll.read_bytes()).hexdigest() == "cc75948d90fdfde259dcb519e9933db7ffa3ccb281ce4fb89e6b1b011557470c"
    disassembler = cs.Cs(cs.CS_ARCH_X86, cs.CS_MODE_64)
    disassembler.detail = True
    lines = ["#pragma once", "#include <cstdint>", "#include <vector>", "",
             "// Generated from verified 1.0.0.18930 loaded code; do not learn anchors from unknown builds.",
             "namespace armor_native {", "struct Anchor { const char *name; uint32_t original; std::vector<uint8_t> bytes, mask; };",
             "inline const std::vector<Anchor> anchors{"]
    for module, spans in SPANS.items():
        _, image = read_module(pid, module)
        pe = struct.unpack_from("<I", image, 0x3c)[0]
        stamp = struct.unpack_from("<I", image, pe + 8)[0]
        assert stamp == (0x6a86132e if module == "game.dll" else 0x6a85c636)
        for name, start, end in spans:
            data = image[start:end]
            mask = bytearray([255] * len(data))
            instructions = list(disassembler.disasm(data, start))
            assert sum(i.size for i in instructions) == len(data), (name, "incomplete decoding")
            for instruction in instructions:
                position = instruction.address - start
                if instruction.bytes[0] in (0xe8, 0xe9):
                    target = instruction.operands[0].imm
                    if not start <= target < end:
                        mask[position + instruction.imm_offset:position + instruction.imm_offset + instruction.imm_size] = bytes(instruction.imm_size)
                for operand in instruction.operands:
                    if operand.type == cs.x86.X86_OP_MEM and operand.mem.base == cs.x86.X86_REG_RIP:
                        mask[position + instruction.disp_offset:position + instruction.disp_offset + instruction.disp_size] = bytes(instruction.disp_size)
            lines.append(f'    {{"{name}", 0x{start:x}, {{')
            for offset in range(0, len(data), 24):
                lines.append("        " + ",".join(f"0x{x:02x}" for x in data[offset:offset+24]) + ",")
            lines.append("    }, {")
            for offset in range(0, len(mask), 32):
                lines.append("        " + ",".join(str(x) for x in mask[offset:offset+32]) + ",")
            lines.append("    }},")
            print(name, len(data), "masked", mask.count(0))
    lines.extend(["};", "} // namespace armor_native", ""])
    (ROOT / "include/armor_native_anchors.hpp").write_text("\n".join(lines), encoding="ascii")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--reviewed-assembly", action="store_true", help="reproduce the manually reviewed 1.0.0.19099 fixture")
    args = parser.parse_args()
    if args.reviewed_assembly:
        generate_reviewed_assembly(args.pid, args.game)
    else:
        generate(args.pid, args.game)
