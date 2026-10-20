# Armor Isolation: Resource Graph Rewriting and Runtime Kit Redirection

Implementation described: October 20, 2026. Windows x64, universal `ArmorIsolation.addon64` backend, ReShade 6.5.1 / SDK API 17.

## 1. The underlying sharing problem

Armor Isolation separates cosmetic replacements that would otherwise propagate through shared game resources. The relevant distinction is between an equipment item's identity and the resources used to construct its appearance.

A **Kit** identifies an equipment configuration. It contains **Body** groups, which contain **Piece** records. A Piece stores a model **Unit** reference and additional appearance-resource references. A Unit in turn references materials and a bones resource; materials reference textures and may reference a base material. These are separate levels of indirection.

Two different Kits can point to the same Unit. Two different Units can also share a material or texture. Consequently, replacing one resource under its original ID can change every equipment item that reaches that resource through the reference graph.

Consider a simplified original graph:

```text
Kit A -> Piece -> Unit U -> Material M -> Texture T
Kit B -> Piece -> Unit U -> Material M -> Texture T
```

Replacing the contents of `U` while keeping its original ID affects both Kits. Renaming the patch file does not change that relationship: the references still resolve to the same internal resource ID.

The desired graph for isolating Kit A is:

```text
Kit A -> private configuration -> Unit U_A -> Material M_P -> Texture T_P
Kit B -> original configuration -> Unit U   -> Material M   -> Texture T
```

`U_A` is private to the selected Kit. `M_P` and `T_P` are private to the generated package and may be reused by other selected Units within that package. Isolation from the original resources does not require duplicating every texture for every variant.

This requires two coordinated transformations:

1. An **offline resource transformation** creates the private resources and rewrites their dependencies.
2. A **runtime configuration transformation** redirects selected Kits to the private resource graph.

Private resources alone are unreachable if the Kit still references the original Unit. A redirected Unit alone is insufficient if its material and texture references still lead into shared modified resources.

## 2. Resource identity and namespace construction

Resources are identified by a pair:

```text
ResourceKey = (64-bit resource type, 64-bit resource ID)
```

The supported resource classes are:

| Type | Type ID | Relevant dependencies |
| --- | --- | --- |
| Unit | `e0a48d0be9a7453f` | Materials and bones |
| Material | `eac0b497876adedf` | Base material and textures |
| Texture | `cd4238c6a0c69e32` | Copied payload in the supported transformation |
| Bones | `18dead01056b72e9` | Validated and copied as a complete bones payload |

A numeric ID without its resource type is not enough to identify a dependency. The ownership dimension is also necessary: the same original Unit can need different private copies for different Kits.

For the generic generator, package identity is derived from a canonical JSON description containing the three source-lane hashes, selected target IDs, transformation-rule identity, supplied coexistence information, and applicable game-compatibility identity. A SHA-256 digest is truncated to 24 hexadecimal characters for the package identifier. Modular generation adds its component/variant identity through its own package-identity path.

A private resource name is constructed under a namespace of the following form:

```text
mods/armor_isolation/v1/<package-id>/kit_<owner>/<resource-kind>/<original-id>
```

The ASCII name is hashed with MurmurHash64A to obtain the new resource ID. `owner` is the target Kit for Units and the shared package scope for supported shared materials, textures, and bones. If a candidate ID conflicts with the reserved set, a numeric salt is appended and hashing is repeated.

The allocator rejects zero, an occupied full 64-bit ID, and an occupied upper 32-bit value. The upper-half restriction is an additional implementation collision constraint; it is not a claim that every engine operation treats a 64-bit resource ID as only 32 bits.

The reserved set includes the supported known game/source resources and explicitly supplied coexisting private resources. This is deterministic collision avoidance within that evidence, not a guarantee against every unrelated mod that might later be installed. At runtime, installed isolation configurations are checked together for conflicts. Two packages targeting the same Kit are still incompatible even if their private resource IDs differ.

## 3. Rewriting references without corrupting other identifiers

The generator parses resource-specific fields rather than replacing every matching eight-byte sequence. A resource ID, a 32-bit material-slot hash, a bone index, and a mesh selector have different meanings even when their byte values happen to overlap.

In the supported binary layouts:

- A Unit's 64-bit field at `+0x08` references a **bones resource**. It is not the Unit's own ID.
- The Unit's material-table offset is read at `+0x70`. The table contains a count, a 32-bit identifier array, and a 64-bit material-reference array. Only the typed material references are remapped.
- A Material's base-material reference is at `+0x18`. Its texture count is at `+0x40`; texture references follow the slot identifiers in the table beginning at `+0x88`.
- Bones data is bounds-checked for its arrays and terminated names, then copied under its private ID. Joint and skinning data are not globally renumbered as resource references.

Conceptually, a typed reference is transformed as follows:

```text
for each parsed (referenced_type, field_offset):
    original_id = read_u64(payload, field_offset)
    if (referenced_type, original_id) belongs to the mapping:
        write_u64(payload, field_offset, private_id)
    else:
        record an external dependency
```

An external dependency is not automatically an error. An unchanged stock dependency can remain external. A dependency that would reconnect the private graph to modified shared textures or an affected base material requires additional handling; unsupported cloning cases are rejected.

The generator follows actual selected-Unit dependencies. It does not copy every material and texture in a large source mod into every target Kit. For modular inputs, it resolves component selection and mutually exclusive branches before evaluating whether each allowed configuration can supply its dependencies. A resource found in one exclusive branch is not assumed to exist in another.

## 4. Archive reconstruction and LOD integrity

The generated archive has three physical lanes: main data, stream data, and GPU resources. Resource renaming is accompanied by TOC reconstruction, not just a filename change.

The writer rebuilds resource ordering and type counts, recalculates disk offsets and sizes, preserves the lane-specific alignment requirements, and recomputes the main/GPU in-memory buffer offsets and aggregate sizes. In the supported format, those memory-buffer positions advance by each resource size rounded up to 256 bytes. They are distinct from physical file offsets.

A zero-size segment has no bytes to read. Its aligned offset may lie beyond the physical end of a lane; bounds checks apply to nonempty segments. Nonempty out-of-range or overlapping segments are rejected.

There is a separate model-integrity issue: a replacement Unit can add helper meshes, moving the positions of existing MeshInfo entries. An unchanged numerical LOD selector can then choose a different mesh. Resource-ID isolation does not repair that automatically.

The LOD transformation matches the MeshInfo identity selected by the original Unit to its position in the replacement Unit:

```text
new_selector = replacement_index(original_mesh_identity[original_selector])
```

It does not add a fixed offset to all selectors. Duplicate identities, partial loss of the required original mesh set, incompatible selector counts, and conflicting author edits during a required remap are rejected. If the selected original meshes have not moved, the author's valid LOD order is retained. A fully custom model with none of those original selected mesh identities retains its own validated selectors because there is no justified correspondence to impose.

The completed resources and configuration are validated in a tool-owned temporary directory before output publication. This generation phase does not install the result into the game or edit the source mod.

## 5. How the runtime learns what to redirect

The generated configuration describes a constrained transformation plan:

```text
package identity and build identity
selected Kit metadata
    Kit ID, Archive ID, type, passive ID
    Body types and Piece counts
    Piece slot, type, weight, tone variation, source Unit
resource mappings
    (owner, resource type, original ID, private ID)
Piece field mappings
    (Kit ID, field offset, expected original ID, private ID)
required resources per Kit
    (resource type, private ID)
```

This is declarative input. It supplies expected values and resource substitutions, not arbitrary process addresses, machine code, or callable function pointers.

The current transport appends the JSON configuration and a 64-byte footer to the generated main `.patch_N`. The footer stores a format marker/version, payload location and length, and CRC-32. The loader verifies bounds, patch magic, reserved bytes, payload checksum, and stable file size. CRC-32 detects payload corruption; it is not an authenticity signature.

The footer does not become a game resource and does not require the plugin to modify the resource TOC while loading it. The existing generated resource segments precede this appended metadata. Stream/GPU companions do not receive the configuration footer.

The plugin scans only active main-patch names in the top-level game `data` directory, with legacy JSON support. Multiple component patches can carry the same package configuration. Matching copies are deduplicated by package identity; different contents claiming the same identity reject the group. Installed configuration identities, target ownership, resource collisions, field plans, and dependency declarations are validated before target publication begins.

Group validation and runtime publication have different granularity: a malformed/conflicting configuration group is rejected together, but valid targets become ready and publish independently. The runtime does not offer an atomic all-Kit commit or roll back earlier valid targets when another target is still waiting for a resource.

## 6. The Kit/Body/Piece memory model

The native backend uses the following supported x64 layout. These offsets describe the implementation's accepted data model, not a promise about every future game build.

| Record | Size | Fields relevant to isolation |
| --- | --- | --- |
| Kit | `0x40` bytes | ID `+0x00`, passive `+0x1c`, Archive `+0x20`, type `+0x28`, Body pointer `+0x30`, Body count `+0x38` |
| Body | `0x18` bytes | Body type `+0x00`, Piece pointer `+0x08`, Piece count `+0x10` |
| Piece | `0x60` bytes | Unit ID `+0x00`, slot `+0x08`, type `+0x0c`, weight `+0x10`, appearance references `+0x18` through `+0x50`, tone variation `+0x58` |

Slot and Piece type are separate fields. The relevant slots are head `0`, cape `1`, torso `2`, and hips `3`. The backend leaves Slot 1 pieces unchanged, including default-cape metadata that can appear in a helmet Kit.

The discovered Kit global points to a store containing the Kit-pointer table and its count:

```text
loaded game.dll base + validated Kit-store RVA
    -> store
        +0x00 -> Kit* table
        +0x08 -> count

table[i] -> Kit -> Body[] -> Piece[]
```

Each poll builds an index from Kit ID to its table-entry address and current pointer. A target must have exactly one readable match. Duplicate IDs are not resolved by selecting the first entry. The built-in path expects its baseline table count; the validated native path accepts a bounded count up to 4096.

The index is a lookup aid for that poll, not a persistent proof of memory identity. The target read verifies the current store, table, count, entry pointer, Kit fields, Body metadata, Piece arrays, and source resource references against the generated profile.

## 7. Constructing a private configuration copy

The backend reads the source configuration into a flattened byte snapshot:

```text
[ Kit: 64 bytes ][ Body records: 24 bytes each ][ Piece records: 96 bytes each ]
```

Its total size is:

```text
64 + 24 * body_count + 96 * total_piece_count
```

Flattening records the bytes needed for comparison and cloning; it does not modify the original records. The candidate begins as a copy of this snapshot, preserving fields that are not part of the allowed transformation.

Candidate construction checks the Kit ID, Archive, equipment type, passive ID, Body types/counts, Piece slot/type/weight/tone metadata, and original Unit values. Planned appearance fields must match their declared source values. The transformation accepts only the Unit reference and the supported aligned 64-bit appearance-resource fields. It rejects empty, unchanged, duplicated, or inconsistent substitutions and validates the expected number of Unit changes.

The passive ID is checked and copied, not replaced with a value chosen by the mod. Preserving this identifier describes the code's transformation boundary; it does not independently prove every possible asset input has only cosmetic effects.

After dependencies are observed ready, the backend reserves and commits a non-executable `PAGE_READWRITE` allocation. It copies the candidate there and fixes internal pointers to addresses within that allocation:

```text
clone_base
    + Kit
        bodies = clone_base + 64
    + Body[0..B-1]
        pieces = clone_base + 64 + 24*B + 96*first_piece_index
    + Piece[0..P-1]
        Unit/appearance IDs = planned private IDs
```

Without this pointer fixup, copying the Kit bytes alone would leave the clone referencing the original Body/Piece arrays, defeating ownership separation.

The game has not been redirected at this point. The new block is a prepared candidate owned by the plugin's publication process.

## 8. Dependency readiness is more than finding an ID

A patch being present on disk does not establish that its model, material, texture, or bones resource is online in the game's resource manager.

The probe follows the validated application global to the ResourceManager, then traverses the supported type table, per-type name table, and resource records. It uses bounded hash-chain lookup rather than scanning the entire resource table for each dependency.

The implementation distinguishes `ready`, `pending`, `missing`, `unreadable`, `incompatible`, and `redirected`. A matching name entry is insufficient if it contains the pending-resource sentinel, an out-of-range record index, a null resource pointer, or an unreadable record. A private ID found in either supported resource-redirection map is treated as redirected rather than accepted as the intended private resource.

The probe performs two lookups and compares their supporting snapshots: application/manager pointers, type-table header, type entry, name entry, and resource record. A changing result is treated as pending. The generator supplies the transitive dependency plan; the runtime checks that explicit plan instead of reconstructing the entire material graph from live payloads.

Each Kit waits only for its own required set. Within one poll, a small cache avoids repeated observations of a shared dependency. It does not cache readiness across polls, and publication performs a fresh complete dependency check without accepting that earlier cache as sufficient.

These checks are observations, not engine locks or retained resource handles. Stable reads do not guarantee that a resource cannot unload immediately afterward. This is a concrete limitation of the current backend.

## 9. Publishing the clone: compare, recheck, exchange

Immediately before exposing a clone to the game, the backend repeats the source snapshot read. It compares the store/table/count, original Kit pointer, original Body/Piece pointers, and complete flattened bytes. With the shared per-poll index, it also compares the complete current Kit-pointer table to the table expected by that poll.

It then rechecks all required resources and the backend-ownership guard. A mismatch discards the unpublished allocation and defers or rejects publication.

Publication itself is one aligned pointer exchange:

```cpp
// Schematic equivalent of the publication operation.
observed = InterlockedCompareExchangePointer(
    address_of_target_table_entry,
    clone_pointer,
    expected_original_pointer);

success = (observed == expected_original_pointer);
```

Before the exchange, `VirtualQuery` confirms that the slot is committed, aligned, within the region, and already writable as `PAGE_READWRITE` or `PAGE_WRITECOPY`. This path does not change a protected page to writable. Structured exception handling contains a page-access failure at the exchange.

The new allocation is fully constructed before publication. The game-owned write is the eight-byte table entry; candidate construction and internal pointer fixups write into the new allocation. No executable instruction replacement is used for this publication mechanism.

On success, the shared index is updated only for this plugin's successful exchange. Other ready Kits can then publish in the same poll while the full-table guard continues to reject unrelated changes. The original game-owned Kit and arrays are left allocated and unmodified by the cloning operation.

CAS provides atomicity for that pointer slot and rejects an unexpected value at that instant. It does not lock the Kit's nested records, suspend engine readers, or make earlier source/resource observations one atomic transaction. The implementation uses repeated validation to narrow those races; it does not claim to eliminate them.

A reader that already retained the old pointer may continue using the old configuration. Consequently, `APPLIED` means the table pointer changed, not that every existing preview or character instance rebuilt its appearance. Switching equipment can cause the game to consume the new configuration.

## 10. Ownership and lifetime after publication

A published clone remains live because the game can retain its address outside the table lookup. The plugin records its address and expected contents and checks later observations for unexpected changes. It does not free a published block merely because the user disables publication.

Unpublished failed candidates are freed. Published configuration memory is not hot-restored or reclaimed during normal operation. A per-target publication limit bounds repeated configuration reload publication; reaching the limit requires a restart.

`Enabled=0` stops subsequent work. `DiagnosticOnly=1` validates a candidate and dependencies but reports `READY` before allocating/publishing a new game configuration. Neither option reverses pointers already published in that process. Installing, replacing, removing, or switching the backend therefore requires a full game restart.

## 11. Native layout discovery and its evidence chain

The automatic-adaptation path reads loaded executable sections of `game.dll` and `helldivers2.exe`. It matches predefined masked native signatures and reviewed complete instruction templates. It is read-only code inspection, separate from the later data-pointer write.

The required evidence includes:

| Evidence | Why it is required |
| --- | --- |
| Kit collection/selection loop | Locates the Kit global through its native reference. |
| `armor_assembly` | Establishes how the native consumer uses Piece Unit, slot, and appearance fields. |
| `material_texture` | Locates and cross-checks the application reference used for resource access. |
| `resource_lookup` and `resource_redirect` | Confirms the supported lookup/redirection behavior. |
| `resource_online` and `type_find` | Checks resource readiness logic and type-lookup call relationships. |

A relative reference is decoded as the instruction RVA plus instruction length plus its signed displacement. It is bounds-checked inside the relevant module. The assembly consumer and collector must reference the same Kit global. Independent application references must agree; the online function's calls must resolve to the matched type-lookup function. The live manager/type tables must also fit the accepted layout.

A matching prologue alone is insufficient. The assembly matcher accepts reviewed instruction families, allowing only specified external-layout operands to vary under group constraints. Piece-field offsets, instruction/register structure, internal branches, and other fixed template bytes remain constrained. Missing or ambiguous matches reject adaptation rather than combining unrelated short matches or learning a new template automatically.

DLL/EXE SHA-256 hashes bind adaptive packages and observations to the relevant files. Hash agreement identifies the build relationship; it does not replace live structural validation. Conversely, a similar native signature is not enough to reuse a package whose required build identity or source Kit metadata differs.

Thus adaptation supports relocation and already-understood layout variations. A new instruction sequence, changed Piece schema, or incompatible resource table still requires implementation review.

## 12. Startup snapshot collection and offline reuse

The startup worker performs native discovery, file hashing, and optional metadata capture before this add-on publishes its own Kit clones. It holds references to the plugin and `game.dll` while reading, then returns an immutable result for the present path to consume. It does not publish Kit pointers from the worker.

Snapshot collection walks the Kit table and reads equipment metadata and resource references. It verifies table identity while walking and compares two complete metadata captures. The exported JSON contains those records, DLL/EXE identity, layout/function evidence, and a Kit-content digest. It is structured metadata, not a complete process dump.

The fixed export is `ArmorIsolation.local-game.json` in the game root. A temporary file is completed before replacement. An existing export must match current build identity and validation requirements before the generator can reuse it. The generator does not authorize runtime writes from addresses stored in that file; the plugin discovers and validates its own live layout.

A separate collector executable uses `OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ)` and `ReadProcessMemory` for manual diagnostics or generation fallback. If isolation is already loaded, externally observed modified metadata is not automatically promoted to a trusted original snapshot for an unknown build. The plugin's startup-before-publication capture is a separate provenance path.

Required native-validation failure prevents unsupported publication. Optional export failure is reported separately and does not invalidate an otherwise accepted runtime layout. Capture is not repeated after publication to reinterpret the plugin's own clones as original game data.

## 13. Independent startup controls

```ini
[ArmorIsolation]
Enabled=1
DiagnosticOnly=0
CaptureLocalSnapshot=1
AutoAdapt=1
```

`CaptureLocalSnapshot` and `AutoAdapt` default to `1`. They are latched for the session, and changes require a complete game restart. The overlay distinguishes saved settings from the current session's effective settings.

| Capture | Adapt | Behavior |
| --- | --- | --- |
| 1 | 1 | Validate the native layout, collect/export metadata, and adopt the accepted layout. |
| 0 | 1 | Validate/adopt the layout without the full Kit snapshot and JSON export. |
| 1 | 0 | Perform discovery needed for snapshot export, but do not adopt the discovered runtime layout. |
| 0 | 0 | Skip the native startup background task, full signature scan, build-file hashing, and export. |

With adaptation disabled, a new build or adaptive package cannot silently use baseline offsets. Only the accepted built-in build/baseline-package path can continue its normal guarded processing. Snapshot-only operation can export its observation without authorizing native publication for an unsupported build.

Both options being disabled does not mean zero process-memory reads: the built-in path still checks version/code, source configuration, and resource readiness. These settings do not disable the desktop collector/generator, remove existing export files, or control another add-on.

## 14. IAS backend separation

When HD2 Independent Armor System (IAS) is detected, Armor Isolation stops its own native startup scanning and Kit publication. It checks previously prepared IAS `.isolation.ini` declarations instead.

An offline helper, run with the game closed, reads installed active packages and emits declarations for the supported IAS format. These preserve the original equipment/Archive identity and express original-to-private Unit mappings. The private materials, textures, and bones are already connected inside the generated resource payloads.

This declaration format cannot express every native Piece-field transformation. For example, runtime Piece texture-field substitutions cannot be reduced to a Unit-only handoff. Such configurations, unsupported Archive ownership combinations, and incompatible inputs are rejected as a group rather than exported partially.

The integration uses declaration files rather than IAS internal calls or export invocation. It manages only its own marked files. Detection after native publication, or a backend change during a session, requires a restart. `IAS_HANDOFF` confirms declaration matching, not IAS binding, resource readiness, rendering success, or the behavior of IAS itself.

## 15. Observable behavior and current verification scope

| Operation | Mechanism |
| --- | --- |
| Native plugin loading | ReShade add-on registration, present callback, overlay callback |
| In-process observation | Loaded-module enumeration, `ReadProcessMemory` on the current process, PE/signature inspection |
| Optional external observation | Read/query process handle and `ReadProcessMemory` |
| Candidate storage | Non-executable `VirtualAlloc` allocation and ordinary memory copies |
| Game-owned publication | Aligned `InterlockedCompareExchangePointer` on one target Kit-table entry per successful publication |
| Local files | Patch/config reads, INI/log writes, optional snapshot replacement; offline output/declaration generation |

The October 20 control build passed three native test suites, 26 relevant Python tests, and a standalone-EXE relocation test that generated and validated a complete four-target package. These checks establish isolated implementation/package behavior. They do not establish EAC acceptance or successful rendering in the updated game. The described build has not been deployed or tested under the new EAC environment.

| Artifact | SHA-256 |
| --- | --- |
| `ArmorIsolation.addon64` | `67e75672de9c310067d7aab76f5be2aeff7ab7f2bdf5c8ca4cb34e54f5de8429` |
| `ArmorIsolation.exe` | `adadffe141c44f0722caf5db1f0bfe2940e089db97c6a768a76476615f678b74` |

## 16. Implementation references and licenses

Project repository: https://github.com/TYHH100/hd2_ArmorIsolation

The source files below are the implementation basis for this description. Repository-relative links also identify the relevant files when this document is read as an attachment.

| Source | Responsibility |
| --- | --- |
| [`tools/build_generic_isolated.py`](../tools/build_generic_isolated.py) | Package identity, per-Kit/shared mapping, dependencies, output verification |
| [`tools/build_modular_isolated.py`](../tools/build_modular_isolated.py) | Modular components, variants, shared mapping across component patches |
| [`tools/build_cm14_isolated.py`](../tools/build_cm14_isolated.py) | Typed reference parsing, ID allocation, archive reconstruction, LOD repair |
| [`src/cm14_isolation_addon.cpp`](../src/cm14_isolation_addon.cpp) | Kit snapshots, candidate construction, guards, CAS publication, startup/options |
| [`include/cm14_resource_probe.hpp`](../include/cm14_resource_probe.hpp) | Bounded resource lookup, redirects, pending states, stable observations |
| [`include/armor_runtime_profile.hpp`](../include/armor_runtime_profile.hpp) | Declarative schema, identity and ownership validation |
| [`include/armor_embedded_profile.hpp`](../include/armor_embedded_profile.hpp) | Patch-footer transport and installed-package loading |
| [`include/armor_native_compatibility.hpp`](../include/armor_native_compatibility.hpp) | Native discovery and cross-reference checks |
| [`include/armor_assembly_compatibility.hpp`](../include/armor_assembly_compatibility.hpp) | Reviewed assembly templates and constrained operands |
| [`include/armor_local_data.hpp`](../include/armor_local_data.hpp) | Stable metadata extraction and atomic export |
| [`tools/game_compatibility.py`](../tools/game_compatibility.py) | Export validation, build-bound generation context, offline reuse |
| [`tools/validate_runtime_profile.cpp`](../tools/validate_runtime_profile.cpp) | External collector and native helper entry points |
| [`tests/test_universal_addon.cpp`](../tests/test_universal_addon.cpp) | Native transactions, source guards, startup lifecycle/control regressions |

Open-source license files: [Armor Isolation — MIT](../LICENSE), [ReShade SDK — BSD-3-Clause](../third_party/reshade-v6.5.1/LICENSE.md), [Dear ImGui — MIT](../third_party/imgui/LICENSE.txt), and [nlohmann/json — MIT](../third_party/nlohmann-json-3.12.0/LICENSE.MIT). Runtime distributions include these notices; the standalone executable also bundles the Python, Tk, python-lz4, and PyInstaller notices.

Operating-system API references:

- [ReadProcessMemory](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-readprocessmemory)
- [Process security and access rights](https://learn.microsoft.com/en-us/windows/win32/procthread/process-security-and-access-rights)
- [VirtualAlloc](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-virtualalloc)
- [VirtualQuery](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-virtualquery)
- [InterlockedCompareExchangePointer](https://learn.microsoft.com/en-us/windows/win32/api/winnt/nf-winnt-interlockedcompareexchangepointer)
- [GetModuleHandleExW](https://learn.microsoft.com/en-us/windows/win32/api/libloaderapi/nf-libloaderapi-getmodulehandleexw)
- [FreeLibraryWhenCallbackReturns](https://learn.microsoft.com/en-us/windows/win32/api/threadpoolapiset/nf-threadpoolapiset-freelibrarywhencallbackreturns)

These links document the Windows mechanisms. Game-specific structure meanings and compatibility claims are bounded by the implementation and evidence described above.
