#define CM14_ISOLATION_TEST
#include "../src/cm14_isolation_addon.cpp"
#include <fstream>
#include <chrono>
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

    TargetState cached;
    REQUIRE(prepare_candidate(target, source, cached, error));
    const auto *storage = cached.cached_candidate.data();
    REQUIRE(prepare_candidate(target, source, cached, error));
    REQUIRE(cached.cached_candidate.data() == storage && cached.cached_changes == 2);
    Snapshot changed_source = source;
    changed_source.data[first_non_cape + 0x18] ^= 0x40;
    REQUIRE(!prepare_candidate(target, changed_source, cached, error));
    REQUIRE(cached.cached_source.empty() && cached.cached_candidate.empty());
    REQUIRE(prepare_candidate(target, source, cached, error));
    REQUIRE(cached.cached_source == source.data);

    size_t probes = 0;
    bool available = false;
    const auto probe = [&](uintptr_t, uint64_t, uint64_t, HANDLE) {
        ++probes;
        return available ? cm14_isolation::resource_state::ready : cm14_isolation::resource_state::pending;
    };
    REQUIRE(!private_resources_ready(0, target, error, &cached, probe));
    REQUIRE(probes == 1 && cached.waiting_resource != 0);
    probes = 0;
    REQUIRE(!private_resources_ready(0, target, error, &cached, probe));
    REQUIRE(probes == 1);
    available = true;
    probes = 0;
    REQUIRE(private_resources_ready(0, target, error, &cached, probe));
    REQUIRE(probes == 4 && cached.waiting_resource == 0);
    available = false;
    REQUIRE(!private_resources_ready(0, target, error, nullptr, probe));
}

void test_session_log(const std::filesystem::path &directory) {
    const auto saved_path = log_path;
    const auto saved_status = last_status;
    const bool saved_started = log_started;
    const auto path = directory / "session.log";
    log_path = path.wstring();
    { std::ofstream old(path); old << "previous session must disappear"; }
    const auto read_log = [&]() {
        std::ifstream file(path, std::ios::binary);
        return std::string(std::istreambuf_iterator<char>(file), {});
    };
    log_started = false;
    last_status.clear();
    status("[CONFIG]", "first session");
    status("[WAIT]", "current session");
    const auto first = read_log();
    REQUIRE(first.find("previous session") == std::string::npos);
    REQUIRE(first.find("first session") != std::string::npos && first.find("current session") != std::string::npos);
    status("[WAIT]", "current session");
    REQUIRE(read_log() == first);
    log_started = false;
    last_status.clear();
    status("[CONFIG]", "second session");
    REQUIRE(read_log().find("first session") == std::string::npos);
    REQUIRE(read_log().find("second session") != std::string::npos);
    log_path = (directory / "missing" / "session.log").wstring();
    log_started = false;
    last_status.clear();
    status("[CONFIG]", "retry");
    REQUIRE(!log_started && last_status.empty());
    std::filesystem::create_directory(directory / "missing");
    status("[CONFIG]", "retry");
    REQUIRE(log_started && last_status == "[CONFIG] retry");
    log_path = saved_path;
    last_status = saved_status;
    log_started = saved_started;
}

void test_local_observation(const std::filesystem::path &directory) {
    const auto digest_path = directory / "digest.txt";
    { std::ofstream file(digest_path, std::ios::binary); file << "abc"; }
    REQUIRE(armor_local_data::file_sha256(digest_path) ==
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    auto anchor = armor_local_data::kit_anchor;
    REQUIRE(armor_local_data::anchor_matches(anchor.data()));
    const int32_t relocated = 0x2000 - 0x1000 - 0xa7;
    std::memcpy(anchor.data() + 0xa3, &relocated, sizeof(relocated));
    REQUIRE(armor_local_data::anchor_matches(anchor.data()));
    REQUIRE(armor_local_data::anchor_global(0x1000, anchor.data(), 0x3000) == 0x2000);
    anchor[0x16] ^= 1;
    REQUIRE(!armor_local_data::anchor_matches(anchor.data()));
    // Synthetic loaded PE proves relocation discovery, ambiguity rejection and bounds.
    std::vector<uint8_t> image(0x4000);
    auto *dos = reinterpret_cast<IMAGE_DOS_HEADER *>(image.data());
    dos->e_magic = IMAGE_DOS_SIGNATURE;
    dos->e_lfanew = 0x100;
    auto *nt = reinterpret_cast<IMAGE_NT_HEADERS64 *>(image.data() + 0x100);
    nt->Signature = IMAGE_NT_SIGNATURE;
    nt->FileHeader.Machine = IMAGE_FILE_MACHINE_AMD64;
    nt->FileHeader.NumberOfSections = 1;
    nt->FileHeader.SizeOfOptionalHeader = sizeof(IMAGE_OPTIONAL_HEADER64);
    nt->OptionalHeader.Magic = IMAGE_NT_OPTIONAL_HDR64_MAGIC;
    nt->OptionalHeader.SizeOfImage = static_cast<DWORD>(image.size());
    auto *section = reinterpret_cast<IMAGE_SECTION_HEADER *>(image.data() + 0x100 + sizeof(*nt));
    section->VirtualAddress = 0x1000;
    section->Misc.VirtualSize = 0x1000;
    section->Characteristics = IMAGE_SCN_MEM_EXECUTE;
    anchor = armor_local_data::kit_anchor;
    std::memcpy(anchor.data() + 0xa3, &relocated, sizeof(relocated));
    std::memcpy(image.data() + 0x1000, anchor.data(), anchor.size());
    const auto base = reinterpret_cast<uintptr_t>(image.data());
    REQUIRE(armor_local_data::discover(GetCurrentProcess(), base).global_rva == 0x2000);
    const auto rejects = [&]() {
        try { armor_local_data::discover(GetCurrentProcess(), base); return false; }
        catch (const std::exception &) { return true; }
    };
    std::memcpy(image.data() + 0x1200, anchor.data(), anchor.size());
    REQUIRE(rejects());
    image[0x1200] = 0;
    image[0x1016] ^= 1;
    REQUIRE(rejects());
    image[0x1016] ^= 1;
    section->Misc.VirtualSize = 0x4000;
    REQUIRE(rejects());
    auto report = armor_local_data::capture(GetCurrentProcess(), 0);
    REQUIRE(report.at("status") == "unsupported_or_not_ready");
    REQUIRE(report.at("write_authorized") == false && !report.contains("kits"));
    const auto path = directory / "observation.json";
    armor_local_data::save(path, report);
    report["error"] = "second session";
    armor_local_data::save(path, report);
    std::ifstream file(path);
    REQUIRE(nlohmann::json::parse(file) == report);
    REQUIRE(!std::filesystem::exists(path.wstring() + L".tmp"));
}

void test_native_anchors() {
    for (const auto &anchor : armor_native::anchors) {
        armor_native::Image image;
        image.size = 0x10000;
        image.code.emplace_back(0x2000, std::vector<uint8_t>(anchor.bytes.size() + 32, 0xcc));
        auto &bytes = image.code.front().second;
        std::copy(anchor.bytes.begin(), anchor.bytes.end(), bytes.begin() + 16);
        for (size_t i = 0; i < anchor.mask.size(); ++i)
            if (!anchor.mask[i]) bytes[16 + i] ^= 0x55;
        REQUIRE(armor_native::find(image, anchor) == 0x2010);
        const auto rejects = [&]() {
            try { armor_native::find(image, anchor); return false; }
            catch (const std::exception &) { return true; }
        };
        image.code.emplace_back(0x5000, image.code.front().second);
        REQUIRE(rejects());
        image.code.pop_back();
        image.code.front().second[16] ^= 1;
        REQUIRE(rejects());
    }

    const auto append_anchor = [](armor_native::Image &image, const armor_native::Anchor &anchor, uintptr_t rva) {
        image.code.emplace_back(rva, std::vector<uint8_t>(anchor.bytes.size() + 32, 0xcc));
        auto &bytes = image.code.back().second;
        std::copy(anchor.bytes.begin(), anchor.bytes.end(), bytes.begin() + 16);
        for (size_t i = 0; i < anchor.mask.size(); ++i)
            if (!anchor.mask[i]) bytes[16 + i] ^= 0x55;
    };
    for (bool reviewed : {false, true}) {
        const auto &assembly = reviewed ? armor_native::reviewed_assembly : armor_native::anchors.front();
        const std::string variant = reviewed ? "assembly-family-19099" : "assembly-family-18930";
        armor_native::Image game_image, exe_image;
        game_image.size = exe_image.size = 0x10000;
        append_anchor(game_image, assembly, 0x2000);
        for (size_t i = 1; i < armor_native::anchors.size(); ++i)
            append_anchor(exe_image, armor_native::anchors[i], 0x2000 * i);
        json diagnostics;
        const auto functions = armor_native::discover_functions(game_image, exe_image, &diagnostics);
        REQUIRE(functions.size() == 6 && functions.at("armor_assembly") == 0x2010);
        REQUIRE(diagnostics.at("required") == 6 && diagnostics.at("matched") == 6);
        REQUIRE(diagnostics.at("functions").at("armor_assembly").at("variant") == variant);
        for (size_t i = 1; i < armor_native::anchors.size(); ++i)
            REQUIRE(functions.at(armor_native::anchors[i].name) == 0x2000 * i + 16);
        for (const auto &anchor : armor_native::anchors)
            REQUIRE(diagnostics.at("functions").at(anchor.name).at("status") == "matched");
        const auto rejects = [&](const armor_native::Image &game, const armor_native::Image &exe,
                                 json *detail = nullptr) {
            try { armor_native::discover_functions(game, exe, detail); return false; }
            catch (const std::exception &) { return true; }
        };
        const auto set_parameter = [](armor_native::Image &image, size_t offset, int32_t value) {
            std::memcpy(image.code.front().second.data() + 16 + offset, &value, sizeof(value));
        };
        auto changed = game_image;
        for (int group = 0; group < 3; ++group) {
            const auto *source = assembly.bytes.data();
            if (group == 0) {
                const auto count = static_cast<int32_t>(armor_native::assembly_parameter(source, 0x218) + 0x1000);
                set_parameter(changed, 0x218, count);
                set_parameter(changed, 0x223, count + 8);
                set_parameter(changed, 0x4ed, count + 0x133);
                set_parameter(changed, 0x4fb, count + 0x28);
            } else if (group == 1) {
                const auto stride = static_cast<int32_t>(armor_native::assembly_parameter(source, 0x80d) + 0x28);
                set_parameter(changed, 0x7eb, 32 * stride);
                set_parameter(changed, 0x80d, stride);
                set_parameter(changed, 0xae8, stride);
                set_parameter(changed, 0xafb,
                    static_cast<int32_t>(armor_native::assembly_parameter(source, 0xafb) + 4));
            } else {
                const auto world = static_cast<int32_t>(armor_native::assembly_parameter(source, 0xb83) + 0x80);
                set_parameter(changed, 0xb83, world);
                set_parameter(changed, 0xbab, world);
                set_parameter(changed, reviewed ? 0xbf7 : 0xc1b, world + 0x10);
            }
            REQUIRE(armor_native::assembly_parameters_valid(changed.code.front().second.data() + 16, reviewed));
            REQUIRE(armor_native::discover_functions(changed, exe_image, &diagnostics).size() == 6);
            REQUIRE(diagnostics.at("matched") == 6 &&
                diagnostics.at("functions").at("armor_assembly").at("variant") == variant);
        }
        const std::array<size_t, 11> parameters{0x218, 0x223, 0x4ed, 0x4fb,
            0x7eb, 0x80d, 0xae8, 0xafb, 0xb83, 0xbab, reviewed ? 0xbf7u : 0xc1bu};
        for (const auto offset : parameters) {
            changed = game_image;
            changed.code.front().second[16 + offset] ^= 1;
            REQUIRE(!armor_native::assembly_parameters_valid(changed.code.front().second.data() + 16, reviewed));
            REQUIRE(rejects(changed, exe_image, &diagnostics));
            REQUIRE(diagnostics.at("matched") == 5 && diagnostics.at("required") == 6);
            REQUIRE(diagnostics.at("functions").at("armor_assembly").at("status") == "failed");
            REQUIRE(diagnostics.at("functions").at("armor_assembly").at("error").get<std::string>().find(
                "external layout parameters disagree") != std::string::npos);
        }
        // Keep the prologue and all resource-manager code intact while changing
        // the Piece material_lut field read from +0x18 to +0x20.
        changed = game_image;
        const std::array<uint8_t, 5> material_lut_read{0x4d, 0x8b, 0x44, 0x24, 0x18};
        auto &changed_bytes = changed.code.front().second;
        const auto field = std::search(changed_bytes.begin(), changed_bytes.end(),
                                       material_lut_read.begin(), material_lut_read.end());
        REQUIRE(field != changed_bytes.end());
        REQUIRE(assembly.mask[static_cast<size_t>(field - changed_bytes.begin()) - 16 + 4] == 255);
        *(field + 4) = 0x20;
        REQUIRE(rejects(changed, exe_image));
        // A Body-loop branch displacement and the saved Piece stack slot stay
        // strict even though unrelated global-layout operands may change.
        const auto shape = armor_native::assembly_shape(reviewed);
        for (const size_t offset : {0x2fcu, 0x359u}) {
            REQUIRE(shape.mask[offset] == 255);
            changed = game_image;
            changed.code.front().second[16 + offset] ^= 1;
            REQUIRE(rejects(changed, exe_image));
        }
        changed = game_image;
        changed.code.clear();
        REQUIRE(rejects(changed, exe_image, &diagnostics));
        REQUIRE(diagnostics.at("required") == 6 && diagnostics.at("matched") == 5);
        REQUIRE(diagnostics.at("functions").at("armor_assembly").at("status") == "failed");
        for (size_t i = 1; i < armor_native::anchors.size(); ++i)
            REQUIRE(diagnostics.at("functions").at(armor_native::anchors[i].name).at("status") == "matched");
        auto two_missing = exe_image;
        two_missing.code.erase(two_missing.code.begin());
        REQUIRE(rejects(changed, two_missing, &diagnostics));
        REQUIRE(diagnostics.at("required") == 6 && diagnostics.at("matched") == 4);
        for (size_t i = 0; i < armor_native::anchors.size(); ++i)
            REQUIRE(diagnostics.at("functions").at(armor_native::anchors[i].name).at("status") ==
                (i < 2 ? "failed" : "matched"));
        changed = game_image;
        append_anchor(changed, assembly, 0x7000);
        REQUIRE(rejects(changed, exe_image));
        changed = game_image;
        append_anchor(changed, reviewed ? armor_native::anchors.front() : armor_native::reviewed_assembly, 0x7000);
        REQUIRE(rejects(changed, exe_image));
        for (size_t i = 0; i < exe_image.code.size(); ++i) {
            auto missing = exe_image;
            missing.code.erase(missing.code.begin() + i);
            REQUIRE(rejects(game_image, missing, &diagnostics));
            REQUIRE(diagnostics.at("required") == 6 && diagnostics.at("matched") == 5);
            for (size_t j = 0; j < armor_native::anchors.size(); ++j)
                REQUIRE(diagnostics.at("functions").at(armor_native::anchors[j].name).at("status") ==
                    (j == i + 1 ? "failed" : "matched"));
        }
    }

    // The assembly and independent collector must refer to the same Kit table.
    std::vector<uint8_t> module(0x4000);
    const uintptr_t assembly_rva = 0x1000, kit_store = 0x3000;
    const auto module_base = reinterpret_cast<uintptr_t>(module.data());
    const auto reference = [&](size_t offset, uintptr_t target) {
        const std::array<uint8_t, 3> opcode{0x4c, 0x8b, 0x15};
        std::copy(opcode.begin(), opcode.end(), module.begin() + assembly_rva + offset);
        const auto delta = static_cast<int32_t>(target) - static_cast<int32_t>(assembly_rva + offset + 7);
        std::memcpy(module.data() + assembly_rva + offset + 3, &delta, sizeof(delta));
    };
    reference(0x1b5, kit_store);
    reference(0x468, kit_store);
    armor_native::validate_assembly_references(GetCurrentProcess(), module_base, assembly_rva,
        kit_store, static_cast<uint32_t>(module.size()));
    const auto references_reject = [&]() {
        try {
            armor_native::validate_assembly_references(GetCurrentProcess(), module_base, assembly_rva,
                kit_store, static_cast<uint32_t>(module.size()));
            return false;
        } catch (const std::exception &) { return true; }
    };
    reference(0x468, kit_store + 8);
    REQUIRE(references_reject());
    reference(0x468, module.size());
    REQUIRE(references_reject());
    reference(0x468, kit_store);
    reference(0x1b5, module.size() - 7);
    REQUIRE(references_reject());
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
    KitIndex shared;
    REQUIRE(build_kit_index(game, shared, error));
    Snapshot indexed, baseline;
    REQUIRE(capture_snapshot(game, profile_targets()[0], indexed, error, &shared));
    REQUIRE(capture_snapshot(game, profile_targets()[0], baseline, error));
    REQUIRE(indexed.data == baseline.data && indexed.entry == baseline.entry);
    const auto benchmark = [&](bool use_index) {
        const auto start = std::chrono::steady_clock::now();
        KitIndex cycle;
        if (use_index) REQUIRE(build_kit_index(game, cycle, error));
        for (size_t i = 0; i < 402; ++i)
            REQUIRE(capture_snapshot(game, profile_targets()[i % count], indexed, error, use_index ? &cycle : nullptr));
        return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
    };
    const double before_ms = benchmark(false), after_ms = benchmark(true);
    std::printf("KIT_SCAN_BENCH synthetic 402 captures: separate=%.3fms shared=%.3fms\n", before_ms, after_ms);
    const auto original_entry = table[5];
    table[5] = reinterpret_cast<uintptr_t>(&unrelated_id);
    REQUIRE(!capture_snapshot(game, profile_targets()[0], indexed, error, &shared));
    table[5] = original_entry;
    store.count = 401;
    REQUIRE(!capture_snapshot(game, profile_targets()[0], indexed, error, &shared));
    store.count = 402;
    table[6] = table[5];
    KitIndex duplicate;
    REQUIRE(build_kit_index(game, duplicate, error));
    REQUIRE(!capture_snapshot(game, profile_targets()[0], indexed, error, &duplicate));
    table[6] = reinterpret_cast<uintptr_t>(&unrelated_id);
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
        initialize_mapping_indexes();
        for (const auto &target : profile_targets()) test_target(target);
        test_independent_publication();
        test_session_log(temporary.directory);
        test_local_observation(temporary.directory);
        test_native_anchors();
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
