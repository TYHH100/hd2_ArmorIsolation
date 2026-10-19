"""Explain unsupported IAS file-contract conversions before invoking the native exporter."""


def unsupported_reason(profile):
    fields = profile["piece_fields"]
    if any(row["offset"] != 0 for row in fields):
        return "IAS 隔离声明 v1 不支持 Piece 纹理字段替换，不能仅交出 Unit 映射"
    archives = set()
    for kit in profile["selected_kit_metadata"]:
        if kit["archive"] in archives:
            return "多个独立 Kit 共用 Archive，IAS 隔离声明 v1 无法分别声明"
        archives.add(kit["archive"])
        if len(kit["bodies"]) != (1 if kit["type"] == 1 else 3):
            return "IAS 要求头盔 1 组、体甲 3 组 Body"
        if any(not 1 <= len(body["pieces"]) <= 64 for body in kit["bodies"]):
            return "目标超出 IAS 每组 1 至 64 个 Piece 的容量"
        count = sum(row["kit"] == kit["id"] and row["type"] == "e0a48d0be9a7453f"
                    for row in profile["mapping"])
        if not 1 <= count <= 64:
            return "目标超出 IAS 每份声明 1 至 64 条 Unit 映射的容量"
        sources = {row["source"] for row in profile["mapping"]
                   if row["kit"] == kit["id"] and row["type"] == "e0a48d0be9a7453f"}
        if any(piece["slot"] == 1 and piece["resources"]["unit"] in sources
               for body in kit["bodies"] for piece in body["pieces"]):
            return "IAS 按 Unit 匹配会同时替换默认披风，本包不能直接交接"
    if len(archives) > 256:
        return "超出 IAS 256 份隔离声明的容量"
    return None
