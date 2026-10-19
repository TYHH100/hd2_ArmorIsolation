#include <atomic>
#include <cstdint>

namespace {
std::atomic<uint32_t> result{0x6400};
std::atomic<uint64_t> managed{0};
std::atomic<uint32_t> ownership_calls{0};
}

extern "C" __declspec(dllexport) void ias_fixture_configure(uint32_t reply, uint64_t unit) {
    managed.store(unit);
    result.store(reply);
    ownership_calls.store(0);
}

extern "C" __declspec(dllexport) uint32_t ias_fixture_ownership_calls() {
    return ownership_calls.load();
}

extern "C" __declspec(dllexport) uint32_t hd2ir_native_resource_ownership_v2(const uint64_t *units, uint32_t count) {
    ++ownership_calls;
    if (!units || count != 1) return 0x100;
    const auto reply = result.load();
    return reply == 1 && *units == managed.load() ? 2 : reply;
}
