#include "armor_embedded_profile.hpp"
#include "armor_local_data.hpp"
#include "armor_native_compatibility.hpp"
#include <cstdio>
#include <filesystem>
#include <string>

DWORD find_game_process(const std::filesystem::path &directory) {
    const auto expected = std::filesystem::weakly_canonical(directory / L"bin/helldivers2.exe");
    const HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snapshot == INVALID_HANDLE_VALUE) throw std::runtime_error("cannot enumerate processes");
    PROCESSENTRY32W entry{};
    entry.dwSize = sizeof(entry);
    DWORD found = 0;
    if (Process32FirstW(snapshot, &entry)) do {
        if (_wcsicmp(entry.szExeFile, L"helldivers2.exe") != 0) continue;
        const HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, entry.th32ProcessID);
        if (!process) continue;
        std::array<wchar_t, 32768> path{};
        DWORD size = static_cast<DWORD>(path.size());
        const BOOL valid = QueryFullProcessImageNameW(process, 0, path.data(), &size);
        CloseHandle(process);
        if (valid && _wcsicmp(path.data(), expected.c_str()) == 0) {
            if (found) { CloseHandle(snapshot); throw std::runtime_error("multiple matching game processes"); }
            found = entry.th32ProcessID;
        }
    } while (Process32NextW(snapshot, &entry));
    CloseHandle(snapshot);
    if (!found) throw std::runtime_error("selected game is not running or cannot be inspected");
    return found;
}

int wmain(int argc, wchar_t **argv) {
    if (argc < 2) {
        std::fputs("Usage: validate_runtime_profile.exe <package.json|main.patch_N|JSON-directory> | --inputs <files...> | --patches <data-directory> [legacy-directory]\n", stderr);
        return 2;
    }
    try {
        const std::filesystem::path input(argv[1]);
        if ((input == L"--capture-local" || input == L"--capture-game") && argc == 4) {
            wchar_t *end = nullptr;
            const auto pid_value = input == L"--capture-game" ? find_game_process(argv[2]) : std::wcstoul(argv[2], &end, 10);
            if (!pid_value || (input == L"--capture-local" && (!end || *end))) throw std::runtime_error("invalid process id");
            const DWORD pid = static_cast<DWORD>(pid_value);
            const HANDLE modules = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, pid);
            if (modules == INVALID_HANDLE_VALUE) throw std::runtime_error("cannot enumerate game modules");
            uintptr_t game = 0, exe = 0;
            std::filesystem::path game_path;
            std::filesystem::path exe_path;
            bool executable = false, isolation_loaded = false;
            MODULEENTRY32W entry{};
            entry.dwSize = sizeof(entry);
            if (Module32FirstW(modules, &entry)) do {
                std::wstring name(entry.szModule);
                std::transform(name.begin(), name.end(), name.begin(), ::towlower);
                if (name == L"armorisolation.addon64" || name == L"cm14isolation.addon64" ||
                    name == L"b01isolation.addon64" || name.find(L"armorisolation_") == 0) isolation_loaded = true;
                if (_wcsicmp(entry.szModule, L"game.dll") == 0) {
                    game = reinterpret_cast<uintptr_t>(entry.modBaseAddr);
                    game_path = entry.szExePath;
                }
                if (_wcsicmp(entry.szModule, L"helldivers2.exe") == 0) {
                    executable = true;
                    exe = reinterpret_cast<uintptr_t>(entry.modBaseAddr);
                    exe_path = entry.szExePath;
                }
            } while (Module32NextW(modules, &entry));
            CloseHandle(modules);
            if (!game || !executable) throw std::runtime_error("Helldivers 2 game module not found");
            const HANDLE process = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, FALSE, pid);
            if (!process) throw std::runtime_error("cannot open game for read-only observation");
            nlohmann::json report;
            try {
                report = armor_local_data::capture(process, game, game_path);
                report["snapshot_stage"] = isolation_loaded ? "observed_only" : "without_isolation";
                {
                    try {
                        armor_native::attach_evidence(report, process, game, exe, game_path, exe_path);
                    } catch (const std::exception &error) { report["native_compatibility_error"] = error.what(); }
                }
            }
            catch (...) { CloseHandle(process); throw; }
            CloseHandle(process);
            armor_local_data::save(argv[3], report);
            std::printf("[LOCAL_DATA] status=%s kits=%zu write_authorized=false\n",
                report.at("status").get<std::string>().c_str(), report.value("kits", nlohmann::json::array()).size());
            return report.at("status") == "observed_layout_candidate" ? 0 : 1;
        }
        universal_isolation::Profile profile;
        std::string error;
        bool valid = false;
        if (input == L"--inputs" && argc >= 3) {
            std::vector<std::filesystem::path> paths;
            for (int i = 2; i < argc; ++i) paths.emplace_back(argv[i]);
            valid = universal_isolation::load_package_files(paths, profile, error);
        } else if (input == L"--patches" && (argc == 3 || argc == 4)) {
            valid = universal_isolation::load_installed_packages(argv[2], argc == 4 ? argv[3] : L"", profile, error);
        } else if (argc == 2) {
            valid = std::filesystem::is_directory(input) ?
                universal_isolation::load_directory(input, profile, error) :
                universal_isolation::load_package_files({input}, profile, error);
        } else error = "invalid arguments";
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
