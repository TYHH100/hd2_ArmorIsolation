# B-01「夏菲·蓝光」资源隔离实验记录

日期：2026-09-19。用户已确认 CM-14 修正版体甲、头盔正常，随后指定 B-01 系列作为高复用样本。此文保留专用实验过程；后续通用工具另见 [通用处理工具](generic-isolation-tool.md)。以下数量和依赖关系均由本机文件计算；构建成功不等于游戏外观验收成功。

验收更新：用户已反馈“根据测试没有任何问题”，确认 revision 4 测试正常，并要求推进通用工具。此版为 92 个按 Kit 独立的 Unit，加一份模组内共用的私有材质及 13 个私有纹理，共 106 个唯一资源；另有三个头盔的 LOD 网格索引定点修正。验收来源为用户游戏实测反馈，没有新增原生 LOD 动态跟踪或显存测量。下面保留方案变更与当时的检查结果，历史进程和安装状态不代表当前状态。

## 1. 输入和目标

用户消息中的路径分隔与磁盘目录不同。核对后的实际源文件为：

`G:\Temp\HD2ModManager\Mods\Mods\VRC_夏菲 替换 B-01系列_6cb08803\蓝光\9ba626afa44a3aa3.patch_6`

使用此文件及同名 `.stream`、`.gpu_resources`；目录内 `.hd2mm-backup` 不作为输入。源模组保持原样。游戏目录为 `G:\AppData\SteamLibrary\steamapps\common\Helldivers 2`，工作区为 `G:\Temp\Githud\hd2_mods-test`。

Kit 名称由管理器 `armor-names.json`、`helmet-names.json` 对照；结构取自同版本 402 Kit 快照。目标是四件体甲和四件独立头盔，不能按同名体甲推定头盔已经包含。

| 名称 | 类型 | Kit ID | Archive |
| --- | --- | --- | --- |
| B-01 Tactical (Variation 1) | 体甲 | `61b31723` | `58e4bd4b2278d15c` |
| B-01 Tactical (Variation 2) | 体甲 | `4f7fb2bd` | `562a45e9bc984eb9` |
| B-01 Tactical (Variation 3) | 体甲 | `6351a9aa` | `6cd3d55c05d4eac1` |
| B-01 Tactical (Variation 4) | 体甲 | `6d30f386` | `519cc1ec2eb56e1d` |
| B-01 Tactical (Variation 1) | 头盔 | `261c4a52` | `fd109bfeeed36726` |
| B-01 Tactical (Variation 2) | 头盔 | `45d80a38` | `3b143cc283b7f707` |
| B-01 Tactical (Variation 3) | 头盔 | `b4027b70` | `f4880623d32bafa9` |
| B-01 Tactical (Variation 4) | 头盔 | `df8e4ada` | `8313c9a556b8ee85` |

四个体甲均为被动 1，Body 布局 `(3,7)、(0,8)、(1,8)`；排除默认披风后各 22 个 Unit。四个头盔均为被动 0，Body 布局 `(3,1)`，各 1 个 Slot0 Unit。Body0/1 分别对应壮硕/纤细；Body3 为通用部分。

## 2. 找到真正需要隔离的资源

源 TOC 共 136 条：106 Unit、4 Material、26 Texture。八目标的 92 个 Unit 引用全部由输入覆盖，跨 Kit 去重后为 46 个 Unit，无需从原版补齐 Unit。

从每个目标的非披风 Piece 开始，按类型递归遍历 `Unit -> Material -> BaseMaterial/Texture`，并检查 Piece 动态纹理字段。结果八目标都只用到源材质 `ad686c7fb5d3db1c` 及其 13 个 Texture。另有 60 Unit、3 Material、13 Texture 不在目标依赖范围，共 76 条资源不进入实验包。

原模组的 Unit ID 还被 56 个非目标 Kit 引用，其中 36 件体甲、20 个头盔；CM-14 体甲共享其中 8 Unit。这说明原 ID 覆盖存在污染通道，不表示这 56 件已经逐一确认视觉异常。详细名单保存于 `G:\Temp\Githud\hd2_mods-test\docs\b01-source-analysis.json`。

目标仍引用 21 个原版外部材质及基材质。在八个目标 Archive、`9ba626afa44a3aa3` 和 `18235e0c9ec0e636` 中全部找到，递归核对确认：这些材质的纹理不命中源 26 Texture，BaseMaterial 也不命中源 4 Material。八个 Kit 的 Piece 动态纹理字段同样不命中源纹理。因此本例可保留这些原版引用，无需额外复制原版材质；这是本例证据，不是对所有模组的通用假设。

## 3. 私有命名与运行时连接

当前 Unit 映射键仍为 `(Kit ID, Unit 类型, 原资源 ID)`，四件体甲和四个头盔保持独立 Unit。材质/纹理映射改为 `(模组私有范围, 资源类型, 原资源 ID)`，使用 `owner=00000000` 表示这八个目标共用。此标记只是生成器、插件与探针的归属约定，不是游戏中一个可供全局使用的 Kit；非目标装备不改写引用。新 ID 同时避开已检查的原版、源补丁及 CM-14 私有 ID，并检查完整 64 位值和高 32 位冲突。

每个体甲有 22 个私有 Unit，每个头盔有 1 个私有 Unit，合计 92 个；八目标共同引用 1 个私有 Material 和 13 个私有 Texture，总计 `92 + 1 + 13 = 106` 条。每个体甲的就绪条件仍为 `22 + 14 = 36`，每个头盔为 `1 + 14 = 15`，但同一组 14 个资源只在 TOC 存放一次。输出 TOC 不含源资源 ID，因此不会通过原 ID 覆盖其他 Kit；前提是旧 ID 覆盖模组已经停用。

只重写已解析的 64 位资源引用：Piece.Unit、Unit 材质表的值、Material 纹理表或基材质的值。保留 32 位材料槽/纹理用途哈希、骨骼和 Mesh 索引、资源类型、Piece 参数及默认披风。盲目查找替换整段二进制会把绑定协议和索引一起破坏。

当前 manifest 的 `rewritten_references` 汇总为 197 处：184 处 Unit→Material、13 处 Material→Texture；Kit 内的 92 处 Piece.Unit 更新由 `piece_fields` 单独记录。不能将资源条目数、资源内部引用数和运行时 Piece 引用数混作同一指标。

ReShade 插件沿用 CM-14 已验证的机制，但采用独立 B-01 配置、日志和映射：验证游戏版本与配置结构，确认目标私有资源可用，复制 Kit/Body/Piece 数据，改写该目标的非披风 Unit 引用，再原子替换对应 Kit 表指针。八目标分别发布，每个体甲应改 22 项，每个头盔应改 1 项，总计 92 项。原始配置内容不改写，已生成模型需切换装备触发重建；这不是绘制阶段的全局纹理替换。

## 4. 本次解决的格式差异

源 `.stream` 长度为 `14155896`，许多 TOC 条目的 stream 偏移为 `14155904`，但长度为 0。偏移只是尾部对齐位置，超过 EOF 8 字节，并没有要读取的数据。原共享校验器无条件检查偏移，因而误报越界。

修法是在 `validate_segments` 中先跳过长度 0 的 lane，只对非空数据验证边界和重叠；不修改源文件，不放宽非空数据要求。新增测试确认“长度 0、偏移超 EOF”允许，同位置长度改为 1 则必须拒绝。资源重打包仍重新计算三路磁盘偏移、主/GPU 内存缓冲偏移以及按 256 字节逐资源对齐的头部缓冲总量。

### 4.1 首版体积问题与修正

首版把 Unit、材质和纹理全部按 Kit 复制。四体甲各 36 条、四头盔各 15 条，得到 204 条资源，即 92 Unit、8 Material、104 Texture。GPU 文件为 `2249516160` 字节，约 2.09 GiB，三个补丁总计 `2250961808` 字节。用户实际试用后指出体积过大，并明确要求同一模组内共用材质/纹理。

问题在于把“避免污染非目标装备”扩大成“本模组所有目标都各存同一套纹理”。对这一个模组，依赖遍历已证明八目标指向相同源材质和相同 13 张纹理，所以保留独立 Unit，建立一份全新的模组私有材质/纹理即可。代价是之后修改这组共享材质/纹理，会同时改变本模组八个目标；这符合本轮用户指定的共享范围。

中间曾评估多个 TOC 条目共用相同 GPU 磁盘区间，只减少磁盘副本。该办法已放弃，当前代码与命令不再提供此选项。revision 3 直接减少为 106 个唯一资源，使用标准的不重叠 TOC 数据区间，同时让运行时资源 ID 也共用。

当前 GPU 文件为 `353952896` 字节，约 337.6 MiB，比首版减少 `1895563264` 字节，约 84.3%；主文件 `1396816` 字节，stream 为 0，总计 `355349712` 字节。GPU 内存缓冲布局总量为 `353960448` 字节，包含逐条对齐，不能直接用磁盘长度替代。实际显存占用仍须在游戏中测量，不能由这几个磁盘数字推定。

### 4.2 三个头盔的 LOD 修正候选

用户明确反馈此问题出现在首版隔离包中，四个 B-01 头盔仅一个显示。它不能归因于用户后来恢复的普通模组，也不能仅靠资源加载成功就宣布解决。进一步对照源 Unit 和原版结构发现三个头盔各增加了 10 个辅助 Mesh，LOD 表仍使用旧网格索引 `4/3/2/1`。按原版 `MeshInfo+0x28` 的 MeshID/GroupBoneHash 匹配对应网格后，目标索引为 `14/13/12/11`。

| 头盔 Kit | 源 Unit | 本候选处理 |
| --- | --- | --- |
| `261c4a52` | `bc20d0b4efff128c` | 用户正常显示的第一种，保持原值 |
| `45d80a38` | `7b23e3c0ab4cf618` | 修正四处 LOD 网格索引 |
| `b4027b70` | `c96cb2e72d7a0525` | 修正四处 LOD 网格索引 |
| `df8e4ada` | `781134771dd69fbe` | 修正四处 LOD 网格索引 |

三个 Unit 均只修改相对主数据偏移 `0xDC / 0xEC / 0xFC / 0x154` 的 32 位值，共 12 处。构建器同时核对源 Unit 主数据 SHA-256 和字段旧值，两者符合才应用，避免把只适用该源文件的索引规则套到其他版本。主数据长度和 GPU payload 不变。该操作只针对已核对的 LOD 结构，与资源私有化的 197 个 64 位引用重写分别记录于 manifest。

详细对照见[头盔分析](b01-helmet-analysis.md)和[LOD 结构证据](b01-helmet-lod-evidence.json)。revision 4 加入精确守卫修改后通过离线测试，随后用户确认游戏测试没有问题。该反馈支持本次修正结果，但不等同于动态原生 LOD 调用跟踪；推广到另一模组时仍须核对源结构，不能统一给索引加 10。

## 5. 可复现命令

以下命令在 PowerShell 7 执行。先进入固定工作区；分析和构建只写工作区产物。

```powershell
Set-Location -LiteralPath 'G:\Temp\Githud\hd2_mods-test'
& 'G:\Temp\Githud\hd2-lua_mods_test\.venv\Scripts\python.exe' -B 'G:\Temp\Githud\hd2_mods-test\tools\analyze_b01_source.py' --source 'G:\Temp\HD2ModManager\Mods\Mods\VRC_夏菲 替换 B-01系列_6cb08803\蓝光\9ba626afa44a3aa3.patch_6' --game 'G:\AppData\SteamLibrary\steamapps\common\Helldivers 2' --reader-tools 'G:\Temp\Githud\hd2-lua_mods_test\tools'
& 'G:\Temp\Githud\hd2-lua_mods_test\.venv\Scripts\python.exe' -B 'G:\Temp\Githud\hd2_mods-test\tools\build_b01_isolated.py' --source 'G:\Temp\HD2ModManager\Mods\Mods\VRC_夏菲 替换 B-01系列_6cb08803\蓝光\9ba626afa44a3aa3.patch_6' --game 'G:\AppData\SteamLibrary\steamapps\common\Helldivers 2' --reader-tools 'G:\Temp\Githud\hd2-lua_mods_test\tools'
& 'G:\Temp\Githud\hd2_mods-test\tools\build_b01_addon.ps1'
& 'G:\Temp\Githud\hd2-lua_mods_test\.venv\Scripts\python.exe' -B -m unittest discover -s 'G:\Temp\Githud\hd2_mods-test\tests' -p 'test_*builder.py' -v
ctest --test-dir 'G:\Temp\Githud\hd2_mods-test\build\b01-addon' --output-on-failure
& 'G:\Temp\Githud\hd2_mods-test\tools\manage_b01_test.ps1' -Action Check
```

插件构建脚本加载本机 MSVC x64 开发环境。ReShade SDK 固定 6.5.1/API17。产物目录 `G:\Temp\Githud\hd2_mods-test\dist\b01-isolated` 包含三个补丁、`B01Isolation.addon64`、INI 和记录映射/输入输出 SHA-256 的 `manifest.json`。`Check` 只读检查版本、文件哈希、现有补丁冲突与下一个连续编号，不安装。

## 6. 安装、探针与回滚

先正常退出游戏，并通过原管理器停用旧 B-01 模组及预检提示的原 ID 覆盖补丁，再重新运行 `Check`。可以保留 CM-14 私有实验包；安装脚本自动选择基础包的下一个连续补丁编号，禁止覆盖已有文件。工作区文件名 `.patch_0` 只是包模板，不能直接拿来覆盖游戏中 CM-14 的 `.patch_0`。

首版安装前曾在只保留 CM-14 时通过预检，预计追加 `patch_1`；这只是历史记录。当前用户已恢复大量普通模组，本轮只读观察的游戏进程为 PID `20236`，旧 ID 冲突包括原 B-01 `patch_12`，当前预检会拒绝安装。实际安装编号必须重新计算，不能继续写死为 `patch_1`，更不能把当前存在的 `patch_1` 当作旧实验文件直接删除。

若已安装首版隔离包，退出游戏后须依据有效安装记录确认文件归属并移除旧实验版，再一起安装新版三个补丁和插件。若收据缺失、文件已被管理器重新编号或哈希不同，应先核对当前部署，不能按历史编号删除。当前候选包含 revision 3 起变更的映射与共享规则，以及 revision 4 的 LOD 修正，混用新补丁与旧插件不受支持。

当前确实没有 `bin/B01Isolation.install.json`，但 `bin/B01Isolation.addon64` 仍为首版，SHA-256 为 `a791caf1f483ea7370f13e67c821de71d48b4972ab04f54d1a4b2c0324640044`；工作区新版插件 SHA-256 为 `235e47e9828debe6907140bb9d12f8815b85fd12af7d5e654112bf3e6fe17818`。因此脚本不能直接卸载这个手动版本，`Install` 也会拒绝覆盖现有插件。退出游戏后，应按原手动部署方式同时更新确认属于本实验的三路补丁和插件；或者先清理归属已确认的旧实验插件/INI与补丁，再走脚本安装。两种方式均须先停用原 B-01 及提示的旧 ID 冲突；不要混用手动覆盖和脚本收据，也不要误删当前其他模组的 `patch_1`。

```powershell
& 'G:\Temp\Githud\hd2_mods-test\tools\manage_b01_test.ps1' -Action Install
& 'G:\Temp\Githud\hd2_mods-test\tools\manage_b01_test.ps1' -Action Status
```

正常启动游戏后，查看日志并运行只读探针。避免使用 PowerShell 保留变量 `$PID` 保存游戏进程号。

```powershell
$b01GameProcess = Get-Process -Name helldivers2 -ErrorAction Stop
& 'G:\Temp\Githud\hd2_mods-test\build\b01-addon\probe_b01_resources.exe' $b01GameProcess.Id
Get-Content -LiteralPath 'G:\AppData\SteamLibrary\steamapps\common\Helldivers 2\bin\B01Isolation.log' -Tail 60
```

预期全部加载后为 `PRIVATE_READY 106/106`、`SHARED_READY 14/14`；八目标各有 `APPLIED`。各体甲 `TARGET_READY 36/36`、各头盔 `15/15`，其中每个目标均含同一组共享 14 条，不能将这些分目标数字相加当作唯一资源总数。探针目标总计 `original=0 private=92`，`other_private=0 wrong_owner_private=0`；各体甲 22、各头盔 1。若目标资源尚未加载，应先查看对应 `TARGET_READY` 与等待日志，不能把探针退出成功当作全部加载成功。`APPLIED` 仅证明配置发布，需要继续视觉验收。

回滚也须先正常退出游戏，不能热卸载已发布配置。使用安装收据只移除本实验拥有且哈希匹配的文件；日志保留用于排查。

```powershell
& 'G:\Temp\Githud\hd2_mods-test\tools\manage_b01_test.ps1' -Action Uninstall
```

若实验补丁之后还有更高编号，脚本会拒绝直接删除，以免留下编号空洞；先由管理器重新安排后续补丁。若已安装文件被修改，先核对具体文件再处理，不能通过删除收据跳过归属验证。需要恢复旧 B-01 时，在本实验卸载后再由原管理器启用。

## 7. 游戏验收记录要求

1. 四个 B-01 体甲逐个切换，壮硕和纤细均检查躯干、四肢、肩部、蓝光与材质；每个目标发布后切换离开再切回。
2. 四个 B-01 头盔逐个检查，并分别与 B-01、非 B-01 体甲混搭；B-01 体甲也配原版非目标头盔，避免再次遗漏独立头盔 Kit。
3. 对照 B-24、SA 系列以及报告中共享 Unit 的代表套装；CM-14 私有体甲和头盔应维持已验收效果。记录具体套装、体型及截图，不用少数样本推定全部 56 Kit 已通过。
4. 分别观察装备界面预览、舰桥实际角色、任务内角色；检查换装后及重启后结果。披风只确认行为未异常，本实验没有按所选披风隔离披风模型。
5. 记录帧率、内存/显存与加载等待。当前 revision 4 沿用 106 个唯一资源，三文件磁盘合计 `355349712` 字节，其中 GPU 约 337.6 MiB；与首版对照时记录相同场景和装备，不能直接把磁盘差值当作显存节省。

## 8. 当前证据边界

已完成 revision 4 源分析与构建：8 个目标、106 个唯一私有资源、92 个 Piece 引用、12 处候选 LOD 修正，排除 76 条源资源，21 个外部材质检查完整。输出主数据按映射及 LOD 调整逐项对照，stream/GPU 各资源段验证，输入三文件构建前后哈希一致。11 个 Python 构建测试、C++ 编译和两个 CTest 均通过，包含 B-01 事务及 CM-14 回归。

首版的安装前探针文件 `G:\Temp\Githud\hd2_mods-test\docs\b01-before-install-probe.txt` 记录 `PRIVATE_READY 0/204`、原引用 92、私有引用 0，是当时尚未安装的基线。用户自行测试首版后给出体积和头盔反馈；revision 4 交付后又确认“根据测试没有任何问题”。原 manifest 与机器证据保留生成时的运行时验证标记，用户验收单独记录在本文，避免混淆机器自动检查和人工验收。实际显存变化没有新测量数据。

生成 revision 4 时，探针对 PID `20236` 的只读结果为 `PRIVATE_READY 0/106`、`SHARED_READY 0/14`、`original=92 private=0`，仅证明当时新版没有加载。这一记录早于用户后续测试确认；进程号、冲突和补丁编号均属历史快照，后续安装前必须重新读取。

## 9. 外部参考与本地证据

- [Filediver Unit 解析，固定提交](https://github.com/xypwn/filediver/blob/70f3447cd415c964e0bd29ff0770b97a4d0f160d/stingray/unit/unit.go)：Unit 材质列表、槽位与资源值的格式参考。
- [Filediver Material 解析，固定提交](https://github.com/xypwn/filediver/blob/70f3447cd415c964e0bd29ff0770b97a4d0f160d/stingray/unit/material/material.go)：纹理用途、纹理 ID 和 BaseMaterial 格式参考。
- [ReShade 6.5.1 SDK](https://github.com/crosire/reshade/tree/v6.5.1/include)：插件 API 版本依据。
- 本地证据为 `G:\Temp\Githud\hd2_mods-test\docs\b01-source-analysis.json`、`G:\Temp\Githud\hd2_mods-test\dist\b01-isolated\manifest.json`；运行日志和探针结果需要另行保存。外部解析器提供格式参考，不能替代本机版本、加载状态或游戏画面的验证。
