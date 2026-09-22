# 补丁内嵌运行时配置

新生成包把运行时 JSON 直接放进主 `.patch_N` 文件，用户无需安装 `ArmorIsolation/*.json`。先安装一次新版 `ArmorIsolation.addon64` 与 INI；以后管理器照常安装、勾选配件、停用和卸载模组。手动安装只需将所选补丁及其 stream/GPU 文件放入游戏 `data` 顶层，三路使用同一空闲、连续编号。更改仍须完整退出游戏后进行。

原选项清单、目录及配件文件名保留。每个活动主补丁携带完整且相同的包配置，插件按包 ID 去重；无需指定一个必须保留原文件名的配置载体。基础模型和依赖材质选项仍须启用，不能把互斥分支一起安装。游戏端只从 EXE 所在 `bin` 的同级 `data` 顶层扫描 `16位十六进制.patch_数字`，忽略 stream/GPU、备份后缀及子目录。

## 格式

标识：`hd2-armor-patch-footer/1`。主补丁布局为原 archive 字节、UTF-8 JSON、64 字节 footer。追加不修改 TOC、资源内容、资源偏移、内存缓冲大小或两个副文件。footer 均为小端：

| 偏移 | 长度 | 含义 |
| --- | --- | --- |
| 0 | 16 | `HD2ARMORPROFILE` 加一个 NUL |
| 16 | 4 | 版本 1 |
| 20 | 4 | footer 大小 64 |
| 24 | 8 | JSON 起点，也是原 archive 文件大小 |
| 32 | 8 | JSON 字节长度，最多 8 MiB |
| 40 | 4 | JSON 的 CRC32，仅用于损坏检测 |
| 44 | 20 | 保留，必须全零 |

插件只读取固定尾部和限定大小的 JSON，不把纹理大包全读入内存。无标识的普通补丁跳过；标识有效但版本、长度、CRC、JSON 或 schema 错误时拒绝整组。标识本身丢失或损坏时无法与普通补丁区分，该文件不提供配置。

同包配置内容一致时去重；相同包 ID 内容不同、重复 Kit、资源 ID 冲突等仍拒绝整组。原有版本守卫、目标源值守卫、按 Kit 等待实际资源、原子发布和禁止热恢复保持有效。CRC 不代表签名，也不证明模型完整或已经加载。

生成器在自有暂存目录追加并回读，再用原生校验器直接加载实际补丁及并存配置，成功后才发布；外层 manifest 的 `output` 与 `package_files` 均记录追加后的哈希。`addon.profile_storage` 标识格式，`addon.embedded_profiles` 记录补丁路径和原 archive/配置大小。生成器拒绝复用不声明该格式能力的旧 DLL 发布包。

## 迁移与验证

旧 `bin/ArmorIsolation/*.json` 仍兼容；与内嵌配置完全一致时合并为一包。迁移到新生成包时移除对应旧 JSON，否则卸载补丁后旧配置仍会被发现；不要把旧私有 ID 的配置配给新包。旧专用插件仍需停用。生成工具不修改游戏目录，也不批量改写以前的输出。

```powershell
# 按实际安装规则，只扫描 data 顶层
dist/armor-isolation-runtime/validate_runtime_profile.exe --patches '<游戏目录>/data'
# 同时检查旧配置
dist/armor-isolation-runtime/validate_runtime_profile.exe --patches '<游戏目录>/data' '<游戏目录>/bin/ArmorIsolation'
# 直接检查指定的多个补丁；用于未部署的模块化输出
dist/armor-isolation-runtime/validate_runtime_profile.exe --inputs '<主补丁1>' '<主补丁2>'
```

自动测试覆盖改编号、组件去重、旧配置兼容、同 ID 不同配置、跨包冲突、损坏数据、忽略备份与卸载发现行为。真实样本回归核对资源段、原清单、目录、哈希和 Python 写入/C++ 读取的一致性。临时大包测试完成后清理。

**当前为待游戏验收实现**：离线解析通过不能证明游戏读取器允许附加尾部。本机管理器 `ModService.Deploy.cs` 的小文件路径使用完整复制/链接，大文件复制至 EOF，按该实现会保留尾部；尚未执行管理器到游戏的完整部署实测。需安装生成包验证游戏加载、两种体型、选项切换及卸载重启。所有新包继续标记 `game_runtime_verified=false`。

2026-09-21 离线验证：90 项 Python 测试中 89 通过，1 项符号链接权限测试跳过；两项原生测试通过。CM-14/B-01 生成与并存校验、TG-122 的 192 次组合等价检查、4K/8K 的四次单选覆盖检查均通过。新版 EXE 位于 `dist/portable-embedded/ArmorIsolation.exe`；仅复制单个 EXE 并清除 Python 搜索环境后，完成旧版四目标模组的实际生成、内嵌配置及输出哈希验证，见[单文件验证记录](embedded-portable-validation.json)。本轮临时测试包与构建目录已清理，未部署游戏。

外部结构参考：[Filediver Archive 读取实现](https://github.com/xypwn/filediver/blob/70f3447cd415c964e0bd29ff0770b97a4d0f160d/stingray/archive.go)、[Helldivers2ModManager](https://github.com/TYHH100/Helldivers2ModManager)。footer 为本项目自定义协议，并非上述项目或游戏官方支持声明。
