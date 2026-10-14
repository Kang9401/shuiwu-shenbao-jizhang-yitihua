def income_category(item: str, fallback: str = "") -> str:
    item = item or ""
    if "限售股" in item or "限售股" in fallback:
        return "限售股所得"
    if "偶然" in item:
        return "分类所得"
    if any(word in item for word in ("工资薪金", "劳务报酬", "证券经纪", "稿酬", "特许权使用费")):
        return "综合所得"
    if "综合" in fallback:
        return "综合所得"
    return "分类所得"
