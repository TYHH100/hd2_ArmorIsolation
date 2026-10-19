# IAS 隔离后端交接

检测到 IAS 时，`ArmorIsolation.addon64` 停止自己的 Kit 写入和原生扫描，改用 IAS 的 `isolation_version=1` 文件声明。没有 IAS 时继续原有隔离。二者不同时写同一批 Kit，也不热恢复已发布的配置。

## 当前支持与边界

文件格式已核对本机 IAS 1.4.6，SHA-256：

`df37a3489edf51887cde7b130651282e3c7745d9586b9348662908403430e1d1`

IAS 没有提供本次可使用的公开源码或集成 API。这里沿用它已经消费的 `.isolation.ini`，没有调用其导出、修改其二进制、接入内部地址，亦未分发其文件或还原源码。其他 IAS 构建在核对格式前保持自有隔离暂停，并明确报告未支持。

- 每个 Kit 导出一份声明，保留原装备键、Archive 和全部原 Unit → 私有 Unit 映射，不重新分配 ID，不改补丁资源。
- 普通模型不生成 `rig_profile=`；该字段对应真实 Rig Profile 依赖，并非任意私有 Unit。
- 材质、纹理、bones 的私有引用已经写在生成资源中，原有补丁继续使用。若还需要改运行时 Piece 的纹理字段，IAS v1 无法完整表达，整组拒绝交接。
- IAS 要求体甲 3 组、头盔 1 组，每组 1..64 Piece，每份声明 1..64 条 Unit 映射。多个 Kit 使用同一 Archive 时当前不支持交接；不能错误合并不同的 Kit 私有映射。
- 同步前整组检查现有 IAS 声明的装备、Archive、身份、目标 Unit 和原始 Unit 别名冲突，失败不发布部分目标。
- 仅管理有本工具标记及匹配身份的 `armorbridge_*.isolation.ini`。停用模组后重新同步会清除对应过期声明，保留其他 IAS 声明、差分、Rig Profile、物理配置和选项。

生成器同时给出通用隔离补丁与 `ias/HD2IndependentRig/` 声明，记录在隔离包报告中，不改变源模组的标准 manifest。不能交接的包明确列出原因，不生成只有 Unit 的半份转换。

Python 图形界面和命令行共享同一原生同步入口。新版单文件工具为 `dist/portable-ias-handoff/ArmorIsolation.exe`；窗口点击“同步已安装模组到 IAS”，或执行 `ArmorIsolation.exe --cli prepare-ias --game <游戏目录>`。同步只使用已安装补丁，生成结果会分别显示声明已导出或不支持的具体原因。便携版内置本次运行组件、两份 CMD、交接说明和组件许可证。

## 安装和自动启动

新运行包位于 `dist/armor-isolation-ias-handoff/`，附带全部开源许可证。

1. 正常退出游戏，再备份并替换 `bin/ArmorIsolation.addon64`。保留已有 INI、IAS、模组补丁。不要在游戏运行时替换文件。
2. 将 `validate_runtime_profile.exe`、`Prepare-IAS-Handoff.cmd`、`Start-Game-With-Isolation.cmd` 放在同一目录。运行：

   ```powershell
   .\Prepare-IAS-Handoff.cmd "G:\AppData\SteamLibrary\steamapps\common\Helldivers 2"
   ```

   工具从当前 `data` 顶层活动主补丁和旧 `bin/ArmorIsolation/*.json` 整组读取配置，校验通过后写入 `bin/HD2IndependentRig/armorbridge_*.isolation.ini`。发现游戏进程就停止，不远程修改游戏。

3. 此后安装、卸载或切换隔离模组时，需要在下一次启动前同步。可以使用自动同步再启动的入口：

   ```powershell
   .\Start-Game-With-Isolation.cmd "G:\AppData\SteamLibrary\steamapps\common\Helldivers 2"
   ```

   没有 IAS 时预检不写文件，继续启动原隔离；有 IAS 时仅在声明校验和同步成功后启动 Steam 游戏。也可以手动同步后使用原启动方式。

4. 启动后插件自动识别 IAS，核对声明与活动补丁，显示 `IAS_HANDOFF`。它表示声明文件已准备、将 Kit 发布交给 IAS，**不表示已经观测到 IAS 实际绑定或画面正常**。缺失、过期、冲突、未知版本显示 `IAS_PAUSED` 及原因，自身仍不写 Kit；退出后重新准备。
5. IAS 在自有隔离已经发布后才加载，或 IAS 在会话中卸载/变化，显示 `RESTART_REQUIRED`。本次会话不恢复另一后端。

IAS 在自己的初始化阶段读取声明，因此运行中的插件不会生成、热加载声明或调用不明 reload ABI。直接从 Steam 启动不会自动执行本工具的离线同步；要每次自动同步请用上述启动入口。

## 只导出候选，不改游戏

```powershell
.\validate_runtime_profile.exe --ias-plan "<游戏目录>" "<新的输出目录>"
# 根据一个或多个生成主补丁导出，供生成器打包：
.\validate_runtime_profile.exe --ias-export "<新的输出目录>" "<主补丁1>" "<主补丁2>"
```

2026-10-19 只读检查当前游戏活动包：6 包、12 个 Kit、267 条资源映射、143 条 Piece 字段，字段全为 Unit。已导出 12 份候选声明，且与当前 IAS 原有声明无冲突；当前补丁不需要重命名或重打包。声明位于候选运行包的 `installed-declarations/`，只作本次环境的可审阅产物。正式同步仍按当时活动补丁重新读取，不盲目复制此快照。

## 验证与游戏反馈

- 原生回归覆盖：IAS 存在时零 Kit 写入、CAS 前晚加载拦截、卸载后锁定、无 IAS 正常发布；交接覆盖体甲/头盔、相同原 Unit 的不同私有映射、不生成虚构 Rig Profile、冲突前验证、过期声明清理、其他 IAS 文件保留及不支持的纹理/分组/Archive 组合。
- 打包回归覆盖完整模块化包中的交接文件、失败不发布、不能表达的配置不导出半份声明。
- 单文件 EXE 已在中文独立目录、移除 Python 搜索环境后完成实际生成：4 个目标、65 个资源、4 份 IAS 声明；无 IAS 时不写入声明。源模组保持不变，测试复制品和临时包已清理，详见 [便携版验证记录](ias-portable-validation.json)。
- 用户测试 IAS 交接后身体差分恢复；随后曾观察到“只保留 IAS 时头盔差分和幻化正常，启用除 B-01 外的旧隔离模组后失效”。这批旧包尚未用新工具重新生成。
- **2026-10-20 用户定位结果：头盔问题由另一个给头盔和披风添加护甲被动的 Lua 模组引起，并非本次隔离模型改造问题。** 不再据此前组合测试把头盔故障归因于私有 Unit ID，也不为此修改生成资源。Lua 与 IAS 冲突的内部机制尚未分析；该结论来自用户游戏排查反馈。
- 此前只读复核中，6 个旧包与 12 份已安装交接声明逐字节一致，旧补丁 TOC 与 IAS 自有声明的 Unit/Rig Profile ID 没有完整 ID 或 high32 的直接重合。同版本历史采集亦曾看到 IAS 头盔原 Unit 到私有 Unit 的成功绑定。这些证据与用户后续定位分开记录，不能代替完整游戏验收。

安装后需验证：日志为 `IAS_HANDOFF` 且无自有 `APPLIED`；IAS 幻化、身体/头盔差分能实际改变外观；12 个隔离目标与原共用资源的其他装备保持独立，并检查两种体型和场景切换。编译和离线回归不能替代这些步骤。

## 参考与许可证

- 模块检测和引用：[GetModuleHandleExW](https://learn.microsoft.com/en-us/windows/win32/api/libloaderapi/nf-libloaderapi-getmodulehandleexw)、[FreeLibrary](https://learn.microsoft.com/en-us/windows/win32/api/libloaderapi/nf-libloaderapi-freelibrary)。
- 文件发布：[MoveFileExW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw)。IAS 文件格式和限制来自本机同版本二进制及现有声明，不是微软文档的结论。
- [项目 MIT 许可证](../LICENSE)、[ReShade SDK 许可证](../third_party/reshade-v6.5.1/LICENSE.md)、[nlohmann/json MIT 许可证](../third_party/nlohmann-json-3.12.0/LICENSE.MIT)、[Dear ImGui MIT 许可证](../third_party/imgui/LICENSE.txt)。运行产物 `licenses/` 随附四份许可证。
