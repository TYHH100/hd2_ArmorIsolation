#include "armor_runtime_profile.hpp"

#include <chrono>
#include <cstdio>
#include <functional>
#include <sstream>

namespace {
using namespace universal_isolation;
using json = nlohmann::json;
using Documents = std::vector<std::pair<std::string, std::string>>;
int checks = 0;

void check(bool condition, const char *message)
{
    ++checks;
    if (!condition) throw std::runtime_error(message);
}

std::string hex_id(std::uint64_t value, std::size_t width = 16)
{
    constexpr char digits[] = "0123456789abcdef";
    std::string output(width, '0');
    while (width) {
        output[--width] = digits[value & 15];
        value >>= 4;
    }
    return output;
}

json valid_profile(unsigned index = 1)
{
    const auto kit = hex_id(index, 8);
    const auto unit_destination = hex_id(0x2000000000000000ULL + (std::uint64_t(index) << 32));
    const auto texture_destination = hex_id(0x3000000000000000ULL + (std::uint64_t(index) << 32));
    const auto material_destination = hex_id(0x6000000000000000ULL + (std::uint64_t(index) << 32));
    json references = {{"unit", "1000000000000001"}, {"material_lut", "4000000000000001"}};
    for (const char *key : {"pattern_lut", "cape_lut", "cape_gradient", "cape_nac", "decal_scalar_fields",
                           "base_data", "decal_sheet"})
        references[key] = "0000000000000000";
    json piece = {{"slot", 0}, {"type", 0}, {"weight", 1}, {"tone_variations", 0}, {"resources", references}};
    json kit_metadata = {{"id", kit}, {"archive", "a000000000000001"}, {"type", 1}, {"passive", 0},
                         {"bodies", json::array({{{"type", 3}, {"pieces", json::array({piece})}}})}};
    return {{"schema", runtime_schema}, {"package_id", std::string(23, 'a') + char('a' + index)},
            {"expected_game_dll_sha256", expected_game_dll_sha256}, {"expected_game_version", expected_game_version},
            {"selected_kit_metadata", json::array({kit_metadata})},
            {"mapping", json::array({
                {{"kit", kit}, {"type", hex_id(unit_type)}, {"source", "1000000000000001"}, {"target", unit_destination}},
                {{"kit", "00000000"}, {"type", hex_id(texture_type)}, {"source", "4000000000000001"}, {"target", texture_destination}},
                {{"kit", "00000000"}, {"type", hex_id(material_type)}, {"source", "5000000000000001"}, {"target", material_destination}}
            })},
            {"piece_fields", json::array({
                {{"kit", kit}, {"offset", 0}, {"source", "1000000000000001"}, {"target", unit_destination}},
                {{"kit", kit}, {"offset", 24}, {"source", "4000000000000001"}, {"target", texture_destination}}
            })},
            {"required_resources", json::array({
                {{"kit", kit}, {"type", hex_id(unit_type)}, {"target", unit_destination}},
                {{"kit", kit}, {"type", hex_id(texture_type)}, {"target", texture_destination}},
                {{"kit", kit}, {"type", hex_id(material_type)}, {"target", material_destination}}
            })}};
}

std::pair<std::string, std::string> document(const json &profile)
{
    return {profile.at("package_id").get<std::string>() + ".json", profile.dump()};
}

void refuses(const json &input, const char *message)
{
    Profile output;
    std::string error;
    check(!load_documents({document(input)}, output, error) && !error.empty() && output.targets.empty(), message);
}

void mutate_refuses(const std::function<void(json &)> &mutation, const char *message)
{
    auto input = valid_profile();
    mutation(input);
    refuses(input, message);
}

struct TemporaryDirectory {
    std::filesystem::path path;
    TemporaryDirectory()
    {
        path = std::filesystem::temp_directory_path() /
            ("hd2-runtime-profile-test-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        if (!std::filesystem::create_directory(path)) throw std::runtime_error("could not create owned test directory");
    }
    ~TemporaryDirectory() { std::error_code ignored; std::filesystem::remove_all(path, ignored); }
};

void write_document(const std::filesystem::path &directory, const json &input)
{
    const auto [name, text] = document(input);
    std::ofstream stream(directory / name, std::ios::binary);
    stream << text;
    if (!stream) throw std::runtime_error("could not write test profile");
}

void run()
{
    Profile output;
    std::string error;
    const auto first = valid_profile();
    auto second = valid_profile(2);
    check(load_documents({document(first), document(second)}, output, error), "valid multi-profile load failed");
    check(output.targets.size() == 2 && output.resources.size() == 6 && output.required_resources.size() == 6,
          "combined profile sizes are wrong");
    check(output.requirements_by_kit.at(1).size() == 3 && output.requirements_by_kit.at(2).size() == 3,
          "target dependency lookup index is incomplete");
    check(output.resources[0].source == output.resources[3].source && output.resources[0].target != output.resources[3].target,
          "shared old Unit sources must remain legal between packages");
    check(output.target_packages.at(1) == first.at("package_id").get<std::string>(), "target package attribution is wrong");
    const auto *original_piece = output.targets[0].pieces;
    const auto *original_body = output.targets[0].bodies;
    Profile moved = std::move(output);
    std::vector<Profile> moved_again;
    moved_again.push_back(std::move(moved));
    moved_again.emplace_back();
    check(moved_again.front().targets[0].pieces == original_piece && original_piece->source_unit == 0x1000000000000001ULL &&
          moved_again.front().targets[0].bodies == original_body && original_body->piece_count == 1,
          "profile move invalidated target pointers");
    output = std::move(moved_again.front());
    check(!load_documents({document(first), document(first)}, output, error) && output.targets.size() == 2 &&
          output.targets[0].pieces == original_piece, "failed group load partially replaced the active profile");

    second["selected_kit_metadata"][0]["id"] = "00000001";
    check(!load_documents({document(first), document(second)}, output, error), "overlapping Kit accepted");
    second = valid_profile(2);
    second["mapping"][0]["target"] = first["mapping"][0]["target"];
    second["piece_fields"][0]["target"] = first["mapping"][0]["target"];
    second["required_resources"][0]["target"] = first["mapping"][0]["target"];
    check(!load_documents({document(first), document(second)}, output, error), "duplicate private ID accepted");
    second["mapping"][0]["target"] = "2000000100000001";
    second["piece_fields"][0]["target"] = "2000000100000001";
    second["required_resources"][0]["target"] = "2000000100000001";
    check(!load_documents({document(first), document(second)}, output, error), "duplicate high32 accepted");
    second = valid_profile(2);
    second["mapping"][0]["source"] = first["mapping"][0]["target"];
    second["piece_fields"][0]["source"] = first["mapping"][0]["target"];
    second["selected_kit_metadata"][0]["bodies"][0]["pieces"][0]["resources"]["unit"] = first["mapping"][0]["target"];
    check(!load_documents({document(first), document(second)}, output, error), "cross-package source/target alias accepted");

    auto fixed_style = valid_profile();
    fixed_style["mapping"][1]["kit"] = "00000001";
    fixed_style["mapping"][2]["kit"] = "00000001";
    check(load_documents({document(fixed_style)}, output, error), "fixed CM14-style owned materials/textures rejected");
    mutate_refuses([](json &v) { v["expected_game_version"] = "1.0.0.1"; }, "wrong game version accepted");
    mutate_refuses([](json &v) { v["expected_game_dll_sha256"] = std::string(64, 'a'); }, "wrong game hash accepted");
    mutate_refuses([](json &v) { v["schema"] = "hd2-armor-runtime/2"; }, "wrong runtime schema accepted");
    mutate_refuses([](json &v) { v["address"] = "0000000000010000"; }, "unknown user address accepted");
    mutate_refuses([](json &v) { v["mapping"][0]["kit"] = "00000000"; }, "shared Unit owner accepted");
    mutate_refuses([](json &v) { v["mapping"][1]["kit"] = "ffffffff"; }, "foreign owner accepted");
    mutate_refuses([](json &v) { v["mapping"][0]["type"] = "1111111111111111"; }, "unknown resource type accepted");
    mutate_refuses([](json &v) { v["mapping"][0]["target"] = 1; }, "numeric resource ID accepted");
    mutate_refuses([](json &v) { v["mapping"][0]["source"] = "1"; }, "short resource ID accepted");
    mutate_refuses([](json &v) { v["mapping"][0]["target"] = "0000000000000000"; }, "zero resource accepted");
    mutate_refuses([](json &v) { v["selected_kit_metadata"][0]["type"] = true; }, "boolean integer accepted");
    mutate_refuses([](json &v) { v["selected_kit_metadata"][0]["type"] = 1.0; }, "floating integer accepted");
    mutate_refuses([](json &v) { v["selected_kit_metadata"][0]["passive"] = -1; }, "negative integer accepted");
    mutate_refuses([](json &v) { v["selected_kit_metadata"][0]["passive"] = 0xffffffffffffffffULL; }, "overflowing integer accepted");
    mutate_refuses([](json &v) { v["piece_fields"].push_back(v["piece_fields"][0]); }, "duplicate piece field accepted");
    mutate_refuses([](json &v) { v["piece_fields"][0]["offset"] = 8; }, "metadata write offset accepted");
    mutate_refuses([](json &v) { v["piece_fields"][1]["offset"] = 32; }, "unused dynamic field accepted");
    mutate_refuses([](json &v) { v["piece_fields"].erase(0); }, "missing Unit field accepted");
    mutate_refuses([](json &v) { v["piece_fields"].erase(1); }, "missing texture field accepted");
    mutate_refuses([](json &v) { v["required_resources"].erase(0); }, "missing owned Unit dependency accepted");
    mutate_refuses([](json &v) { v["required_resources"].erase(1); }, "missing referenced texture dependency accepted");
    mutate_refuses([](json &v) { v["required_resources"].erase(2); }, "unclaimed shared resource accepted");
    mutate_refuses([](json &v) { v["required_resources"].push_back(v["required_resources"][0]); }, "duplicate dependency accepted");
    mutate_refuses([](json &v) { v["mapping"].push_back(v["mapping"][0]); }, "duplicate typed resource accepted");
    mutate_refuses([](json &v) { v["selected_kit_metadata"][0]["type"] = 0;
        v["selected_kit_metadata"][0]["bodies"][0]["pieces"][0]["slot"] = 1; }, "cape-only target accepted");
    mutate_refuses([](json &v) { v["selected_kit_metadata"][0]["bodies"][0]["pieces"][0]["slot"] = 2; }, "helmet using armor slot accepted");
    mutate_refuses([](json &v) { v["mapping"] = json::array(); for (std::size_t i = 0; i <= max_resources; ++i)
        v["mapping"].push_back(json::object()); }, "oversized resource array accepted");

    auto [name, text] = document(first);
    check(!load_documents({{name, text.substr(0, text.size() - 1)}}, output, error), "truncated JSON accepted");
    check(!load_documents({{name, std::string(max_profile_bytes + 1, ' ')}}, output, error), "oversized file accepted");
    check(!load_documents(Documents(max_profile_files + 1, document(first)), output, error), "too many files accepted");
    check(!load_documents({{"wrong.json", text}}, output, error), "filename/package mismatch accepted");
    text.insert(1, "\"schema\":\"hd2-armor-runtime/1\",");
    check(!load_documents({{name, text}}, output, error) && error.find("duplicate JSON") != std::string::npos,
          "duplicate JSON key accepted");
    check(!load_documents({{name, std::string(34, '[') + "0" + std::string(34, ']')}}, output, error) &&
          error.find("nesting") != std::string::npos, "excessive JSON depth accepted");

    TemporaryDirectory temporary;
    check(load_directory(temporary.path, output, error) && output.targets.empty(), "empty directory was not handled");
    write_document(temporary.path, first);
    write_document(temporary.path, valid_profile(2));
    check(load_directory(temporary.path, output, error) && output.targets.size() == 2, "directory loading failed");
    const auto *retained_piece = output.targets[0].pieces;
    {
        std::ofstream invalid(temporary.path / "invalid.json");
        invalid << "{}";
    }
    check(!load_directory(temporary.path, output, error) && output.targets.size() == 2 &&
          output.targets[0].pieces == retained_piece, "bad file permitted partial directory publication");
    check(!load_files({temporary.path / "missing.json"}, output, error), "missing file accepted");
    check(!load_directory(temporary.path / "missing", output, error), "missing directory accepted");
}
} // namespace

int main()
{
    try {
        run();
        std::printf("runtime_profile: %d checks passed\n", checks);
        return 0;
    } catch (const std::exception &exception) {
        std::fprintf(stderr, "runtime_profile failed after %d checks: %s\n", checks, exception.what());
        return 1;
    }
}
