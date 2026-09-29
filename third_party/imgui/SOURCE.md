# Dear ImGui headers

- Upstream: <https://github.com/ocornut/imgui/tree/v1.91.9b-docking>
- Version: 1.91.9b, `IMGUI_VERSION_NUM 19191`
- License: MIT, see `LICENSE.txt`
- Reason: ReShade 6.5.1 (API 17) checks `IMGUI_VERSION_NUM` in `reshade_overlay.hpp` and errors out on any other value.

Only the headers are vendored. The add-on never compiles or links `imgui.cpp`; ReShade owns the
ImGui context and exposes it through the function table that `reshade_overlay.hpp` populates.

| File | Bytes | SHA-256 |
| --- | --- | --- |
| `imgui.h` | 409679 | `ea876e477f06f9619206284551638171c7ba4ed4dbc6ba67002e8f2e4ad7d3c7` |
| `imconfig.h` | 11579 | `0884061cc43e27e1d346fe18dcd1425792eb2532d3d16610a82eb5ac751f7594` |
| `LICENSE.txt` | 1083 | `c80c5789748d955c4a650562baa0d750494e2c7128c2ca66aaebe2e3c4e198bf` |

The copies match the files already used by `hd2-lua_mods_test/experiments/armor_ui_swap/native`.
