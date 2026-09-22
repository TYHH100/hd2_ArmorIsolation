#pragma once
#include "armor_local_data.hpp"
#include "armor_native_anchors.hpp"
#include "armor_assembly_compatibility.hpp"
#include "cm14_resource_probe.hpp"
#include <map>

namespace armor_native {
struct Image {
    uint32_t size = 0;
    std::vector<std::pair<uintptr_t, std::vector<uint8_t>>> code;
};

inline Image read_image(HANDLE process, uintptr_t base) {
    using namespace armor_local_data;
    const auto dos = read<IMAGE_DOS_HEADER>(process, base);
    require(dos.e_magic == IMAGE_DOS_SIGNATURE && dos.e_lfanew >= sizeof(dos) && dos.e_lfanew < 0x10000,
            "native compatibility: invalid DOS header");
    const auto nt = read<IMAGE_NT_HEADERS64>(process, base + dos.e_lfanew);
    require(nt.Signature == IMAGE_NT_SIGNATURE && nt.FileHeader.Machine == IMAGE_FILE_MACHINE_AMD64 &&
        nt.OptionalHeader.Magic == IMAGE_NT_OPTIONAL_HDR64_MAGIC && nt.FileHeader.NumberOfSections <= 96 &&
        nt.OptionalHeader.SizeOfImage && nt.OptionalHeader.SizeOfImage <= 256 * 1024 * 1024,
        "native compatibility: invalid PE header");
    Image image;
    image.size = nt.OptionalHeader.SizeOfImage;
    const auto table = base + dos.e_lfanew + 24 + nt.FileHeader.SizeOfOptionalHeader;
    for (size_t i = 0; i < nt.FileHeader.NumberOfSections; ++i) {
        const auto section = read<IMAGE_SECTION_HEADER>(process, table + i * sizeof(IMAGE_SECTION_HEADER));
        if (!(section.Characteristics & IMAGE_SCN_MEM_EXECUTE) || !section.Misc.VirtualSize) continue;
        require(section.VirtualAddress < image.size && section.Misc.VirtualSize <= image.size - section.VirtualAddress,
                "native compatibility: invalid section bounds");
        std::vector<uint8_t> bytes(section.Misc.VirtualSize);
        read(process, base + section.VirtualAddress, bytes.data(), bytes.size());
        image.code.emplace_back(section.VirtualAddress, std::move(bytes));
    }
    require(!image.code.empty(), "native compatibility: no executable section");
    return image;
}

inline bool matches(const uint8_t *data, const Anchor &anchor) {
    for (size_t i = 0; i < anchor.bytes.size(); ++i)
        if ((data[i] & anchor.mask[i]) != (anchor.bytes[i] & anchor.mask[i])) return false;
    return true;
}

inline uintptr_t find(const Image &image, const Anchor &anchor) {
    using armor_local_data::require;
    require(!anchor.bytes.empty() && anchor.bytes.size() == anchor.mask.size(), "invalid native anchor");
    size_t prefix = 0;
    while (prefix < anchor.mask.size() && anchor.mask[prefix] == 255) ++prefix;
    require(prefix >= 4, "native anchor prefix too short");
    uintptr_t found = 0;
    for (const auto &[rva, bytes] : image.code) {
        auto cursor = bytes.begin();
        while (cursor != bytes.end()) {
            cursor = std::search(cursor, bytes.end(), anchor.bytes.begin(), anchor.bytes.begin() + prefix);
            if (cursor == bytes.end()) break;
            const size_t offset = static_cast<size_t>(cursor - bytes.begin());
            if (bytes.size() - offset >= anchor.bytes.size() && matches(bytes.data() + offset, anchor)) {
                require(!found, "native compatibility: ambiguous full-function anchor");
                found = rva + offset;
            }
            ++cursor;
        }
    }
    if (!found) throw std::runtime_error(std::string("native compatibility: function changed or unavailable: ") + anchor.name);
    return found;
}

inline uintptr_t relative(HANDLE process, uintptr_t base, uintptr_t instruction, size_t displacement, size_t length,
                          uint32_t image_size) {
    const auto delta = armor_local_data::read<int32_t>(process, base + instruction + displacement);
    const int64_t target = static_cast<int64_t>(instruction) + length + delta;
    armor_local_data::require(target > 0 && static_cast<uint64_t>(target) + 8 <= image_size,
                             "native compatibility: reference outside module");
    return static_cast<uintptr_t>(target);
}

struct Layout {
    uintptr_t kit_store = 0, application = 0;
    std::map<std::string, uintptr_t> functions;
};

inline std::map<std::string, uintptr_t> discover_functions(const Image &game_image, const Image &exe_image,
                                                          armor_local_data::json *diagnostics = nullptr) {
    // The assembly consumer is mandatory: CollectPieces alone does not prove
    // the meanings of the Unit, Slot, Type and material fields in each Piece.
    // Match reviewed complete instruction families independently of disk hashes.
    // The operation still binds its data and generated package to both file hashes.
    std::map<std::string, uintptr_t> functions;
    armor_local_data::json detail = {{"required", anchors.size()}, {"matched", 0},
                                    {"functions", armor_local_data::json::object()}};
    std::string failures;
    for (size_t i = 0; i < anchors.size(); ++i) {
        const auto name = anchors[i].name;
        try {
            const auto assembly = i == 0 ? find_assembly(game_image) : AssemblyMatch{};
            const auto rva = i == 0 ? assembly.rva : find(exe_image, anchors[i]);
            functions.emplace(name, rva);
            detail["functions"][name] = {{"status", "matched"}, {"rva", rva}};
            if (i == 0) detail["functions"][name]["variant"] = assembly.variant;
        } catch (const std::exception &error) {
            detail["functions"][name] = {{"status", "failed"}, {"error", error.what()}};
            if (!failures.empty()) failures += "; ";
            failures += error.what();
        }
    }
    detail["matched"] = functions.size();
    if (diagnostics) *diagnostics = std::move(detail);
    if (!failures.empty()) throw std::runtime_error("native compatibility: matched " +
        std::to_string(functions.size()) + "/" + std::to_string(anchors.size()) + "; " + failures);
    return functions;
}

inline void validate_assembly_references(HANDLE process, uintptr_t game, uintptr_t assembly,
                                         uintptr_t kit_store, uint32_t image_size) {
    armor_local_data::require(
        relative(process, game, assembly + 0x1b5, 3, 7, image_size) == kit_store &&
        relative(process, game, assembly + 0x468, 3, 7, image_size) == kit_store,
        "native compatibility: assembly and collector Kit references disagree");
}

inline Layout discover(HANDLE process, uintptr_t game, uintptr_t exe,
                       armor_local_data::json *diagnostics = nullptr) {
    using namespace armor_local_data;
    Layout result;
    result.kit_store = armor_local_data::discover(process, game).global_rva;
    const auto game_image = read_image(process, game), exe_image = read_image(process, exe);
    result.functions = discover_functions(game_image, exe_image, diagnostics);
    validate_assembly_references(process, game, result.functions.at("armor_assembly"),
                                 result.kit_store, game_image.size);
    const auto material = result.functions.at("material_texture");
    result.application = relative(process, exe, material + 8, 3, 7, exe_image.size);
    require(relative(process, exe, material + 0xb7, 3, 7, exe_image.size) == result.application,
            "native compatibility: application references disagree");
    const auto online = result.functions.at("resource_online");
    require(relative(process, exe, online + 0x25, 1, 5, exe_image.size) == result.functions.at("type_find") &&
            relative(process, exe, online + 0x66, 1, 5, exe_image.size) == result.functions.at("type_find"),
            "native compatibility: resource type lookup calls disagree");
    const auto application = read<uintptr_t>(process, exe + result.application);
    const auto manager = read<uintptr_t>(process, application + 0x3f8);
    const auto types = read<cm14_isolation::resource_probe_detail::map_header>(process, manager + 0x2e8);
    require(cm14_isolation::resource_probe_detail::valid_map(types, 0xd0) && types.count > 0,
            "native compatibility: resource manager not ready or incompatible");
    for (const uint64_t type : {0xe0a48d0be9a7453fULL, 0xcd4238c6a0c69e32ULL, 0xeac0b497876adedfULL}) {
        cm14_isolation::resource_probe_detail::found_entry entry{};
        require(cm14_isolation::resource_probe_detail::find(process, types, type, 0xd0, 0xc8, entry) ==
                    cm14_isolation::resource_state::ready, "native compatibility: required resource type absent");
    }
    return result;
}

inline void attach_evidence(armor_local_data::json &report, HANDLE process, uintptr_t game, uintptr_t exe,
                            const std::filesystem::path &game_path, const std::filesystem::path &exe_path) {
    using namespace armor_local_data;
    require(report.at("status") == "observed_layout_candidate", "Kit snapshot not ready");
    const auto hash = file_sha256(exe_path);
    armor_local_data::json diagnostics;
    Layout layout;
    try {
        layout = discover(process, game, exe, &diagnostics);
        require(hash == file_sha256(exe_path) && report.at("game_dll_sha256") == file_sha256(game_path),
                "game files changed during discovery");
    } catch (const std::exception &error) {
        diagnostics["status"] = "failed";
        diagnostics["error"] = error.what();
        report["native_diagnostics"] = std::move(diagnostics);
        throw;
    }
    diagnostics["status"] = "passed";
    report["native_diagnostics"] = std::move(diagnostics);
    report["native_compatibility"] = {{"mode", "signature-validated-v1"},
        {"exe_sha256", hash}, {"kit_store_rva", hex(layout.kit_store, 8)},
        {"application_rva", hex(layout.application, 8)}, {"functions", layout.functions}};
    report["kits_sha256"] = kits_sha256(report.at("kits"));
}
} // namespace armor_native
