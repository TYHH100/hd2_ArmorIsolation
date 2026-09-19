#pragma once

#include <nlohmann/json.hpp>
#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <initializer_list>
#include <map>
#include <memory>
#include <set>
#include <stdexcept>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace universal_isolation {

inline constexpr char expected_game_dll_sha256[] = "cc75948d90fdfde259dcb519e9933db7ffa3ccb281ce4fb89e6b1b011557470c";
inline constexpr char expected_game_version[] = "1.0.0.18930";
inline constexpr char runtime_schema[] = "hd2-armor-runtime/1";
inline constexpr std::uint64_t unit_type = 0xe0a48d0be9a7453fULL;
inline constexpr std::uint64_t texture_type = 0xcd4238c6a0c69e32ULL;
inline constexpr std::uint64_t material_type = 0xeac0b497876adedfULL;
inline constexpr std::size_t max_profile_bytes = 8 * 1024 * 1024;
inline constexpr std::size_t max_total_profile_bytes = 32 * 1024 * 1024;
inline constexpr std::size_t max_profile_files = 64;
inline constexpr std::size_t max_resources = 16384;
inline constexpr std::size_t max_targets = 402;
inline constexpr std::size_t max_fields = 32768;
inline constexpr std::size_t max_required_resources = 131072;

struct ResourceMapping { std::uint32_t kit_id; std::uint64_t type, source, target; };
struct FieldMapping { std::uint32_t kit_id, field_offset; std::uint64_t source, target; };
struct RequiredResource { std::uint32_t kit_id; std::uint64_t type, target; };
struct ExpectedBody { std::uint32_t body_type, piece_count; };
struct ExpectedPiece {
    std::uint32_t body_type, slot, piece_type, weight, tone_variations;
    std::uint64_t source_unit;
};
struct TargetKit {
    std::uint32_t id; std::uint64_t archive; std::uint32_t type, passive;
    const ExpectedBody *bodies; std::size_t body_count;
    const ExpectedPiece *pieces; std::size_t piece_count;
    std::size_t expected_unit_changes;
};

struct TargetStorage {
    std::vector<ExpectedBody> bodies;
    std::vector<ExpectedPiece> pieces;
    std::vector<std::array<std::uint64_t, 9>> references;
};

struct Profile {
    std::vector<ResourceMapping> resources;
    std::vector<FieldMapping> piece_fields;
    std::vector<RequiredResource> required_resources;
    std::vector<TargetKit> targets;
    std::vector<std::string> package_ids;
    std::map<std::uint32_t, std::string> target_packages;
    std::map<std::uint32_t, std::set<std::pair<std::uint64_t, std::uint64_t>>> requirements_by_kit;
    // Separate allocations keep TargetKit pointers stable across profile moves.
    std::vector<std::unique_ptr<TargetStorage>> storage;

    Profile() = default;
    Profile(const Profile &) = delete;
    Profile &operator=(const Profile &) = delete;
    Profile(Profile &&) noexcept = default;
    Profile &operator=(Profile &&) noexcept = default;
};

namespace profile_detail {
using json = nlohmann::json;
using ResourceKey = std::pair<std::uint64_t, std::uint64_t>;
using OwnedSource = std::tuple<std::uint32_t, std::uint64_t, std::uint64_t>;
using FieldKey = std::tuple<std::uint32_t, std::uint32_t, std::uint64_t, std::uint64_t>;
using RequiredKey = std::tuple<std::uint32_t, std::uint64_t, std::uint64_t>;

[[noreturn]] inline void reject(const std::string &message) { throw std::runtime_error(message); }

inline void keys(const json &object, std::initializer_list<const char *> expected)
{
    if (!object.is_object() || object.size() != expected.size())
        reject("object fields do not match the runtime schema");
    for (const char *key : expected)
        if (!object.contains(key)) reject(std::string("missing field: ") + key);
}

inline const json &array(const json &value, std::size_t maximum, bool nonempty = true)
{
    if (!value.is_array() || value.size() > maximum || (nonempty && value.empty()))
        reject("invalid array size");
    return value;
}

inline std::string string(const json &value)
{
    if (!value.is_string()) reject("expected a string");
    return value.get<std::string>();
}

inline std::uint32_t integer(const json &value, std::uint32_t maximum)
{
    if (!value.is_number_integer() || (value.is_number_integer() && !value.is_number_unsigned() &&
                                      value.get<std::int64_t>() < 0))
        reject("expected a nonnegative integer");
    const auto result = value.get<std::uint64_t>();
    if (result > maximum) reject("integer is out of range");
    return static_cast<std::uint32_t>(result);
}

inline std::string hex_string(const json &value, std::size_t digits)
{
    auto result = string(value);
    if (result.size() != digits || !std::all_of(result.begin(), result.end(), [](char c) {
            return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
        })) reject("expected fixed-width lowercase hexadecimal text");
    return result;
}

inline std::uint64_t hex(const json &value, std::size_t digits, bool allow_zero = false)
{
    const auto text = hex_string(value, digits);
    std::uint64_t result = 0;
    for (char c : text)
        result = (result << 4) | static_cast<unsigned>(c <= '9' ? c - '0' : c - 'a' + 10);
    if (!allow_zero && result == 0) reject("zero resource or Kit ID is not allowed");
    return result;
}

inline json parse(const std::string &text)
{
    if (text.empty() || text.size() > max_profile_bytes) reject("profile file exceeds the size limit or is empty");
    std::vector<std::set<std::string>> object_keys;
    return json::parse(text, [&](int depth, json::parse_event_t event, json &parsed) {
        if (depth > 32) reject("JSON nesting exceeds 32 levels");
        if (event == json::parse_event_t::object_start) object_keys.emplace_back();
        else if (event == json::parse_event_t::key) {
            if (object_keys.empty() || !object_keys.back().insert(parsed.get<std::string>()).second)
                reject("duplicate JSON object key");
        } else if (event == json::parse_event_t::object_end) object_keys.pop_back();
        return true;
    });
}

inline std::uint64_t kind(const json &value)
{
    const auto result = hex(value, 16);
    if (result != unit_type && result != texture_type && result != material_type)
        reject("unsupported resource type");
    return result;
}

inline std::size_t field_index(std::uint32_t offset)
{
    if (offset == 0) return 0;
    if (offset < 0x18 || offset > 0x50 || offset % 8 != 0)
        reject("piece field is not an allowed resource offset");
    return 1 + (offset - 0x18) / 8;
}

inline std::uint32_t field_offset(std::size_t index)
{
    return index == 0 ? 0 : static_cast<std::uint32_t>(0x18 + (index - 1) * 8);
}

inline void parse_target(const json &input, const std::string &package_id, Profile &output)
{
    keys(input, {"id", "archive", "type", "passive", "bodies"});
    TargetKit target{};
    target.id = static_cast<std::uint32_t>(hex(input.at("id"), 8));
    target.archive = hex(input.at("archive"), 16);
    target.type = integer(input.at("type"), 1);
    target.passive = integer(input.at("passive"), 65535);
    if (!output.target_packages.emplace(target.id, package_id).second)
        reject("multiple packages select the same Kit");
    auto storage = std::make_unique<TargetStorage>();
    std::set<std::uint32_t> body_types;
    for (const auto &body : array(input.at("bodies"), 3)) {
        keys(body, {"type", "pieces"});
        const auto body_type = integer(body.at("type"), 3);
        if (body_type == 2 || !body_types.insert(body_type).second) reject("invalid or duplicate body type");
        const auto &pieces = array(body.at("pieces"), 64);
        storage->bodies.push_back({body_type, static_cast<std::uint32_t>(pieces.size())});
        for (const auto &piece : pieces) {
            keys(piece, {"slot", "type", "weight", "tone_variations", "resources"});
            ExpectedPiece expected{body_type, integer(piece.at("slot"), 9), integer(piece.at("type"), 2),
                                   integer(piece.at("weight"), 2), integer(piece.at("tone_variations"), 255), 0};
            if ((target.type == 1 && expected.slot != 0) || (target.type == 0 && expected.slot == 0))
                reject("piece slot does not belong to the armor or helmet Kit type");
            const auto &references = piece.at("resources");
            keys(references, {"unit", "material_lut", "pattern_lut", "cape_lut", "cape_gradient", "cape_nac",
                              "decal_scalar_fields", "base_data", "decal_sheet"});
            std::array<std::uint64_t, 9> ids{};
            std::size_t index = 0;
            for (const char *name : {"unit", "material_lut", "pattern_lut", "cape_lut", "cape_gradient", "cape_nac",
                                     "decal_scalar_fields", "base_data", "decal_sheet"})
                ids[index++] = hex(references.at(name), 16, std::string(name) != "unit");
            expected.source_unit = ids[0];
            storage->pieces.push_back(expected);
            storage->references.push_back(ids);
            target.expected_unit_changes += expected.slot != 1;
        }
    }
    if (!target.expected_unit_changes) reject("target contains no non-cape pieces");
    target.bodies = storage->bodies.data();
    target.body_count = storage->bodies.size();
    target.pieces = storage->pieces.data();
    target.piece_count = storage->pieces.size();
    output.targets.push_back(target);
    output.storage.push_back(std::move(storage));
}

inline void parse_document(const std::string &filename, const std::string &text, Profile &output)
{
    const auto root = parse(text);
    keys(root, {"schema", "package_id", "expected_game_dll_sha256", "expected_game_version",
                "selected_kit_metadata", "mapping", "piece_fields", "required_resources"});
    if (string(root.at("schema")) != runtime_schema ||
        string(root.at("expected_game_version")) != expected_game_version ||
        hex_string(root.at("expected_game_dll_sha256"), 64) != expected_game_dll_sha256)
        reject("unsupported runtime schema or game version");
    const auto package_id = hex_string(root.at("package_id"), 24);
    if (filename != package_id + ".json") reject("profile filename must equal package_id.json");
    if (std::find(output.package_ids.begin(), output.package_ids.end(), package_id) != output.package_ids.end())
        reject("duplicate package ID");
    output.package_ids.push_back(package_id);
    const auto first_target = output.targets.size();
    for (const auto &target : array(root.at("selected_kit_metadata"), max_targets))
        parse_target(target, package_id, output);
    if (output.targets.size() > max_targets) reject("combined target limit exceeded");
    std::set<std::uint32_t> target_ids;
    for (std::size_t index = first_target; index < output.targets.size(); ++index)
        target_ids.insert(output.targets[index].id);

    std::map<OwnedSource, const ResourceMapping *> sources;
    std::map<ResourceKey, const ResourceMapping *> destinations;
    std::vector<ResourceMapping> resources;
    const auto &mapping = array(root.at("mapping"), max_resources);
    resources.reserve(mapping.size());
    for (const auto &row : mapping) {
        keys(row, {"kit", "type", "source", "target"});
        ResourceMapping resource{static_cast<std::uint32_t>(hex(row.at("kit"), 8, true)), kind(row.at("type")),
                                 hex(row.at("source"), 16), hex(row.at("target"), 16)};
        if ((!resource.kit_id && resource.type == unit_type) ||
            (resource.kit_id && !target_ids.count(resource.kit_id)) || resource.source == resource.target)
            reject("resource owner is invalid or mapping is unchanged");
        resources.push_back(resource);
        const auto *stable = &resources.back();
        if (!sources.emplace(OwnedSource{resource.kit_id, resource.type, resource.source}, stable).second ||
            !destinations.emplace(ResourceKey{resource.type, resource.target}, stable).second)
            reject("duplicate resource mapping");
    }
    std::set<RequiredKey> required;
    std::set<ResourceKey> used_resources;
    for (const auto &row : array(root.at("required_resources"), max_required_resources)) {
        keys(row, {"kit", "type", "target"});
        RequiredResource entry{static_cast<std::uint32_t>(hex(row.at("kit"), 8)), kind(row.at("type")),
                               hex(row.at("target"), 16)};
        const auto found = destinations.find({entry.type, entry.target});
        if (!target_ids.count(entry.kit_id) || found == destinations.end() ||
            (found->second->kit_id && found->second->kit_id != entry.kit_id) ||
            !required.emplace(entry.kit_id, entry.type, entry.target).second)
            reject("required resource has invalid ownership or is duplicated");
        used_resources.emplace(entry.type, entry.target);
        output.required_resources.push_back(entry);
        output.requirements_by_kit[entry.kit_id].emplace(entry.type, entry.target);
    }
    for (const auto &resource : resources) {
        if (!used_resources.count({resource.type, resource.target}) ||
            (resource.kit_id && !required.count({resource.kit_id, resource.type, resource.target})))
            reject("resource is missing from its target dependency list");
    }

    std::set<FieldKey> fields;
    std::set<std::tuple<std::uint32_t, std::uint32_t, std::uint64_t>> field_sources;
    for (const auto &row : array(root.at("piece_fields"), max_fields)) {
        keys(row, {"kit", "offset", "source", "target"});
        FieldMapping field{static_cast<std::uint32_t>(hex(row.at("kit"), 8)), integer(row.at("offset"), 0x50),
                           hex(row.at("source"), 16), hex(row.at("target"), 16)};
        field_index(field.field_offset);
        if (!target_ids.count(field.kit_id) || field.source == field.target ||
            !field_sources.emplace(field.kit_id, field.field_offset, field.source).second)
            reject("invalid or duplicate piece field");
        fields.emplace(field.kit_id, field.field_offset, field.source, field.target);
        output.piece_fields.push_back(field);
    }
    std::set<FieldKey> expected_fields;
    std::set<OwnedSource> used_units;
    for (std::size_t index = first_target; index < output.targets.size(); ++index) {
        const auto &target = output.targets[index];
        const auto &storage = *output.storage[index];
        for (std::size_t piece_index = 0; piece_index < storage.pieces.size(); ++piece_index) {
            if (storage.pieces[piece_index].slot == 1) continue;
            for (std::size_t field = 0; field < 9; ++field) {
                const auto source = storage.references[piece_index][field];
                const auto type = field == 0 ? unit_type : texture_type;
                const auto owned = sources.find({target.id, type, source});
                const auto shared = sources.find({0, type, source});
                if (owned != sources.end() && shared != sources.end()) reject("ambiguous owned and shared resource");
                const auto *resource = owned != sources.end() ? owned->second :
                                       shared != sources.end() ? shared->second : nullptr;
                if (!resource) {
                    if (field == 0) reject("non-cape Unit has no private mapping");
                    continue;
                }
                if (!required.count({target.id, type, resource->target}))
                    reject("piece resource is missing from its target dependency list");
                expected_fields.emplace(target.id, field_offset(field), source, resource->target);
                if (field == 0) used_units.emplace(target.id, type, source);
            }
        }
    }
    if (fields != expected_fields) reject("piece fields do not exactly match the declared target resources");
    for (const auto &resource : resources)
        if (resource.type == unit_type && !used_units.count({resource.kit_id, resource.type, resource.source}))
            reject("Unit mapping does not belong to a non-cape target piece");
    output.resources.insert(output.resources.end(), resources.begin(), resources.end());
    if (output.resources.size() > max_resources || output.piece_fields.size() > max_fields ||
        output.required_resources.size() > max_required_resources)
        reject("combined resource, field or dependency limit exceeded");
}

inline void validate_combined(const Profile &profile)
{
    std::set<std::uint64_t> destinations, originals;
    std::set<std::uint32_t> destination_high, original_high;
    for (const auto &resource : profile.resources) {
        if (!destinations.insert(resource.target).second ||
            !destination_high.insert(static_cast<std::uint32_t>(resource.target >> 32)).second)
            reject("private resource ID or high32 collision across profiles");
        originals.insert(resource.source);
        original_high.insert(static_cast<std::uint32_t>(resource.source >> 32));
    }
    for (const auto &storage : profile.storage)
        for (const auto &references : storage->references)
            for (const auto original : references)
                if (original) {
                    originals.insert(original);
                    original_high.insert(static_cast<std::uint32_t>(original >> 32));
                }
    for (const auto destination : destinations)
        if (originals.count(destination) || original_high.count(static_cast<std::uint32_t>(destination >> 32)))
            reject("private resource aliases an original resource across profiles");
}
} // namespace profile_detail

inline bool load_documents(const std::vector<std::pair<std::string, std::string>> &documents,
                           Profile &output, std::string &error)
{
    try {
        if (documents.size() > max_profile_files) profile_detail::reject("too many runtime profile files");
        Profile candidate;
        std::size_t bytes = 0;
        for (const auto &[name, text] : documents) {
            if (text.size() > max_total_profile_bytes - bytes)
                profile_detail::reject("combined runtime profile size limit exceeded");
            bytes += text.size();
            try { profile_detail::parse_document(name, text, candidate); }
            catch (const std::exception &exception) { profile_detail::reject(name + ": " + exception.what()); }
        }
        profile_detail::validate_combined(candidate);
        output = std::move(candidate);
        error.clear();
        return true;
    } catch (const std::exception &exception) {
        error = exception.what();
        return false;
    }
}

inline bool load_files(const std::vector<std::filesystem::path> &paths, Profile &output, std::string &error)
{
    try {
        if (paths.size() > max_profile_files) profile_detail::reject("too many runtime profile files");
        std::vector<std::pair<std::string, std::string>> documents;
        std::size_t total = 0;
        for (const auto &path : paths) {
            if (!std::filesystem::is_regular_file(path)) profile_detail::reject("profile is not a regular file");
            const auto length = std::filesystem::file_size(path);
            if (!length || length > max_profile_bytes || length > max_total_profile_bytes - total)
                profile_detail::reject("runtime profile file size limit exceeded");
            total += static_cast<std::size_t>(length);
            std::ifstream stream(path, std::ios::binary);
            std::string text(static_cast<std::size_t>(length), '\0');
            if (!stream.read(text.data(), static_cast<std::streamsize>(text.size())) || stream.peek() != EOF)
                profile_detail::reject("runtime profile changed while reading or could not be read");
            documents.emplace_back(path.filename().string(), std::move(text));
        }
        return load_documents(documents, output, error);
    } catch (const std::exception &exception) {
        error = exception.what();
        return false;
    }
}

inline bool load_directory(const std::filesystem::path &directory, Profile &output, std::string &error)
{
    try {
        if (!std::filesystem::is_directory(directory)) profile_detail::reject("runtime profile directory is missing");
        std::vector<std::filesystem::path> paths;
        for (const auto &entry : std::filesystem::directory_iterator(directory)) {
            if (entry.path().extension() != ".json") continue;
            if (!entry.is_regular_file()) profile_detail::reject("JSON profile entry is not a regular file");
            paths.push_back(entry.path());
            if (paths.size() > max_profile_files) profile_detail::reject("too many runtime profile files");
        }
        std::sort(paths.begin(), paths.end());
        return load_files(paths, output, error);
    } catch (const std::exception &exception) {
        error = exception.what();
        return false;
    }
}

} // namespace universal_isolation
