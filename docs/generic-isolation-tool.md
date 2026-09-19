# 通用护甲资源隔离工具

## 当前交付

流程为“选择源模组和目标 -> 依赖分析 -> 私有重打包 -> 生成运行时 JSON -> 固定插件校验 -> 输出完整包”。所有模组使用同一份 `ArmorIsolation.addon64`，生成时不再逐包编译插件。上一版按包生成 C++ 头文件并编译专用 DLL 的入口保留为开发历史，不再用于图形工具的正常生成流程。

用户已确认 CM-14 和 B-01 revision 4 专用包游戏测试正常；新的通用插件仍须游戏验收。当前游戏 DLL 限定为 `1.0.0.18930`、SHA-256 `cc75948d90fdfde259dcb519e9933db7ffa3ccb281ce4fb89e6b1b011557470c`，不会修改 DLL 本身。

## 使用入口

1. 双击项目根目录 `Start-ArmorIsolation.cmd`。也可在 PowerShell 执行 `Start-ArmorIsolation.ps1`，用 `-Python` 指定解释器，用 `-Source` 预填源模组。
2. 选择旧版或 V1 模组根目录或其中的 `manifest.json`，保留整套选项目录；也可继续选择单个主 `.patch_N` 文件或只含一个主补丁的目录。stream/GPU 从同名文件读取，输入只读。
3. 核对游戏和输出目录。附加设置可调整资源读取器、Kit 数据、名称目录以及准备并存的隔离包 `manifest.json`。
4. 点击“分析候选”，按名称、Kit ID、部位和 Unit 覆盖数量选择实际目标。体甲和头盔分别选择，共享资源命中的装备不会自动全选。
5. 点击“生成隔离包”。完整输出在 `dist/generated/armor-<24位包ID>`，已有同名结果不覆盖；失败清理本次临时目录。

普通生成需要 Python 3.11+、tkinter、lz4 和原版数据读取器。启动器优先寻找项目或相邻 `hd2-lua_mods_test` 的虚拟环境，再寻找系统 Python。读取器默认相邻 `hd2-lua_mods_test/tools/archive.py`，Kit 使用绑定版本的本地快照。

固定插件、INI、校验器及发布哈希清单位于 `dist/armor-isolation-runtime/`。生成前核对其版本与文件哈希，生成后复用同一 DLL；普通用户不再需要 MSVC、CMake、Ninja。这些 C++ 工具仅用于开发者更新插件。

## 适用范围

| 输入情况 | 本版行为 |
| --- | --- |
| 单补丁三路数据，类型为 Unit/Material/Texture | 解析并校验 |
| 输入覆盖所选体甲或头盔全部非披风 Unit | 继续依赖检查和生成 |
| 模组内多个目标共用材质/纹理 | 共用一组模组私有资源 |
| V1 模组的本体、外挂材质与配件覆盖 | 保留目录和原清单，整套组件使用一致私有映射 |
| 缺 Version 的旧版清单 | 字符串 Options 为一组多选一；无/null/空 Options 读取根目录补丁 |
| 单选 4K/8K 使用不同纹理 ID | 材质槽结构与独占引用检查通过后归一逻辑纹理，仍只加载所选分支 |
| 不同模组改同一原资源 ID，目标 Kit 不同 | 按包分配私有 ID，允许并存 |
| 多个包控制同一 Kit | 生成时与启动时均可检测；通用插件拒绝冲突组 |
| 部分 Unit、纯材质/纹理、无清单的多主补丁、披风或未知类型 | 本版不支持，明确拒绝 |
| 外部原版材质再指向模组修改的纹理/基材质 | 需要额外依赖克隆，本版拒绝 |
| 游戏 DLL 或 Kit 快照不同 | 拒绝沿用旧布局 |

“候选”说明有原资源交集，不代表作者的替换意图。分析阶段检查直接结构，选择目标后才验证外部依赖，因此候选可选择不等于生成已经通过。

## 生成过程

1. 核对游戏和快照 SHA，读取 TOC，验证三路边界与重叠。副文件缺失仅在该路所有资源长度为零时允许，输出仍有三件套。
2. 从所选非披风 Piece.Unit 和动态纹理追踪 `Unit -> Material -> BaseMaterial/Texture`，只保留实际闭包；外部原版材质须检查纹理及基材质是否返回模组修改资源。
3. 输入三路 SHA、目标集合、schema、已知修正规则及并存清单哈希决定包 ID。Unit 按 `(包, Kit, 类型, 原ID)` 隔离，材质/纹理按 `(包, 类型, 原ID)` 共享。检查已知完整 ID 与高 32 位冲突。
4. 仅重写解析出的 64 位引用，保留槽哈希、骨骼索引与 Piece 标量。B-01 LOD 修正规则仅在源 Unit 主数据 SHA 精确匹配时应用。
5. 重算磁盘偏移、主/GPU 缓冲偏移和 256 字节对齐大小。回读 TOC，验证每条资源数据、源文件未变和输出不含旧 ID 覆盖。
6. 从清单导出 `runtime/ArmorIsolation/<包ID>.json`。绑定目标元数据、typed 映射、允许修改的 Piece 字段和各 Kit 实际依赖；JSON 不提供任意地址、RVA 或可执行脚本。
7. 使用与插件相同加载器的原生校验器检查配置；提供并存清单时一起转换并整组检查。成功后附带同一个预编译 DLL、INI、校验器和说明，再发布最终输出目录。

单补丁模式仍生成 `generated/generic_resource_map.hpp` 离线映射，不参与通用插件编译。模块化模式的逐补丁映射直接记录在外层 manifest；完整处理流程见[保留选项目录的隔离生成](modular-isolation-tool.md)。每个生成包的 `addon.mode` 为 `universal_runtime`，对应 JSON 路径与 DLL SHA 记入 manifest；`package_files` 记录所有输出文件的大小和哈希。

## 部署与迁移

生成工具不写游戏目录。单补丁模式退出游戏后通过管理器安装 `patch/` 三件套；选项模组导入输出的 `mod/<原目录名>/`，仍在管理器中勾选配件，每个 SubOptions 组单选。不要把所有子目录补丁同时启用，也不要导入外层隔离报告。将 `runtime/` 内容按目录结构放入游戏 `bin/`，固定 DLL 只需一份，多个包各放自己的 JSON。

旧 `CM14Isolation.addon64`、`B01Isolation.addon64` 和 `ArmorIsolation_<包ID>.addon64` 不能与通用插件同时使用。现有隔离补丁可以从对应 manifest 导出 JSON，无需重打包或更改私有 ID；详见[通用插件与旧包迁移](universal-reshade-runtime.md)。

配置在启动时整组加载，损坏或冲突配置会阻止整组发布；变更配置须重启，不热更新已发布的指针。日志成功仍不等于外观验收，需要验证体型、头盔、混搭、非目标装备及实际场景。

## 验证命令

```powershell
& 'G:\Temp\Githud\hd2-lua_mods_test\.venv\Scripts\python.exe' -X utf8 -B -m unittest discover -s tests -p 'test_*.py' -v
& '.\Start-ArmorIsolation.ps1' -SmokeTest
& 'G:\Temp\Githud\hd2-lua_mods_test\.venv\Scripts\python.exe' -X utf8 -B tools/validate_generic_samples.py
```

真实样本回归会生成 CM-14/B-01 测试包，比较目标 Unit 归属、数据哈希、互不冲突的私有 ID，以及两个包附带 DLL 的字节一致性；整个过程不逐包调用编译器。测试大包结束后删除，仅保留 [验证结果](generic-sample-validation.json)。

开发者重编固定插件使用 `tools/build_universal_addon.ps1`；脚本新建自有构建目录，运行原生配置/事务测试，生成发布哈希清单后清理临时构建目录。没有新 DLL 的游戏验收记录时，不能因自动测试通过而将生成包标成已实测。

后续扩展仍按部分模型/纯纹理的依赖克隆、更多可选依赖结构、安装事务逐项推进。

模块化输入的原始参考见 [TG-122 配件与外挂材质分析](modular-tg122-reference.md)，现已实现保留结构的多补丁生成。原清单和非补丁文件字节保留；未选择目标的资源也另用私有 ID 保存，不留下旧资源覆盖。每个模组一份有效运行时 JSON，模型配件与分辨率切换不需要重新生成 JSON，仍需完整退出游戏后部署并重启。

格式参考：[Filediver Unit](https://github.com/xypwn/filediver/blob/70f3447cd415c964e0bd29ff0770b97a4d0f160d/stingray/unit/unit.go)、[Material](https://github.com/xypwn/filediver/blob/70f3447cd415c964e0bd29ff0770b97a4d0f160d/stingray/unit/material/material.go)、[ReShade 6.5.1 SDK](https://github.com/crosire/reshade/tree/v6.5.1/include)。本机 Kit 与修复证据见固定实验记录。
