#pragma once

#include <Windows.h>
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <initializer_list>

namespace cm14_isolation {

enum class resource_state { ready, pending, missing, unreadable, incompatible, redirected };

inline const char *resource_state_name(resource_state state) noexcept
{
    switch (state) {
    case resource_state::ready: return "ready";
    case resource_state::pending: return "pending";
    case resource_state::missing: return "missing";
    case resource_state::unreadable: return "unreadable";
    case resource_state::incompatible: return "incompatible";
    case resource_state::redirected: return "redirected";
    }
    return "unknown";
}

namespace resource_probe_detail {

constexpr std::uint32_t end_index = 0x7fffffff;
constexpr std::uint32_t empty_index = 0xfffffffe;
constexpr std::uint32_t pending_resource = 0xfafef0f1;
constexpr std::uint32_t max_slots = 1u << 20;
constexpr std::uint32_t max_chain = 256;

inline bool readable_range(std::uintptr_t address, std::size_t size) noexcept
{
    constexpr std::uintptr_t last = 0x00007ffffffeffffULL;
    return size != 0 && size <= 4096 && address >= 0x10000 &&
           address <= last && size - 1 <= last - address;
}

template <class T>
inline bool read(HANDLE process, std::uintptr_t address, T &value) noexcept
{
    static_assert(sizeof(T) <= 4096, "Only bounded structure reads are permitted");
    SIZE_T done = 0;
    return readable_range(address, sizeof(T)) &&
           ReadProcessMemory(process, reinterpret_cast<LPCVOID>(address), &value,
                             sizeof(T), &done) != FALSE && done == sizeof(T);
}

template <class T, std::size_t N>
inline T field(const std::array<std::uint8_t, N> &bytes, std::size_t offset) noexcept
{
    T result{};
    if (offset <= N && sizeof(T) <= N - offset)
        std::memcpy(&result, bytes.data() + offset, sizeof(T));
    return result;
}

struct map_header {
    std::uint32_t slots;
    std::uint32_t capacity;
    std::uintptr_t entries;
    std::uintptr_t allocator;
    std::uint32_t count;
    std::uint32_t buckets;
};
static_assert(sizeof(map_header) == 0x20 && sizeof(void *) == 8, "x64 only");

inline bool valid_map(const map_header &map, std::size_t stride) noexcept
{
    return map.slots <= map.capacity && map.capacity <= max_slots &&
           map.count <= map.slots && map.buckets <= map.slots &&
           (map.count == 0 || (map.buckets != 0 &&
            readable_range(map.entries, stride) &&
            map.slots <= (0x00007ffffffeffffULL - map.entries) / stride));
}

struct found_entry {
    std::uintptr_t address{};
    std::uint64_t value{};
    std::uint32_t next{};
};

// This follows a single bounded hash chain, never a whole resource table.
inline resource_state find(HANDLE process, const map_header &map, std::uint64_t key,
                           std::size_t stride, std::size_t next_offset,
                           found_entry &found) noexcept
{
    if (!valid_map(map, stride) || next_offset + 4 > stride || stride > 0x318)
        return resource_state::incompatible;
    if (map.count == 0)
        return resource_state::missing;
    std::uint32_t index = static_cast<std::uint32_t>(key >> 32) % map.buckets;
    for (std::uint32_t step = 0; step < max_chain; ++step) {
        if (index >= map.slots)
            return resource_state::pending;
        const auto address = map.entries + static_cast<std::uintptr_t>(index) * stride;
        std::array<std::uint64_t, 2> pair{};
        std::uint32_t next = 0;
        if (!read(process, address, pair) || !read(process, address + next_offset, next))
            return resource_state::unreadable;
        if (next == empty_index)
            return resource_state::missing;
        if (next > end_index)
            return resource_state::pending;
        if (pair[0] == key) {
            found = {address, pair[1], next};
            return resource_state::ready;
        }
        if (next == end_index)
            return resource_state::missing;
        index = next;
    }
    return resource_state::pending;
}

struct snapshot {
    std::uintptr_t application{};
    std::uintptr_t manager{};
    map_header types{};
    std::uintptr_t type_address{};
    std::array<std::uint8_t, 0xd0> type{};
    std::uintptr_t entry_address{};
    std::array<std::uint8_t, 0x18> entry{};
    std::uintptr_t record_address{};
    std::array<std::uint8_t, 0x20> record{};
};

inline resource_state compatible_image(HANDLE process, std::uintptr_t base) noexcept
{
    IMAGE_DOS_HEADER dos{};
    if (!read(process, base, dos))
        return resource_state::unreadable;
    if (dos.e_magic != IMAGE_DOS_SIGNATURE || dos.e_lfanew < 0x40 || dos.e_lfanew > 0x1000)
        return resource_state::incompatible;
    IMAGE_NT_HEADERS64 nt{};
    if (!read(process, base + static_cast<std::uint32_t>(dos.e_lfanew), nt))
        return resource_state::unreadable;
    if (nt.Signature != IMAGE_NT_SIGNATURE || nt.FileHeader.Machine != IMAGE_FILE_MACHINE_AMD64 ||
        nt.OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC ||
        nt.FileHeader.TimeDateStamp != 0x6a85c636 || nt.OptionalHeader.SizeOfImage != 0x039f1000)
        return resource_state::incompatible;
    return resource_state::ready;
}

inline resource_state lookup(HANDLE process, std::uintptr_t base, std::uint64_t type_id,
                             std::uint64_t name, snapshot &out, std::uintptr_t application_rva = 0x1a141c8) noexcept
{
    if (!read(process, base + application_rva, out.application))
        return resource_state::unreadable;
    if (out.application == 0)
        return resource_state::pending;
    if (!readable_range(out.application, 0x400))
        return resource_state::unreadable;
    if (!read(process, out.application + 0x3f8, out.manager))
        return resource_state::unreadable;
    if (out.manager == 0)
        return resource_state::pending;
    if (!readable_range(out.manager, 0x320))
        return resource_state::unreadable;
    if (!read(process, out.manager + 0x2e8, out.types))
        return resource_state::unreadable;
    found_entry type_match{};
    auto state = find(process, out.types, type_id, 0xd0, 0xc8, type_match);
    if (state != resource_state::ready)
        return state;
    out.type_address = type_match.address;
    if (!read(process, out.type_address, out.type))
        return resource_state::unreadable;
    if (field<std::uint64_t>(out.type, 0) != type_id)
        return resource_state::pending;

    // Engine 0x5f0c30 can redirect names before lookup. Private IDs must not redirect.
    for (const auto map_offset : {std::size_t{0x70}, std::size_t{0x98}}) {
        const auto map = field<map_header>(out.type, map_offset);
        found_entry redirect{};
        const bool conditional = map_offset == 0x98;
        state = find(process, map, name, conditional ? 0x318 : 0x18,
                     conditional ? 0x310 : 0x10, redirect);
        if (state == resource_state::ready)
            return resource_state::redirected;
        if (state != resource_state::missing)
            return state;
    }

    const auto names = field<map_header>(out.type, 0x20);
    found_entry match{};
    state = find(process, names, name, 0x18, 0x10, match);
    if (state != resource_state::ready)
        return state;
    out.entry_address = match.address;
    if (!read(process, out.entry_address, out.entry))
        return resource_state::unreadable;
    if (field<std::uint64_t>(out.entry, 0) != name ||
        field<std::uint64_t>(out.entry, 8) != match.value ||
        field<std::uint32_t>(out.entry, 0x10) != match.next)
        return resource_state::pending;

    const auto index = field<std::uint32_t>(out.entry, 8);
    // Same-build ResourceManager::online (EXE 0x5f0fc0) checks this sentinel.
    if (index == pending_resource)
        return resource_state::pending;
    const auto record_count = field<std::uint32_t>(out.type, 8);
    const auto record_capacity = field<std::uint32_t>(out.type, 0xc);
    const auto records = field<std::uintptr_t>(out.type, 0x10);
    if (record_count > record_capacity || record_capacity > max_slots || index >= record_count ||
        !readable_range(records, 0xa0) ||
        record_capacity > (0x00007ffffffeffffULL - records) / 0xa0)
        return resource_state::pending;
    out.record_address = records + static_cast<std::uintptr_t>(index) * 0xa0;
    if (!read(process, out.record_address, out.record))
        return resource_state::unreadable;
    const auto resource = field<std::uintptr_t>(out.record, 0);
    if (resource == 0)
        return resource_state::pending;
    std::uint8_t probe = 0;
    if (!read(process, resource, probe))
        return resource_state::unreadable;
    return resource_state::ready;
}

inline bool same_snapshot(const snapshot &a, const snapshot &b) noexcept
{
    return a.application == b.application && a.manager == b.manager &&
           std::memcmp(&a.types, &b.types, sizeof(map_header)) == 0 &&
           a.type_address == b.type_address && a.type == b.type &&
           a.entry_address == b.entry_address && a.entry == b.entry &&
           a.record_address == b.record_address && a.record == b.record;
}

} // namespace resource_probe_detail

// Only callers that have independently validated native layout may use relocated globals.
inline resource_state probe_validated_layout(std::uintptr_t exe_base, std::uintptr_t application_rva,
                                            std::uint64_t type, std::uint64_t name,
                                            HANDLE process = GetCurrentProcess()) noexcept {
    using namespace resource_probe_detail;
    if (!type || !name || !application_rva) return resource_state::missing;
    snapshot first{}, second{};
    const auto before = lookup(process, exe_base, type, name, first, application_rva);
    if (before == resource_state::incompatible || before == resource_state::unreadable) return before;
    const auto after = lookup(process, exe_base, type, name, second, application_rva);
    return before == after && same_snapshot(first, second) ? after : resource_state::pending;
}

// Observational only: stable reads do not lock or retain engine resources.
// A supplied read-only process handle lets a CLI test exactly the addon code.
inline resource_state probe_resource(std::uintptr_t exe_base, std::uint64_t type,
                                     std::uint64_t name,
                                     HANDLE process = GetCurrentProcess()) noexcept
{
    using namespace resource_probe_detail;
    if (type == 0 || name == 0)
        return resource_state::missing;
    const auto build = compatible_image(process, exe_base);
    if (build != resource_state::ready)
        return build;
    snapshot first{}, second{};
    const auto before = lookup(process, exe_base, type, name, first);
    if (before == resource_state::incompatible || before == resource_state::unreadable)
        return before;
    const auto after = lookup(process, exe_base, type, name, second);
    if (before != after || !same_snapshot(first, second))
        return resource_state::pending;
    return after;
}

inline bool resource_present(std::uintptr_t exe_base, std::uint64_t type,
                             std::uint64_t name,
                             HANDLE process = GetCurrentProcess()) noexcept
{
    return probe_resource(exe_base, type, name, process) == resource_state::ready;
}

} // namespace cm14_isolation
