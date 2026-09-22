#pragma once

// Observational extraction only. Discovery is never authorization for a game write.
#include <Windows.h>
#include <TlHelp32.h>
#include <bcrypt.h>
#pragma comment(lib, "bcrypt.lib")
#include <nlohmann/json.hpp>
#include <algorithm>
#include <array>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#include "armor_kit_anchor.hpp"

namespace armor_local_data {
using json = nlohmann::json;

inline void require(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}
inline void read(HANDLE process, uintptr_t address, void *buffer, size_t length) {
    SIZE_T received = 0;
    require(address >= 0x10000 && length && address + length >= address &&
        ReadProcessMemory(process, reinterpret_cast<const void *>(address), buffer, length, &received) &&
        received == length, "local snapshot memory unavailable or changed");
}
template<class T> inline T read(HANDLE process, uintptr_t address) {
    T value{};
    read(process, address, &value, sizeof(value));
    return value;
}
template<class T, size_t N> inline T field(const std::array<uint8_t, N> &data, size_t offset) {
    T value{};
    require(offset + sizeof(T) <= N, "local snapshot field out of bounds");
    std::memcpy(&value, data.data() + offset, sizeof(T));
    return value;
}
inline std::string hex(uint64_t value, unsigned width = 16) {
    char text[32]{};
    std::snprintf(text, sizeof(text), "%0*llx", width, static_cast<unsigned long long>(value));
    return text;
}

inline std::string stream_sha256(std::istream &input) {
    struct Handles {
        BCRYPT_ALG_HANDLE algorithm = nullptr;
        BCRYPT_HASH_HANDLE hash = nullptr;
        ~Handles() {
            if (hash) BCryptDestroyHash(hash);
            if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
        }
    } handles;
    require(BCryptOpenAlgorithmProvider(&handles.algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) >= 0 &&
        BCryptCreateHash(handles.algorithm, &handles.hash, nullptr, 0, nullptr, 0, 0) >= 0,
        "cannot initialize local file digest");
    require(input.good(), "cannot open local game DLL for hashing");
    std::array<uint8_t, 65536> buffer{};
    while (input) {
        input.read(reinterpret_cast<char *>(buffer.data()), buffer.size());
        if (input.gcount()) require(BCryptHashData(handles.hash, buffer.data(), static_cast<ULONG>(input.gcount()), 0) >= 0,
                                   "cannot hash local game DLL");
    }
    require(input.eof(), "cannot finish reading local game DLL");
    std::array<uint8_t, 32> digest{};
    require(BCryptFinishHash(handles.hash, digest.data(), static_cast<ULONG>(digest.size()), 0) >= 0,
            "cannot finish local file digest");
    std::string result;
    for (const auto byte : digest) result += hex(byte, 2);
    return result;
}

inline std::string file_sha256(const std::filesystem::path &path) {
    std::ifstream input(path, std::ios::binary);
    return stream_sha256(input);
}

inline std::string kits_sha256(const json &kits) {
    std::istringstream input(kits.dump());
    return stream_sha256(input);
}

// Require the complete body/piece selection loop, not just a short function prologue.
inline bool anchor_matches(const uint8_t *bytes) {
    for (size_t i = 0; i < kit_anchor.size(); ++i)
        if ((i < 0xa3 || i >= 0xa7) && bytes[i] != kit_anchor[i]) return false;
    return true;
}
inline uintptr_t anchor_global(uintptr_t anchor_rva, const uint8_t *bytes, uint32_t image_size) {
    int32_t displacement = 0;
    std::memcpy(&displacement, bytes + 0xa3, sizeof(displacement));
    const auto result = static_cast<int64_t>(anchor_rva) + 0xa7 + displacement;
    require(result >= 0 && static_cast<uint64_t>(result) + sizeof(uintptr_t) <= image_size,
            "discovered Kit global is outside the game module");
    return static_cast<uintptr_t>(result);
}

struct Discovery { uintptr_t global_rva = 0; uint32_t timestamp = 0, image_size = 0; };
inline Discovery discover(HANDLE process, uintptr_t game, bool verified_file = false) {
    const auto dos = read<IMAGE_DOS_HEADER>(process, game);
    require(dos.e_magic == IMAGE_DOS_SIGNATURE && dos.e_lfanew >= sizeof(dos) && dos.e_lfanew < 0x10000,
            "invalid game module DOS header");
    const auto nt = read<IMAGE_NT_HEADERS64>(process, game + dos.e_lfanew);
    require(nt.Signature == IMAGE_NT_SIGNATURE && nt.FileHeader.Machine == IMAGE_FILE_MACHINE_AMD64 &&
        nt.OptionalHeader.Magic == IMAGE_NT_OPTIONAL_HDR64_MAGIC &&
        nt.OptionalHeader.SizeOfImage <= 256 * 1024 * 1024 && nt.FileHeader.NumberOfSections <= 96,
        "invalid game module PE header");
    Discovery result{0, nt.FileHeader.TimeDateStamp, nt.OptionalHeader.SizeOfImage};
    if (verified_file && result.timestamp == 0x6a86132e && result.image_size == 0x3a6b000) {
        const auto anchor = read<std::array<uint8_t, kit_anchor.size()>>(process, game + 0xf39010);
        require(anchor_matches(anchor.data()), "verified game file has changed loaded selection code");
        result.global_rva = anchor_global(0xf39010, anchor.data(), result.image_size);
        require(result.global_rva == 0x276c220, "verified game file has changed loaded Kit reference");
        return result;
    }
    const uintptr_t sections = game + dos.e_lfanew + 24 + nt.FileHeader.SizeOfOptionalHeader;
    size_t matches = 0;
    for (unsigned index = 0; index < nt.FileHeader.NumberOfSections; ++index) {
        const auto section = read<IMAGE_SECTION_HEADER>(process, sections + index * sizeof(IMAGE_SECTION_HEADER));
        if (!(section.Characteristics & IMAGE_SCN_MEM_EXECUTE) || section.Misc.VirtualSize < kit_anchor.size()) continue;
        require(section.VirtualAddress < result.image_size &&
            section.Misc.VirtualSize <= result.image_size - section.VirtualAddress, "invalid executable section bounds");
        std::vector<uint8_t> bytes(section.Misc.VirtualSize);
        read(process, game + section.VirtualAddress, bytes.data(), bytes.size());
        auto cursor = bytes.begin();
        while (cursor != bytes.end()) {
            cursor = std::search(cursor, bytes.end(), kit_anchor.begin(), kit_anchor.begin() + 26);
            if (cursor == bytes.end()) break;
            const size_t offset = static_cast<size_t>(cursor - bytes.begin());
            if (bytes.size() - offset >= kit_anchor.size() && anchor_matches(bytes.data() + offset)) {
                result.global_rva = anchor_global(section.VirtualAddress + offset, bytes.data() + offset, result.image_size);
                require(++matches == 1, "ambiguous Kit discovery; no automatic selection");
            }
            ++cursor;
        }
    }
    require(matches == 1, "Kit layout signature not found; automatic extraction unsupported");
    return result;
}

inline json snapshot(HANDLE process, uintptr_t game, const Discovery &layout) {
    const auto store = read<uintptr_t>(process, game + layout.global_rva);
    const auto table = read<uintptr_t>(process, store);
    const auto count = read<uint32_t>(process, store + 8);
    require(count > 0 && count <= 4096, "Kit count outside bounded extraction range");
    std::vector<uintptr_t> pointers(count);
    read(process, table, pointers.data(), pointers.size() * sizeof(uintptr_t));
    json kits = json::array();
    std::set<uint32_t> ids;
    constexpr const char *names[] = {"unit", "material_lut", "pattern_lut", "cape_lut", "cape_gradient",
        "cape_nac", "decal_scalar_fields", "base_data", "decal_sheet"};
    for (uintptr_t pointer : pointers) {
        const auto kit = read<std::array<uint8_t, 64>>(process, pointer);
        const auto id = field<uint32_t>(kit, 0), type = field<uint32_t>(kit, 0x28);
        const auto bodies = field<uintptr_t>(kit, 0x30);
        const auto body_count = field<uint32_t>(kit, 0x38);
        require(id && ids.insert(id).second && type <= 2 && body_count > 0 && body_count <= 8,
                "Kit metadata differs from supported extraction layout");
        json row{{"id", hex(id, 8)}, {"archive", hex(field<uint64_t>(kit, 0x20))},
            {"type", type}, {"passive", field<uint32_t>(kit, 0x1c)}, {"bodies", json::array()}};
        for (uint32_t b = 0; b < body_count; ++b) {
            const auto body = read<std::array<uint8_t, 24>>(process, bodies + b * 24);
            const auto body_type = field<uint32_t>(body, 0), piece_count = field<uint32_t>(body, 16);
            const auto pieces = field<uintptr_t>(body, 8);
            require(body_type <= 3 && piece_count > 0 && piece_count <= 64, "unsupported body layout");
            json body_row{{"type", body_type}, {"pieces", json::array()}};
            for (uint32_t p = 0; p < piece_count; ++p) {
                const auto piece = read<std::array<uint8_t, 96>>(process, pieces + p * 96);
                const auto slot = field<uint32_t>(piece, 8), piece_type = field<uint32_t>(piece, 12);
                require(slot <= 9 && piece_type <= 2, "unsupported piece slot or type");
                json resources = json::object();
                for (size_t r = 0; r < std::size(names); ++r)
                    resources[names[r]] = hex(field<uint64_t>(piece, r == 0 ? 0 : 0x18 + (r - 1) * 8));
                body_row["pieces"].push_back({{"slot", slot}, {"type", piece_type},
                    {"weight", field<uint32_t>(piece, 16)}, {"tone_variations", piece[0x58]}, {"resources", resources}});
            }
            row["bodies"].push_back(std::move(body_row));
        }
        kits.push_back(std::move(row));
    }
    std::vector<uintptr_t> after(count);
    read(process, table, after.data(), after.size() * sizeof(uintptr_t));
    require(read<uintptr_t>(process, game + layout.global_rva) == store &&
        read<uintptr_t>(process, store) == table && read<uint32_t>(process, store + 8) == count && pointers == after,
        "Kit table changed during extraction");
    return kits;
}

inline json capture(HANDLE process, uintptr_t game, const std::filesystem::path &module_path = {}) {
    json report{{"schema", "hd2-local-game-observation/1"}, {"write_authorized", false},
        {"game_runtime_verified", false}, {"source", "read-only loaded game.dll"}};
    try {
        if (!module_path.empty()) report["game_dll_sha256"] = file_sha256(module_path);
        const bool verified_file = report.value("game_dll_sha256", "") ==
            "cc75948d90fdfde259dcb519e9933db7ffa3ccb281ce4fb89e6b1b011557470c";
        const auto layout = discover(process, game, verified_file);
        report["discovery"] = verified_file ? "verified_file_and_full_anchor" : "unique_full_anchor_scan";
        report["pe_timestamp"] = hex(layout.timestamp, 8);
        report["image_size"] = layout.image_size;
        report["kit_store_rva"] = hex(layout.global_rva, 8);
        report["game_version"] = report.value("game_dll_sha256", "") ==
            "cc75948d90fdfde259dcb519e9933db7ffa3ccb281ce4fb89e6b1b011557470c" ? "1.0.0.18930" : "unknown";
        const auto first = snapshot(process, game, layout);
        require(first == snapshot(process, game, layout), "Kit metadata changed between consecutive reads");
        if (!module_path.empty()) require(file_sha256(module_path) == report.at("game_dll_sha256"),
            "game DLL file changed during observation");
        report["kits"] = first;
        report["status"] = "observed_layout_candidate";
    } catch (const std::exception &error) {
        report["status"] = "unsupported_or_not_ready";
        report["error"] = error.what();
    }
    return report;
}

inline void save(const std::filesystem::path &path, const json &report) {
    // Fixed-size session observation, atomically replaced; no historical dump accumulation.
    auto temporary = path;
    temporary += L".tmp";
    try {
        { std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
          output << report.dump(2) << '\n';
          output.close();
          require(!output.fail(), "cannot write local game observation"); }
        require(MoveFileExW(temporary.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH),
                "cannot publish local game observation");
    } catch (...) {
        std::error_code ignored;
        std::filesystem::remove(temporary, ignored);
        throw;
    }
}
} // namespace armor_local_data
