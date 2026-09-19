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
    }
    return snapshot;
}

bool test_target(const TargetKit &target) {
    const Snapshot original = fixture(target);
    const auto source_bytes = original.data;
    const size_t piece_base = kit_size + target.body_count * body_size;
    std::vector<uint8_t> candidate;
    std::string error;
    size_t changed = 0;
    if (!build_candidate(target, original, candidate, changed, error) ||
        changed != target.expected_unit_changes || original.data != source_bytes)
        return false;
    for (size_t index = 0; index < candidate.size(); ++index) {
        const bool unit_field = index >= piece_base && (index - piece_base) % piece_size < 8;
        if (!unit_field && candidate[index] != original.data[index])
            return false;
    }
    for (size_t index = 0; index < target.piece_count; ++index) {
        const size_t offset = piece_base + index * piece_size;
        const auto &expected = target.pieces[index];
        if (expected.slot == 1) {
            if (std::memcmp(candidate.data() + offset, original.data.data() + offset, piece_size))
                return false;
            continue;
        }
        const auto new_id = get<uint64_t>(candidate.data(), offset);
        bool own_mapping = false;
        for (const auto &field : cm14_isolation::piece_fields) {
            if (field.kit_id == target.id && field.field_offset == 0 &&
                field.source == expected.source_unit && field.target == new_id)
                own_mapping = true;
        }
        if (!own_mapping || new_id == expected.source_unit)
            return false;
    }
    // Guards must reject changes to both kit metadata and each piece's semantics.
    const size_t guarded_offsets[] = {0, 0x20, 0x28, 0x1c, 0x38, kit_size, kit_size + 16,
                                     piece_base, piece_base + 8, piece_base + 12,
                                     piece_base + 16, piece_base + 0x58};
    for (const size_t offset : guarded_offsets) {
        Snapshot incompatible = original;
        incompatible.data[offset] ^= 0x40;
        if (build_candidate(target, incompatible, candidate, changed, error))
            return false;
    }
    Snapshot truncated = original;
    truncated.data.pop_back();
    if (build_candidate(target, truncated, candidate, changed, error))
        return false;

    // Matching source IDs under a different Kit ID must never consume this kit's map.
    TargetKit unrelated = target;
    unrelated.id = 0x12345678;
    Snapshot different_kit = original;
    put(different_kit.data.data(), 0, unrelated.id);
    if (build_candidate(unrelated, different_kit, candidate, changed, error))
        return false;
    return true;
}

bool test_generated_namespaces() {
    for (size_t index = 0; index < std::size(cm14_isolation::resources); ++index) {
        const auto &resource = cm14_isolation::resources[index];
        bool known_kit = false;
        for (const auto &target : cm14_isolation::targets)
            known_kit = known_kit || target.id == resource.kit_id;
        if (!known_kit || !resource.source || !resource.target || resource.source == resource.target)
            return false;
        for (size_t other = index + 1; other < std::size(cm14_isolation::resources); ++other) {
            if (resource.target == cm14_isolation::resources[other].target)
                return false;
        }
    }
    for (const auto &field : cm14_isolation::piece_fields) {
        size_t matches = 0;
        for (const auto &resource : cm14_isolation::resources) {
            if (resource.kit_id == field.kit_id && resource.source == field.source &&
                resource.target == field.target)
                ++matches;
        }
        if (matches != 1)
            return false;
    }
    return true;
}

bool test_independent_publication() {
    const auto &armor = cm14_isolation::targets[0];
    const auto &helmet = cm14_isolation::targets[1];
    Snapshot armor_source = fixture(armor), helmet_source = fixture(helmet);
    uint32_t unrelated_id = 0;
    std::array<uintptr_t, 402> table{};
    table.fill(reinterpret_cast<uintptr_t>(&unrelated_id));
    const uintptr_t armor_address = reinterpret_cast<uintptr_t>(armor_source.data.data());
    const uintptr_t helmet_address = reinterpret_cast<uintptr_t>(helmet_source.data.data());
    table[5] = armor_address;
    table[17] = helmet_address;
    struct { uintptr_t table; uint32_t count; } store{reinterpret_cast<uintptr_t>(table.data()), 402};
    uintptr_t store_address = reinterpret_cast<uintptr_t>(&store);
    const uintptr_t game = reinterpret_cast<uintptr_t>(&store_address) - kit_store_rva;
    Snapshot armor_snapshot, helmet_snapshot;
    std::string error;
    if (!capture_snapshot(game, armor, armor_snapshot, error) ||
        !capture_snapshot(game, helmet, helmet_snapshot, error) ||
        !snapshot_unchanged(game, armor, armor_snapshot) ||
        !snapshot_unchanged(game, helmet, helmet_snapshot))
        return false;
    std::vector<uint8_t> armor_candidate, helmet_candidate;
    size_t changed = 0;
    if (!build_candidate(armor, armor_snapshot, armor_candidate, changed, error) || changed != 26 ||
        !build_candidate(helmet, helmet_snapshot, helmet_candidate, changed, error) || changed != 1)
        return false;
    const uintptr_t private_armor = reinterpret_cast<uintptr_t>(armor_candidate.data());
    const uintptr_t private_helmet = reinterpret_cast<uintptr_t>(helmet_candidate.data());
    if (!publish_pointer(armor_snapshot.entry, armor_address, private_armor) ||
        table[5] != private_armor || table[17] != helmet_address ||
        !snapshot_unchanged(game, helmet, helmet_snapshot))
        return false;
    if (publish_pointer(armor_snapshot.entry, armor_address, private_helmet) ||
        table[5] != private_armor || !publish_pointer(helmet_snapshot.entry, helmet_address, private_helmet))
        return false;
    for (size_t index = 0; index < table.size(); ++index) {
        const uintptr_t expected = index == 5 ? private_armor : index == 17 ? private_helmet :
            reinterpret_cast<uintptr_t>(&unrelated_id);
        if (table[index] != expected)
            return false;
    }
    if (publish_pointer(0x123, 0, 1))
        return false;
    store.count = 401;
    if (capture_snapshot(game, armor, armor_snapshot, error))
        return false;
    return true;
}

int main() {
    if (std::size(cm14_isolation::targets) != 2 || cm14_isolation::targets[0].id != 0x38aa207d ||
        cm14_isolation::targets[1].id != 0x203f720c)
        return 1;
    if (!test_generated_namespaces()) return 2;
    for (const auto &target : cm14_isolation::targets) {
        if (!test_target(target)) return 3;
    }
    if (!test_independent_publication()) return 4;
    std::puts("CM14_ADDON_TEST_OK: armor 26 + helmet 1 private references, cape/non-reference bytes preserved, kit/layout guards, isolated namespaces and independent pointer CAS");
    return 0;
}
