#define CM14_ISOLATION_TEST
#include "../src/cm14_isolation_addon.cpp"

Snapshot fixture(const TargetKit &target) {
    Snapshot snapshot;
    snapshot.data.resize(clone_size(target));
    for (size_t index = 0; index < snapshot.data.size(); ++index)
        snapshot.data[index] = static_cast<uint8_t>(index % 251);
    auto *kit = snapshot.data.data();
    put(kit, 0, target.id);
    put(kit, 0x20, target.archive);
    put(kit, 0x28, target.type);
    put(kit, 0x1c, target.passive);
    put<uint32_t>(kit, 0x38, static_cast<uint32_t>(target.body_count));
    put(kit, 0x30, reinterpret_cast<uintptr_t>(kit + kit_size));
    const size_t piece_base = kit_size + target.body_count * body_size;
    size_t piece_index = 0;
    for (size_t index = 0; index < target.body_count; ++index) {
        auto *body = kit + kit_size + index * body_size;
        put(body, 0, target.bodies[index].body_type);
        put(body, 16, target.bodies[index].piece_count);
        put(body, 8, reinterpret_cast<uintptr_t>(kit + piece_base + piece_index * piece_size));
        piece_index += target.bodies[index].piece_count;
    }
    for (size_t index = 0; index < target.piece_count; ++index) {
        auto *piece = kit + piece_base + index * piece_size;
        const auto &expected = target.pieces[index];
        put(piece, 0, expected.source_unit);
        put(piece, 8, expected.slot);
        put(piece, 12, expected.piece_type);
        put(piece, 16, expected.weight);
        piece[0x58] = static_cast<uint8_t>(expected.tone_variations);
        for (const auto &field : isolation_profile::piece_fields)
            if (field.kit_id == target.id && field.field_offset != 0)
                put(piece, field.field_offset, field.source);
    }
    return snapshot;
}

bool test_target(const TargetKit &target) {
    const Snapshot original = fixture(target);
    const auto source_bytes = original.data;
    const size_t piece_base = kit_size + target.body_count * body_size;
    std::vector<uint8_t> candidate;
    std::vector<bool> permitted(original.data.size());
    std::string error;
    size_t changed = 0, expected_changes = 0, unit_changes = 0;
    if (!build_candidate(target, original, candidate, changed, error) || original.data != source_bytes)
        return false;
    for (size_t index = 0; index < target.piece_count; ++index) {
        const size_t offset = piece_base + index * piece_size;
        const auto &expected = target.pieces[index];
        if (expected.slot == 1) {
            if (std::memcmp(candidate.data() + offset, original.data.data() + offset, piece_size)) return false;
            continue;
        }
        size_t matched_units = 0;
        for (const auto &field : isolation_profile::piece_fields) {
            if (field.kit_id != target.id ||
                get<uint64_t>(original.data.data(), offset + field.field_offset) != field.source)
                continue;
            if (get<uint64_t>(candidate.data(), offset + field.field_offset) != field.target) return false;
            for (size_t byte = 0; byte < 8; ++byte) permitted[offset + field.field_offset + byte] = true;
            ++expected_changes;
            matched_units += field.field_offset == 0;
        }
        if (matched_units != 1) return false;
        unit_changes += matched_units;
    }
    if (changed != expected_changes || unit_changes != target.expected_unit_changes) return false;
    for (size_t index = 0; index < candidate.size(); ++index)
        if (!permitted[index] && candidate[index] != original.data[index]) return false;
    const size_t guarded_offsets[] = {0, 0x20, 0x28, 0x1c, 0x38, kit_size, kit_size + 16,
                                     piece_base, piece_base + 8, piece_base + 12,
                                     piece_base + 16, piece_base + 0x58};
    for (const size_t offset : guarded_offsets) {
        Snapshot incompatible = original;
        incompatible.data[offset] ^= 0x40;
        if (build_candidate(target, incompatible, candidate, changed, error)) return false;
    }
    Snapshot truncated = original;
    truncated.data.pop_back();
    if (build_candidate(target, truncated, candidate, changed, error)) return false;
    TargetKit unrelated = target;
    unrelated.id = 0;
    Snapshot different_kit = original;
    put(different_kit.data.data(), 0, unrelated.id);
    return !build_candidate(unrelated, different_kit, candidate, changed, error);
}

bool test_profile() {
    if (std::size(isolation_profile::targets) == 0 || std::size(isolation_profile::targets) > 402) return false;
    for (size_t index = 0; index < std::size(isolation_profile::targets); ++index) {
        const auto &target = isolation_profile::targets[index];
        if (!target.id || !target.body_count || !target.piece_count || !target.expected_unit_changes) return false;
        for (size_t other = index + 1; other < std::size(isolation_profile::targets); ++other)
            if (target.id == isolation_profile::targets[other].id) return false;
    }
    for (size_t index = 0; index < std::size(isolation_profile::resources); ++index) {
        const auto &resource = isolation_profile::resources[index];
        if (!resource.source || !resource.target || resource.source == resource.target) return false;
        size_t owners = 0;
        for (const auto &target : isolation_profile::targets) owners += resource_belongs_to_target(resource, target);
        if (!owners || (!is_shared_resource(resource) && owners != 1)) return false;
        if (!is_shared_resource(resource) && resource.type != 0xe0a48d0be9a7453fULL) return false;
        for (size_t other = index + 1; other < std::size(isolation_profile::resources); ++other)
            if (resource.target == isolation_profile::resources[other].target) return false;
    }
    for (size_t index = 0; index < std::size(isolation_profile::required_resources); ++index) {
        const auto &required = isolation_profile::required_resources[index];
        size_t matching_resources = 0, matching_targets = 0;
        for (const auto &target : isolation_profile::targets) matching_targets += target.id == required.kit_id;
        for (const auto &resource : isolation_profile::resources)
            matching_resources += resource.type == required.type && resource.target == required.target &&
                (resource.kit_id == required.kit_id || is_shared_resource(resource));
        if (matching_resources != 1 || matching_targets != 1) return false;
        for (size_t other = index + 1; other < std::size(isolation_profile::required_resources); ++other) {
            const auto &b = isolation_profile::required_resources[other];
            if (required.kit_id == b.kit_id && required.type == b.type && required.target == b.target) return false;
        }
    }
    for (const auto &field : isolation_profile::piece_fields) {
        size_t matches = 0;
        if (field.field_offset != 0 &&
            (field.field_offset < 0x18 || field.field_offset > 0x50 || field.field_offset % 8)) return false;
        const auto type = field.field_offset == 0 ? 0xe0a48d0be9a7453fULL : 0xcd4238c6a0c69e32ULL;
        for (const auto &target : isolation_profile::targets) {
            if (target.id != field.kit_id) continue;
            for (const auto &resource : isolation_profile::resources)
                matches += resource_belongs_to_target(resource, target) && resource.type == type &&
                    resource.source == field.source && resource.target == field.target;
        }
        if (matches != 1) return false;
    }
    isolation_profile::ResourceMapping unneeded{0, 0xcd4238c6a0c69e32ULL, 1, 0};
    for (const auto &target : isolation_profile::targets)
        if (resource_belongs_to_target(unneeded, target)) return false;
    return true;
}

bool test_independent_publication() {
    constexpr size_t target_count = std::size(isolation_profile::targets);
    std::array<Snapshot, target_count> sources{}, snapshots{};
    std::array<std::vector<uint8_t>, target_count> candidates{};
    uint32_t unrelated_id = 0;
    std::array<uintptr_t, 402> table{};
    table.fill(reinterpret_cast<uintptr_t>(&unrelated_id));
    for (size_t index = 0; index < target_count; ++index) {
        sources[index] = fixture(isolation_profile::targets[index]);
        table[index] = reinterpret_cast<uintptr_t>(sources[index].data.data());
    }
    const auto original_table = table;
    struct { uintptr_t table; uint32_t count; } store{reinterpret_cast<uintptr_t>(table.data()), 402};
    uintptr_t store_address = reinterpret_cast<uintptr_t>(&store);
    const uintptr_t game = reinterpret_cast<uintptr_t>(&store_address) - kit_store_rva;
    std::string error;
    for (size_t index = 0; index < target_count; ++index) {
        size_t changed = 0;
        const auto &target = isolation_profile::targets[index];
        if (!capture_snapshot(game, target, snapshots[index], error) ||
            !snapshot_unchanged(game, target, snapshots[index]) ||
            !build_candidate(target, snapshots[index], candidates[index], changed, error)) return false;
    }
    auto expected_table = original_table;
    for (size_t index = 0; index < target_count; ++index) {
        const uintptr_t candidate = reinterpret_cast<uintptr_t>(candidates[index].data());
        if (!publish_pointer(snapshots[index].entry, original_table[index], candidate)) return false;
        expected_table[index] = candidate;
        if (table != expected_table || publish_pointer(snapshots[index].entry, original_table[index], 0)) return false;
        for (size_t pending = index + 1; pending < target_count; ++pending)
            if (!snapshot_unchanged(game, isolation_profile::targets[pending], snapshots[pending])) return false;
        if (sources[index].data != snapshots[index].data) return false;
    }
    if (publish_pointer(0x123, 0, 1)) return false;
    store.count = 401;
    return !capture_snapshot(game, isolation_profile::targets[0], snapshots[0], error);
}

int main() {
    if (!test_profile()) return 1;
    for (const auto &target : isolation_profile::targets)
        if (!test_target(target)) return 2;
    if (!test_independent_publication()) return 3;
    std::printf("GENERIC_ADDON_TEST_OK: %zu targets, %zu resources; typed dependencies, metadata/cape guards and independent pointer CAS\n",
                std::size(isolation_profile::targets), std::size(isolation_profile::resources));
    return 0;
}
