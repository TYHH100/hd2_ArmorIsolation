#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "armor_ias_handoff.hpp"
#include <cstdio>

#define REQUIRE(value) do { if (!(value)) throw std::runtime_error("check failed: " #value); } while (false)

namespace {
using namespace universal_isolation;
struct Temporary {
    std::filesystem::path path = std::filesystem::temp_directory_path() /
        ("hd2-ias-handoff-" + std::to_string(GetCurrentProcessId()) + "-" + std::to_string(GetTickCount64()));
    Temporary() { REQUIRE(std::filesystem::create_directory(path)); }
    ~Temporary() { std::error_code error; std::filesystem::remove_all(path, error); }
};
template<class F> void refuses(F function, const char *message) {
    bool failed = false;
    try { function(); } catch (const std::exception &error) { failed = std::string(error.what()).find(message) != std::string::npos; }
    REQUIRE(failed);
}
void run() {
    Profile profile;
    std::array<ExpectedBody, 3> body{{{3, 1}, {0, 1}, {1, 1}}};
    ExpectedBody head{3, 1};
    std::array<ExpectedPiece, 3> body_pieces{};
    for (auto &piece : body_pieces) { piece.slot = 2; piece.source_unit = 0x123; }
    ExpectedPiece helmet_piece{};
    helmet_piece.source_unit = 0x123;
    profile.targets = {{0x11111111, 0x101, 0, 0, body.data(), 3, body_pieces.data(), 3, 3},
                       {0x22222222, 0x102, 1, 0, &head, 1, &helmet_piece, 1, 1}};
    profile.target_packages = {{0x11111111, "111111111111111111111111"},
                              {0x22222222, "222222222222222222222222"}};
    // Two Kits sharing an original Unit remain separately routed.
    profile.resources = {{0x11111111, unit_type, 0x123, 0x1000000001},
                          {0x22222222, unit_type, 0x123, 0x2000000001},
                          {0, material_type, 0x500, 0x3000000001},
                          {0, bones_type, 0x600, 0x4000000001}};
    profile.piece_fields = {{0x11111111, 0, 0x123, 0x1000000001}, {0x22222222, 0, 0x123, 0x2000000001}};
    const auto files = armor_ias::make_handoff(profile);
    REQUIRE(files.size() == 2);
    for (const auto &[name, text] : files) {
        REQUIRE(text.find("rig_profile=") == std::string::npos);
        REQUIRE(text.find("unit=0x0000000000000123,") != std::string::npos);
        REQUIRE(armor_ias::owned(name, text));
        const auto declaration = armor_ias::parse_declaration(text);
        REQUIRE(declaration.units.size() == 1 && declaration.equipment.size() == 1);
    }
    Temporary temporary;
    const auto directory = temporary.path / "IAS";
    REQUIRE(!armor_ias::prepared(files, directory));
    REQUIRE(armor_ias::synchronize(files, directory));
    REQUIRE(armor_ias::prepared(files, directory));
    REQUIRE(!armor_ias::synchronize(files, directory));
    const auto stamp = std::filesystem::last_write_time(directory / files.begin()->first);
    REQUIRE(!armor_ias::synchronize(files, directory));
    REQUIRE(std::filesystem::last_write_time(directory / files.begin()->first) == stamp);

    // Preserve unrelated IAS declarations, including their actual Rig dependencies.
    const std::string foreign = "isolation_version=1\nisolation_id=other\ndomain=helmet\narchive=0x999\nequipment=0x33333333\nunit=0x456,0x5000000001\nrig_profile=0x5000000001\n";
    armor_ias::replace_file(directory / "other.isolation.ini", foreign);
    REQUIRE(armor_ias::prepared(files, directory));
    auto reduced = files;
    reduced.erase(std::prev(reduced.end()));
    REQUIRE(!armor_ias::prepared(reduced, directory));
    REQUIRE(armor_ias::synchronize(reduced, directory));
    REQUIRE(armor_ias::read_text(directory / "other.isolation.ini") == foreign);
    REQUIRE(armor_ias::inventory(directory).managed.size() == 1);
    REQUIRE(armor_ias::synchronize(files, directory));

    // Failed stale-file deletion must restore a declaration already replaced.
    const auto stale = directory / std::prev(files.end())->first;
    const HANDLE locked = CreateFileW(stale.c_str(), GENERIC_READ, FILE_SHARE_READ,
        nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    REQUIRE(locked != INVALID_HANDLE_VALUE);
    auto modified = reduced;
    modified.begin()->second += "# new source package selection\n";
    bool rejected = false;
    try { armor_ias::synchronize(modified, directory); }
    catch (const std::exception &) { rejected = true; }
    CloseHandle(locked);
    REQUIRE(rejected);
    REQUIRE(armor_ias::inventory(directory).managed == files);

    auto conflicting = foreign;
    conflicting.replace(conflicting.find("0x999"), 5, "0x101");
    armor_ias::replace_file(directory / "other.isolation.ini", conflicting);
    refuses([&] { armor_ias::synchronize({}, directory); /* foreign only is legal */
        armor_ias::synchronize(files, directory); }, "Archive or identity conflict");
    REQUIRE(armor_ias::inventory(directory).managed.empty());
    armor_ias::replace_file(directory / "other.isolation.ini", foreign);
    REQUIRE(armor_ias::synchronize(files, directory));

    // A conflict must be detected before changing any of our existing files.
    conflicting = foreign;
    conflicting.replace(conflicting.find("0x33333333"), 10, "0x11111111");
    conflicting.replace(conflicting.find("domain=helmet"), 13, "domain=body");
    armor_ias::replace_file(directory / "other.isolation.ini", conflicting);
    refuses([&] { armor_ias::synchronize(reduced, directory); }, "equipment already controlled");
    REQUIRE(armor_ias::inventory(directory).managed == files);
    armor_ias::replace_file(directory / "other.isolation.ini", foreign);
    const auto protected_file = directory / files.begin()->first;
    armor_ias::replace_file(protected_file, "isolation_version=1\n");
    refuses([&] { armor_ias::synchronize(files, directory); }, "unrecognized IAS bridge file");
    REQUIRE(armor_ias::read_text(protected_file) == "isolation_version=1\n");

    profile.piece_fields.push_back({0x11111111, 0x18, 0x700, 0x800});
    refuses([&] { armor_ias::make_handoff(profile); }, "Piece texture changes");
    profile.piece_fields.pop_back();
    profile.targets[1].archive = profile.targets[0].archive;
    refuses([&] { armor_ias::make_handoff(profile); }, "Kits share Archive");
    profile.targets[1].archive = 0x102;
    body_pieces[0].slot = 1;
    refuses([&] { armor_ias::make_handoff(profile); }, "default cape");
    body_pieces[0].slot = 2;
    profile.targets[0].body_count = 1;
    refuses([&] { armor_ias::make_handoff(profile); }, "three body groups");
    std::puts("IAS_HANDOFF_OK: body/head, private IDs, shared original Units, no invented Rig Profiles, conflicts before writes, stale cleanup, foreign preservation, unsupported textures/groups/Archive sharing");
}
}
int main() {
    try { run(); return 0; }
    catch (const std::exception &error) { std::fprintf(stderr, "%s\n", error.what()); return 1; }
}
