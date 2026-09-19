#include "armor_runtime_profile.hpp"
#include <cstdio>
#include <filesystem>
#include <string>

int wmain(int argc, wchar_t **argv) {
    if (argc != 2) {
        std::fputs("Usage: validate_runtime_profile.exe <package.json|configuration-directory>\n", stderr);
        return 2;
    }
    try {
        const std::filesystem::path input(argv[1]);
        universal_isolation::Profile profile;
        std::string error;
        const bool valid = std::filesystem::is_directory(input) ?
            universal_isolation::load_directory(input, profile, error) :
            universal_isolation::load_files({input}, profile, error);
        if (!valid) {
            std::fprintf(stderr, "PROFILE_INVALID: %s\n", error.c_str());
            return 1;
        }
        std::printf("PROFILE_OK packages=%zu targets=%zu resources=%zu fields=%zu required=%zu\n",
            profile.package_ids.size(), profile.targets.size(), profile.resources.size(),
            profile.piece_fields.size(), profile.required_resources.size());
        for (const auto &target : profile.targets) {
            std::printf("package=%s kit=%08x bodies=%zu pieces=%zu unit_changes=%zu\n",
                profile.target_packages.at(target.id).c_str(), target.id,
                static_cast<size_t>(target.body_count), static_cast<size_t>(target.piece_count),
                static_cast<size_t>(target.expected_unit_changes));
        }
        return 0;
    } catch (const std::exception &exception) {
        std::fprintf(stderr, "PROFILE_INVALID: %s\n", exception.what());
        return 1;
    }
}
