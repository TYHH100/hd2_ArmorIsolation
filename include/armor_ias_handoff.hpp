#pragma once

#include "armor_runtime_profile.hpp"
#include <Windows.h>
#include <cctype>
#include <iomanip>
#include <optional>
#include <sstream>

// IAS isolation_version=1 is a file contract, not a native function ABI.
// Keep all private resource IDs. Only IAS publishes the corresponding Kits.
namespace armor_ias {
inline constexpr char supported_addon_sha256[] =
    "df37a3489edf51887cde7b130651282e3c7745d9586b9348662908403430e1d1";
inline constexpr char managed_header[] = "# ArmorIsolation IAS handoff v1\n";
inline constexpr char managed_prefix[] = "armorbridge_";
using Files = std::map<std::string, std::string>;

inline std::string hex(std::uint64_t value, unsigned width = 16) {
    std::ostringstream text;
    text << std::hex << std::setfill('0') << std::setw(width) << value;
    return text.str();
}

struct Declaration {
    std::string id;
    std::uint64_t archive = 0;
    bool helmet = false;
    std::set<std::uint32_t> equipment;
    std::map<std::uint64_t, std::uint64_t> units;
};

inline void require(bool value, const std::string &message) {
    if (!value) throw std::runtime_error(message);
}

inline Files make_handoff(const universal_isolation::Profile &profile) {
    Files result;
    std::set<std::uint64_t> archives;
    for (const auto &field : profile.piece_fields)
        require(field.field_offset == 0, "IAS isolation v1 cannot represent Piece texture changes: kit=" +
                hex(field.kit_id, 8) + " offset=0x" + hex(field.field_offset, 2));
    for (const auto &target : profile.targets) {
        require(archives.insert(target.archive).second,
                "IAS isolation v1 permits one declaration per Archive; independently mapped Kits share Archive=" +
                hex(target.archive));
        require(target.body_count == (target.type == 1 ? 1u : 3u),
                "IAS requires one helmet group or three body groups: kit=" + hex(target.id, 8));
        for (std::size_t i = 0; i < target.body_count; ++i)
            require(target.bodies[i].piece_count > 0 && target.bodies[i].piece_count <= 64,
                    "IAS Piece capacity exceeded: kit=" + hex(target.id, 8));
        const auto owner = profile.target_packages.at(target.id);
        const auto id = std::string(managed_prefix) + owner + "_" + hex(target.id, 8);
        std::map<std::uint64_t, std::uint64_t> units;
        for (const auto &resource : profile.resources)
            if (resource.kit_id == target.id && resource.type == universal_isolation::unit_type)
                units.emplace(resource.source, resource.target);
        require(!units.empty() && units.size() <= 64,
                "IAS Unit route capacity exceeded: kit=" + hex(target.id, 8));
        for (std::size_t i = 0; i < target.piece_count; ++i)
            require(target.pieces[i].slot != 1 || !units.count(target.pieces[i].source_unit),
                    "IAS Unit route would also replace the default cape: kit=" + hex(target.id, 8));
        std::ostringstream text;
        text << managed_header << "isolation_version=1\nisolation_id=" << id
             << "\ndomain=" << (target.type == 1 ? "helmet" : "body")
             << "\narchive=0x" << hex(target.archive) << "\nequipment=0x" << hex(target.id, 8) << '\n';
        for (const auto &[source, destination] : units)
            text << "unit=0x" << hex(source) << ",0x" << hex(destination) << '\n';
        // A private Unit is not a Rig Profile. Ordinary models have no rigbin.
        result.emplace(id + ".isolation.ini", text.str());
    }
    require(result.size() <= 256, "IAS independent manifest capacity exceeded");
    return result;
}

inline std::string read_text(const std::filesystem::path &path) {
    require(std::filesystem::file_size(path) <= 65536, "IAS declaration exceeds 64 KiB: " + path.u8string());
    std::ifstream stream(path, std::ios::binary);
    require(bool(stream), "cannot read IAS declaration: " + path.u8string());
    std::string text(std::istreambuf_iterator<char>(stream), {});
    require(!stream.bad(), "failed reading IAS declaration: " + path.u8string());
    return text;
}

inline std::string trim(std::string value) {
    const auto start = value.find_first_not_of(" \t\r");
    if (start == std::string::npos) return {};
    return value.substr(start, value.find_last_not_of(" \t\r") - start + 1);
}

inline std::uint64_t number(const std::string &text, unsigned bits) {
    const auto value = trim(text);
    require(!value.empty() && value[0] != '-' && value[0] != '+', "invalid IAS resource number");
    std::size_t end = 0;
    const auto result = std::stoull(value, &end, 0);
    require(end == value.size() && result && (bits == 64 || result <= 0xffffffffULL),
            "invalid IAS resource number");
    return result;
}

// Parse ownership fields for conflict detection. IAS remains the final parser.
inline Declaration parse_declaration(const std::string &text) {
    Declaration result;
    std::istringstream stream(text);
    std::string line;
    std::set<std::string> singular;
    while (std::getline(stream, line)) {
        line = trim(line);
        if (line.empty() || line[0] == '#' || line[0] == ';') continue;
        const auto split = line.find('=');
        require(split != std::string::npos, "invalid IAS declaration line");
        const auto key = trim(line.substr(0, split)), value = trim(line.substr(split + 1));
        if (key == "equipment")
            require(result.equipment.insert(static_cast<std::uint32_t>(number(value, 32))).second,
                    "duplicate IAS equipment");
        else if (key == "unit") {
            const auto comma = value.find(',');
            require(comma != std::string::npos, "invalid IAS Unit route");
            require(result.units.emplace(number(value.substr(0, comma), 64),
                                         number(value.substr(comma + 1), 64)).second, "duplicate IAS Unit route");
        } else if (key == "rig_profile") {
            (void)number(value, 64);
        } else {
            require(singular.insert(key).second, "duplicate IAS declaration header");
            if (key == "isolation_version") require(value == "1", "unsupported IAS isolation version");
            else if (key == "isolation_id") result.id = value;
            else if (key == "archive") result.archive = number(value, 64);
            else if (key == "domain") {
                require(value == "body" || value == "helmet", "unknown IAS domain");
                result.helmet = value == "helmet";
            } else require(false, "unknown IAS declaration field: " + key);
        }
    }
    require(singular.size() == 4 && !result.id.empty() && result.archive &&
            !result.equipment.empty() && result.equipment.size() <= 16 &&
            !result.units.empty() && result.units.size() <= 64, "incomplete IAS declaration");
    return result;
}

inline bool owned(const std::filesystem::path &path, const std::string &text) {
    const auto name = path.filename().u8string();
    if (name.compare(0, std::char_traits<char>::length(managed_prefix), managed_prefix) != 0) return false;
    require(text.compare(0, std::char_traits<char>::length(managed_header), managed_header) == 0,
            "refusing to replace unrecognized IAS bridge file: " + path.u8string());
    const auto parsed = parse_declaration(text);
    require(name == parsed.id + ".isolation.ini", "IAS bridge identity differs from filename");
    return true;
}

struct Inventory { Files managed; std::vector<Declaration> foreign; };

inline Inventory inventory(const std::filesystem::path &directory) {
    Inventory result;
    if (!std::filesystem::exists(directory)) return result;
    for (const auto &entry : std::filesystem::recursive_directory_iterator(directory)) {
        if (!entry.is_regular_file()) continue;
        const auto name = entry.path().filename().u8string();
        const std::string suffix = ".isolation.ini";
        if (name.size() < suffix.size() || name.substr(name.size() - suffix.size()) != suffix) continue;
        const auto text = read_text(entry.path());
        if (owned(entry.path(), text)) {
            require(entry.path().parent_path() == directory, "IAS bridge file moved into a subdirectory");
            result.managed.emplace(name, text);
        } else result.foreign.push_back(parse_declaration(text));
    }
    return result;
}

inline void validate_group(const Files &desired, const Inventory &installed) {
    std::vector<Declaration> declarations = installed.foreign;
    for (const auto &[name, text] : desired) {
        (void)name;
        declarations.push_back(parse_declaration(text));
    }
    require(declarations.size() <= 256, "IAS independent manifest capacity exceeded");
    std::set<std::string> ids;
    std::set<std::uint64_t> archives, sources, published;
    std::set<std::pair<bool, std::uint32_t>> equipment;
    for (const auto &declaration : declarations) {
        require(ids.insert(declaration.id).second && archives.insert(declaration.archive).second,
                "IAS declaration Archive or identity conflict: " + declaration.id);
        for (const auto value : declaration.equipment)
            require(equipment.emplace(declaration.helmet, value).second,
                    "IAS equipment already controlled: " + hex(value, 8) + " (" + declaration.id + ")");
        for (const auto &[source, destination] : declaration.units) {
            sources.insert(source);
            require(published.insert(destination).second, "IAS published Unit collision: " + hex(destination));
        }
    }
    for (const auto value : published)
        require(!sources.count(value), "IAS published Unit aliases an original Unit: " + hex(value));
}

inline bool prepared(const Files &desired, const std::filesystem::path &directory) {
    const auto installed = inventory(directory);
    validate_group(desired, installed);
    return installed.managed == desired;
}

inline void replace_file(const std::filesystem::path &path, const std::string &text) {
    const auto temporary = std::filesystem::path(path.wstring() + L".armor-tmp-" + std::to_wstring(GetCurrentProcessId()));
    require(!std::filesystem::exists(temporary), "IAS handoff temporary file already exists");
    try {
        {
            std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
            require(bool(stream), "cannot create IAS handoff file");
            stream.write(text.data(), static_cast<std::streamsize>(text.size()));
            stream.close();
            require(bool(stream), "cannot write IAS handoff file");
        }
        require(MoveFileExW(temporary.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH),
                "cannot publish IAS handoff file");
    } catch (...) {
        std::error_code ignored;
        std::filesystem::remove(temporary, ignored);
        throw;
    }
}

// Offline installation only. The caller must confirm the game has exited.
// Validate the entire group before writing, and restore earlier files on failure.
inline bool synchronize(const Files &desired, const std::filesystem::path &directory) {
    const auto installed = inventory(directory);
    validate_group(desired, installed);
    if (installed.managed == desired) return false;
    std::filesystem::create_directories(directory);
    std::vector<std::pair<std::string, std::optional<std::string>>> changed;
    changed.reserve(desired.size() + installed.managed.size());
    try {
        for (const auto &[name, text] : desired) {
            const auto previous = installed.managed.find(name);
            if (previous != installed.managed.end() && previous->second == text) continue;
            require(!std::filesystem::exists(directory / name) || previous != installed.managed.end(),
                    "IAS handoff destination is occupied");
            auto change = std::make_pair(name, previous == installed.managed.end() ? std::optional<std::string>{} : previous->second);
            replace_file(directory / name, text);
            changed.push_back(std::move(change));
        }
        for (const auto &[name, text] : installed.managed) {
            if (desired.count(name)) continue;
            auto change = std::make_pair(name, std::optional<std::string>{text});
            require(std::filesystem::remove(directory / name), "cannot remove stale IAS handoff file");
            changed.push_back(std::move(change));
        }
    } catch (...) {
        const auto failure = std::current_exception();
        for (auto entry = changed.rbegin(); entry != changed.rend(); ++entry) {
            if (entry->second) replace_file(directory / entry->first, *entry->second);
            else std::filesystem::remove(directory / entry->first);
        }
        std::rethrow_exception(failure);
    }
    return true;
}
} // namespace armor_ias
