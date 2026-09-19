# 保留选项目录的隔离生成

本版支持直接选择旧版或 V1 模组根目录或它的 `manifest.json`。目标体甲和头盔仍须明确勾选；配件与分辨率不在生成时拍平，生成后继续在模组管理器的原选项界面选择。

缺少 `Version` 的清单按旧版处理：字符串数组 `Options` 是一组目录的多选一；`Options` 缺失、null 或空数组时读取根目录补丁。有非空 `Options` 时仅加载所选目录，不自动叠加根目录补丁；目录读取不递归。工具只在内存中归一组件关系，输出保留原清单字节和格式，不补写 `Version` 或改成 V1。选项语义核对自本地管理器 `LegacyModManifest` 与 `ModService.Deploy.GetSelectedPatchFiles`，对应[管理器源码仓库](https://github.com/TYHH100/Helldivers2ModManager)。

## 输出与使用

```text
armor-<包ID>/
  mod/
    <原模组目录名>/
      manifest.json
      <原图片、说明、备份、空目录>
      <原本体目录>/<原补丁文件名和三路数据>
      <原配件目录>/<原补丁文件名和三路数据>
      <原材质目录>/<原分辨率子目录>/<原补丁三路数据>
  runtime/
    ArmorIsolation.addon64
    ArmorIsolation.ini
    ArmorIsolation/<包ID>.json
  manifest.json
  README.md
  runtime-check.log
```

内层 `mod/<原名>/manifest.json` 是原模组清单，原字节保留，包括 Guid、名称、Options、SubOptions、Include、说明及未知附加字段。外层 `manifest.json` 是隔离报告，不能作为模组导入。补丁文件名和所在目录不变，三路内容重打包；所有其他文件原字节复制，原先不存在的默认目录不会被补建。

1. 双击 `Start-ArmorIsolation.cmd`，选择整个源模组目录，或其中的 `manifest.json`。
2. 分析后勾选实际替换的体甲和头盔，生成隔离包。
3. 退出游戏，在管理器中导入输出的 `mod/<原模组名>/`。源清单 Guid 保留，原版与隔离版应通过替换/重新导入切换，不能作为两个相同身份的模组同时启用。
4. 按包内 README 启用基础模型及共享材质选项，其他配件仍独立开关。每个 `SubOptions` 组仍只能选一个，4K 与 8K 不同时安装。
5. 安装包内新版通用 DLL 和本包唯一的 JSON；其他隔离包共用这一份 DLL。以后只改本模组选项时，使用同一 JSON，完整退出游戏后重新部署并重启。

工具只写新的输出目录，源模组和游戏目录不修改。源备份文件也会原样保留；它们是原版备份，不是隔离后的活动补丁。

## 为什么选项仍然有效

资源身份以 `(类型, 原 ID)` 识别。所有组件共用一次分配的映射，本体与配件覆盖同一 Unit 时，输出也覆盖同一私有 Unit。两种体型的不同 Unit 分别处理；多个目标 Kit 原来共用 Unit 时，每个 Kit 分配自己的 Unit，并在各组件补丁内写出相应副本。

每个源 patch 仍单独打包到原路径，不决定哪个版本最终胜出，不按目录顺序重新排列选项，也不把所有可选模型合并成一个。目录、补丁名、Include 和互斥子项关系都保持原样，因此原来的覆盖关系在私有 ID 上继续存在。

跨全部组件追踪材质依赖，模组内的材质和纹理使用一份共享私有映射，留在原材质包里。选定 Kit 不使用的资源也不会删掉：它们另分配未绑定到目标 Kit 的私有 ID，仍保存在原补丁中，避免留下继续覆盖原版的旧 ID。这些资源记录为 `preserved_unbound_mapping`，不加入插件等待列表；提供并存清单时也会预留其 ID。

保持目录中的内容不等于补丁字节完全不变：补丁需要更新 TOC、64 位资源引用与对齐；其他文件保持原字节。每个资源的 stream/GPU 有效数据逐段回读核对，模型主数据只允许已知引用更新及精确哈希匹配的已有 LOD 修正。

## 4K / 8K 使用不同纹理 ID

shinano 样本实际结构为：

- 模型：36 个 Unit，1 个 Material。
- 4K：1 个 Material，3 个 Texture。
- 8K：1 个 Material，3 个 Texture。
- 三个补丁共用 Material `6653c9ef87183af4`，4K 与 8K 的三个纹理原 ID 各自不同。模型内还保留该材质的原版纹理引用版本。

只使用全部原 ID 的并集作为插件依赖，会错误等待未选分辨率的纹理。实现采用互斥材质槽归一：

1. 只检查 manifest 明确互斥的纯 Material/Texture 子选项，名称是否叫 4K/8K 不参与判断。
2. 各分支 Material 资源集合必须一致；清除 Texture64 引用值后，材质主数据必须逐字节相同。本样本每份材质主数据为 1,408 字节，归一后的 SHA 为 `d14c7c8a0e8144e8f65c44876f5ebce5d21586a438f18f06335daee6d9d00db1`。
3. 按原有 32 位材质槽对应纹理，确认每个分支都有自己的本地纹理。相同外部原版引用不改名；不同材质、未知引用或不完整对应不进行推断。
4. 检查别名不能在一个分支内相撞，也不能被组外组件或 Kit 动态纹理直接使用；满足条件才映射到同一私有纹理 ID。
5. 4K/8K 的分辨率、有效 GPU 字节和原始存放目录全部保留。插件只登记对应的三个逻辑纹理，无论选择哪一个分辨率都满足同一份 JSON。

此处同私有 ID 表示互斥版本，不表示两种分辨率内容相同，也不表示两者同时加载。源模型中的原版材质版本保持原来的外部引用，最终由原模组选项的覆盖关系决定使用哪个版本。

## 运行时依赖

先计算所选 Kit 在所有模型版本中的依赖并集，然后证明基础选项能提供这些 ID。每个带子项的选项使用“父 Include 加每一个单选分支”所能提供 ID 的交集；不是把兄弟分支同时启用。

基础模型选项必须在所有自身子项中提供完整目标 Unit；材质选项必须在每个分辨率选择中提供所需逻辑资源。README 和报告列出 `required_options`。TG-122 为“本体、材质包”，shinano 为“模型、贴图”；其他配件开关不被强制启用。

不能证明某个可选组合具备这些依赖时，生成器会拒绝输出。当前不自动克隆未知原版材质，不支持任意缺模型的部分替换或多层嵌套 SubOptions；这些情况不能用一份并集 JSON 假装已支持。

TG-122 的头盔 Kit `c1611ac9` 在绑定快照中同时含 Slot1 默认披风和 Slot0 头盔。此次修正通用加载器：允许头盔元数据保留默认披风，但 Slot1 仍不改 Unit、不改材质，不计入私有资源要求；仅含披风或混入体甲 Slot 的头盔配置仍拒绝。为此重新构建了通用 DLL，旧 JSON schema 与私有 ID 不变。

## 验证与记录

```powershell
& 'G:\Temp\Githud\hd2-lua_mods_test\.venv\Scripts\python.exe' -X utf8 -B -m unittest discover -s tests -p 'test_*.py' -v
& '.\Start-ArmorIsolation.ps1' -SmokeTest
& 'G:\Temp\Githud\hd2-lua_mods_test\.venv\Scripts\python.exe' -X utf8 -B tools/validate_modular_sample.py
& 'G:\Temp\Githud\hd2-lua_mods_test\.venv\Scripts\python.exe' -X utf8 -B tools/validate_modular_sample.py --sample resolution
```

样本脚本生成临时隔离包，验证原生配置加载、全部目录/文件名、原清单及附带文件字节、每条资源数据和源未变，结束删除临时大包，只留下小型证据 JSON。TG-122 遍历 96 个选项组合；分辨率样本分别只启用 4K、只启用 8K。对原始补丁与隔离补丁分别模拟先出现优先和后出现优先，核对覆盖来源一致，不能据此宣称已确认游戏加载器使用哪一种优先级。

本次验证：Python 75 项通过、1 项实际 symlink 创建因权限不足跳过；模拟 Windows reparse 拒绝测试通过。新版通用插件两项原生测试及 GUI 启动通过。TG-122 29 文件/10 目录完整保留，59 个私有资源、192 次覆盖等价检查通过；分辨率样本 14 文件/4 目录完整保留，58 个私有资源、两种单选分支共 4 次覆盖等价检查通过。

旧版兼容回归：夏安 B-27 / CE-101 样本的两件体甲、两个头盔共 4 个目标完整生成，原生校验为 `PROFILE_OK packages=1 targets=4 resources=65 fields=49 required=97`；原清单与图片逐字节一致，文件路径集合保留。Python 共 80 项测试，79 项通过、1 项 symlink 权限不足跳过。临时包已清理，未部署或游戏验证。

另为游戏测试保留了 `dist/modular-preserved/` 下两份正式输出，和已清理的临时验证包分开。shinano 生成时提供 TG-122 并存清单，整组原生配置校验通过：`packages=2 targets=6 resources=117 fields=77 required=141`。正式包的 private ID 以各自外层报告为准；带并存清单生成的 shinano 包 ID 与独立回归记录不同，不得混用两者 JSON。

- [TG-122 验证结果](modular-sample-validation.json)
- [4K / 8K 验证结果](resolution-sample-validation.json)
- [TG-122 原始资源分析](modular-tg122-reference.md)
- [通用插件与旧包迁移](universal-reshade-runtime.md)

这些是离线数据与配置验证。游戏内两种体型、头盔、配件、分辨率切换、其他装备和场景仍需实测，新生成包均保留 `game_runtime_verified=false`。

实现入口：[build_modular_isolated.py](../tools/build_modular_isolated.py)、[modular_source.py](../tools/modular_source.py)、[modular_texture_aliases.py](../tools/modular_texture_aliases.py)。材质槽格式参考沿用 [Filediver 固定提交的 Material 定义](https://github.com/xypwn/filediver/blob/70f3447cd415c964e0bd29ff0770b97a4d0f160d/stingray/unit/material/material.go)，别名可行性以本地样本的结构与引用检查为准。
