# CM-14 头盔遗漏修正

用户验收更新：2026-09-19，用户反馈“OK完美头盔正常显示”，随后要求开始 B-01 实验。CM-14 体甲与头盔显示已得到用户确认；未将该反馈扩展为所有任务场景均已自动验证。

2026-09-19 用户截图显示 CM-14 体甲替换生效，但头盔仍是原版。已确认这是首版隔离范围遗漏头盔，不是体甲修改把头盔模型损坏。

## 原因与证据

- 首版 builder 仅选择体甲 Kit `38aa207d` / Archive `b0db7f4f0a11debd` 的 26 个非披风 Unit。游戏中的同名头盔是另一条 Kit，因此其 Unit 被列入 10 项 `removed_units`。
- CM-14 头盔：Kit `203f720c`，Archive `1bf281b613081b05`，Kit Type `1`、Passive `0`；Body `3` 包含一个 Piece，Slot `0`、Type `0`、Weight `1`、ToneVariations `0`。
- 该 Piece 的 Unit 为 `db8ad4132cebf885`，material_lut 为 `4cc7808591559801`，pattern_lut 为 `f18dfbb5346732c1`；其他资源字段为零。
- TR-117 头盔 Kit `2f51d8dc` / Archive `7c3496a468bf0028` 共用同一 Unit，但 material_lut 为 `072dd57668f76d99`。直接恢复旧 Unit ID 覆盖会再次影响 TR-117。
- 以上字段来自本机版本的 `docs/armor-isolation-live-kits.json`。显示名称由 ModManager 的 `helmet-names.json` 对应 Archive 确认。

## 修正范围

保留已工作的 38 个体甲私有资源，为头盔 Kit 增加独立的 13 个私有资源：一个 Unit、一个 Material 和 11 个 Texture。共 51 个资源，各自按 Kit ID 建立命名空间。目标为体甲 26 处 Unit 引用、头盔 1 处 Unit 引用；剩余 9 个非目标 Unit 继续排除。

源头盔 Unit 有 10 个材质引用：`e61e4053c9ba5788` 四次、`84b327056baf1c6d` 两次、`a781f50f508ed81b` 四次。前者及其 11 个纹理来自源补丁，必须改为头盔私有资源；另外两个材质与 BaseMaterial `ef9b3fc2fc1ba61e` 已递归核对，不依赖这 11 个改动纹理，可保留原引用。Piece 的原版 LUT 字段保持不变。

## 验证边界

本轮修正前，运行中游戏 PID `3704` 的只读探针结果为：体甲私有资源 `38/38` 就绪、体甲原 Unit 引用 `0`、私有 Unit 引用 `26`、其他 Kit 私有引用 `0`。这证明首版体甲重定向已执行；用户截图提供体甲外观生效的观察。

扩展探针分别统计每个目标 Kit 的资源就绪数量和 Unit 引用。其他非目标 Kit 的私有引用计入 `other_private`；目标 Kit 引用另一个目标的私有资源计入 `wrong_owner_private`，两者均应为零。修正全部生效时预期体甲 `38/38`、头盔 `13/13`，Unit 私有引用分别为 `26` 和 `1`。

头盔修正仍须重新加载候选补丁和插件后验证，包括 CM-14 头盔显示、TR-117 头盔保持原外观，以及切换体甲与头盔时是否正常。构建通过或日志发布成功不能替代这一步。

## 离线结果

- 已生成 51 个私有资源，三文件共 355,395,904 字节，排除其余 9 个 Unit；输出不含源补丁任何旧资源 ID。
- 6 个构建测试通过，覆盖头盔目标不能遗漏、不同 Kit 的材质与纹理 ID 不共享，以及原有定点重写和三路打包。
- MSVC x64 Release 构建及 CTest `cm14_addon_transaction` 通过，覆盖体甲 26 / 头盔 1 个引用、元数据守卫、默认披风保留与模拟 402 项 Kit 表中的独立指针发布。插件 SHA-256 为 `ea7608d1eb96ce620a1460a187c8cb63eff976903095a1b1e553bf9f6745c91b`。
- 逐资源检查确认主数据仅改写 66 个已知 64 位引用，stream/GPU 有效数据与源模组一致。体甲的全部 38 个资源 ID 及三路有效数据与当前游戏中的首版相同。
- 12 个外部材质/基础材质依赖检查闭合，源模组三文件 SHA-256 保持不变。
- 当前游戏中三个补丁及插件哈希与首版吻合，本轮未改动这些文件；安装记录不存在，应按 README 的首版更新步骤同时更新补丁与插件。

新版探针对同一首版游戏进程的只读结果进一步确认头盔仍走原始 Unit：

```text
PRIVATE_READY 38/51
TARGET_READY kit=38aa207d 38/38
TARGET_READY kit=203f720c 0/13
TARGET_CONFIG kit=38aa207d found=1 original=0 private=26 expected=26 wrong_owner_private=0
TARGET_CONFIG kit=203f720c found=1 original=1 private=0 expected=1 wrong_owner_private=0
CONFIG_SCAN complete target_count=2 original=1 private=26 other_private=0 wrong_owner_private=0
```
