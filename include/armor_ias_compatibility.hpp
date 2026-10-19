#pragma once

#include <Windows.h>
#include <string>

namespace armor_ias {

// Resource ownership describes Units, not permission to replace an equipment
// Kit or its transmog carrier. Do not call IAS exports to authorize Kit writes.
class Peer {
    HMODULE module_ = nullptr;
public:
    Peer() { GetModuleHandleExW(0, L"HD2IndependentRig.addon64", &module_); }
    ~Peer() { if (module_) FreeLibrary(module_); }
    Peer(const Peer &) = delete;
    Peer &operator=(const Peer &) = delete;
    HMODULE module() const noexcept { return module_; }
};

struct Session {
    HMODULE observed = nullptr;
    bool seen = false, published = false, restart_required = false;
    bool handoff_checked = false, handoff_prepared = false;
    std::string handoff_detail;
    std::string reason;

    bool observe(const Peer &peer) {
        if (!peer.module()) {
            if (seen) {
                restart_required = true;
                reason = "HD2IAS unloaded after detection; isolation remains paused for this session";
            }
            return !seen;
        }
        if (!seen) {
            seen = true;
            observed = peer.module();
            if (published) {
                restart_required = true;
                reason = "HD2IAS appeared after isolation publication; published Kits cannot be restored live";
            }
        } else if (observed != peer.module()) {
            restart_required = true;
            reason = "HD2IAS module changed; isolation remains paused for this session";
        }
        if (!restart_required)
            reason = "HD2IAS selected as the isolation backend; own Kit writes and native startup are disabled; "
                "no IAS native exports are called";
        return false;
    }
};

} // namespace armor_ias
