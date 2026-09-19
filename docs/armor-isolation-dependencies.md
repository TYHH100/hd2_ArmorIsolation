# 护甲材质依赖隔离：结构参考

核对日期：2026-09-19。下列格式来自 Filediver 上游解析代码，用于校验本机资源，不能当作游戏原生函数。URL 指向可变的 `master`。本笔记未改动游戏，也未生成部署补丁。

## 1. Unit 到 Material

来源：[unit.go](https://github.com/xypwn/filediver/blob/master/stingray/unit/unit.go#L1212)；此次目录 API 返回该文件 blob 为 `c6f4b9c685e386056357be0c6234da6239a86b35`。

所有整数为小端，下面的偏移从单个 Unit 主数据起点计算：

```text
T = u32(Unit + 0x70)                       // MaterialListOffset
N = u32(Unit + T)
slot_hash[i]   = u32(Unit + T + 4 + 4*i)
material_id[i]= u64(Unit + T + 4 + 4*N + 8*i)
表结束 = T + 4 + 12*N
```

这是先全部键、后全部值的数组，不是交错的 `(u32,u64)` 记录。`slot_hash` 是32位材料槽名称哈希；`material_id` 才是64位 `material` 资源名哈希。

Mesh 信息在 [unit.go:1177](https://github.com/xypwn/filediver/blob/master/stingray/unit/unit.go#L1177) 中按其 `MaterialOffset` 读取32位 `Materials[]`，按 `GroupOffset` 读取绘制组。`MeshGroup.MaterialIdx` 选择 Mesh 的材料槽，再通过 Unit 的材料映射找到资源。不要把组索引或32位槽哈希改成新资源ID，也不要默认材质/分组表总是紧邻固定头部。

## 2. Material 到基础材质和 Texture

来源：[material.go 头部](https://github.com/xypwn/filediver/blob/master/stingray/unit/material/material.go#L14)、[LoadMain](https://github.com/xypwn/filediver/blob/master/stingray/unit/material/material.go#L243)；此次 blob 为 `d03bd9e5f843423c07ed3d7651284d1215985a76`。

```text
BaseMaterial = u64(Material + 0x18)
N = u32(Material + 0x40)                   // NumTextures
S = u32(Material + 0x68)                   // NumSettings
texture_usage[i] = u32(Material + 0x88 + 4*i)
texture_id[i]    = u64(Material + 0x88 + 4*N + 8*i)
设置定义起点 = 0x88 + 12*N
```

头部大小 `0x88`。每条设置定义为20字节：五个 `u32` 字段 `Type, Count, Usage, Offset, Stride`；其 `Offset` 相对所有设置定义之后的数据起点。设置值主要是浮点标量/向量，不能当资源ID扫描替换。

`BaseMaterial` 指向的资源类型仍是 `material`：[提取器明确使用 `NewFileID(BaseMaterial, Sum("material"))`](https://github.com/xypwn/filediver/blob/master/extractor/material/extractor.go#L1970)。基础材质的GPU数据可以含着色器程序；不能因此将该引用类型改成 `shader`。纹理表的值指向 `texture` 资源，键是着色器用途槽。

## 3. 引用改名闭包

```text
护甲 Piece 的体型对应 Unit ID
  -> 新 Unit 资源 ID
  -> Unit.Materials 的64位值
  -> 新 Material 资源 ID
  -> Material.BaseMaterial / Material.Textures 的64位值
  -> 新基础材质 / 新 Texture 资源 ID
```

若目标包括材质与纹理完全分离，递归收集基础材质和纹理，以 `(资源类型, 资源名ID)` 去重并处理环路；每份资源同时核对其主数据、GPU数据和stream段。资源目录条目的新ID与上游引用必须一致。仅复制字节或只重命名磁盘包文件不会改变这条引用链。

护甲 Piece 的动态材质、LUT、贴花和图案引用也必须纳入：它们可能在运行时覆盖 Material 默认纹理。因此仅把 Unit 材料表和 Material 纹理表改名，不足以证明完整隔离。包资源目录和资源依赖登记是否接受新增ID，仍需独立验证。

应保持不变：资源类型ID、材料槽哈希、纹理用途哈希、参数用途哈希、Mesh材料索引、骨骼名称哈希、骨骼remap、节点索引。它们是绑定协议或局部索引，不是可任意更名的资源。

本机小范围核对入口：Archive `58e4bd4b2278d15c`，Unit `f6d665ef313b5a3c`。按上述格式先验证计数、边界、材料槽映射和引用目标类型，再对内存副本改引用；该验证只能证明字节结构与引用计划一致，不能替代游戏运行加载验证。
