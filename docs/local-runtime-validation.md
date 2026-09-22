# 性能、日志与本机数据提取验证

2026-09-21，以下为前一阶段“性能与本机诊断版”记录；后续适配版见 [adaptive-runtime-validation.md](adaptive-runtime-validation.md)。本阶段未部署插件，未写入运行中的游戏。

- 新版 EXE：`dist/portable-local/ArmorIsolation.exe`，SHA-256 `64cfaacabc45b72f0974447a34f82e8c0cb1c03190c9e3ad1cb89266734637f2`。
- 新版插件：`dist/armor-isolation-runtime/ArmorIsolation.addon64`，SHA-256 `52574ac9eb017f6f6c5b8b0d259cb27afa28d5a24b32fa0895b9f73d7a9635f2`。
- 全新目录构建通用插件，两项原生测试通过，通用临时目录已清理；另在全新目录构建 CM14/B01 两项事务回归，通过。工具自动审批拒绝清理 `build/local-fixed-regression`（仅返回 `blocked by policy`），该目录及三个分析中间文件暂留。
- Python 96 项：95 通过，1 项符号链接权限测试跳过。
- 回归覆盖每次会话日志截断、后续追加及首次打开失败重试；候选缓存源变化失效；缺失依赖单次探测、就绪后全量复查；共享 Kit 索引过期/重复拒绝；特征重定位、歧义、修改和越界拒绝；SHA-256 已知向量；诊断差异和失败清理。
- 本机只读提取 402 条 Kit，磁盘 DLL SHA-256 `cc75948d90fdfde259dcb519e9933db7ffa3ccb281ce4fb89e6b1b011557470c`，版本 `1.0.0.18930`。与原始基准相比，`41dd184d`、`bc5cf836` 两条 Body 数据不同，未确认差异来源，未回写基准。
- 移动单个 EXE、移除 Python 环境并限制 PATH 后，完成 GUI 启动、本机提取及实际四目标模组生成。详见 [本机提取记录](local-data-validation.json) 和 [生成验证记录](local-portable-validation.json)。测试复制品和生成包已自动清理。

性能改善来自每轮共用 Kit 表扫描、按目标索引映射、复用未变化候选、优先探测上次缺失依赖。未进行大量模组的游戏帧时间压测，不能将回归通过解释为 FPS 提升数值。

自动提取与比较已可使用；未知游戏版本的完整自动适配尚未完成，生成器及运行时仍有原版本守卫。原生接口参考：[ReadProcessMemory](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-readprocessmemory)、[PE 格式](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format)。
