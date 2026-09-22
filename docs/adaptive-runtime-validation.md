# 本机自动适配与导出验证

2026-09-21。新版 EXE：`dist/portable-adaptive/ArmorIsolation.exe`，SHA-256 `c5806ca650860ee534c87cbeaf8ab67471ac60476cf7ef17426d21d3ae7cefa4`。插件 SHA-256 `18718e762af8ab693fb5f7e2793a368570d4da9f5e53376a6c29bd34f2705e20`。

- 全新临时目录构建通用插件及校验器，2 项原生测试通过；构建临时目录自动清理。覆盖完整掩码特征的重定位、固定指令变化和歧义拒绝，以及 v2 配置混合身份/注入地址拒绝。
- Python 共 99 项，98 通过、1 项符号链接权限测试跳过。覆盖适配上下文隔离、文件变化拒绝、缺证据/污染快照拒绝、内容摘要、原子导出与离线复用、EXE 更新使旧导出失效、临时目录清理；原有生成、隔离、内嵌配置回归继续通过。
- 本机重启后只读获取 402 Kit，6 个原生函数及 Kit/资源管理器发现通过。C++ 和 Python 对 Kit 内容的摘要一致。游戏运行中的旧插件仍在；没有替换插件，也没有由本轮工具修改游戏内存。
- 按用户要求，通过新版单文件 EXE 导出 `G:/AppData/SteamLibrary/steamapps/common/Helldivers 2/ArmorIsolation.local-game.json`，2,335,780 字节。已知版本以绑定 DLL 的原始快照导出，保留两条运行中差异在诊断报告，未采纳为原始 Kit。见 [导出验证](adaptive-export-validation.json)。
- 真实四目标模组走通 v2 适配生成、资源重打包、快照随包保存、内嵌配置及原生检查，65 个资源、49 个字段、97 个依赖。该项用当前版本注入适配上下文，明确是流程模拟，没有修改游戏二进制冒充更新版本。见 [适配流程验证](adaptive-package-validation.json)。
- 单 EXE 移动至临时目录，清除 Python 搜索环境并限制 PATH，验证界面启动、实际分析/生成及手动导出；临时复制的 EXE、快照和测试包自动清理。生成验收见 [便携程序验证](adaptive-portable-validation.json)。

尚未部署新插件验证启动时自动导出，也没有真实未知版本的场景验收。当前支持范围是关键原生特征及既有数据布局仍匹配的版本，不能保证任意未来更新无需修改代码。日志每启动清空及多模组缓存优化保留；未测量大量模组的 FPS 收益。

前一阶段被自动审批以 `blocked by policy` 阻止删除的 `build/local-fixed-regression` 及三个中间文件仍保留，本轮没有绕过该拒绝；详见 [前阶段记录](local-runtime-validation.md)。

本轮最终清理 `build/adaptive-live.json`、`build/adaptive-inspection/local-game-analysis.json` 的请求同样被自动审批拒绝，仅返回 `blocked by policy`；这两份中间分析报告及所在目录暂留。上面自动临时目录内的 EXE 复制品与测试生成包已清理，游戏根目录的导出文件按用户要求保留。

依据：[Windows PE 格式](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format)、[ReadProcessMemory](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-readprocessmemory)。这些资料只支持 Windows 地址/读取规则，不证明游戏内部结构兼容。
