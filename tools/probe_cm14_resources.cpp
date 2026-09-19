#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>
#include <Psapi.h>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <iterator>
#if defined(GENERIC_ISOLATION)
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
constexpr uint64_t unit_type = 0xe0a48d0be9a7453f;
constexpr uint64_t texture_type = 0xcd4238c6a0c69e32;
constexpr uint64_t material_type = 0xeac0b497876adedf;
struct TargetStatus {
    size_t ready = 0, resources = 0, found = 0;
    size_t original = 0, private_units = 0, wrong_owner_private = 0;
};
constexpr size_t no_target = std::size(isolation_profile::targets);

bool is_shared_resource(const isolation_profile::ResourceMapping &resource) {
    return resource.kit_id == 0 && (resource.type == texture_type || resource.type == material_type);
}

bool resource_belongs_to_target(const isolation_profile::ResourceMapping &resource, uint32_t id) {
    if (resource.kit_id != id && !is_shared_resource(resource))
        return false;
#ifdef GENERIC_ISOLATION
    for (const auto &required : isolation_profile::required_resources)
        if (required.kit_id == id && required.type == resource.type && required.target == resource.target)
            return true;
    return false;
#else
    return true;
#endif
}

size_t target_index(uint32_t id) {
    for (size_t i = 0; i < std::size(isolation_profile::targets); ++i)
        if (isolation_profile::targets[i].id == id) return i;
    return no_target;
}
} // namespace

int main(int argc, char **argv) {
    if (argc != 2) {
#if defined(GENERIC_ISOLATION)
        std::fprintf(stderr, "Usage: probe_generic_resources.exe PID (read-only)\n");
#elif defined(B01_ISOLATION)
        std::fprintf(stderr, "Usage: probe_b01_resources.exe PID (read-only)\n");
#else
        std::fprintf(stderr, "Usage: probe_cm14_resources.exe PID (read-only)\n");
#endif
        return 2;
    }
    char *end = nullptr;
    const unsigned long pid = std::strtoul(argv[1], &end, 10);
    if (!pid || !end || *end) return 2;
    const HANDLE process = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, FALSE, pid);
    if (!process) {
        std::fprintf(stderr, "OpenProcess failed: %lu\n", GetLastError());
        return 2;
    }
    std::array<HMODULE, 2048> modules{};
    DWORD needed = 0;
    uintptr_t exe = 0, game = 0;
    if (EnumProcessModulesEx(process, modules.data(), sizeof(modules), &needed, LIST_MODULES_ALL) &&
        needed <= sizeof(modules)) {
        for (size_t i = 0; i < needed / sizeof(HMODULE); ++i) {
            wchar_t name[512]{};
            if (!GetModuleBaseNameW(process, modules[i], name, 512)) continue;
            if (_wcsicmp(name, L"helldivers2.exe") == 0) exe = reinterpret_cast<uintptr_t>(modules[i]);
            if (_wcsicmp(name, L"game.dll") == 0) game = reinterpret_cast<uintptr_t>(modules[i]);
        }
    }
    if (!exe || !game) {
        std::fprintf(stderr, "HD2 executable and game.dll were not found\n");
        CloseHandle(process);
        return 2;
    }
    const auto known = cm14_isolation::probe_resource(exe, 0xe0a48d0be9a7453f,
                                                      0x3c33cf10a26cbb3e, process);
    std::printf("BASELINE_CAPE %s\n", cm14_isolation::resource_state_name(known));
    size_t ready = 0, shared_ready = 0, shared_total = 0;
    std::array<TargetStatus, std::size(isolation_profile::targets)> statuses{};
    for (const auto &resource : isolation_profile::resources) {
        const auto state = cm14_isolation::probe_resource(exe, resource.type, resource.target, process);
        ready += state == cm14_isolation::resource_state::ready;
        const auto owner = target_index(resource.kit_id);
        const bool shared = is_shared_resource(resource);
        if (owner == no_target && !shared) {
            std::fprintf(stderr, "Unknown resource owner: %08x\n", resource.kit_id);
            CloseHandle(process);
            return 2;
        }
        if (shared) {
            ++shared_total;
            shared_ready += state == cm14_isolation::resource_state::ready;
        }
        for (size_t i = 0; i < statuses.size(); ++i) {
            if (!resource_belongs_to_target(resource, isolation_profile::targets[i].id)) continue;
            ++statuses[i].resources;
            statuses[i].ready += state == cm14_isolation::resource_state::ready;
        }
        std::printf("RESOURCE owner=%08x %016llx %016llx %s\n", resource.kit_id,
                    static_cast<unsigned long long>(resource.type),
                    static_cast<unsigned long long>(resource.target),
                    cm14_isolation::resource_state_name(state));
    }
    std::printf("PRIVATE_READY %zu/%zu\n", ready, std::size(isolation_profile::resources));
    if (shared_total)
        std::printf("SHARED_READY %zu/%zu\n", shared_ready, shared_total);
    for (size_t i = 0; i < statuses.size(); ++i)
        std::printf("TARGET_READY kit=%08x %zu/%zu\n", isolation_profile::targets[i].id,
                    statuses[i].ready, statuses[i].resources);

    using cm14_isolation::resource_probe_detail::read;
    uintptr_t store = 0, table = 0;
    uint32_t count = 0;
    size_t target_original = 0, target_private = 0, other_private = 0, target_count = 0;
    size_t wrong_owner_private = 0;
    constexpr uint32_t reference_offsets[] = {0, 0x18, 0x20, 0x28, 0x30,
                                              0x38, 0x40, 0x48, 0x50};
    bool complete = read(process, game + 0x276c220, store) && read(process, store, table) &&
        read(process, store + 8, count) && count == 402;
    for (uint32_t i = 0; complete && i < count; ++i) {
        uintptr_t kit = 0, bodies = 0;
        uint32_t id = 0, body_count = 0;
        complete = read(process, table + i * 8, kit) && read(process, kit, id) &&
            read(process, kit + 0x30, bodies) && read(process, kit + 0x38, body_count) && body_count <= 16;
        if (!complete) break;
        const auto owner = target_index(id);
        if (owner != no_target) {
            ++target_count;
            ++statuses[owner].found;
        }
        for (uint32_t b = 0; complete && b < body_count; ++b) {
            uintptr_t pieces = 0;
            uint32_t piece_count = 0;
            complete = read(process, bodies + b * 24 + 8, pieces) &&
                read(process, bodies + b * 24 + 16, piece_count) && piece_count <= 128;
            for (uint32_t p = 0; complete && p < piece_count; ++p) {
                for (const auto offset : reference_offsets) {
                    uint64_t reference = 0;
                    complete = read(process, pieces + p * 96 + offset, reference);
                    if (!complete) break;
                    const auto type = offset == 0 ? unit_type : texture_type;
                    for (const auto &resource : isolation_profile::resources) {
                        if (resource.type != type) continue;
                        if (owner != no_target && resource.kit_id == id && offset == 0) {
                            statuses[owner].original += reference == resource.source;
                            statuses[owner].private_units += reference == resource.target;
                        }
                        if (reference != resource.target) continue;
                        if (owner == no_target) {
                            ++other_private;
                        } else if (!resource_belongs_to_target(resource, id)) {
                            ++wrong_owner_private;
                            ++statuses[owner].wrong_owner_private;
                        }
                    }
                }
            }
        }
    }
    CloseHandle(process);
    bool targets_complete = true;
    for (size_t i = 0; i < statuses.size(); ++i) {
        const auto &status = statuses[i];
        const auto &target = isolation_profile::targets[i];
        target_original += status.original;
        target_private += status.private_units;
        targets_complete &= status.found == 1 &&
            status.original + status.private_units == target.expected_unit_changes;
        std::printf("TARGET_CONFIG kit=%08x found=%zu original=%zu private=%zu expected=%zu "
                    "wrong_owner_private=%zu\n", target.id, status.found, status.original,
                    status.private_units, target.expected_unit_changes, status.wrong_owner_private);
    }
    std::printf("CONFIG_SCAN %s target_count=%zu original=%zu private=%zu other_private=%zu "
                "wrong_owner_private=%zu\n",
                complete ? "complete" : "incomplete", target_count,
                target_original, target_private, other_private, wrong_owner_private);
    return complete && targets_complete && other_private == 0 && wrong_owner_private == 0 ? 0 : 3;
}
