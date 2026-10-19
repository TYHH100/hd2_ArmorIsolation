# 启动退出、等待与重新装备分析

分析日期：2026-10-13，时间均为本机 Asia/Shanghai。检查部署、日志、Windows 事件与转储；另在独立测试进程复现共享索引及线程池 API 问题。没有启动游戏、写入游戏内存或替换已部署插件；后续新版由用户自行安装，新的崩溃分析见末尾。

## 结论

1. **已确认：同轮发布会使自己的共享索引过期。** 16 个目标被分散到约 14 秒内逐个发布，日志中的“加载中”主要是发布检查失败，不能解释成资源仍在加载。
2. **已确认：发布配置不会重建已经穿着的外观。** 先装配原版角色、后发布私有 Kit 时，原来的外观仍保留；切换装备才重新消费配置。当前实现明确要求重新装备。
3. **已确认存在同步重任务；尚未量化实际卡顿。** present 回调同步执行本机快照、全代码特征识别、文件哈希、配置读取和依赖探测。启动重试还阻挡了后面的配置初始化与目标发布。这是停顿与延迟的重要嫌疑，但没有帧耗时或装备调用跟踪，不能把用户感受到的全部停顿归到某个函数。
4. **原版启动退出尚未定因；本轮新版连续两次启动崩溃已确认是新引入的 API 使用错误。** 12:59:50 的 DStorageCore.dll 事件、13:02:24 的历史 EXE 偏移与新版 ntdll 的 `0xc000000d` 是不同失败。新版在同一后台回调两次登记 DLL 延后释放，本机复现、插件返回地址及导入表共同锁定这一调用。

## 本次环境

| 项目 | 本地读取得到的值 |
| --- | --- |
| game.dll | `data/game/game.dll`，文件版本 `1.0.0.19155` |
| game.dll SHA-256 | `2e2c3b7c2500646dadd5f2b4c6e0504dbb7e7896139f64cddc0d1813c718f51e` |
| ArmorIsolation.addon64 SHA-256 | `3b25bdafd9659d3f4aa45ee2a45815dbe33f855ed6700de234b3f77b27e008d6` |
| 插件文件比对 | 游戏 bin 与 `dist/armor-isolation-runtime` 完全同哈希 |
| 实际 ReShade | `6.8.0.2155`；Armor Isolation 注册 API17 成功 |
| 同时加载的其他插件 | HD2ArmorShader、HD2IndependentRig、HD2PreviewRuntime、HD2TransmogResources、ShaderToggler |
| 配置 | Enabled=1，DiagnosticOnly=0，7 包、16 目标、327 资源 |

历史文档中的 ReShade 6.5.1 是构建 SDK/旧环境记录；本次实际运行版本由 ReShade.log 确认。API17 注册成功，不能单凭版本不同判定不兼容。

## 共享索引造成逐秒排队

`src/cm14_isolation_addon.cpp` 的实际调用链：

- `poll()` 第 1060 行为一整轮建立 `KitIndex`，第 1067 行依次处理全部目标。
- `poll_target()` 第 917 行调用 `snapshot_unchanged(..., shared_index)`。
- 第 569–579 行的 `kit_index_unchanged()` 比较**整个 Kit 指针数组**。
- 第一个目标成功 CAS 替换自己的表项后，共享索引中的该项仍是旧指针。因此后面的目标即使自身完全没变，也会被整表比较拒绝。
- 下一轮重新建立索引才继续；`on_present()` 第 1082 行正常每 1000ms 轮询一次，形成“一轮发布一个”的现象。

本次日志摘录：

```text
2026-10-13 13:00:24 [LOCAL_DATA] cannot save local observation: Kit snapshot not ready
2026-10-13 13:01:08 [LOCAL_DATA] exported ArmorIsolation.local-game.json in game root for the generator
2026-10-13 13:01:08 [CONFIG] validated packages=7 targets=16 resources=327; configuration is fixed until process restart
2026-10-13 13:01:08 [APPLIED] package=17ba59ec54ec68093ad1eb10 kit=7a07031f published private config with 26 resource fields; switch away from this Armor item and back; RESTART_REQUIRED for removal
2026-10-13 13:01:08 [WAIT] package=17ba59ec54ec68093ad1eb10 kit=b18b6c66 source config or resource readiness changed before publication; no config published
```

16 条首次发布记录从 13:01:08 到 13:01:22；同一秒内前两个成功，其余随后逐秒成功。第一轮时间跨度可能跨过秒边界，日志只有秒精度，不能据此精确还原每次回调耗时。本会话 `private resources checked_ready=...` 等具体缺失依赖日志为 **0 条**；未记录具体依赖缺失不代表从未缺失，但不能把这些 WAIT 当作磁盘或 GPU 资源加载进度。

独立复现复用当前测试的两个 Kit、实际 `capture_snapshot`、`snapshot_unchanged` 与 `publish_pointer`，只访问测试进程自身内存：

```text
SAME_POLL_REPRO second_target_unchanged=true old_shared_index=BLOCKED independent=PASS fresh_shared_index=PASS
```

编译、运行成功；临时 CPP/OBJ/EXE 已删除。现有 `test_independent_publication()` 虽然测试了发布后其他目标不变，但第 516 行调用时**没有传共享索引**，遗漏了生产调用路径。

## 原版外观与停顿

配置发布只有一处游戏写入：用 `InterlockedCompareExchangePointer` 替换 Kit 表项。没有调用角色外观刷新/重新装备函数。第 869、933 行的 APPLIED 文案也明确要求切走再切回。APPLIED 代表配置指针已发布，不代表已存在的角色或预览对象已经重建。用户报告“启动穿着原版，军备库重新装备后正常”与此机制吻合；本次没有动态跟踪角色装配，不能声称已捕获其确切先后时刻。

延迟还有独立的代码原因：

- `poll()` 第 942–979 行先导出本机数据，之后才初始化模组配置。未知于内置基准的新版本在模块出现后就尝试完整识别；首次 Kit 未准备好时失败，10 秒重试间隔中的 `return` 会阻挡整条后续路径，最多尝试 6 次。
- `armor_local_data::capture()` 做 DLL 哈希、Kit 锚点发现和双读完整快照；`armor_native::attach_evidence()` 又识别完整原生特征并做文件哈希。
- 导出后，adaptive 配置在 `poll()` 第 1015–1037 行再做一轮 DLL/EXE 哈希与 `armor_native::discover()`；导出中得到的布局没有复用到运行时状态。
- 这些操作全部在 `on_present()` 中同步执行；代码没有背景工作线程。每次待发布目标还要探测依赖，发布前再独立全量复核依赖和源快照。

13:00:24 到 13:01:08 的日志空档共 44 秒，**并不是某个扫描函数运行了 44 秒的测量**：期间可能没有 present、处于重试间隔或执行重任务。装备停顿的精确归因仍需要分阶段耗时记录；不能用这段日志直接声称 CPU 阻塞 44 秒。

## 两次不同的退出

| 发生时间 | 证据 | 已确认 | 尚未确认 |
| --- | --- | --- | --- |
| 2026-10-13 12:59:50 | Application 1000/1001；WER Report.wer | `DStorageCore.dll+0x3d910`，`0xc0000409`，子码 7；ArmorIsolation 等六个插件已加载 | 最初触发快速终止的原因、崩溃线程调用链、是否存在插件间接影响 |
| 2026-10-13 13:02:24 | Arrowhead minidump 异常流、模块表、线程栈 | `helldivers2.exe+0x626296`，`0xc0000005`，读取 `0x20679f648a0`；与此前多份转储同一偏移 | 实际指令与完整调用链、相关对象生命周期、具体致因 |

第一份 WER 位于：

```text
C:/ProgramData/Microsoft/Windows/WER/ReportArchive/AppCrash_helldivers2.exe_771c45404613c2d1e86b6c26f19695a6b2c19c45_21e9b68a_8def99d9-92d3-4097-abeb-3c442e3bd541/Report.wer
```

该归档只有 Report.wer，事件指向的临时完整转储已不存在，不能恢复其调用栈。快速终止状态码不自动等于栈缓冲溢出；首个参数才是细分原因，不能按 BEX64 标签下结论。

第二份文件名包含 `13.00.17`，那是文件名中的会话时间；**转储头时间为 13:02:24**，不是 13:00:17 崩溃：

```text
C:/Users/29845/AppData/Roaming/Arrowhead/Helldivers2/dumps/dump-2026-10-13-13.00.17-2914e210-DESKTOP-RT4MS47-41.dmp
```

检查最新 12 份转储，其中 10 份异常落在 EXE `+0x626296`；这次不是新的崩溃偏移。最新转储异常地址不在 ArmorIsolation 模块。崩溃线程从 RSP 起最多 2KiB 的原始栈值扫描没有命中插件模块地址，但**这不等于已经展开调用链，也不能证明没有插件调用或间接影响**。本次没有运行中的游戏，也没有可连接的 WinDbg 会话；未对加壳 EXE 的磁盘内容作无效反汇编。

## 后续处理顺序

1. 先修共享索引：已知 CAS 发布成功后同步本轮预期索引，或在后续目标前重建并重新校验；仍保留整表外部变化、重复 Kit、源快照及资源就绪守卫。补上“同轮多个目标 + 共享索引”的生产路径回归。
2. 再处理同步重任务：记录导出/特征识别/配置/依赖/发布分段耗时；本机导出失败不应无提示地阻挡运行时初始化，并研究复用同会话、同文件身份且已完整验证的布局证据。暂不把热刷新角色作为已经安全可行的修复。
3. 启动退出单独定位：需要失败会话的完整转储/调用栈，以及只变更 ArmorIsolation 启用状态的对照；`Enabled=0` 仍可能执行前置本机采集，不能当作“插件未参与”的完整对照。不能声称修复发布排队就已经修复 DStorage 退出。

## 外部接口依据

- [Microsoft：__fastfail](https://learn.microsoft.com/en-us/cpp/intrinsics/fastfail?view=msvc-170)：`0xc0000409` 和首个异常参数的意义。
- [Microsoft：EXCEPTION_RECORD](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-exception_record)：访问违规异常参数中的读/写标志与目标地址。
- [ReShade v6.5.1 present 事件接口](https://github.com/crosire/reshade/blob/v6.5.1/include/reshade_events.hpp)：当前插件编译所用回调接口。游戏行为结论来自本地日志、源码与复现，不由 SDK 文档证明。

## 本轮修复与验证

2026-10-13 已实现：

- 成功 CAS 后只同步本轮共享索引中自己发布的 Kit，后续目标继续使用完整源/整表/资源守卫；就绪目标能够同轮发布。
- 原生完整扫描、模块哈希和本机快照导出移到单个只读线程池任务；present 不等待。任务完成后最快下一个 present 接收，同会话布局直接复用，不再重复完整扫描。
- 原生校验未通过仍拒绝发布并有界重试；身份不匹配立即拒绝。原生校验通过而可选快照导出失败时继续初始化，不再为导出等待六轮。禁用状态不启动新采集任务。
- 导出仍在自身首次发布前完成尝试；游戏配置写入只留在原 present 路径。后台通过模块引用持有代码与游戏模块，DllMain 不创建或等待工作线程。耗时只写日志，不添加额外覆盖层视图；最初后台实现的引用释放错误及修正见下一节。

验证：

- 新目录 `--clean-first` 构建通用插件与校验器，两项原生 CTest 通过（事务 0.91s、配置 1.67s）。新增测试覆盖生产 `poll_target` 的共享索引路径、同轮多个发布、整表外部改动、CAS 失败、发布前资源回退、后台未完成时不阻塞、可选导出失败继续、身份/布局/模块变更拒绝、复用快照与独立发现一致及 PE 身份变化拒绝。
- 另起全新构建目录，只编译 CM14/B01 事务测试，两项通过（0.97s、1.07s）；没有覆盖固定实验 DLL。
- 17 项 Python 快照/原生证据/发布清单相关测试通过。扩展尝试的 43 项中 26 项通过、17 项失败，失败原因是本机缺少旧 `dist/cm14-isolated` / `dist/b01-isolated` manifest 或可用 Python 缺少 lz4；没有伪造样本或放宽验证。完整 Python 回归未通过，不声称全套成功。
- 发布清单三个文件的大小/SHA-256，以及生成器 `runtime_release()` 校验通过；`git diff --check` 通过。
- 新插件：`dist/armor-isolation-runtime/ArmorIsolation.addon64`，SHA-256 `2b2bb23546ada097253555b952d746ade39fdd21cbe4c1c4f3a846ebfad29a6e`。游戏目录仍是旧哈希 `3b25bdaf...`，未自动部署；已存在的单文件工具仍内置旧插件，本轮只更新源码运行时发行文件。

临时复现文件与本轮自有构建目录已清理。尚未进行新插件游戏实测；已有角色仍可能需要切换装备才能重建外观，DStorage 启动退出也没有被证明已修复。

线程池生命周期参考：[GetModuleHandleExW](https://learn.microsoft.com/en-us/windows/win32/api/libloaderapi/nf-libloaderapi-getmodulehandleexw)、[FreeLibraryWhenCallbackReturns](https://learn.microsoft.com/en-us/windows/win32/api/threadpoolapiset/nf-threadpoolapiset-freelibrarywhencallbackreturns)。

## 新版连续两次启动崩溃及修正

用户安装第一版后台修复后连续两次启动崩溃。游戏 bin 插件与该版发行文件的 SHA-256 均为 `2b2bb23546ada097253555b952d746ade39fdd21cbe4c1c4f3a846ebfad29a6e`。这两次是本轮新引入的启动回归，不能沿用原历史崩溃的未证实结论。

| 证据 | 第一次 | 第二次 |
| --- | --- | --- |
| Windows 事件时间 | 2026-10-13 13:42:43 | 2026-10-13 13:48:45 |
| 转储头本地时间 | 13:42:51 | 13:48:53 |
| 异常 | `0xc000000d`，`ntdll.dll+0x7e907` | 同一代码及偏移 |
| 崩溃线程原始栈候选 | RSP+`0xd8` 为 `ArmorIsolation.addon64+0x3f751` | 相同 |

转储文件分别为 `dump-2026-10-13-13.42.35-f3885141-DESKTOP-RT4MS47-41.dmp` 与 `dump-2026-10-13-13.48.38-eef05d57-DESKTOP-RT4MS47-41.dmp`。文件名中的时间不是异常时间；事件与转储记录的时间也分别保留，不混用。这里是原始栈扫描，未声称完成调用栈展开。

对已验证哈希的未加壳插件做可靠 PE 反汇编及导入表核对：RVA `0x3f74b` 是第二次 `FreeLibraryWhenCallbackReturns` 间接调用，`0x3f751` 恰为该调用返回地址；两次调用均通过 IAT RVA `0x6e058`，导入名称明确为 `KERNEL32.dll!FreeLibraryWhenCallbackReturns`。最新插件日志只有 `[CONFIG]` 与后台 `[WAIT]`，尚无任务完成或 Kit 发布。

独立 Python 子进程加载两个系统 DLL，在同一线程池回调中分别登记延后释放：第一次成功，第二次在 API 中抛出 `0xc000000d`，由 ctypes 捕获并报告；准备任务未被执行。该复现没有启动或操作游戏。由 API 复现、同一插件返回地址及两次新异常模式共同确认是后台回调重复登记导致，异常落在 ntdll 不代表与插件无关。Microsoft 接口页描述回调完成时卸载 DLL，但未明确列出重复登记限制；这一限制来自本机实证。

修正：

- 同一回调只登记插件自身一次延后释放，确保回调代码返回前仍在内存中。
- game.dll 的增持引用在准备任务最后读取之后用 `FreeLibrary` 释放，再发布 `ready`；正常返回与 C++ 异常均走释放路径。
- 去掉 `queue_startup` 中测试宏对模块引用逻辑的跳过。新增可卸载测试 DLL，实际覆盖宿主在工作中卸载、准备期间仍可访问、正常/异常完成释放及获取失败回滚。测试回调自身位于测试 EXE，因此未声称独立验证了真实 ReShade 卸载插件的全过程。

本次修正后，全新目录 `--clean-first` 构建通用插件、校验器与测试 DLL，两项 CTest 通过（事务 1.70s、配置 1.61s）。发行清单三项大小/哈希校验及生成器 `runtime_release()` 校验通过，`git diff --check` 通过；构建目录与自有日志清理。仅改变通用插件启动路径，没有重跑上一节的 Python 或固定实验回归，也没有进行修正版游戏实测。

修正版插件为 `dist/armor-isolation-runtime/ArmorIsolation.addon64`，SHA-256 `044cf92e9c4b603cb9c9d1f33165c5f5b1373a32b8447c2ee866c1bd0485fa31`。未自动部署；游戏 bin 中仍为产生这两次崩溃的 `2b2bb235...` 版本。单文件工具仍内置旧运行时，本次未重打包。

接口依据：[FreeLibraryWhenCallbackReturns](https://learn.microsoft.com/en-us/windows/win32/api/threadpoolapiset/nf-threadpoolapiset-freelibrarywhencallbackreturns)、[FreeLibrary](https://learn.microsoft.com/en-us/windows/win32/api/libloaderapi/nf-libloaderapi-freelibrary)。
