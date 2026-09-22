# 通用 ReShade 护甲隔离插件

## 一个插件加载多个包

`ArmorIsolation.addon64` 不再内置某个模组的资源 ID。新版固定 DLL 启动时读取游戏 `data` 顶层主补丁的内嵌配置，并兼容同目录的旧 `ArmorIsolation/*.json`。校验后按目标 Kit 独立检查资源和发布配置。新版生成包只需增减补丁，DLL 共用。

游戏目录布局：

```text
Helldivers 2/
  ArmorIsolation.local-game.json
  bin/
    ArmorIsolation.addon64
    ArmorIsolation.ini
    ArmorIsolation.log
  data/
    <管理器分配编号的补丁三件套，主补丁内嵌配置>
```

运行环境为 ReShade 6.5.1 / API17；已验证基准为 `game.dll 1.0.0.18930`，另支持关键原生特征与既有数据布局仍匹配的更新，不保证任意游戏版本兼容。

## 加载与发布流程

1. 首次 present 回调读取游戏 data 顶层主补丁的固定尾部与配置，不在 DllMain 中访问文件，不递归备份目录。同包组件配置一致则去重，不同则整组拒绝；旧 JSON 可兼容读取。读取一次后保持不变。
2. 用 nlohmann/json 解析并严格验证 schema、重复键、数据类型、数量与大小。单文件上限 8 MiB、总计 32 MiB、最多 64 包和 402 目标。
3. 整组验证包 ID、Kit 归属、完整及高 32 位资源 ID 冲突、私有 ID 返回原资源的别名、允许的 Piece 偏移及实际依赖。重复 Kit 或任一损坏配置让整组停止，不先发布一部分。
4. 配置只声明资源和布局，不接受地址或函数调用。目标体甲/头盔、Body/Piece 及源 Unit 必须与实际游戏配置相符；计划修改的纹理字段也逐 Piece 核对原值。材质到纹理的传递依赖由离线生成器解析，插件核对显式依赖表，不能仅靠 JSON 再解析游戏资源。
5. 已知版本检查 PE 标识及代码；未知版本和 v2 适配包通过完整掩码特征重新发现 Kit 全局、关键函数和资源管理器，核对交叉引用与三类资源表。v2 包另绑定 DLL/EXE SHA-256；不使用配置指定的地址。所有目标仍核对源结构与原值，只等待自身依赖。
6. 沿用已验证的配置克隆和指针原子发布。Body/Piece 存储由独立分配持有，Profile 移动不会留下悬空指针。发布后的游戏引用不做热释放，移除需退出游戏。

INI 内容：

```ini
[ArmorIsolation]
Enabled=1
DiagnosticOnly=0
```

### 大量目标与日志（2026-09-21）

每秒轮询共用一次完整 Kit 表索引；每个目标仍核对当前表、指针及原始数据。字段与资源映射预索引，源数据相同时复用候选配置；发生变化立即重新校验。等待资源时先检查上次未就绪项，遇到未就绪项提前结束，发布前仍重新检查全部依赖及完整源快照，不缓存跨轮询的“已就绪”结论。`checked_ready` 仅表示本次已检查的部分，不能当成总加载进度。

`ArmorIsolation.log` 每次插件启动的首次成功写入清空旧内容，之后追加本次状态变化；相同状态不会重复写入。首次打开失败会在后续日志调用重试。

启动后、该插件首次发布前，提取稳定 Kit 和原生布局证据，成功后原子覆盖 **游戏根目录** 的 `ArmorIsolation.local-game.json`。文件包含 DLL/EXE SHA-256、Kit 内容摘要及来源阶段。失败保留旧完整文件并记录日志，10 秒间隔最多尝试 6 次；不每秒扫描、不累积历史转储。未知版本检测在代码段中要求唯一完整特征，跨模块引用和资源表也需符合既有布局。

生成器现在可以消费匹配当前文件哈希的导出，无需保持游戏运行。缺失、损坏或过期则尝试重新提取，失败提示先启动游戏。未知版本外部提取若发现已加载隔离插件，不提升为原始快照；改用新插件在自身发布前导出的文件。生成操作独立绑定游戏身份和快照，发布包前再次检查，输出 v2 配置和 `compatibility/kits.json`。

自动适配支持地址重定位及仍符合已识别原生特征/数据布局的更新；不是任意未来实现的自动逆向。掩码特征允许外部相对地址变化，不证明整个游戏语义不变。关键函数、资源格式或字段变化会停止，可能仍需工具更新；源字段变化则须重建模组包。旧 v1 包跨版本也必须通过原生检查及源值守卫；不同身份或 v1/v2 配置不能混装。真实未知版本的运行效果尚未验收。

可在不部署插件的情况下只读验证正在运行的游戏：

```powershell
dist/armor-isolation-runtime/validate_runtime_profile.exe --capture-local <PID> <报告路径.json>
# 自动按安装目录查找进程；存在多个匹配进程则拒绝
dist/armor-isolation-runtime/validate_runtime_profile.exe --capture-game <游戏目录> <报告路径.json>
```

桌面工具的“读取本机游戏数据”比较内置基准并报告新增、缺失和变化，保存单份 `local-game-analysis.json`；检查通过也导出游戏根目录的复用文件。当前本机 402 条记录中 2 条不同于原始快照，因此已知版本导出明确使用内置原始 Kit 配合本机布局证据，标记 `verified_baseline`，不会把这两条变化纳入原始数据。

外部接口依据：[ReadProcessMemory](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-readprocessmemory)、[PE 格式](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format)、[fopen 写入模式](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/fopen-wfopen)。这些文档不证明游戏内部结构兼容。

`DiagnosticOnly=1` 只检查、不发布新配置；`Enabled=0` 停止继续发布。若已经发布，两个选项都不能恢复旧配置，仍须重启。

日志 `CONFIG` 给出包、目标和资源总数；各目标的 `WAIT`、`READY`、`APPLIED`、`FAILED` 携带包 ID 和 Kit ID。配置组校验通过不代表资源已加载，`APPLIED` 也不代表场景外观已验收。

格式与新版安装方式见[补丁内嵌配置](embedded-patch-profile.md)。旧包的独立 JSON 仍支持，但卸载时需自行一并移除；重新生成新版后移除对应旧 JSON。

## 旧包迁移

通用插件检测到已加载 `CM14Isolation.addon64`、`B01Isolation.addon64` 或 `ArmorIsolation_<包ID>.addon64` 时会停止写入，并提示退出游戏迁移。不要让旧插件先发布后再热加载新插件。

已经准备的兼容配置位于 `dist/armor-isolation-runtime/compatibility/cm14-b01/ArmorIsolation/`：

| 配置 | 对应补丁 | 目标 | 资源 |
| --- | --- | --- | --- |
| `19d10a2d21b513a1e6cfcb3f.json` | 已验收 CM-14 专用版 | 2 | 51 |
| `5d0fe0c0c33fec377e654b73.json` | 已验收 B-01 revision 4 | 8 | 106 |

两份配置保留原专用补丁的私有 ID。完整退出游戏后，保留这些已验证补丁，停用确认属于旧实验的插件，安装固定 `ArmorIsolation.addon64` / INI，再将对应 JSON 放入 `bin/ArmorIsolation/`。只安装一个补丁时只放对应配置；未加载资源的目标会停留在 WAIT。

这两份配置不能用于重新生成、私有 ID 已不同的包。其他已生成的隔离包可以从自己的 manifest 导出：

```powershell
& 'G:\Temp\Githud\hd2-lua_mods_test\.venv\Scripts\python.exe' -X utf8 -B tools/runtime_profile.py --manifest '<包目录>\manifest.json' --output '<已存在的配置目录>'
& '.\dist\armor-isolation-runtime\validate_runtime_profile.exe' '<配置目录>'
```

导出只写 JSON，不复制或更改补丁。文件名必须与包 ID 一致，不覆盖已有文件。校验器与 DLL 使用同一加载器，只检查数据，不读写游戏进程。

回退时退出游戏，移除对应 JSON 和所属补丁；其他模组仍使用时保留通用 DLL/INI。若退回专用插件，还需停用通用版避免并存。文件归属和补丁编号由原部署方式管理，工具不自动删除游戏文件。

## 构建和证据

`tools/build_universal_addon.ps1` 只编译一次固定 DLL、原生校验器和测试，不依赖 `generic_resource_map.hpp`。生成 `runtime-release.json` 绑定三个发布文件的大小与 SHA；图形生成工具核对发布清单后复用同一组文件，无需每个模组安装 C++ 工具链。

配置解析覆盖多包、重复/损坏配置、归属和字段、容量限制、指针稳定等边界；事务测试覆盖声明式目标的源数据守卫、披风与标量保留、独立指针发布。游戏内验证另行进行，本轮不部署。

2026-09-19 初版验证结果：41 项 Python 测试通过；通用配置/事务两项原生测试，以及在全新目录重编的 CM-14/B-01 两项回归通过。旧补丁兼容组经校验器报告 `packages=2 targets=10 resources=157 fields=119 required=255`。初版两包使用相同 DLL，SHA-256 均为 `65525e0d7af5f088d628a84275f2e29139542fb4235a24652348cbb4f7f4fcf7`，详见[历史样本验证记录](generic-sample-validation.json)；临时测试大包和构建目录已清理。

同日模块化扩展修正了 TG-122 头盔带默认 Slot1 披风的校验：允许保留披风元数据，但不新增披风写入。新版 DLL SHA-256 为 `1bd484fb5ea14ea3380e1d0db2cd752a25209c17316ae014172333d03342b300`；JSON schema 与旧私有资源 ID 不变。新版两项原生测试、CM14/B01 旧配置兼容检查及 TG-122/4K/8K 两个真实模块化样本验证通过。Python 全套 76 项中 75 通过、1 项因本机创建 symlink 权限不足跳过，Windows reparse 拒绝检查通过；GUI 启动检查通过。详见[模块化处理与验证](modular-isolation-tool.md)。

JSON 库使用官方 [nlohmann/json 3.12.0](https://github.com/nlohmann/json/releases/tag/v3.12.0)，单头文件 SHA-256 为 `aaf127c04cb31c406e5b04a63f1ae89369fccde6d8fa7cdda1ed4f32dfc5de63`，已按官方公布值核对，MIT 许可随源文件保留。ReShade 接口依据 [6.5.1 SDK](https://github.com/crosire/reshade/tree/v6.5.1/include)。
