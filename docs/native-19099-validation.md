# 1.0.0.19099 原生适配修复

2026-09-22，只读检查本机运行中的游戏。未安装新版插件，未修改游戏内存；场景外观与启动自动导出仍待更新插件后重启验证。

## 失败原因与修复

本次 `armor_assembly` 发生真实指令变化，原完整特征正确拒绝。旧函数 RVA `0x8164b0..0x817323`，3699 字节；新函数 RVA `0x81f470..0x8202c3`，3667 字节。新入口前 32 字节在已加载模块中唯一出现，完整解码至 `ret`。七段异常展开范围连续覆盖整个函数：`0x81f470/0x81f67a/0x81f799/0x81f952/0x81f98f/0x82028b/0x820293/0x8202c3`；不能仅截取第一条 `.pdata`。

逐指令对比确认：全局对象字段 `0x1ae40→0x1ae60`、`0x2cd00→0x2d200` 等调整，外部数组步长 `0x1668→0x1690`，函数后段删除两次调用并改变寄存器传值。Kit/Body 遍历、Piece 的 Unit/Slot/Type、`+0x18..+0x50` 纹理资源字段及 `+0x58` 色调读取保持原布局。该结论来自静态运行时代码比较，不是动态调用跟踪。

保留旧完整模板；加入 `include/armor_reviewed_assembly.hpp` 的人工核验变体，由 `include/armor_assembly_compatibility.hpp` 同时扫描两种完整指令序列，不要求新版本加入 DLL 哈希白名单。除原有外部相对地址及 RIP 位移，仅参数化 11 个已核实的外部对象操作数，并检查其关系、边界和对齐：对象表字段相对位置一致，角色数组两处步长一致且数量字段位移等于 32 个元素跨度，世界对象三处字段位移保持约束。

Piece 字段、寄存器、栈槽、内部跳转、调用指令及其余函数字节保持严格匹配；不跳过任意代码段。跨两个模板只能有一个候选，装配函数两处 Kit 引用还必须等于独立遍历特征发现的 Kit 表。其余五个资源/类型函数、资源管理器结构、源值及依赖守卫全部保留。`armor_assembly` 不允许降为可选，缺任一函数就拒绝适配。操作上下文、导出与生成包仍绑定当前 DLL/EXE 哈希。

六项函数诊断一次完成，失败也记录全部结果；诊断计数不构成写入授权。界面分别显示布局结果、快照阶段和适配文件是否可用。已有可信且与当前文件匹配的导出会复用，插件加载后的观察数据不会覆盖它。

维护者可使用 `tools/generate_native_anchors.py --reviewed-assembly --pid <PID> --game <游戏目录>` 复现该变体；脚本要求已审定 DLL、模块身份、完整代码 SHA 和两次稳定读取，不接纳任意未知版本。

## 现场身份和结果

| 项目 | 已确认值 |
|---|---|
| game.dll 文件版本 | 1.0.0.19099 |
| game.dll 磁盘 SHA-256 | `73374bd4e38386beb9a23bef480082b67d457ebc77485fbec5f488b4e95e201f` |
| EXE 文件版本 | 1.8.45850.0 |
| EXE 磁盘 SHA-256 | `d8e23968d1412b07e06785321727d63edf74e711214d6f6adeb3bfca95ca6827` |
| DLL 时间戳 / SizeOfImage | `0x6aa96b14` / `0x04770000` |
| 新装配函数原始代码 SHA-256 | `809ad3d4b02ff628528e1bddc1b43dada0d6418791dc58f041d22e82fdd45f6c` |
| Kit store RVA | `0x033264f8` |
| Application RVA | `0x01a101c8` |

修复后的校验器在真实进程中匹配全部六个原生函数及资源管理器；稳定读取 411 Kit，比内置 402 条新增 9 条（各 3 件体甲、头盔、披风），缺失 0。两件体甲 `5d0d8002`、`a45385cd` 的 passive 从 40 改为 41；其余既有字段相同。涉及这些源字段的旧包仍须重新生成，不能跳过源值检查。

当前进程加载旧 `ArmorIsolation.addon64`，因此外部快照仍标记 `observed_only`，禁止提升为可复用原始快照。应正常退出游戏后安装新 DLL，重启进入主菜单，确认游戏根目录 `ArmorIsolation.local-game.json` 自动导出，再重新分析/生成。分析报告的布局通过与导出可用是不同结果。

## 验证

- 全新构建目录的 2 项原生回归通过，覆盖两种完整模板、外部参数联动、矛盾参数、装配引用不一致、Piece 字段和内部指令改变、缺失/跨模板歧义，以及全部六项诊断。同时修正日志测试对 `[CONFIG]` 字面值的旧断言错误。
- 17 项 Python 回归通过，覆盖不完整原生证据不得放行、可信导出复用及观察数据不得升级。
- 最终便携文件：`dist/portable-compatible/ArmorIsolation.exe`；发布哈希在同目录 `release.json`，本机报告在 `ArmorIsolation-output/local-game-analysis.json`，移动单文件验证记录见 `native-19099-portable-validation.json`。
- 运行时文件：`dist/armor-isolation-runtime/ArmorIsolation.addon64`；发布 SHA-256 见同目录 `runtime-release.json`。
- 游戏外观、运行时发布及本次版本的实际生成流程尚待新插件启动导出，不能将只读验证标成 `game_runtime_verified=true`。

本轮中间产物清理被自动审批拒绝（`blocked by policy`），仍保留 `build/verify-runtime`、`build/runtime-check-output`、`build/live-inspection`、`build/new-observation.json`、`dist/portable-adaptive-fixed`。`dist/portable-19099` 是本轮较早的候选，仅最终 `dist/portable-compatible` 代表本次交付。全新原生构建目录与最终打包临时目录由各自脚本清理。

依据：[Microsoft PE 格式](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format)、[ReadProcessMemory](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-readprocessmemory)。这些文档说明地址与读取规则；游戏内部布局的结论依据本机代码和测试。
