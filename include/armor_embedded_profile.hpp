#pragma once

#include "armor_runtime_profile.hpp"

namespace universal_isolation {
namespace embedded_detail {
inline constexpr char magic[17] = "HD2ARMORPROFILE\0";
inline constexpr std::size_t footer_size = 64;

inline std::uint64_t little(const unsigned char *data, std::size_t count)
{
    std::uint64_t value = 0;
    for (std::size_t i = 0; i < count; ++i) value |= std::uint64_t(data[i]) << (8 * i);
    return value;
}

inline std::uint32_t crc32(const std::string &text)
{
    std::uint32_t crc = 0xffffffffU;
    for (unsigned char byte : text) {
        crc ^= byte;
        for (int bit = 0; bit < 8; ++bit) crc = (crc >> 1) ^ (0xedb88320U & (0U - (crc & 1)));
    }
    return ~crc;
}

inline bool patch_name(const std::filesystem::path &path)
{
    const auto name = path.filename().wstring();
    if (name.size() < 24 || name.substr(16, 7) != L".patch_") return false;
    for (std::size_t i = 0; i < 16; ++i)
        if (!((name[i] >= L'0' && name[i] <= L'9') || (name[i] >= L'a' && name[i] <= L'f') ||
              (name[i] >= L'A' && name[i] <= L'F'))) return false;
    return std::all_of(name.begin() + 23, name.end(), [](wchar_t c) { return c >= L'0' && c <= L'9'; });
}

inline bool read_patch(const std::filesystem::path &path, std::string &text)
{
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    if (!stream) profile_detail::reject("cannot open installed patch");
    const auto end = stream.tellg();
    if (end < 0) profile_detail::reject("cannot read patch size");
    const auto length = static_cast<std::uint64_t>(end);
    if (length < footer_size) return false;
    std::array<unsigned char, footer_size> footer{};
    stream.seekg(static_cast<std::streamoff>(length - footer_size));
    if (!stream.read(reinterpret_cast<char *>(footer.data()), footer.size()))
        profile_detail::reject("cannot read patch footer");
    if (!std::equal(footer.begin(), footer.begin() + 16, magic)) return false;
    const auto offset = little(footer.data() + 24, 8), size = little(footer.data() + 32, 8);
    if (little(footer.data() + 16, 4) != 1 || little(footer.data() + 20, 4) != footer_size ||
        !std::all_of(footer.begin() + 44, footer.end(), [](unsigned char c) { return c == 0; }) ||
        !size || size > max_profile_bytes || offset < 72 || offset > length - footer_size ||
        size != length - footer_size - offset)
        profile_detail::reject("invalid embedded profile footer");
    std::array<unsigned char, 4> header{};
    stream.seekg(0);
    if (!stream.read(reinterpret_cast<char *>(header.data()), header.size()) || little(header.data(), 4) != 0xf0000011)
        profile_detail::reject("embedded profile is not attached to a game patch");
    text.resize(static_cast<std::size_t>(size));
    stream.seekg(static_cast<std::streamoff>(offset));
    if (!stream.read(text.data(), static_cast<std::streamsize>(size)) || crc32(text) != little(footer.data() + 40, 4))
        profile_detail::reject("embedded profile checksum mismatch or truncated payload");
    if (std::filesystem::file_size(path) != length) profile_detail::reject("patch changed while reading");
    return true;
}
} // namespace embedded_detail

// Validate the whole group before publishing. Identical component copies and
// a matching legacy sidecar count as one package; differing copies are errors.
inline bool load_package_files(const std::vector<std::filesystem::path> &paths, Profile &output, std::string &error)
{
    try {
        std::map<std::string, std::string> unique;
        std::size_t total = 0;
        for (const auto &path : paths) {
            try {
                if (!std::filesystem::is_regular_file(path)) profile_detail::reject("package input is not a regular file");
                std::string text;
                const bool embedded = embedded_detail::patch_name(path);
                if (embedded) {
                    if (!embedded_detail::read_patch(path, text)) continue;
                } else {
                    if (path.extension() != ".json") profile_detail::reject("expected main patch or legacy JSON");
                    const auto length = std::filesystem::file_size(path);
                    if (!length || length > max_profile_bytes) profile_detail::reject("runtime profile file size limit exceeded");
                    text.resize(static_cast<std::size_t>(length));
                    std::ifstream stream(path, std::ios::binary);
                    if (!stream.read(text.data(), static_cast<std::streamsize>(length)) || stream.peek() != EOF)
                        profile_detail::reject("cannot read legacy profile");
                }
                const auto root = profile_detail::parse(text);
                const auto id = profile_detail::hex_string(root.at("package_id"), 24);
                if (!embedded && path.filename() != std::filesystem::path(id + ".json"))
                    profile_detail::reject("profile filename must equal package_id.json");
                const auto canonical = root.dump();
                const auto found = unique.find(id);
                if (found != unique.end()) {
                    if (found->second != canonical) profile_detail::reject("different configurations claim the same package ID");
                    continue;
                }
                if (unique.size() >= max_profile_files || canonical.size() > max_total_profile_bytes - total)
                    profile_detail::reject("combined package configuration limit exceeded");
                total += canonical.size();
                unique.emplace(id, canonical);
            } catch (const std::exception &exception) {
                profile_detail::reject(path.u8string() + ": " + exception.what());
            }
        }
        std::vector<std::pair<std::string, std::string>> documents;
        for (auto &[id, text] : unique) documents.emplace_back(id + ".json", std::move(text));
        return load_documents(documents, output, error);
    } catch (const std::exception &exception) { error = exception.what(); return false; }
}

inline bool load_installed_packages(const std::filesystem::path &data, const std::filesystem::path &legacy,
                                    Profile &output, std::string &error)
{
    try {
        if (!std::filesystem::is_directory(data)) profile_detail::reject("game data directory is missing");
        std::vector<std::filesystem::path> paths;
        // Never recurse into backups, disabled mods, or option source folders.
        for (const auto &entry : std::filesystem::directory_iterator(data))
            if (embedded_detail::patch_name(entry.path())) paths.push_back(entry.path());
        if (!legacy.empty() && std::filesystem::exists(legacy))
            for (const auto &entry : std::filesystem::directory_iterator(legacy))
                if (entry.path().extension() == ".json") paths.push_back(entry.path());
        std::sort(paths.begin(), paths.end());
        return load_package_files(paths, output, error);
    } catch (const std::exception &exception) { error = exception.what(); return false; }
}
} // namespace universal_isolation
