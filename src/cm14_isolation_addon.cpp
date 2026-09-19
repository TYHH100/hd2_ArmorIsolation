#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>
#if defined(UNIVERSAL_ISOLATION)
#include <TlHelp32.h>
#include <algorithm>
#include <cwctype>
#include <filesystem>
#endif
#include <reshade.hpp>
#include <array>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <iterator>
#include <string>
#include <utility>
#include <vector>

#if defined(UNIVERSAL_ISOLATION)
#include "armor_runtime_profile.hpp"
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
constexpr uintptr_t kit_store_rva = 0x276c220;
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
};

HMODULE module_handle = nullptr;
std::atomic_flag callback_active = ATOMIC_FLAG_INIT;
#if defined(UNIVERSAL_ISOLATION)
isolation_profile::Profile active_profile;
std::vector<TargetState> target_states;
bool profiles_initialized = false;
std::filesystem::path profiles_directory;
#else
std::array<TargetState, std::size(isolation_profile::targets)> target_states{};
#endif
uint64_t last_poll = 0;
std::wstring log_path, config_path;
std::string last_status;
bool fatal_error = false;

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
    previous = message;
    initialize_paths();
    FILE *file = nullptr;
    if (log_path.empty() || _wfopen_s(&file, log_path.c_str(), L"ab") != 0)
        return;
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
    std::error_code filesystem_error;
    if (profiles_directory.empty()) {
        fatal_error = true;
        status("FAILED", "cannot locate the add-on configuration directory; RESTART_REQUIRED; no config write");
        return false;
    }
    const bool directory_exists = std::filesystem::exists(profiles_directory, filesystem_error);
    if (filesystem_error) {
        fatal_error = true;
        status("FAILED", "cannot inspect ArmorIsolation directory; RESTART_REQUIRED; no config write");
        return false;
    }
    if (!directory_exists) {
        status("EMPTY", "ArmorIsolation directory is absent; add package JSON files and restart the game; no config write");
        return true;
    }
    std::string error;
    if (!isolation_profile::load_directory(profiles_directory, active_profile, error)) {
        fatal_error = true;
        status("FAILED", "package configuration group rejected: " + error +
            "; RESTART_REQUIRED; no config write");
        return false;
    }
    target_states.resize(active_profile.targets.size());
    if (target_states.empty()) {
        status("EMPTY", "no package JSON files in ArmorIsolation; restart after adding configuration; no config write");
    } else {
        status("CONFIG", "validated packages=" + std::to_string(active_profile.package_ids.size()) +
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

bool capture_snapshot(uintptr_t game, const TargetKit &target, Snapshot &result, std::string &error) {
    result.data.resize(clone_size(target));
    result.pieces.resize(target.body_count);
    if (!read_value(game + kit_store_rva, result.store) || !result.store ||
        !read_value(result.store, result.table) ||
        !read_value(result.store + 8, result.count) || !result.table || result.count != 402) {
        error = "kit store is not initialized or count differs from 402";
        return false;
    }
    std::vector<uintptr_t> pointers(result.count);
    if (!read_bytes(result.table, pointers.data(), pointers.size() * sizeof(uintptr_t))) {
        error = "kit pointer array is unreadable";
        return false;
    }
    size_t matches = 0;
    for (size_t index = 0; index < pointers.size(); ++index) {
        uint32_t id = 0;
        if (!read_value(pointers[index], id)) {
            error = "kit array changed while reading";
            return false;
        }
        if (id == target.id) {
            ++matches;
            result.kit = pointers[index];
            result.entry = result.table + index * sizeof(uintptr_t);
        }
    }
    if (matches != 1 || !read_bytes(result.kit, result.data.data(), kit_size)) {
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

bool snapshot_unchanged(uintptr_t game, const TargetKit &target, const Snapshot &original) {
    Snapshot current;
    std::string error;
    return capture_snapshot(game, target, current, error) && current.store == original.store &&
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
    const isolation_profile::TargetStorage *declared = nullptr;
    for (size_t index = 0; index < active_profile.targets.size(); ++index)
        if (active_profile.targets[index].id == target.id) declared = active_profile.storage[index].get();
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
        for (const auto &field : profile_fields()) {
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
            for (const auto &resource : profile_resources()) {
                if (resource_belongs_to_target(resource, target) && resource.type == expected_type &&
                    resource.source == field.source && resource.target == field.target) {
                    own_resource = true;
                    break;
                }
            }
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

bool private_resources_ready(uintptr_t exe, const TargetKit &target, std::string &error) {
    size_t ready = 0, total = 0;
    uint64_t first_type = 0, first_target = 0;
    const char *first_state = "ready";
    const auto inspect_resource = [&](uint64_t type, uint64_t target_id) {
        ++total;
        const auto state = cm14_isolation::probe_resource(exe, type, target_id);
        if (state == cm14_isolation::resource_state::ready) {
            ++ready;
        } else if (!first_target) {
            first_type = type;
            first_target = target_id;
            first_state = cm14_isolation::resource_state_name(state);
        }
    };
#if defined(UNIVERSAL_ISOLATION)
    const auto required = active_profile.requirements_by_kit.find(target.id);
    if (required == active_profile.requirements_by_kit.end()) {
        error = "target has no validated resource dependencies; no config write";
        return false;
    }
    for (const auto &[type, target_id] : required->second)
        inspect_resource(type, target_id);
#else
    for (const auto &resource : profile_resources()) {
        if (resource.kit_id == 0 && !is_shared_resource(resource)) {
            error = "only materials and textures may use the shared resource owner; no config write";
            return false;
        }
        if (!resource_belongs_to_target(resource, target))
            continue;
        inspect_resource(resource.type, resource.target);
    }
#endif
    if (ready == total && ready > 0)
        return true;
    char details[256]{};
    std::snprintf(details, sizeof(details),
        "private resources ready=%zu/%zu first_type=%016llx first_id=%016llx state=%s; "
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
                 TargetState &runtime, bool diagnostic) {
    if (runtime.fatal_error)
        return;
    Snapshot snapshot;
    std::string error;
    if (!capture_snapshot(game, target, snapshot, error)) {
        target_status(target, runtime, "WAIT", error);
        return;
    }
    for (size_t index = 0; index < runtime.publication_count; ++index) {
        if (runtime.publications[index].address != snapshot.kit)
            continue;
        if (snapshot.data != runtime.publications[index].expected) {
            runtime.fatal_error = true;
            target_status(target, runtime, "FAILED", "published target config changed; RESTART_REQUIRED; no further writes for this kit");
        } else {
            target_status(target, runtime, "APPLIED", std::string("private config active; switch away from this ") +
                profile_label + " item and back to rebuild appearance; RESTART_REQUIRED for removal");
        }
        return;
    }
    std::vector<uint8_t> candidate;
    size_t changed = 0;
    if (!build_candidate(target, snapshot, candidate, changed, error)) {
        target_status(target, runtime, "FAILED", error + "; no config write");
        return;
    }
    if (!private_resources_ready(exe, target, error)) {
        target_status(target, runtime, "WAIT", error);
        return;
    }
    if (diagnostic) {
        target_status(target, runtime, "READY", "all target guards passed; DiagnosticOnly=1; no config write");
        return;
    }
    if (runtime.publication_count == publication_limit) {
        runtime.fatal_error = true;
        target_status(target, runtime, "FAILED", "configuration reload limit reached; RESTART_REQUIRED; no further writes for this kit");
        return;
    }
    auto *allocation = static_cast<uint8_t *>(VirtualAlloc(nullptr, candidate.size(), MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE));
    if (!allocation) {
        target_status(target, runtime, "FAILED", "cannot allocate independent target config; no config write");
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
    if (!snapshot_unchanged(game, target, snapshot) || !private_resources_ready(exe, target, error) ||
        !publish_pointer(snapshot.entry, snapshot.kit, clone)) {
        VirtualFree(allocation, 0, MEM_RELEASE);
        target_status(target, runtime, "WAIT", "source config or resource readiness changed before publication; no config published");
        return;
    }
    // Published storage may still be held by the game after a reload or add-on unload.
    // It is intentionally process-lifetime storage, bounded to 16 allocations per kit.
    runtime.publications[runtime.publication_count++] = {clone, std::move(candidate)};
    uintptr_t published = 0;
    if (!read_value(snapshot.entry, published) || published != clone) {
        target_status(target, runtime, "WAIT", "kit table changed immediately after publication; retained config allocation; retry after reload");
        return;
    }
    target_status(target, runtime, "APPLIED", "published private config with " + std::to_string(changed) +
        " resource fields; switch away from this " + profile_label + " item and back; RESTART_REQUIRED for removal");
}

void poll() {
    initialize_paths();
    if (fatal_error)
        return;
#if defined(UNIVERSAL_ISOLATION)
    if (!initialize_profiles() || active_profile.targets.empty())
        return;
    std::string conflict;
    if (!no_legacy_addons(conflict)) {
        fatal_error = true;
        status("FAILED", conflict);
        return;
    }
#endif
    const int enabled = GetPrivateProfileIntW(config_section, L"Enabled", 1, config_path.c_str());
    const int diagnostic = GetPrivateProfileIntW(config_section, L"DiagnosticOnly", 0, config_path.c_str());
    if ((enabled != 0 && enabled != 1) || (diagnostic != 0 && diagnostic != 1)) {
        status("FAILED", "Enabled and DiagnosticOnly must be 0 or 1");
        return;
    }
    if (!enabled) {
        bool published = false;
        for (const auto &runtime : target_states)
            published = published || runtime.publication_count != 0;
        status("WAIT", published ? "disabled after publication; RESTART_REQUIRED to restore original config" :
                                   "disabled by configuration; no config write");
        return;
    }
    const uintptr_t game = reinterpret_cast<uintptr_t>(GetModuleHandleW(L"game.dll"));
    const uintptr_t exe = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
    if (!game) {
        status("WAIT", "game.dll is not loaded");
        return;
    }
    if (!module_matches(game, 0x6a86132e, 0x3a6b000) || !module_matches(exe, 0x6a85c636, 0x39f1000)) {
        fatal_error = true;
        status("FAILED", "unsupported game.dll or EXE version; no config write");
        return;
    }
    if (!code_matches(game)) {
        status("WAIT", "verified armor selection code is not available; no config write");
        return;
    }
    // Each target has its own readiness, status and atomic pointer publication.
    for (size_t index = 0; index < std::size(profile_targets()); ++index)
        poll_target(game, exe, profile_targets()[index], target_states[index], diagnostic != 0);
}

void on_present(reshade::api::command_queue *, reshade::api::swapchain *, const reshade::api::rect *,
                const reshade::api::rect *, uint32_t, const reshade::api::rect *) noexcept {
    if (callback_active.test_and_set(std::memory_order_acquire))
        return;
    const uint64_t now = GetTickCount64();
    if (now - last_poll >= 1000) {
        last_poll = now;
        try {
            poll();
        } catch (...) {
            fatal_error = true;
            OutputDebugStringA(profile_label);
            OutputDebugStringA(" isolation FAILED: unexpected C++ exception; no further writes\n");
        }
    }
    callback_active.clear(std::memory_order_release);
}
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
    } else if (reason == DLL_PROCESS_DETACH && reserved == nullptr) {
        reshade::unregister_event<reshade::addon_event::present>(on_present);
        reshade::unregister_addon(handle);
        OutputDebugStringA(profile_label);
        OutputDebugStringA(" isolation unloaded; RESTART_REQUIRED to restore original config\n");
    }
    return TRUE;
}
#endif
