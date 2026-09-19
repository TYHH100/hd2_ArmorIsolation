# B-01 三个头盔缺失：定位与修正

验收更新（2026-09-19）：用户在 revision 4 测试后确认“根据测试没有任何问题”。下文保留定位阶段证据；游戏实测反馈与原生 LOD 动态跟踪是不同证据，后者未执行。

日期：2026-09-19。用户反馈来自最初 204 资源、GPU 数据展开的隔离版本：第一个头盔正常，其余三个头部缺失或偏离角色位置。此前日志八 Kit 均为 `APPLIED`，因此不能把“配置发布成功”当作模型正确绘制。GPU 磁盘去重未参与这次截图，也已按用户要求停止；后续采用同模组内部共享材质与纹理。

## 查到的差异

| Kit | 源 Unit | 源主/GPU字节 | 源 MeshInfo数 | 原版 MeshInfo数 | Joints数 |
| --- | --- | --- | ---: | ---: | ---: |
| `261c4a52` | `bc20d0b4efff128c` | 6776 / 6640456 | 5 | 5 | 18 |
| `45d80a38` | `7b23e3c0ab4cf618` | 31628 / 2967528 | 15 | 5 | 82 |
| `b4027b70` | `c96cb2e72d7a0525` | 31628 / 4324328 | 15 | 5 | 82 |
| `df8e4ada` | `781134771dd69fbe` | 31628 / 2967528 | 15 | 5 | 82 |

四个 Unit 均有完整 GPU 数据。每个 Unit 的四条材质表记录都指向 `ad686c7fb5d3db1c`，不存在漏掉第二种普通材质的问题。辅助 Mesh 使用的 `093fc934` 槽在原版中也不在普通材质表，不能据此判为丢依赖。GeometryGroup、StateMachine 均为 0。

四个主要绘制 Mesh 分别有 35515、15127、21843、15127 个顶点，索引范围正确，没有退化三角；位置均为有限值，皮肤权重和全部为 1。四头的实际几何不同，不能用“第一个 Unit 替换全部头盔”掩盖差异。

关键差异在 MeshInfo 顺序。第一个保留五 Mesh 结构，绘制 Mesh 在索引 1..4。其他三个插入了十个辅助 Mesh，总数变为十五，绘制 Mesh 移到 11..14，但 LOD 中的四个小整数仍保持原版 1..4。若按 MeshInfo 数组下标解释，LOD 此时会选择辅助 Mesh，无法选中实际头部。

## 为什么不是盲目加 10

按原版 LOD 所选 Mesh 的 `GroupBoneHash`，在源文件中查找唯一同哈希 Mesh。该字段位于每个 MeshInfo 头部 `+0x28`；Filediver 称 `GroupBoneHash`，社区 SDK 称 `MeshID`。三头的匹配结果完全一致：

| Unit 内字段偏移 | 原索引 | 原版目标哈希 | 源同哈希索引 | 源旧索引指向的哈希 |
| --- | ---: | --- | ---: | --- |
| `0xDC` | 4 | `564da8fd` | 14 | `e889a3e3` |
| `0xEC` | 3 | `7682a507` | 13 | `a620a54c` |
| `0xFC` | 2 | `e3001fda` | 12 | `bb77952b` |
| `0x154` | 1 | `547c28dd` | 11 | `cdc3c39a` |

新源中的真实 MeshID 是这些 32 位哈希，未发现保留旧小整数 1..4 的另一个显式 Mesh ID。MeshData 尾部仅有 `{count=15,0}`，不能提供把旧 1..4 映射回新 11..14 的重定向表。

外部结构证据支持修正，但还没有同版本原生 LOD 执行跟踪：Filediver 解析 `LODEntry.Indices`，按 MeshInfo 偏移表构建数组；它的导出流程不能单独证明游戏执行语义。社区 SDK 把整块 LOD 数据作为 `UnreversedLODGroupListData` 原样序列化，说明“改了 Mesh 数量而保留旧 LOD”是合理的导出问题解释，不能反推这个模组一定使用了该 SDK。

因此修正使用**源 SHA 和旧值双重守卫**：只对上述三个源 Unit 的四个字段重映射，不改第一个头盔，不替换几何，不修改所有头盔的任意同值整数。构建时记录的 `runtime_verified=false` 保留为历史机器检查状态，后续用户验收见本文开头。

## 骨架检查的结果

`Unit+0x08` 引用的是 `bones` 类型，外部名称表恰与源 Unit 同名，不是需要跟随私有 Unit 改名的 Unit 自引用。四个对应原版 Archive 都有该 bones 资源。Filediver 的 bones 解析提供名称哈希/字符串映射；关节矩阵与层级还存在 Unit 自己的 Joints 段内，不能因为 18/82 的差异直接换成另一个 bones ID。

四个源 Unit 的 Joints 段与对应原版逐字节一致。后三个绘制 Mesh 的 transform 索引仍是 78..81，与原版相同；GPU 骨索引 0 经 Remap 5 指到 Joint71，其名称哈希为 `8c5570c9`。实际使用的绑定矩阵与对应原版同哈希，未找到源数据损坏导致错绑的证据。第一个则经相同名称哈希绑定 Joint10。保留 Bones、Joints、皮肤映射和 transform 原数据。

这些检查排除了若干静态数据问题，不能保证运行时骨架链接已正确。若 LOD 修正后仍偏移，应继续观察真实实例的选择与挂接，不能直接宣布定位已闭环。

## 复查与验收

机器证据：[b01-helmet-lod-evidence.json](G:/Temp/Githud/hd2_mods-test/docs/b01-helmet-lod-evidence.json)，包含四源/原版结构、主数据 SHA、候选 12 个字段及 `native_lod_execution_verified=false`。

```powershell
& 'G:\Temp\Githud\hd2-lua_mods_test\.venv\Scripts\python.exe' -B 'G:\Temp\Githud\hd2_mods-test\tools\analyze_b01_helmets.py'
```

该脚本只读游戏和源文件，写工作区 JSON。安装新候选须正常退出游戏并停用旧原 ID 模组；当前运行进程若已切回原模组，其资源状态不能用来否定此前隔离版截图。验收逐个切换四头，保留不同模型，检查近景/远景、预览/舰桥，以及与其他体甲混搭。首次成功后还需退出重启复验。

外部参考：[Filediver Unit 结构](https://github.com/xypwn/filediver/blob/70f3447cd415c964e0bd29ff0770b97a4d0f160d/stingray/unit/unit.go#L878)、[Bones 引用读取](https://github.com/xypwn/filediver/blob/70f3447cd415c964e0bd29ff0770b97a4d0f160d/extractor/unit/extractor.go#L34)、[Bones 格式](https://github.com/xypwn/filediver/blob/70f3447cd415c964e0bd29ff0770b97a4d0f160d/stingray/bones/bones.go)、[社区 SDK Unit 导入/导出](https://github.com/Boxofbiscuits97/HD2SDK-CommunityEdition/blob/main/stingray/unit.py)。最后一个链接指向可变 main，其代码为本次查询快照。
