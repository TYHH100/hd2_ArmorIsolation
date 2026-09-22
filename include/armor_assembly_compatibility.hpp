#pragma once
#include "armor_reviewed_assembly.hpp"
#include <algorithm>
#include <array>
#include <cstring>
#include <map>
#include <stdexcept>
#include <string>
#include <utility>

namespace armor_native {
struct AssemblyMatch {
    uintptr_t rva = 0;
    std::string variant;
};

inline int64_t assembly_parameter(const uint8_t *bytes, size_t offset) {
    int32_t value = 0;
    std::memcpy(&value, bytes + offset, sizeof(value));
    return value;
}

inline bool assembly_parameters_valid(const uint8_t *bytes, bool reviewed) {
    // These operands address external global objects, never Kit/Body/Piece.
    // Keep each group coherent instead of accepting arbitrary wildcard bytes.
    const auto table_count = assembly_parameter(bytes, 0x218);
    const auto table_base = assembly_parameter(bytes, 0x223);
    const auto table_flags = assembly_parameter(bytes, 0x4ed);
    const auto table_value = assembly_parameter(bytes, 0x4fb);
    if (table_count <= 0 || table_count > 16 * 1024 * 1024 || table_count % 8 != 0 ||
        table_base != table_count + 8 || table_flags != table_count + 0x133 ||
        table_value != table_count + 0x28)
        return false;

    const auto character_count = assembly_parameter(bytes, 0x7eb);
    const auto character_stride = assembly_parameter(bytes, 0x80d);
    const auto indexed_stride = assembly_parameter(bytes, 0xae8);
    const auto character_field = assembly_parameter(bytes, 0xafb);
    if (character_stride <= 0 || character_stride >= 1024 * 1024 || character_stride % 8 != 0 ||
        indexed_stride != character_stride || character_count != 32 * character_stride ||
        character_field < 0 || character_field % 4 != 0 || character_field + 0x38 + 4 > character_stride)
        return false;

    const auto world = assembly_parameter(bytes, 0xb83);
    const auto second_world = assembly_parameter(bytes, 0xbab);
    const auto auxiliary_world = assembly_parameter(bytes, reviewed ? 0xbf7 : 0xc1b);
    return world > 0 && world % 8 == 0 && world <= 1024 * 1024 && second_world == world &&
        auxiliary_world == world + 0x10 && auxiliary_world <= 1024 * 1024;
}

inline Anchor assembly_shape(bool reviewed) {
    auto shape = reviewed ? reviewed_assembly : anchors.front();
    // Operand byte offsets, each exactly one signed disp32 or imm32. The
    // instruction opcodes/registers, Piece fields, internal branches, and all
    // remaining function bytes retain the reviewed template's existing mask.
    const std::array<size_t, 11> parameters{0x218, 0x223, 0x4ed, 0x4fb,
        0x7eb, 0x80d, 0xae8, 0xafb, 0xb83, 0xbab, reviewed ? 0xbf7u : 0xc1bu};
    if (shape.bytes.empty() || shape.bytes.size() != shape.mask.size())
        throw std::runtime_error("native compatibility: invalid armor_assembly shape");
    for (const auto offset : parameters) {
        if (offset > shape.mask.size() || shape.mask.size() - offset < sizeof(int32_t))
            throw std::runtime_error("native compatibility: invalid armor_assembly parameter bounds");
        std::fill_n(shape.mask.begin() + offset, sizeof(int32_t), uint8_t{0});
    }
    return shape;
}

template <class ImageType>
inline AssemblyMatch find_assembly(const ImageType &image) {
    // Both reviewed instruction shapes remain complete, from entry through ret.
    // Candidate uniqueness is checked before accepting external-layout values;
    // a second shape occurrence is never silently ignored as a bad parameter set.
    std::map<uintptr_t, std::pair<bool, std::string>> candidates;
    for (bool reviewed : {false, true}) {
        const auto shape = assembly_shape(reviewed);
        size_t prefix = 0;
        while (prefix < shape.mask.size() && shape.mask[prefix] == 255) ++prefix;
        if (prefix < 4)
            throw std::runtime_error("native compatibility: armor_assembly shape prefix too short");
        for (const auto &[rva, bytes] : image.code) {
            auto cursor = bytes.begin();
            while (cursor != bytes.end()) {
                cursor = std::search(cursor, bytes.end(), shape.bytes.begin(), shape.bytes.begin() + prefix);
                if (cursor == bytes.end()) break;
                const auto offset = static_cast<size_t>(cursor - bytes.begin());
                if (bytes.size() - offset >= shape.bytes.size()) {
                    const auto *data = bytes.data() + offset;
                    bool matched = true;
                    for (size_t i = 0; i < shape.bytes.size(); ++i)
                        if ((data[i] & shape.mask[i]) != (shape.bytes[i] & shape.mask[i])) {
                            matched = false;
                            break;
                        }
                    if (matched) {
                        const bool valid = assembly_parameters_valid(data, reviewed);
                        const std::string variant = reviewed ? "assembly-family-19099" : "assembly-family-18930";
                        const auto [candidate, inserted] = candidates.emplace(rva + offset, std::make_pair(valid, variant));
                        if (!inserted && valid) candidate->second = {true, variant};
                        if (candidates.size() > 1)
                            throw std::runtime_error("native compatibility: ambiguous armor_assembly function family");
                    }
                }
                ++cursor;
            }
        }
    }
    if (candidates.empty())
        throw std::runtime_error("native compatibility: function changed or unavailable: armor_assembly");
    const auto &[rva, evidence] = *candidates.begin();
    if (!evidence.first)
        throw std::runtime_error("native compatibility: armor_assembly external layout parameters disagree");
    return {rva, evidence.second};
}
} // namespace armor_native
