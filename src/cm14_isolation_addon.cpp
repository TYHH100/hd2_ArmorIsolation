#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>
#if defined(UNIVERSAL_ISOLATION)
#include <TlHelp32.h>
#include <algorithm>
#include <cwctype>
#include <filesystem>
// ReShade 6.5.1 only exposes its overlay ImGui bindings when this translation unit
// already saw 'IMGUI_VERSION_NUM 19191', so the Dear ImGui headers come first.
#define ImTextureID ImU64
#include <imgui.h>
#endif
#include <reshade.hpp>
#include <array>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <iterator>
#include <map>
#include <memory>
#include <set>
#include <tuple>
#include <string>
#include <utility>
#include <vector>

#if defined(UNIVERSAL_ISOLATION)
#include "armor_embedded_profile.hpp"
#include "armor_local_data.hpp"
#include "armor_native_compatibility.hpp"
namespace isolation_profile = universal_isolation;
#elif defined(GENERIC_ISOLATION)
#include "generic_resource_map.hpp"
namespace isolation_profile = generic_isolation;
#elif defined(B01_ISOLATION)
#include "b01_resource_map.hpp"
namespace isolation_profile = b01_isolation;
#else
#include "cm14_resource_map.hpp"
namespace isolation_profile = cm14_isolation;
#endif
#include "cm14_resource_probe.hpp"

namespace {
#if defined(UNIVERSAL_ISOLATION)
constexpr wchar_t config_section[] = L"ArmorIsolation";
constexpr char profile_label[] = "Armor";
constexpr char profile_name[] = "Armor Resource Isolation";
constexpr char profile_description[] = "Version-guarded armor isolation using validated package configuration files.";
#elif defined(GENERIC_ISOLATION)
constexpr wchar_t config_section[] = L"ArmorIsolation";
constexpr char profile_label[] = "Armor";
constexpr char profile_name[] = "Armor Resource Isolation " ISOLATION_PACKAGE_ID;
constexpr char profile_description[] = "Version-guarded package-private armor and helmet resource configuration.";
#elif defined(B01_ISOLATION)
constexpr wchar_t config_section[] = L"B01Isolation";
constexpr char profile_label[] = "B01";
constexpr char profile_name[] = "B01 Resource Isolation";
constexpr char profile_description[] = "Version-guarded B01 private armor and helmet resource configuration.";
#else
constexpr wchar_t config_section[] = L"CM14Isolation";
constexpr char profile_label[] = "CM14";
constexpr char profile_name[] = "CM14 Resource Isolation";
constexpr char profile_description[] = "Version-guarded CM14 private armor and helmet resource configuration.";
#endif
#if defined(UNIVERSAL_ISOLATION)
constexpr char overlay_title[] = "Armor Isolation";
#endif
uintptr_t kit_store_rva = 0x276c220;
constexpr size_t kit_size = 64, body_size = 24, piece_size = 96;
constexpr size_t publication_limit = 16;
using isolation_profile::TargetKit;

size_t clone_size(const TargetKit &target) noexcept {
    return kit_size + target.body_count * body_size + target.piece_count * piece_size;
}

struct Snapshot {
    uintptr_t store = 0, table = 0, entry = 0, kit = 0, bodies = 0;
    uint32_t count = 0;
    std::vector<uintptr_t> pieces;
    std::vector<uint8_t> data;
};
struct Publication {
    uintptr_t address = 0;
    std::vector<uint8_t> expected;
};
struct TargetState {
    std::array<Publication, publication_limit> publications{};
    size_t publication_count = 0;
    std::string last_status;
    bool fatal_error = false;
    std::vector<uint8_t> cached_source, cached_candidate;
    size_t cached_changes = 0;
    uint64_t waiting_type = 0, waiting_resource = 0;
};

struct KitLocation { uintptr_t entry = 0, kit = 0; size_t matches = 0; };
struct KitIndex {
    uintptr_t store = 0, table = 0;
    uint32_t count = 0;
    std::vector<uintptr_t> pointers;
    std::map<uint32_t, KitLocation> locations;
};

HMODULE module_handle = nullptr;
std::atomic_flag callback_active = ATOMIC_FLAG_INIT;
#if defined(UNIVERSAL_ISOLATION)
isolation_profile::Profile active_profile;
std::vector<TargetState> target_states;
bool profiles_initialized = false;
bool local_data_saved = false;
uint64_t last_local_attempt = 0;
unsigned local_attempts = 0;
bool native_layout_validated = false;
uint64_t last_native_attempt = 0;
size_t native_attempts = 0;
armor_native::Layout native_layout;
std::filesystem::path profiles_directory;
std::filesystem::path patches_directory;
struct TargetMappings {
    const isolation_profile::TargetStorage *declared = nullptr;
    std::vector<isolation_profile::FieldMapping> fields;
};
std::map<uint32_t, TargetMappings> mappings_by_kit;
std::set<std::tuple<uint32_t, uint64_t, uint64_t, uint64_t>> owned_mappings;
#else
std::array<TargetState, std::size(isolation_profile::targets)> target_states{};
#endif
uint64_t last_poll = 0;
std::wstring log_path, config_path;
std::string last_status;
bool fatal_error = false;
bool log_started = false;

#if defined(UNIVERSAL_ISOLATION)
// The overlay only reads published snapshots. The poll callback owns the working copy and
// swaps it in once per update, so the render thread never observes a half-written row.
// Status rows keep the complete text: the overlay shows the whole reason string without
// truncation, and ArmorIsolation.log keeps the full history.
struct UiTargetRow {
    uint32_t kit_id = 0;
    uint32_t type = 0, passive = 0;
    uint32_t body_count = 0, piece_count = 0, unit_changes = 0;
    uint32_t required_resources = 0, publications = 0;
    std::string package, state, detail;
};
struct UiSnapshot {
    uint64_t updated_ms = 0;
    bool enabled = true;
    bool diagnostic_only = false;
    bool options_known = false;
    bool profiles_failed = false;
    bool native_adapted = false;
    std::string global_state = "PENDING", global_detail;
    uint32_t package_count = 0, target_count = 0, resource_count = 0;
    uint32_t pending_count = 0, waiting_count = 0, ready_count = 0, applied_count = 0, failed_count = 0;
    std::vector<UiTargetRow> targets;
};
std::array<UiSnapshot, 2> ui_snapshots;
std::atomic<unsigned> ui_published{0};
std::atomic<bool> ui_poll_requested{false};
// The overlay stores these directly, so a click is reflected on the next frame instead of
// waiting up to a second for the next poll; the poll callback still re-reads the INI afterwards.
std::atomic<bool> active_enabled{true};
std::atomic<bool> active_diagnostic{false};
std::atomic<bool> active_options_known{false};

struct ParsedStatus { std::string state, detail; };

ParsedStatus parse_status(const std::string &text) {
    ParsedStatus result;
    if (text.empty()) {
        result.state = "PENDING";
        return result;
    }
    const size_t space = text.find(' ');
    std::string head = space == std::string::npos ? text : text.substr(0, space);
    result.detail = space == std::string::npos ? std::string() : text.substr(space + 1);
    if (head.size() >= 2 && head.front() == '[' && head.back() == ']')
        head = head.substr(1, head.size() - 2);
    result.state = std::move(head);
    return result;
}

unsigned state_rank(const std::string &state) noexcept {
    if (state == "APPLIED") return 3;
    if (state == "READY") return 2;
    if (state == "FAILED") return 4;
    if (state == "WAIT") return 1;
    return 0;
}

void publish_ui_snapshot() {
    const unsigned published = ui_published.load(std::memory_order_relaxed);
    UiSnapshot &next = ui_snapshots[published ^ 1u];
    next.updated_ms = GetTickCount64();
    next.enabled = active_enabled.load(std::memory_order_relaxed);
    next.diagnostic_only = active_diagnostic.load(std::memory_order_relaxed);
    next.options_known = active_options_known.load(std::memory_order_relaxed);
    next.profiles_failed = fatal_error;
    next.native_adapted = native_layout_validated;
    const ParsedStatus global = parse_status(last_status);
    next.global_state = global.state;
    next.global_detail = global.detail;
    next.package_count = static_cast<uint32_t>(active_profile.package_ids.size());
    next.resource_count = static_cast<uint32_t>(active_profile.resources.size());
    const auto &targets = active_profile.targets;
    const size_t target_count = targets.size();
    next.target_count = static_cast<uint32_t>(target_count);
    next.targets.assign(target_count, UiTargetRow{});
    next.pending_count = next.waiting_count = next.ready_count = next.applied_count = next.failed_count = 0;
    for (size_t index = 0; index < target_count; ++index) {
        auto &row = next.targets[index];
        row.kit_id = targets[index].id;
        row.type = targets[index].type;
        row.passive = targets[index].passive;
        row.body_count = static_cast<uint32_t>(targets[index].body_count);
        row.piece_count = static_cast<uint32_t>(targets[index].piece_count);
        row.unit_changes = static_cast<uint32_t>(targets[index].expected_unit_changes);
        const auto requirements = active_profile.requirements_by_kit.find(row.kit_id);
        row.required_resources = requirements == active_profile.requirements_by_kit.end() ? 0u :
            static_cast<uint32_t>(requirements->second.size());
        row.publications = index < target_states.size() ?
            static_cast<uint32_t>(target_states[index].publication_count) : 0u;
        const auto owner = active_profile.target_packages.find(row.kit_id);
        row.package = owner == active_profile.target_packages.end() ? "unknown" : owner->second;
        const ParsedStatus target = parse_status(index < target_states.size() ? target_states[index].last_status : std::string());
        row.state = target.state;
        row.detail = target.detail;
        switch (state_rank(target.state)) {
        case 1: ++next.waiting_count; break;
        case 2: ++next.ready_count; break;
        case 3: ++next.applied_count; break;
        case 4: ++next.failed_count; break;
        default: ++next.pending_count; break;
        }
    }
    // The overlay keeps the current per-target status; ArmorIsolation.log keeps the full history.
    ui_published.store(published ^ 1u, std::memory_order_release);
}
#endif

const auto &profile_targets() noexcept {
#if defined(UNIVERSAL_ISOLATION)
    return active_profile.targets;
#else
    return isolation_profile::targets;
#endif
}
const auto &profile_resources() noexcept {
#if defined(UNIVERSAL_ISOLATION)
    return active_profile.resources;
#else
    return isolation_profile::resources;
#endif
}
const auto &profile_fields() noexcept {
#if defined(UNIVERSAL_ISOLATION)
    return active_profile.piece_fields;
#else
    return isolation_profile::piece_fields;
#endif
}

bool read_bytes(uintptr_t address, void *output, size_t size) noexcept {
    if (address < 0x10000 || size == 0 || address + size < address)
        return false;
    SIZE_T received = 0;
    return ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<const void *>(address),
                             output, size, &received) && received == size;
}
template <class T> bool read_value(uintptr_t address, T &output) noexcept {
    return read_bytes(address, &output, sizeof(output));
}
template <class T> T get(const uint8_t *data, size_t offset) noexcept {
    T result{};
    std::memcpy(&result, data + offset, sizeof(result));
    return result;
}
template <class T> void put(uint8_t *data, size_t offset, T value) noexcept {
    std::memcpy(data + offset, &value, sizeof(value));
}

void initialize_paths() {
    if (!log_path.empty())
        return;
    std::array<wchar_t, 32768> path{};
    const DWORD length = GetModuleFileNameW(module_handle, path.data(), static_cast<DWORD>(path.size()));
    if (!length || length >= path.size())
        return;
    std::wstring stem(path.data(), length);
#if defined(UNIVERSAL_ISOLATION)
    const auto parent = std::filesystem::path(stem).parent_path();
    log_path = (parent / L"ArmorIsolation.log").wstring();
    config_path = (parent / L"ArmorIsolation.ini").wstring();
    profiles_directory = parent / L"ArmorIsolation";
    const DWORD exe_length = GetModuleFileNameW(nullptr, path.data(), static_cast<DWORD>(path.size()));
    if (exe_length && exe_length < path.size())
        patches_directory = std::filesystem::path(std::wstring(path.data(), exe_length)).parent_path().parent_path() / L"data";
#else
    const auto extension = stem.find_last_of(L'.');
    const auto separator = stem.find_last_of(L"\\/");
    if (extension != std::wstring::npos && (separator == std::wstring::npos || extension > separator))
        stem.resize(extension);
    log_path = stem + L".log";
    config_path = stem + L".ini";
#endif
}

void status(const char *state, const std::string &detail, std::string &previous = last_status) {
    const std::string message = std::string(state) + " " + detail;
    if (message == previous)
        return;
    initialize_paths();
    FILE *file = nullptr;
    // First successful write starts a fresh log; later status changes append.
    if (log_path.empty() || _wfopen_s(&file, log_path.c_str(), log_started ? L"ab" : L"wb") != 0)
        return;
    log_started = true;
    previous = message;
    SYSTEMTIME time{};
    GetLocalTime(&time);
    std::fprintf(file, "%04u-%02u-%02u %02u:%02u:%02u %s\r\n", time.wYear, time.wMonth,
                 time.wDay, time.wHour, time.wMinute, time.wSecond, message.c_str());
    std::fclose(file);
}

void target_status(const TargetKit &target, TargetState &runtime,
                   const char *state, const std::string &detail) {
    char prefix[32]{};
    std::snprintf(prefix, sizeof(prefix), "kit=%08x ", target.id);
#if defined(UNIVERSAL_ISOLATION)
    const auto owner = active_profile.target_packages.find(target.id);
    const std::string package = owner == active_profile.target_packages.end() ? "unknown" : owner->second;
    status(state, "package=" + package + " " + prefix + detail, runtime.last_status);
#else
    status(state, prefix + detail, runtime.last_status);
#endif
}

#if defined(UNIVERSAL_ISOLATION)
void initialize_mapping_indexes() {
    mappings_by_kit.clear();
    owned_mappings.clear();
    for (size_t index = 0; index < active_profile.targets.size(); ++index)
        mappings_by_kit[active_profile.targets[index].id].declared = active_profile.storage[index].get();
    for (const auto &field : active_profile.piece_fields)
        mappings_by_kit[field.kit_id].fields.push_back(field);
    for (const auto &resource : active_profile.resources)
        owned_mappings.emplace(resource.kit_id, resource.type, resource.source, resource.target);
}

bool legacy_addon_name(std::wstring name) {
    std::transform(name.begin(), name.end(), name.begin(), [](wchar_t value) {
        return static_cast<wchar_t>(std::towlower(value));
    });
    constexpr wchar_t suffix[] = L".addon64";
    return name == L"cm14isolation.addon64" || name == L"b01isolation.addon64" ||
        (name.compare(0, 15, L"armorisolation_") == 0 && name.size() > 23 &&
         name.compare(name.size() - 8, 8, suffix) == 0);
}

bool no_legacy_addons(std::string &error) {
    const HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, GetCurrentProcessId());
    if (snapshot == INVALID_HANDLE_VALUE) {
        error = "cannot enumerate loaded add-ons; no config write";
        return false;
    }
    MODULEENTRY32W entry{};
    entry.dwSize = sizeof(entry);
    if (!Module32FirstW(snapshot, &entry)) {
        CloseHandle(snapshot);
        error = "cannot inspect loaded add-ons; no config write";
        return false;
    }
    do {
        if (entry.hModule != module_handle && legacy_addon_name(entry.szModule)) {
            const std::wstring name(entry.szModule);
            CloseHandle(snapshot);
            error = "legacy add-on " + std::string(name.begin(), name.end()) +
                " is loaded; migrate its package to ArmorIsolation JSON and remove the old add-on "
                "after exiting the game; RESTART_REQUIRED; no further config writes";
            return false;
        }
    } while (Module32NextW(snapshot, &entry));
    const DWORD enumeration_error = GetLastError();
    CloseHandle(snapshot);
    if (enumeration_error != ERROR_NO_MORE_FILES) {
        error = "loaded add-on enumeration changed or failed; no config write";
        return false;
    }
    return true;
}

bool initialize_profiles() {
    if (profiles_initialized)
        return !fatal_error;
    profiles_initialized = true;
    if (profiles_directory.empty() || patches_directory.empty()) {
        fatal_error = true;
        status("[FAILED]", "cannot locate the add-on configuration directory; RESTART_REQUIRED; no config write");
        return false;
    }
    std::string error;
    if (!isolation_profile::load_installed_packages(patches_directory, profiles_directory, active_profile, error)) {
        fatal_error = true;
        status("[FAILED]", "package configuration group rejected: " + error +
            "; RESTART_REQUIRED; no config write");
        return false;
    }
    initialize_mapping_indexes();
    target_states.resize(active_profile.targets.size());
    if (target_states.empty()) {
        status("[EMPTY]", "no embedded patch profiles or legacy JSON; install an isolation mod and restart; no config write");
    } else {
        status("[CONFIG]", "validated packages=" + std::to_string(active_profile.package_ids.size()) +
            " targets=" + std::to_string(active_profile.targets.size()) +
            " resources=" + std::to_string(active_profile.resources.size()) +
            "; configuration is fixed until process restart");
    }
    return true;
}
#endif

bool module_matches(uintptr_t base, uint32_t timestamp, uint32_t image_size) noexcept {
    IMAGE_DOS_HEADER dos{};
    IMAGE_NT_HEADERS64 pe{};
    return read_value(base, dos) && dos.e_magic == IMAGE_DOS_SIGNATURE &&
        dos.e_lfanew >= sizeof(dos) && dos.e_lfanew < 0x10000 &&
        read_value(base + dos.e_lfanew, pe) && pe.Signature == IMAGE_NT_SIGNATURE &&
        pe.FileHeader.Machine == IMAGE_FILE_MACHINE_AMD64 &&
        pe.FileHeader.TimeDateStamp == timestamp &&
        pe.OptionalHeader.Magic == IMAGE_NT_OPTIONAL_HDR64_MAGIC &&
        pe.OptionalHeader.SizeOfImage == image_size;
}

bool code_matches(uintptr_t game) noexcept {
    constexpr std::array<uint8_t, 26> expected{
        0x48, 0x89, 0x5c, 0x24, 0x08, 0x48, 0x89, 0x6c, 0x24, 0x10,
        0x48, 0x89, 0x74, 0x24, 0x18, 0x48, 0x89, 0x7c, 0x24, 0x20,
        0x41, 0x56, 0x8b, 0x71, 0x38, 0x33};
    std::array<uint8_t, expected.size()> observed{};
    return read_bytes(game + 0xf39010, observed.data(), observed.size()) && observed == expected;
}

bool layout_matches(const TargetKit &target, const Snapshot &snapshot, std::string &error) {
    if (snapshot.data.size() != clone_size(target) || !target.body_count || !target.piece_count) {
        error = "configuration snapshot size differs from the target layout";
        return false;
    }
    const auto *kit = snapshot.data.data();
    if (get<uint32_t>(kit, 0) != target.id || get<uint64_t>(kit, 0x20) != target.archive ||
        get<uint32_t>(kit, 0x28) != target.type || get<uint32_t>(kit, 0x1c) != target.passive ||
        get<uint32_t>(kit, 0x38) != target.body_count) {
        error = "target kit ID, archive, type, passive or body count differs";
        return false;
    }
    size_t piece_index = 0;
    for (size_t body_index = 0; body_index < target.body_count; ++body_index) {
        const auto *body = kit + kit_size + body_index * body_size;
        const auto &expected = target.bodies[body_index];
        if (get<uint32_t>(body, 0) != expected.body_type ||
            get<uint32_t>(body, 16) != expected.piece_count ||
            expected.piece_count > target.piece_count - piece_index) {
            error = "target body types or piece counts differ";
            return false;
        }
        for (size_t index = 0; index < expected.piece_count; ++index) {
            if (target.pieces[piece_index++].body_type != expected.body_type) {
                error = "generated piece and body layouts disagree";
                return false;
            }
        }
    }
    if (piece_index != target.piece_count) {
        error = "generated body counts do not cover the piece layout";
        return false;
    }
    return true;
}

bool build_kit_index(uintptr_t game, KitIndex &result, std::string &error) {
    result = {};
    if (!read_value(game + kit_store_rva, result.store) || !result.store ||
        !read_value(result.store, result.table) ||
        !read_value(result.store + 8, result.count) || !result.table ||
#if defined(UNIVERSAL_ISOLATION)
        (native_layout_validated ? (result.count == 0 || result.count > 4096) : result.count != 402)) {
#else
        result.count != 402) {
#endif
        error = "kit store is not initialized or count differs from 402";
        return false;
    }
    result.pointers.resize(result.count);
    if (!read_bytes(result.table, result.pointers.data(), result.pointers.size() * sizeof(uintptr_t))) {
        error = "kit pointer array is unreadable";
        return false;
    }
    for (size_t index = 0; index < result.pointers.size(); ++index) {
        uint32_t id = 0;
        if (!read_value(result.pointers[index], id)) {
            error = "kit array changed while reading";
            return false;
        }
        auto &location = result.locations[id];
        ++location.matches;
        location.kit = result.pointers[index];
        location.entry = result.table + index * sizeof(uintptr_t);
    }
    return true;
}

bool capture_snapshot(uintptr_t game, const TargetKit &target, Snapshot &result, std::string &error,
                      const KitIndex *shared_index = nullptr) {
    result.data.resize(clone_size(target));
    result.pieces.resize(target.body_count);
    KitIndex local_index;
    if (!shared_index) {
        if (!build_kit_index(game, local_index, error))
            return false;
        shared_index = &local_index;
    }
    const auto location = shared_index->locations.find(target.id);
    if (location == shared_index->locations.end() || location->second.matches != 1) {
        error = "expected exactly one readable target kit";
        return false;
    }
    result.entry = location->second.entry;
    // An index is only a lookup hint for this poll, never proof that memory is unchanged.
    if (!read_value(game + kit_store_rva, result.store) || result.store != shared_index->store ||
        !read_value(result.store, result.table) || result.table != shared_index->table ||
        !read_value(result.store + 8, result.count) || result.count != shared_index->count ||
        !read_value(result.entry, result.kit) || result.kit != location->second.kit ||
        !read_bytes(result.kit, result.data.data(), kit_size) || get<uint32_t>(result.data.data(), 0) != target.id) {
        error = "kit index changed while reading; retry next poll";
        return false;
    }
    if (!result.kit) {
        error = "expected exactly one readable target kit";
        return false;
    }
    const uint8_t *kit = result.data.data();
    result.bodies = get<uintptr_t>(kit, 0x30);
    if (get<uint32_t>(kit, 0x38) != target.body_count ||
        !read_bytes(result.bodies, result.data.data() + kit_size, target.body_count * body_size)) {
        error = "target body count differs or body array is unreadable";
        return false;
    }
    if (!layout_matches(target, result, error))
        return false;
    size_t piece_index = 0;
    for (size_t body_index = 0; body_index < target.body_count; ++body_index) {
        const auto *body = result.data.data() + kit_size + body_index * body_size;
        result.pieces[body_index] = get<uintptr_t>(body, 8);
        if (!read_bytes(result.pieces[body_index], result.data.data() + kit_size + target.body_count * body_size +
                        piece_index * piece_size, target.bodies[body_index].piece_count * piece_size)) {
            error = "target piece array is unreadable";
            return false;
        }
        piece_index += target.bodies[body_index].piece_count;
    }
    return true;
}

bool kit_index_unchanged(uintptr_t game, const KitIndex &original) {
    uintptr_t store = 0, table = 0;
    uint32_t count = 0;
    if (!read_value(game + kit_store_rva, store) || store != original.store ||
        !read_value(store, table) || table != original.table ||
        !read_value(store + 8, count) || count != original.count ||
        original.pointers.size() != count)
        return false;
    std::vector<uintptr_t> pointers(count);
    return read_bytes(table, pointers.data(), pointers.size() * sizeof(uintptr_t)) &&
        pointers == original.pointers;
}

bool snapshot_unchanged(uintptr_t game, const TargetKit &target, const Snapshot &original,
                        const KitIndex *shared_index = nullptr) {
    if (shared_index && !kit_index_unchanged(game, *shared_index))
        return false;
    Snapshot current;
    std::string error;
    return capture_snapshot(game, target, current, error, shared_index) && current.store == original.store &&
        current.table == original.table && current.entry == original.entry &&
        current.kit == original.kit && current.bodies == original.bodies &&
        current.pieces == original.pieces && current.data == original.data;
}

bool is_shared_resource(const isolation_profile::ResourceMapping &resource) noexcept {
    return resource.kit_id == 0 && (resource.type == 0xeac0b497876adedfULL ||
                                    resource.type == 0xcd4238c6a0c69e32ULL);
}

bool resource_belongs_to_target(const isolation_profile::ResourceMapping &resource,
                               const TargetKit &target) noexcept {
#if defined(UNIVERSAL_ISOLATION)
    if (resource.kit_id != target.id && !is_shared_resource(resource))
        return false;
    const auto required = active_profile.requirements_by_kit.find(target.id);
    return required != active_profile.requirements_by_kit.end() &&
        required->second.count({resource.type, resource.target}) != 0;
#elif defined(GENERIC_ISOLATION)
    if (resource.kit_id != target.id && !is_shared_resource(resource))
        return false;
    const auto &required_resources = isolation_profile::required_resources;
    for (const auto &required : required_resources) {
        if (required.kit_id == target.id && required.type == resource.type && required.target == resource.target)
            return true;
    }
    return false;
#else
    return resource.kit_id == target.id || is_shared_resource(resource);
#endif
}

bool build_candidate(const TargetKit &target, const Snapshot &snapshot, std::vector<uint8_t> &candidate,
                     size_t &changed, std::string &error) {
    changed = 0;
    if (!layout_matches(target, snapshot, error))
        return false;
#if defined(UNIVERSAL_ISOLATION)
    const auto mapping = mappings_by_kit.find(target.id);
    const auto *declared = mapping == mappings_by_kit.end() ? nullptr : mapping->second.declared;
    if (!declared || declared->references.size() != target.piece_count) {
        error = "target has no validated source resource metadata";
        return false;
    }
#endif
    candidate = snapshot.data;
    size_t changed_units = 0;
    for (size_t index = 0; index < target.piece_count; ++index) {
        const size_t offset = kit_size + target.body_count * body_size + index * piece_size;
        uint8_t *piece = candidate.data() + offset;
        const uint8_t *original_piece = snapshot.data.data() + offset;
        const auto &expected = target.pieces[index];
        if (get<uint64_t>(piece, 0) != expected.source_unit || get<uint32_t>(piece, 8) != expected.slot ||
            get<uint32_t>(piece, 12) != expected.piece_type || get<uint32_t>(piece, 16) != expected.weight ||
            piece[0x58] != expected.tone_variations) {
            error = "target piece metadata or source Unit differs at index " + std::to_string(index);
            return false;
        }
        // Slot1 is the default cape and remains untouched for every target.
        if (expected.slot == 1)
            continue;
        size_t unit_changes = 0;
        std::array<bool, piece_size / sizeof(uint64_t)> mapped_offsets{};
#if defined(UNIVERSAL_ISOLATION)
        for (const auto &field : mapping->second.fields) {
#else
        for (const auto &field : profile_fields()) {
#endif
            if (field.kit_id != target.id)
                continue;
            if (field.field_offset != 0 && (field.field_offset < 0x18 ||
                field.field_offset > 0x50 || field.field_offset % 8 != 0)) {
                error = "generated map contains a non-resource piece offset";
                return false;
            }
#if defined(UNIVERSAL_ISOLATION)
            const size_t resource_index = field.field_offset == 0 ? 0 : 1 + (field.field_offset - 0x18) / 8;
            if (declared->references[index][resource_index] != field.source)
                continue;
            if (get<uint64_t>(original_piece, field.field_offset) != field.source) {
                error = "planned source resource field differs from the validated profile at piece " + std::to_string(index);
                return false;
            }
#else
            if (get<uint64_t>(original_piece, field.field_offset) != field.source)
                continue;
#endif
            if (!field.source || !field.target || field.target == field.source ||
                mapped_offsets[field.field_offset / sizeof(uint64_t)]) {
                error = "generated map contains an empty, unchanged or ambiguous resource ID";
                return false;
            }
            const uint64_t expected_type = field.field_offset == 0 ?
                0xe0a48d0be9a7453fULL : 0xcd4238c6a0c69e32ULL;
            bool own_resource = false;
#if defined(UNIVERSAL_ISOLATION)
            const auto required = active_profile.requirements_by_kit.find(target.id);
            own_resource = required != active_profile.requirements_by_kit.end() &&
                required->second.count({expected_type, field.target}) != 0 &&
                (owned_mappings.count({target.id, expected_type, field.source, field.target}) != 0 ||
                 (expected_type == isolation_profile::texture_type &&
                  owned_mappings.count({0, expected_type, field.source, field.target}) != 0));
#else
            for (const auto &resource : profile_resources()) {
                if (resource_belongs_to_target(resource, target) && resource.type == expected_type &&
                    resource.source == field.source && resource.target == field.target) {
                    own_resource = true;
                    break;
                }
            }
#endif
            if (!own_resource) {
                error = "generated piece field has no matching target or shared resource";
                return false;
            }
            mapped_offsets[field.field_offset / sizeof(uint64_t)] = true;
            put(piece, field.field_offset, field.target);
            ++changed;
            unit_changes += field.field_offset == 0;
        }
        if (unit_changes != 1) {
            error = "every non-cape target piece must map to exactly one private Unit";
            return false;
        }
        changed_units += unit_changes;
    }
    if (changed_units != target.expected_unit_changes) {
        error = "private Unit count differs from the target specification";
        return false;
    }
    return true;
}

bool prepare_candidate(const TargetKit &target, const Snapshot &snapshot, TargetState &runtime,
                       std::string &error) {
    if (!runtime.cached_candidate.empty() && runtime.cached_source == snapshot.data)
        return true;
    runtime.cached_source.clear();
    runtime.cached_candidate.clear();
    if (!build_candidate(target, snapshot, runtime.cached_candidate, runtime.cached_changes, error)) {
        runtime.cached_candidate.clear();
        return false;
    }
    runtime.cached_source = snapshot.data;
    return true;
}

cm14_isolation::resource_state probe_active_resource(uintptr_t exe, uint64_t type, uint64_t name, HANDLE process) {
#if defined(UNIVERSAL_ISOLATION)
    if (native_layout_validated)
        return cm14_isolation::probe_validated_layout(exe, native_layout.application, type, name, process);
#endif
    return cm14_isolation::probe_resource(exe, type, name, process);
}

// A resource can be required by several targets in one poll. Reuse only the
// result from this poll; readiness is intentionally rechecked on the next poll
// and immediately before publication.
struct PollResourceCache {
    std::map<std::pair<uint64_t, uint64_t>, cm14_isolation::resource_state> states;

    template <class Probe>
    cm14_isolation::resource_state get(uintptr_t exe, uint64_t type, uint64_t name,
                                       HANDLE process, Probe probe) {
        const auto key = std::make_pair(type, name);
        const auto found = states.find(key);
        if (found != states.end())
            return found->second;
        const auto state = probe(exe, type, name, process);
        states.emplace(key, state);
        return state;
    }
};

template<class Probe = decltype(&probe_active_resource)>
bool private_resources_ready(uintptr_t exe, const TargetKit &target, std::string &error,
                             TargetState *waiting = nullptr, Probe probe = &probe_active_resource) {
    size_t ready = 0, total = 0;
    uint64_t first_type = 0, first_target = 0;
    const char *first_state = "ready";
    const auto inspect_resource = [&](uint64_t type, uint64_t target_id) {
        ++total;
        const auto state = probe(exe, type, target_id, GetCurrentProcess());
        if (state == cm14_isolation::resource_state::ready) {
            ++ready;
        } else if (!first_target) {
            first_type = type;
            first_target = target_id;
            first_state = cm14_isolation::resource_state_name(state);
            if (waiting) {
                waiting->waiting_type = type;
                waiting->waiting_resource = target_id;
            }
        }
    };
    // Retry the last unavailable dependency first, but never cache a ready result.
    if (waiting && waiting->waiting_resource)
        inspect_resource(waiting->waiting_type, waiting->waiting_resource);
#if defined(UNIVERSAL_ISOLATION)
    const auto required = active_profile.requirements_by_kit.find(target.id);
    if (required == active_profile.requirements_by_kit.end()) {
        error = "target has no validated resource dependencies; no config write";
        return false;
    }
    for (const auto &[type, target_id] : required->second) {
        if (first_target) break;
        inspect_resource(type, target_id);
    }
#else
    for (const auto &resource : profile_resources()) {
        if (first_target) break;
        if (resource.kit_id == 0 && !is_shared_resource(resource)) {
            error = "only materials and textures may use the shared resource owner; no config write";
            return false;
        }
        if (!resource_belongs_to_target(resource, target))
            continue;
        inspect_resource(resource.type, resource.target);
    }
#endif
    if (ready == total && ready > 0) {
        if (waiting) waiting->waiting_type = waiting->waiting_resource = 0;
        return true;
    }
    char details[256]{};
    std::snprintf(details, sizeof(details),
        "private resources checked_ready=%zu/%zu first_type=%016llx first_id=%016llx state=%s; "
        "load the target %s armor or helmet in the armory; no config write", ready, total,
        static_cast<unsigned long long>(first_type), static_cast<unsigned long long>(first_target), first_state,
        profile_label);
    error = details;
    return false;
}

bool writable_pointer(uintptr_t address) noexcept {
    MEMORY_BASIC_INFORMATION memory{};
    if (address % alignof(void *) != 0 ||
        VirtualQuery(reinterpret_cast<void *>(address), &memory, sizeof(memory)) != sizeof(memory) ||
        memory.State != MEM_COMMIT || (memory.Protect & (PAGE_GUARD | PAGE_NOACCESS)))
        return false;
    const DWORD protection = memory.Protect & 0xff;
    const uintptr_t end = reinterpret_cast<uintptr_t>(memory.BaseAddress) + memory.RegionSize;
    return address <= end && end - address >= sizeof(void *) &&
        (protection == PAGE_READWRITE || protection == PAGE_WRITECOPY);
}

bool publish_pointer(uintptr_t address, uintptr_t expected, uintptr_t desired) noexcept {
    if (!writable_pointer(address))
        return false;
    // SEH contains a page invalidation between VirtualQuery and the atomic operation.
    __try {
        return InterlockedCompareExchangePointer(reinterpret_cast<void *volatile *>(address),
            reinterpret_cast<void *>(desired), reinterpret_cast<void *>(expected)) == reinterpret_cast<void *>(expected);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

void poll_target(uintptr_t game, uintptr_t exe, const TargetKit &target,
                 TargetState &runtime, bool diagnostic, const KitIndex *shared_index = nullptr,
                 PollResourceCache *poll_resources = nullptr) {
    if (runtime.fatal_error)
        return;
    Snapshot snapshot;
    std::string error;
    if (!capture_snapshot(game, target, snapshot, error, shared_index)) {
        target_status(target, runtime, "[WAIT]", error);
        return;
    }
    for (size_t index = 0; index < runtime.publication_count; ++index) {
        if (runtime.publications[index].address != snapshot.kit)
            continue;
        if (snapshot.data != runtime.publications[index].expected) {
            runtime.fatal_error = true;
            target_status(target, runtime, "[FAILED]", "published target config changed; RESTART_REQUIRED; no further writes for this kit");
        } else {
            target_status(target, runtime, "[APPLIED]", std::string("private config active; switch away from this ") +
                profile_label + " item and back to rebuild appearance; RESTART_REQUIRED for removal");
        }
        return;
    }
    if (!prepare_candidate(target, snapshot, runtime, error)) {
        target_status(target, runtime, "[FAILED]", error + "; no config write");
        return;
    }
    if (poll_resources) {
        const auto cached_probe = [poll_resources](uintptr_t resource_exe, uint64_t type,
                                                   uint64_t name, HANDLE process) {
            return poll_resources->get(resource_exe, type, name, process, &probe_active_resource);
        };
        if (!private_resources_ready(exe, target, error, &runtime, cached_probe)) {
            target_status(target, runtime, "[WAIT]", error);
            return;
        }
    } else if (!private_resources_ready(exe, target, error, &runtime)) {
        target_status(target, runtime, "[WAIT]", error);
        return;
    }
    if (diagnostic) {
        target_status(target, runtime, "[READY]", "all target guards passed; DiagnosticOnly=1; no config write");
        return;
    }
    if (runtime.publication_count == publication_limit) {
        runtime.fatal_error = true;
        target_status(target, runtime, "[FAILED]", "configuration reload limit reached; RESTART_REQUIRED; no further writes for this kit");
        return;
    }
    auto candidate = runtime.cached_candidate;
    const size_t changed = runtime.cached_changes;
    auto *allocation = static_cast<uint8_t *>(VirtualAlloc(nullptr, candidate.size(), MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE));
    if (!allocation) {
        target_status(target, runtime, "[FAILED]", "cannot allocate independent target config; no config write");
        return;
    }
    const uintptr_t clone = reinterpret_cast<uintptr_t>(allocation);
    put(candidate.data(), 0x30, clone + kit_size);
    size_t piece_index = 0;
    for (size_t body_index = 0; body_index < target.body_count; ++body_index) {
        put(candidate.data(), kit_size + body_index * body_size + 8,
            clone + kit_size + target.body_count * body_size + piece_index * piece_size);
        piece_index += target.bodies[body_index].piece_count;
    }
    std::memcpy(allocation, candidate.data(), candidate.size());
    // The only game-owned write is one aligned pointer, after two complete source reads.
    if (!snapshot_unchanged(game, target, snapshot, shared_index) || !private_resources_ready(exe, target, error) ||
        !publish_pointer(snapshot.entry, snapshot.kit, clone)) {
        VirtualFree(allocation, 0, MEM_RELEASE);
        target_status(target, runtime, "[WAIT]", "source config or resource readiness changed before publication; no config published");
        return;
    }
    // Published storage may still be held by the game after a reload or add-on unload.
    // It is intentionally process-lifetime storage, bounded to 16 allocations per kit.
    runtime.publications[runtime.publication_count++] = {clone, std::move(candidate)};
    runtime.cached_source.clear();
    runtime.cached_candidate.clear();
    uintptr_t published = 0;
    if (!read_value(snapshot.entry, published) || published != clone) {
        target_status(target, runtime, "[WAIT]", "kit table changed immediately after publication; retained config allocation; retry after reload");
        return;
    }
    target_status(target, runtime, "[APPLIED]", "published private config with " + std::to_string(changed) +
        " resource fields; switch away from this " + profile_label + " item and back; RESTART_REQUIRED for removal");
}

void poll() {
    initialize_paths();
    if (fatal_error)
        return;
#if defined(UNIVERSAL_ISOLATION)
    if (!local_data_saved) {
        const auto observed_game = reinterpret_cast<uintptr_t>(GetModuleHandleW(L"game.dll"));
        uintptr_t observed_store = 0;
        uint32_t observed_count = 0;
        const bool known = observed_game && module_matches(observed_game, 0x6a86132e, 0x3a6b000);
        const bool ready = known && code_matches(observed_game) &&
            read_value(observed_game + kit_store_rva, observed_store) &&
            read_value(observed_store + 8, observed_count) && observed_count > 0;
        if (observed_game && (!known || ready)) {
            const auto now = GetTickCount64();
            if (last_local_attempt && now - last_local_attempt < 10000) return;
            last_local_attempt = now;
            ++local_attempts;
            try {
                std::string conflict;
                if (!no_legacy_addons(conflict)) throw std::runtime_error(conflict);
                std::array<wchar_t, 32768> observed_path{};
                const DWORD length = GetModuleFileNameW(reinterpret_cast<HMODULE>(observed_game),
                    observed_path.data(), static_cast<DWORD>(observed_path.size()));
                if (!length || length >= observed_path.size()) throw std::runtime_error("cannot locate loaded game.dll");
                auto report = armor_local_data::capture(GetCurrentProcess(), observed_game, observed_path.data());
                std::array<wchar_t, 32768> exe_path{};
                const auto exe_length = GetModuleFileNameW(nullptr, exe_path.data(), static_cast<DWORD>(exe_path.size()));
                if (!exe_length || exe_length >= exe_path.size()) throw std::runtime_error("cannot locate game executable");
                armor_native::attach_evidence(report, GetCurrentProcess(), observed_game,
                    reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr)), observed_path.data(), exe_path.data());
                report["snapshot_stage"] = "before_isolation";
                const auto path = std::filesystem::path(exe_path.data()).parent_path().parent_path() / L"ArmorIsolation.local-game.json";
                armor_local_data::save(path, report);
                local_data_saved = true;
                status("[LOCAL_DATA]", "exported ArmorIsolation.local-game.json in game root for the generator");
            } catch (const std::exception &error) {
                status("[LOCAL_DATA]", std::string("cannot save local observation: ") + error.what());
                if (local_attempts < 6) return;
                local_data_saved = true;
            }
        }
    }
    if (!initialize_profiles() || active_profile.targets.empty())
        return;
    std::string conflict;
    if (!no_legacy_addons(conflict)) {
        fatal_error = true;
        status("[FAILED]", conflict);
        return;
    }
#endif
    const int enabled = GetPrivateProfileIntW(config_section, L"Enabled", 1, config_path.c_str());
    const int diagnostic = GetPrivateProfileIntW(config_section, L"DiagnosticOnly", 0, config_path.c_str());
    if ((enabled != 0 && enabled != 1) || (diagnostic != 0 && diagnostic != 1)) {
        status("[FAILED]", "Enabled and DiagnosticOnly must be 0 or 1");
        return;
    }
#if defined(UNIVERSAL_ISOLATION)
    active_enabled.store(enabled != 0, std::memory_order_relaxed);
    active_diagnostic.store(diagnostic != 0, std::memory_order_relaxed);
    active_options_known.store(true, std::memory_order_relaxed);
#endif
    if (!enabled) {
        bool published = false;
        for (const auto &runtime : target_states)
            published = published || runtime.publication_count != 0;
        status("[WAIT]", published ? "disabled after publication; RESTART_REQUIRED to restore original config" :
                                   "disabled by configuration; no config write");
        return;
    }
    const uintptr_t game = reinterpret_cast<uintptr_t>(GetModuleHandleW(L"game.dll"));
    const uintptr_t exe = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
    if (!game) {
        status("[WAIT]", "game.dll is not loaded");
        return;
    }
#if defined(UNIVERSAL_ISOLATION)
    if (!native_layout_validated && (active_profile.adaptive ||
        !module_matches(game, 0x6a86132e, 0x3a6b000) || !module_matches(exe, 0x6a85c636, 0x39f1000))) {
        const uint64_t now = GetTickCount64();
        if (last_native_attempt && now - last_native_attempt < 10000) return;
        last_native_attempt = now;
        ++native_attempts;
        try {
            std::array<wchar_t, 32768> game_path{}, exe_path{};
            const auto game_length = GetModuleFileNameW(reinterpret_cast<HMODULE>(game), game_path.data(), static_cast<DWORD>(game_path.size()));
            const auto exe_length = GetModuleFileNameW(nullptr, exe_path.data(), static_cast<DWORD>(exe_path.size()));
            armor_local_data::require(game_length && game_length < game_path.size() && exe_length && exe_length < exe_path.size(),
                                      "cannot locate current modules");
            const auto game_hash = armor_local_data::file_sha256(game_path.data());
            const auto exe_hash = armor_local_data::file_sha256(exe_path.data());
            armor_local_data::require(!active_profile.adaptive ||
                (game_hash == active_profile.expected_game_dll_sha256 && exe_hash == active_profile.compatibility.at("exe_sha256")),
                "adaptive package belongs to another game build; regenerate against the current game");
            native_layout = armor_native::discover(GetCurrentProcess(), game, exe);
            armor_local_data::require(game_hash == armor_local_data::file_sha256(game_path.data()) &&
                exe_hash == armor_local_data::file_sha256(exe_path.data()), "game files changed during native validation");
            kit_store_rva = native_layout.kit_store;
            native_layout_validated = true;
            status("[ADAPTED]", "native layout signatures and resource manager validated; source guards remain mandatory");
        } catch (const std::exception &error) {
            fatal_error = native_attempts >= 6;
            status(fatal_error ? "FAILED" : "WAIT", std::string("automatic compatibility not ready or unsupported: ") + error.what());
            return;
        }
    }
    if (!native_layout_validated && !code_matches(game)) {
        status("[WAIT]", "verified armor selection code is not available; no config write");
        return;
    }
#else
    if (!module_matches(game, 0x6a86132e, 0x3a6b000) || !module_matches(exe, 0x6a85c636, 0x39f1000)) {
        fatal_error = true;
        status("[FAILED]", "unsupported game.dll or EXE version; no config write");
        return;
    }
    if (!code_matches(game)) {
        status("[WAIT]", "verified armor selection code is not available; no config write");
        return;
    }
#endif
    // Each target has its own readiness, status and atomic pointer publication.
    KitIndex kit_index;
    std::string index_error;
    if (!build_kit_index(game, kit_index, index_error)) {
        status("[WAIT]", index_error);
        return;
    }
    PollResourceCache poll_resources;
    for (size_t index = 0; index < std::size(profile_targets()); ++index)
        poll_target(game, exe, profile_targets()[index], target_states[index], diagnostic != 0,
                    &kit_index, &poll_resources);
}

void on_present(reshade::api::command_queue *, reshade::api::swapchain *, const reshade::api::rect *,
                const reshade::api::rect *, uint32_t, const reshade::api::rect *) noexcept {
    if (callback_active.test_and_set(std::memory_order_acquire))
        return;
    const uint64_t now = GetTickCount64();
#if defined(UNIVERSAL_ISOLATION)
    const bool requested = ui_poll_requested.exchange(false, std::memory_order_acq_rel);
#else
    const bool requested = false;
#endif
    if (requested || now - last_poll >= 1000) {
        last_poll = now;
        try {
            poll();
        } catch (...) {
            fatal_error = true;
            OutputDebugStringA(profile_label);
            OutputDebugStringA(" isolation FAILED: unexpected C++ exception; no further writes\n");
        }
#if defined(UNIVERSAL_ISOLATION)
        publish_ui_snapshot();
#endif
    }
    callback_active.clear(std::memory_order_release);
}

#if defined(UNIVERSAL_ISOLATION)
bool persist_option(const wchar_t *key, bool value) {
    initialize_paths();
    if (config_path.empty())
        return false;
    // The INI stays the single source of truth: the next poll reads the new value and the
    // publication path is unchanged. Nothing here can restore an already published config.
    return WritePrivateProfileStringW(config_section, key, value ? L"1" : L"0", config_path.c_str()) != FALSE;
}

// Overlay wording only. The status and log text itself is diagnostic evidence and stays in the
// language it is written to ArmorIsolation.log, so log parsing and the documented format do not
// change with the selected UI language.
enum class UiLanguage { english, chinese };

struct UiStrings {
    const char *subtitle, *options, *enabled, *enabled_help, *diagnostic, *diagnostic_help,
        *language, *status, *check_now, *updated, *waiting_first, *counts, *summary,
        *options_unknown, *rejected, *adapted, *targets_empty, *copy_status, *copied_status,
        *status_footer, *write_failed, *target_type, *target_structure, *target_runtime;
};

constexpr UiStrings ui_strings_english{
    "read-only status; options are stored in ArmorIsolation.ini beside this add-on",
    "Options",
    "Enabled",
    "Turning this off only stops future publications. It cannot restore a configuration that was "
        "already published; that still needs a full game restart.",
    "Diagnostic only",
    "Diagnostic only checks every guard and dependency and reports READY without writing to the game process.",
    "Language",
    "Status",
    "Check now",
    "updated %.1f s ago",
    "waiting for the first poll",
    "packages %u   targets %u   resources %u",
    "waiting %u   ready %u   applied %u   failed %u   not checked %u",
    "ArmorIsolation.ini has not been read yet in this session",
    "the configuration group was rejected; see the log below",
    "native layout was re-discovered for this game build",
    "no targets loaded; install an isolation package and restart the game",
    "Copy status",
    "copied %zu target rows to the clipboard",
    "Full history: ArmorIsolation.log. Published configurations need a game restart to be removed.",
    "Cannot write ArmorIsolation.ini, so the change was not applied. Check that the game folder is writable.",
    "type %s   passive %u", "bodies %u   pieces %u   private Units %u   required resources %u",
    "publications %u"
};

constexpr UiStrings ui_strings_chinese{
    "只读状态；选项保存在插件旁的 ArmorIsolation.ini",
    "选项",
    "启用",
    "关闭只停止后续发布，无法恢复已经发布的配置；恢复原状仍需完整重启游戏。",
    "仅诊断",
    "只校验全部守卫与依赖并报告 READY，不写入游戏进程。",
    "语言",
    "状态",
    "立即检查",
    "更新于 %.1f 秒前",
    "等待首次轮询",
    "配置包 %u   目标 %u   资源 %u",
    "等待 %u   就绪 %u   已应用 %u   失败 %u   未检查 %u",
    "本次会话尚未读取 ArmorIsolation.ini",
    "配置组被拒绝；详见下方日志",
    "已为该游戏版本重新发现原生布局",
    "没有载入目标；请安装隔离包后重启游戏",
    "复制状态",
    "已复制 %zu 条目标状态到剪贴板",
    "完整历史见 ArmorIsolation.log。已发布的配置需重启游戏才能移除。",
    "无法写入 ArmorIsolation.ini，改动未生效。请检查游戏目录是否可写。",
    "类型 %s   被动 %u", "Body %u   Piece %u   私有 Unit %u   依赖资源 %u",
    "已发布 %u 次"
};

// ReShade owns the ImGui context and exposes no way to add a font, so Chinese text is only
// legible when the user points ReShade's own font setting at a font with CJK glyphs.
constexpr char ui_cjk_warning[] =
    "The ReShade font has no CJK glyphs, so Chinese text renders as empty boxes. Set Font in "
    "ReShade's [STYLE] settings to a CJK font (for example C:\\Windows\\Fonts\\msyh.ttc) and then "
    "reload the overlay. / 当前 ReShade 字体不含中文字形，中文会显示为方框：请在 ReShade 的 "
    "[STYLE] 设置里把 Font 指向中文字体（例如 C:\\Windows\\Fonts\\msyh.ttc）后重新加载覆盖层。";

UiLanguage ui_language = UiLanguage::english;
bool ui_language_known = false;

bool font_has_cjk_glyphs() {
    ImFont *font = ImGui::GetFont();
    return font != nullptr && font->FindGlyphNoFallback(static_cast<ImWchar>(0x4E2D)) != nullptr;
}

bool persist_language(UiLanguage language) {
    initialize_paths();
    if (config_path.empty())
        return false;
    return WritePrivateProfileStringW(config_section, L"Language",
        language == UiLanguage::chinese ? L"zh" : L"en", config_path.c_str()) != FALSE;
}

void initialize_language() {
    initialize_paths();
    std::wstring configured;
    if (!config_path.empty()) {
        wchar_t value[16]{};
        GetPrivateProfileStringW(config_section, L"Language", L"", value,
            static_cast<DWORD>(std::size(value)), config_path.c_str());
        configured = value;
    }
    if (configured == L"zh")
        ui_language = UiLanguage::chinese;
    else if (configured == L"en")
        ui_language = UiLanguage::english;
    else
        ui_language = font_has_cjk_glyphs() ? UiLanguage::chinese : UiLanguage::english;
    ui_language_known = true;
}

void on_overlay(reshade::api::effect_runtime *) {
    if (!ui_language_known)
        initialize_language();
    const bool cjk = font_has_cjk_glyphs();
    const UiStrings *text = ui_language == UiLanguage::chinese ? &ui_strings_chinese : &ui_strings_english;
    const UiSnapshot &snapshot = ui_snapshots[ui_published.load(std::memory_order_acquire) & 1u];
    bool enabled = snapshot.enabled, diagnostic = snapshot.diagnostic_only;
    const uint64_t now = GetTickCount64();
    static uint64_t copy_deadline = 0, write_failed_deadline = 0;
    static size_t copy_count = 0;
    ImGui::SetNextWindowSize(ImVec2(660.0f, 620.0f), ImGuiCond_FirstUseEver);
    if (!ImGui::Begin(overlay_title, nullptr, 0)) {
        ImGui::End();
        return;
    }
    ImGui::TextUnformatted(profile_name, nullptr);
    ImGui::TextDisabled("%s", text->subtitle);
    if (!cjk && ui_language == UiLanguage::chinese)
        ImGui::TextColored(ImVec4(1.0f, 0.55f, 0.2f, 1.0f), "%s", ui_cjk_warning);
    ImGui::SeparatorText(text->options);
    // Options take effect on the next frame: the new value is stored right here and an immediate
    // poll is queued, so nothing waits for the one-second interval or a game restart.
    if (ImGui::Checkbox(text->enabled, &enabled)) {
        if (persist_option(L"Enabled", enabled)) {
            active_enabled.store(enabled, std::memory_order_relaxed);
            active_options_known.store(true, std::memory_order_relaxed);
            ui_poll_requested.store(true, std::memory_order_release);
        } else {
            write_failed_deadline = now + 5000;
        }
    }
    ImGui::TextWrapped("%s", text->enabled_help);
    if (ImGui::Checkbox(text->diagnostic, &diagnostic)) {
        if (persist_option(L"DiagnosticOnly", diagnostic)) {
            active_diagnostic.store(diagnostic, std::memory_order_relaxed);
            active_options_known.store(true, std::memory_order_relaxed);
            ui_poll_requested.store(true, std::memory_order_release);
        } else {
            write_failed_deadline = now + 5000;
        }
    }
    ImGui::TextWrapped("%s", text->diagnostic_help);
    ImGui::TextUnformatted(text->language, nullptr);
    ImGui::SameLine(0.0f, 12.0f);
    int language = ui_language == UiLanguage::chinese ? 1 : 0;
    if (ImGui::RadioButton("English", &language, 0) && ui_language != UiLanguage::english) {
        ui_language = UiLanguage::english;
        if (!persist_language(ui_language))
            write_failed_deadline = now + 5000;
    }
    ImGui::SameLine(0.0f, 12.0f);
    // Without CJK glyphs the Chinese label itself would be unreadable, so it falls back to ASCII.
    if (ImGui::RadioButton(cjk ? "简体中文" : "Chinese", &language, 1) && ui_language != UiLanguage::chinese) {
        ui_language = UiLanguage::chinese;
        if (!persist_language(ui_language))
            write_failed_deadline = now + 5000;
    }
    if (write_failed_deadline > now)
        ImGui::TextColored(ImVec4(1.0f, 0.4f, 0.4f, 1.0f), "%s", text->write_failed);
    ImGui::SeparatorText(text->status);
    if (ImGui::Button(text->check_now, ImVec2(130.0f, 0.0f)))
        ui_poll_requested.store(true, std::memory_order_release);
    ImGui::SameLine(0.0f, 12.0f);
    if (snapshot.updated_ms)
        ImGui::TextDisabled(text->updated, (now - snapshot.updated_ms) / 1000.0);
    else
        ImGui::TextDisabled("%s", text->waiting_first);
    ImGui::Text(text->counts, snapshot.package_count, snapshot.target_count, snapshot.resource_count);
    if (snapshot.target_count)
        ImGui::ProgressBar(static_cast<float>(snapshot.ready_count + snapshot.applied_count) /
            static_cast<float>(snapshot.target_count), ImVec2(-1.0f, 0.0f), nullptr);
    ImGui::Text(text->summary, snapshot.waiting_count, snapshot.ready_count, snapshot.applied_count,
        snapshot.failed_count, snapshot.pending_count);
    if (!snapshot.options_known)
        ImGui::TextDisabled("%s", text->options_unknown);
    if (snapshot.profiles_failed)
        ImGui::TextColored(ImVec4(1.0f, 0.4f, 0.4f, 1.0f), "%s", text->rejected);
    if (snapshot.native_adapted)
        ImGui::TextDisabled("%s", text->adapted);
    ImGui::TextWrapped("[%s] %s", snapshot.global_state.c_str(), snapshot.global_detail.c_str());
    // One status view only: the per-target rows below carry the complete reason text, and the
    // full history stays in ArmorIsolation.log.
    if (ImGui::Button(text->copy_status, ImVec2(140.0f, 0.0f))) {
        std::string all;
        for (const auto &row : snapshot.targets) {
            char prefix[256]{};
            std::snprintf(prefix, sizeof(prefix),
                "%08x  [%s]  %s  type=%s passive=%u bodies=%u pieces=%u units=%u resources=%u publications=%u  ",
                row.kit_id, row.state.c_str(), row.package.c_str(), row.type == 1 ? "helmet" : "armor",
                row.passive, row.body_count, row.piece_count, row.unit_changes, row.required_resources,
                row.publications);
            all += prefix;
            all += row.detail;
            all += "\r\n";
        }
        ImGui::SetClipboardText(all.c_str());
        copy_deadline = now + 3000;
        copy_count = snapshot.targets.size();
    }
    if (copy_deadline > now) {
        ImGui::SameLine(0.0f, 12.0f);
        ImGui::TextDisabled(text->copied_status, copy_count);
    }
    const ImVec2 available = ImGui::GetContentRegionAvail();
    const float list_height = available.y > 80.0f ? available.y - 20.0f : 80.0f;
    if (ImGui::BeginChild("armor-isolation-targets", ImVec2(0.0f, list_height), 0, 0)) {
        if (snapshot.targets.empty())
            ImGui::TextDisabled("%s", text->targets_empty);
        for (const auto &row : snapshot.targets) {
            const bool chinese_ui = ui_language == UiLanguage::chinese && cjk;
            const char *kind = row.type == 1 ? (chinese_ui ? "头盔" : "Helmet") :
                (chinese_ui ? "体甲" : "Armor");
            ImGui::PushID(static_cast<int>(row.kit_id));
            const bool expanded = ImGui::TreeNodeEx("target", ImGuiTreeNodeFlags_SpanAvailWidth,
                "%08x  [%s]  %s", row.kit_id, row.state.c_str(), row.package.c_str());
            if (expanded) {
                ImGui::Text(text->target_type, kind, row.passive);
                ImGui::Text(text->target_structure, row.body_count, row.piece_count,
                    row.unit_changes, row.required_resources);
                ImGui::Text(text->target_runtime, row.publications);
                ImGui::TextWrapped("%s", row.detail.c_str());
                ImGui::TreePop();
            }
            ImGui::PopID();
        }
    }
    ImGui::EndChild();
    ImGui::TextDisabled("%s", text->status_footer);
    ImGui::End();
}
#endif
} // namespace

#ifndef CM14_ISOLATION_TEST
extern "C" __declspec(dllexport) const char *NAME = profile_name;
extern "C" __declspec(dllexport) const char *DESCRIPTION = profile_description;

BOOL APIENTRY DllMain(HMODULE handle, DWORD reason, LPVOID reserved) {
    if (reason == DLL_PROCESS_ATTACH) {
        module_handle = handle;
        DisableThreadLibraryCalls(handle);
        if (!reshade::register_addon(handle))
            return FALSE;
        reshade::register_event<reshade::addon_event::present>(on_present);
#if defined(UNIVERSAL_ISOLATION)
        reshade::register_overlay(overlay_title, on_overlay);
#endif
    } else if (reason == DLL_PROCESS_DETACH && reserved == nullptr) {
#if defined(UNIVERSAL_ISOLATION)
        reshade::unregister_overlay(overlay_title, on_overlay);
#endif
        reshade::unregister_event<reshade::addon_event::present>(on_present);
        reshade::unregister_addon(handle);
        OutputDebugStringA(profile_label);
        OutputDebugStringA(" isolation unloaded; RESTART_REQUIRED to restore original config\n");
    }
    return TRUE;
}
#endif
