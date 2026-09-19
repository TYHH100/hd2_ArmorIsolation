#define CM14_ISOLATION_TEST
#include "../src/cm14_isolation_addon.cpp"
#include <fstream>
#include <stdexcept>

#define REQUIRE(condition) do { if (!(condition)) throw std::runtime_error("assertion failed at line " + std::to_string(__LINE__)); } while (false)

namespace {
using json = nlohmann::json;

std::string hex_id(uint64_t value, unsigned width = 16) {
    char text[32]{};
    std::snprintf(text, sizeof(text), "%0*llx", width, static_cast<unsigned long long>(value));
    return text;
}

struct TemporaryProfiles {
    std::filesystem::path directory = std::filesystem::temp_directory_path() /
        ("hd2-universal-test-" + std::to_string(GetCurrentProcessId()) + "-" + std::to_string(GetTickCount64()));
    TemporaryProfiles() { REQUIRE(std::filesystem::create_directory(directory)); }
    ~TemporaryProfiles() { std::error_code ignored; std::filesystem::remove_all(directory, ignored); }
};

json piece(uint32_t slot, uint64_t source_unit) {
    return {{"slot", slot}, {"type", 0}, {"weight", 1}, {"tone_variations", 0},
        {"resources", {{"unit", hex_id(source_unit)}, {"material_lut", hex_id(0x10)},
            {"pattern_lut", hex_id(0)}, {"cape_lut", hex_id(0)}, {"cape_gradient", hex_id(0)},
            {"cape_nac", hex_id(0)}, {"decal_scalar_fields", hex_id(0)}, {"base_data", hex_id(0)},
            {"decal_sheet", hex_id(0)}}}};
}

json package(unsigned index) {
    const std::string id = hex_id(index, 8), package_id = hex_id(index, 24);
    const std::string unit = hex_id(index), private_unit = hex_id((0x100ULL + index) << 32);
    const std::string texture = hex_id(0x10), private_texture = hex_id((0x200ULL + index) << 32);
    const std::string material = hex_id(0x20), private_material = hex_id((0x300ULL + index) << 32);
    auto pieces = json::array();
    if (index == 1) pieces.push_back(piece(1, 0x50));
    pieces.push_back(piece(index == 1 ? 2 : 0, index));
    return {{"schema", universal_isolation::runtime_schema}, {"package_id", package_id},
        {"expected_game_dll_sha256", universal_isolation::expected_game_dll_sha256},
        {"expected_game_version", universal_isolation::expected_game_version},
        {"selected_kit_metadata", json::array({{{"id", id}, {"archive", hex_id(0x80 + index)},
            {"type", index == 1 ? 0 : 1}, {"passive", 0},
            {"bodies", json::array({{{"type", 3}, {"pieces", pieces}}})}}})},
        {"mapping", json::array({
            {{"kit", id}, {"type", hex_id(universal_isolation::unit_type)}, {"source", unit}, {"target", private_unit}},
            {{"kit", "00000000"}, {"type", hex_id(universal_isolation::texture_type)}, {"source", texture}, {"target", private_texture}},
            {{"kit", "00000000"}, {"type", hex_id(universal_isolation::material_type)}, {"source", material}, {"target", private_material}}})},
        {"piece_fields", json::array({{{"kit", id}, {"offset", 0}, {"source", unit}, {"target", private_unit}},
            {{"kit", id}, {"offset", 0x18}, {"source", texture}, {"target", private_texture}}})},
        {"required_resources", json::array({{{"kit", id}, {"type", hex_id(universal_isolation::unit_type)}, {"target", private_unit}},
            {{"kit", id}, {"type", hex_id(universal_isolation::texture_type)}, {"target", private_texture}},
            {{"kit", id}, {"type", hex_id(universal_isolation::material_type)}, {"target", private_material}}})}};
}

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
        auto *data = kit + piece_base + index * piece_size;
        const auto &expected = target.pieces[index];
        put(data, 0, expected.source_unit);
        put(data, 8, expected.slot);
        put(data, 12, expected.piece_type);
        put(data, 16, expected.weight);
        data[0x58] = static_cast<uint8_t>(expected.tone_variations);
        for (const auto &field : profile_fields())
            if (field.kit_id == target.id && field.field_offset)
                put(data, field.field_offset, field.source);
    }
    return snapshot;
}

void test_target(const TargetKit &target) {
    const Snapshot source = fixture(target);
    const auto unchanged = source.data;
    const size_t piece_base = kit_size + target.body_count * body_size;
    std::vector<uint8_t> candidate;
    std::vector<bool> permitted(source.data.size());
    std::string error;
    size_t changed = 0, expected_changes = 0;
    REQUIRE(build_candidate(target, source, candidate, changed, error));
    REQUIRE(source.data == unchanged);
    size_t first_non_cape = 0;
    for (size_t index = 0; index < target.piece_count; ++index) {
        const size_t offset = piece_base + index * piece_size;
        if (target.pieces[index].slot == 1) {
            REQUIRE(std::memcmp(candidate.data() + offset, source.data.data() + offset, piece_size) == 0);
            continue;
        }
        if (!first_non_cape) first_non_cape = offset;
        for (const auto &field : profile_fields()) {
            if (field.kit_id != target.id || get<uint64_t>(source.data.data(), offset + field.field_offset) != field.source)
                continue;
            REQUIRE(get<uint64_t>(candidate.data(), offset + field.field_offset) == field.target);
            for (size_t byte = 0; byte < 8; ++byte) permitted[offset + field.field_offset + byte] = true;
            ++expected_changes;
        }
    }
    REQUIRE(changed == expected_changes && changed == 2);
    for (size_t index = 0; index < candidate.size(); ++index)
        REQUIRE(permitted[index] || candidate[index] == source.data[index]);
    const size_t guarded[] = {0, 0x20, 0x28, 0x1c, 0x38, kit_size, kit_size + 16,
        first_non_cape, first_non_cape + 8, first_non_cape + 12, first_non_cape + 16,
        first_non_cape + 0x18, first_non_cape + 0x58};
    for (size_t offset : guarded) {
        Snapshot stale = source;
        stale.data[offset] ^= 0x40;
        REQUIRE(!build_candidate(target, stale, candidate, changed, error));
    }
    Snapshot truncated = source;
    truncated.data.pop_back();
    REQUIRE(!build_candidate(target, truncated, candidate, changed, error));
    size_t own_required = 0, other_shared = 0;
    for (const auto &resource : profile_resources()) {
        own_required += resource_belongs_to_target(resource, target);
        if (!resource.kit_id && !resource_belongs_to_target(resource, target)) ++other_shared;
    }
    REQUIRE(own_required == 3 && other_shared == 2);
}

void test_independent_publication() {
    const size_t count = profile_targets().size();
    std::vector<Snapshot> sources(count), snapshots(count);
    std::vector<std::vector<uint8_t>> candidates(count);
    uint32_t unrelated_id = 0;
    std::array<uintptr_t, 402> table{};
    table.fill(reinterpret_cast<uintptr_t>(&unrelated_id));
    for (size_t index = 0; index < count; ++index) {
        sources[index] = fixture(profile_targets()[index]);
        table[index * 7 + 5] = reinterpret_cast<uintptr_t>(sources[index].data.data());
    }
    auto expected_table = table;
    struct { uintptr_t table; uint32_t count; } store{reinterpret_cast<uintptr_t>(table.data()), 402};
    uintptr_t store_address = reinterpret_cast<uintptr_t>(&store);
    const uintptr_t game = reinterpret_cast<uintptr_t>(&store_address) - kit_store_rva;
    std::string error;
    for (size_t index = 0; index < count; ++index) {
        size_t changed = 0;
        REQUIRE(capture_snapshot(game, profile_targets()[index], snapshots[index], error));
        REQUIRE(snapshot_unchanged(game, profile_targets()[index], snapshots[index]));
        REQUIRE(build_candidate(profile_targets()[index], snapshots[index], candidates[index], changed, error));
    }
    for (size_t index = 0; index < count; ++index) {
        const size_t slot = index * 7 + 5;
        const uintptr_t previous = expected_table[slot];
        const auto destination = reinterpret_cast<uintptr_t>(candidates[index].data());
        REQUIRE(publish_pointer(snapshots[index].entry, previous, destination));
        expected_table[slot] = destination;
        REQUIRE(table == expected_table);
        REQUIRE(!publish_pointer(snapshots[index].entry, previous, 0));
        for (size_t pending = index + 1; pending < count; ++pending)
            REQUIRE(snapshot_unchanged(game, profile_targets()[pending], snapshots[pending]));
        REQUIRE(sources[index].data == snapshots[index].data);
    }
    REQUIRE(!publish_pointer(0x123, 0, 1));
}
} // namespace

int main() {
    try {
        TemporaryProfiles temporary;
        for (unsigned index = 1; index <= 2; ++index) {
            const auto document = package(index);
            std::ofstream file(temporary.directory / (document.at("package_id").get<std::string>() + ".json"));
            file << document.dump(2);
            REQUIRE(file.good());
        }
        universal_isolation::Profile loaded;
        std::string error;
        if (!universal_isolation::load_directory(temporary.directory, loaded, error))
            throw std::runtime_error("fixture load failed: " + error);
        REQUIRE(loaded.targets.size() == 2 && loaded.resources.size() == 6);
        const auto *first_bodies = loaded.targets.front().bodies;
        const auto *first_pieces = loaded.targets.front().pieces;
        universal_isolation::Profile moved(std::move(loaded));
        active_profile = std::move(moved);
        REQUIRE(active_profile.targets.front().bodies == first_bodies && active_profile.targets.front().pieces == first_pieces);
        target_states.resize(active_profile.targets.size());
        for (const auto &target : profile_targets()) test_target(target);
        test_independent_publication();
        REQUIRE(legacy_addon_name(L"CM14Isolation.addon64"));
        REQUIRE(legacy_addon_name(L"B01Isolation.ADDON64"));
        REQUIRE(legacy_addon_name(L"ArmorIsolation_abc123.addon64"));
        REQUIRE(!legacy_addon_name(L"ArmorIsolation.addon64"));
        REQUIRE(!legacy_addon_name(L"unrelated.addon64"));
        std::puts("UNIVERSAL_ADDON_TEST_OK: loaded JSON profiles, stable ownership, actual dependencies, cape/metadata preserved, source guards, independent CAS, legacy conflict detection");
        return 0;
    } catch (const std::exception &exception) {
        std::fprintf(stderr, "UNIVERSAL_ADDON_TEST_FAILED: %s\n", exception.what());
        return 1;
    }
}
