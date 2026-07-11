"""统计计算：按时间 / 地点 / 分类 / 总览。

入参 rows 为已排除充值的支出列表（每条含 txdate, mername, amount, category）。
"""
from collections import defaultdict
from datetime import datetime


def _parse(txdate: str):
    try:
        return datetime.strptime(txdate[:19], "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def _time_key(txdate: str, granularity: str) -> str:
    dt = _parse(txdate)
    if dt is None:
        return (txdate or "")[:10] or "未知"
    if granularity == "month":
        return dt.strftime("%Y-%m")
    if granularity == "year":
        return dt.strftime("%Y")
    if granularity == "week":
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    return dt.strftime("%Y-%m-%d")  # day（默认）


def by_time(rows: list, granularity: str = "day") -> list:
    """时间序列：[{key, total, count}]，按 key 升序。"""
    buckets: dict = defaultdict(lambda: {"total": 0.0, "count": 0})
    for r in rows:
        k = _time_key(r["txdate"], granularity)
        buckets[k]["total"] += r["amount"]
        buckets[k]["count"] += 1
    items = [
        {"key": k, "total": round(v["total"], 2), "count": v["count"]}
        for k, v in buckets.items()
    ]
    items.sort(key=lambda x: x["key"])
    return items


def by_location(rows: list, top_n: int = 15) -> list:
    """地点（商户）排行：[{name, total, count}]，按金额倒序，取前 top_n。"""
    agg: dict = defaultdict(lambda: {"total": 0.0, "count": 0})
    for r in rows:
        name = r["mername"] or "未知商户"
        agg[name]["total"] += r["amount"]
        agg[name]["count"] += 1
    items = [
        {"name": k, "total": round(v["total"], 2), "count": v["count"]}
        for k, v in agg.items()
    ]
    items.sort(key=lambda x: x["total"], reverse=True)
    return items[:top_n]


def _cafeteria_name(mername: str) -> str:
    """从商户名提取食堂名。
    规则：
    - 天猫* → 保留全名以区分各分店（天猫清芬店、天猫观畴店等）
    - 含 _ → 取 _ 前部分（如 清芬园_一层主食 → 清芬园）
    - 其他 → 保留原名
    """
    name = (mername or "").strip()
    if "_" in name:
        return name.split("_")[0]
    return name


# 清华 16 座食堂白名单（食堂广度 / 忠诚度勋章只计这些）
_KNOWN_CANTEENS = {
    "紫荆园", "桃李园", "清芬园", "听涛园", "丁香园", "观畴园", "玉树园", "澜园",
    "寓园", "南园", "荷园", "芝兰园", "北园", "家园", "熙春园", "融园",
}


def _window_name(mername: str) -> str:
    """从商户名提取窗口名。规则：取 '_' 后部分；若无 '_' 则为空。"""
    name = (mername or "").strip()
    if "_" in name:
        parts = name.split("_", 1)
        return parts[1] if len(parts) > 1 else ""
    return ""


def by_location_detailed(rows: list) -> list:
    """地点（商户）详细统计（窗口级）：含地址、笔均、占比，按金额倒序。"""
    agg: dict = defaultdict(lambda: {"total": 0.0, "count": 0, "addr": "", "category": ""})
    for r in rows:
        name = r["mername"] or "未知商户"
        agg[name]["total"] += r["amount"]
        agg[name]["count"] += 1
        agg[name]["addr"] = r.get("meraddr") or agg[name]["addr"] or ""
        agg[name]["category"] = r.get("category") or agg[name]["category"] or ""
    grand_total = sum(v["total"] for v in agg.values())
    items = []
    for name, v in agg.items():
        items.append({
            "name": name,
            "cafeteria": _cafeteria_name(name),
            "window": _window_name(name),
            "addr": v["addr"],
            "category": v["category"],
            "total": round(v["total"], 2),
            "count": v["count"],
            "avg": round(v["total"] / v["count"], 2) if v["count"] else 0,
            "pct": round(v["total"] / grand_total * 100, 1) if grand_total > 0 else 0,
        })
    items.sort(key=lambda x: x["total"], reverse=True)
    return items


def by_location_cafeteria(rows: list) -> list:
    """地点（商户）详细统计（食堂级）：按食堂聚合，含笔均、占比、窗口数，按金额倒序。"""
    agg: dict = defaultdict(lambda: {"total": 0.0, "count": 0, "windows": set(), "cats": defaultdict(float)})
    for r in rows:
        name = r["mername"] or "未知商户"
        caf = _cafeteria_name(name)
        agg[caf]["total"] += r["amount"]
        agg[caf]["count"] += 1
        agg[caf]["windows"].add(name)
        agg[caf]["cats"][r.get("category") or "其他"] += r["amount"]
    grand_total = sum(v["total"] for v in agg.values())
    items = []
    for caf, v in agg.items():
        # 标签取该分组下金额占比最高的交易分类（如天猫校园 → 超市，而非笼统"食堂"）
        cat = max(v["cats"], key=lambda k: v["cats"][k]) if v["cats"] else "食堂"
        items.append({
            "name": caf,
            "cafeteria": caf,
            "window": "",
            "addr": "",
            "category": cat,
            "total": round(v["total"], 2),
            "count": v["count"],
            "avg": round(v["total"] / v["count"], 2) if v["count"] else 0,
            "pct": round(v["total"] / grand_total * 100, 1) if grand_total > 0 else 0,
            "window_count": len(v["windows"]),
        })
    items.sort(key=lambda x: x["total"], reverse=True)
    return items


def by_category(rows: list) -> list:
    """分类汇总：[{category, total, count}]，按金额倒序。"""
    agg: dict = defaultdict(lambda: {"total": 0.0, "count": 0})
    for r in rows:
        cat = r["category"] or "其他"
        agg[cat]["total"] += r["amount"]
        agg[cat]["count"] += 1
    items = [
        {"category": k, "total": round(v["total"], 2), "count": v["count"]}
        for k, v in agg.items()
    ]
    items.sort(key=lambda x: x["total"], reverse=True)
    items.append({
        "category": "合计", "total": round(sum(i["total"] for i in items), 2),
        "count": sum(i["count"] for i in items),
    })
    return items


def summary(rows: list) -> dict:
    """总览：总支出、笔数、笔均、日均、活跃天数、最大单笔/日/月/年、本月支出、日期范围。"""
    if not rows:
        return {
            "total": 0, "count": 0, "avg": 0, "daily_avg": 0, "days": 0,
            "this_month": 0, "date_from": "", "date_to": "",
            "max": {"amount": 0, "txdate": "", "mername": ""},
            "max_day": {"date": "", "amount": 0, "count": 0},
            "max_month": {"month": "", "amount": 0, "count": 0},
            "max_year": {"year": "", "amount": 0, "count": 0},
        }
    total = round(sum(r["amount"] for r in rows), 2)
    count = len(rows)
    dates = sorted({r["txdate"][:10] for r in rows if r.get("txdate")})
    days = len(dates)
    mr = max(rows, key=lambda r: r["amount"])
    ym = datetime.now().strftime("%Y-%m")
    this_month = round(
        sum(r["amount"] for r in rows if (r.get("txdate") or "")[:7] == ym), 2
    )

    # 最大日支出
    day_agg: dict = defaultdict(lambda: {"amount": 0.0, "count": 0})
    for r in rows:
        d = (r.get("txdate") or "")[:10]
        day_agg[d]["amount"] += r["amount"]
        day_agg[d]["count"] += 1
    max_day_date = max(day_agg, key=lambda k: day_agg[k]["amount"]) if day_agg else ""
    max_day = {
        "date": max_day_date,
        "amount": round(day_agg[max_day_date]["amount"], 2),
        "count": day_agg[max_day_date]["count"],
    } if max_day_date else {"date": "", "amount": 0, "count": 0}

    # 最大月支出
    month_agg: dict = defaultdict(lambda: {"amount": 0.0, "count": 0})
    for r in rows:
        m = (r.get("txdate") or "")[:7]
        month_agg[m]["amount"] += r["amount"]
        month_agg[m]["count"] += 1
    max_month_key = max(month_agg, key=lambda k: month_agg[k]["amount"]) if month_agg else ""
    max_month = {
        "month": max_month_key,
        "amount": round(month_agg[max_month_key]["amount"], 2),
        "count": month_agg[max_month_key]["count"],
    } if max_month_key else {"month": "", "amount": 0, "count": 0}

    # 最大年支出
    year_agg: dict = defaultdict(lambda: {"amount": 0.0, "count": 0})
    for r in rows:
        y = (r.get("txdate") or "")[:4]
        year_agg[y]["amount"] += r["amount"]
        year_agg[y]["count"] += 1
    max_year_key = max(year_agg, key=lambda k: year_agg[k]["amount"]) if year_agg else ""
    max_year = {
        "year": max_year_key,
        "amount": round(year_agg[max_year_key]["amount"], 2),
        "count": year_agg[max_year_key]["count"],
    } if max_year_key else {"year": "", "amount": 0, "count": 0}

    return {
        "total": total,
        "count": count,
        "avg": round(total / count, 2) if count else 0,
        "daily_avg": round(total / days, 2) if days else 0,
        "days": days,
        "this_month": this_month,
        "date_from": dates[0],
        "date_to": dates[-1],
        "max": {
            "amount": mr["amount"],
            "txdate": mr["txdate"],
            "mername": mr["mername"],
        },
        "max_day": max_day,
        "max_month": max_month,
        "max_year": max_year,
    }


def _hour(txdate: str) -> int:
    """从 txdate 提取小时（0-23），无效返回 -1。"""
    h = (txdate or "")[11:13]
    return int(h) if h.isdigit() else -1


def _is_water_window(name: str) -> bool:
    """判断是否为饮水机/直饮水等非就餐窗口（不计入窗口类勋章）。"""
    n = name or ""
    return ("饮水" in n) or ("开水" in n) or ("直饮" in n) or n.endswith("BOT") or ("_BOT" in n)


def _resolve_series(title, value, tiers, progress_str):
    """解析一个勋章系列：取达成最高档为当前勋章，未达最低档则锁定。
    tiers: 升序 [(threshold, icon, name, tier_color, thresh_desc), ...]
    返回带 series/level/maxLevel/family 的勋章对象，desc 为达成门槛。
    """
    earned_idx = -1
    for i, t in enumerate(tiers):
        if value >= t[0]:
            earned_idx = i
    # 家族：每一档的达成状态（done/current/locked）
    family_rows = []
    for i, t in enumerate(tiers):
        _th, icon, name, color, desc = t
        if i == earned_idx:
            status = "current"
        elif i < earned_idx:
            status = "done"
        else:
            status = "locked"
        family_rows.append({"icon": icon, "name": name, "desc": desc, "status": status})
    if earned_idx >= 0:
        _th, icon, name, color, desc = tiers[earned_idx]
        return {
            "series": title, "icon": icon, "name": name, "tier": color,
            "level": earned_idx + 1, "maxLevel": len(tiers),
            "desc": desc, "progress": progress_str, "earned": True,
            "family": {"title": title, "progress": progress_str, "rows": family_rows},
        }
    _th, icon, name, _color, desc = tiers[0]
    return {
        "series": title, "icon": icon, "name": name, "tier": "",
        "level": 0, "maxLevel": len(tiers),
        "desc": desc, "progress": progress_str, "earned": False,
        "family": {"title": title, "progress": progress_str, "rows": family_rows},
    }


def _single_badge(icon, name, cond, color, desc, progress_str):
    """单枚勋章（无升级系列）。"""
    status = "current" if cond else "locked"
    return {
        "series": "", "icon": icon, "name": name, "tier": color if cond else "",
        "level": 1 if cond else 0, "maxLevel": 1,
        "desc": desc, "progress": progress_str, "earned": bool(cond),
        "family": {"title": name, "progress": progress_str,
                   "rows": [{"icon": icon, "name": name, "desc": desc, "status": status}]},
    }


def badges(rows: list) -> dict:
    """勋章（徽章）计算，基于真实消费数据。
    采用「升级系列」设计：同一指标的多档勋章合并为一枚可升级勋章（带等级点），
    消除重复；desc 显示达成门槛，progress 显示当前值。
    阈值面向广大用户分层（新手→资深）。返回 {"badges": [...], "count", "total"}。
    制霸类勋章（食堂/清青/水果…全制霸）由前端基于成就数据补充。
    """
    # ---------- 计算各项指标 ----------
    total = round(sum(r["amount"] for r in rows), 2)
    count = len(rows)
    date_set = {r["txdate"][:10] for r in rows if r.get("txdate")}
    sorted_dates = sorted(date_set)
    days = len(date_set)
    # 最长连续活跃天数（不间断打卡）
    max_streak = 0
    cur_streak = 0
    for i, d in enumerate(sorted_dates):
        if i == 0:
            cur_streak = 1
        else:
            from datetime import datetime
            prev = datetime.strptime(sorted_dates[i - 1], "%Y-%m-%d")
            curr = datetime.strptime(d, "%Y-%m-%d")
            if (curr - prev).days == 1:
                cur_streak += 1
            else:
                cur_streak = 1
        if cur_streak > max_streak:
            max_streak = cur_streak
    max_amount = max((r["amount"] for r in rows), default=0)

    caf_agg: dict = defaultdict(lambda: {"total": 0.0, "count": 0})
    for r in rows:
        caf = _cafeteria_name(r.get("mername") or "")
        caf_agg[caf]["total"] += r["amount"]
        caf_agg[caf]["count"] += 1
    # 已知食堂子集（食堂广度 / 忠诚度只计 16 座食堂，排除便利店/超市/水果店等）
    known_caf_agg = {k: v for k, v in caf_agg.items() if k in _KNOWN_CANTEENS}
    distinct_caf = len(known_caf_agg)

    # 窗口级聚合（排除饮水机等非就餐窗口）
    win_agg: dict = defaultdict(lambda: {"total": 0.0, "count": 0})
    for r in rows:
        name = r.get("mername") or "未知"
        if _is_water_window(name):
            continue
        win_agg[name]["total"] += r["amount"]
        win_agg[name]["count"] += 1
    distinct_win = len(win_agg)
    top_win = max(win_agg.items(), key=lambda kv: kv[1]["count"]) if win_agg else None
    top_win_count = top_win[1]["count"] if top_win else 0

    # 食堂忠诚度（最高占比食堂从已知食堂中选取，分母为全部消费总额，与地点统计页面一致）
    best_caf = max(known_caf_agg.items(), key=lambda kv: kv[1]["total"]) if known_caf_agg else None
    best_caf_share = (best_caf[1]["total"] / total * 100) if (best_caf and total > 0) else 0

    # 笔均价（样本≥3 的食堂中最高，所有商户均可参与）
    avg_list = [v["total"] / v["count"] for v in caf_agg.values() if v["count"] >= 3]
    best_avg_val = max(avg_list) if avg_list else 0

    early = sum(1 for r in rows if 0 <= _hour(r.get("txdate") or "") < 7)
    late = sum(1 for r in rows if _hour(r.get("txdate") or "") >= 22)
    midnight = sum(1 for r in rows if 0 <= _hour(r.get("txdate") or "") < 5)

    day_agg: dict = defaultdict(float)
    for r in rows:
        day_agg[(r.get("txdate") or "")[:10]] += r["amount"]
    max_day_total = max(day_agg.values()) if day_agg else 0

    money_s = "¥" + format(int(total), ",")
    result = []

    # ===== 升级系列（每系列一枚，显示当前最高档 + 等级点） =====
    result.append(_resolve_series("消费额度", total, [
        (1000, "💰", "小富翁", "bronze", "累计消费 ¥1000+"),
        (5000, "💸", "挥金如土", "silver", "累计消费 ¥5000+"),
        (10000, "🤑", "富甲一方", "gold", "累计消费 ¥10000+"),
        (20000, "👑", "富可敌国", "gold", "累计消费 ¥20000+"),
    ], money_s))

    result.append(_resolve_series("消费频次", count, [
        (100, "🍴", "小吃货", "bronze", "累计 100+ 笔消费"),
        (500, "🍱", "饭桶本桶", "silver", "累计 500+ 笔消费"),
        (2000, "🤖", "干饭机器", "gold", "累计 2000+ 笔消费"),
        (5000, "🐲", "饭神在世", "gold", "累计 5000+ 笔消费"),
    ], str(count) + " 笔"))

    result.append(_resolve_series("食堂广度", distinct_caf, [
        (3, "🐣", "初出茅庐", "bronze", "探索 3+ 个食堂"),
        (8, "🥢", "老饕", "silver", "探索 8+ 个食堂"),
        (12, "🗺️", "地头蛇", "gold", "探索 12+ 个食堂"),
    ], str(distinct_caf) + " 个"))

    result.append(_resolve_series("窗口广度", distinct_win, [
        (30, "🔍", "美食侦探", "bronze", "光顾 30+ 个不同窗口"),
        (60, "🐙", "八爪鱼", "silver", "光顾 60+ 个不同窗口"),
        (100, "🌊", "海王", "gold", "光顾 100+ 个不同窗口"),
    ], str(distinct_win) + " 个"))

    result.append(_resolve_series("食堂忠诚度", best_caf_share, [
        (20, "💕", "情有独钟", "bronze", "某食堂消费占比 20%+"),
        (35, "💗", "深情专一", "silver", "某食堂消费占比 35%+"),
        (50, "❤️", "从一而终", "gold", "某食堂消费占比 50%+"),
    ], "最高 " + str(round(best_caf_share)) + "%"))

    result.append(_resolve_series("窗口忠诚度", top_win_count, [
        (10, "🤝", "老朋友", "bronze", "单个窗口打卡 10+ 次"),
        (50, "💍", "缘定此窗", "silver", "单个窗口打卡 50+ 次"),
        (200, "🏠", "此窗我家", "gold", "单个窗口打卡 200+ 次"),
    ], "最高 " + str(top_win_count) + " 次"))

    result.append(_resolve_series("笔均价", best_avg_val, [
        (12, "💎", "轻奢食堂", "silver", "某食堂笔均价 ¥12+"),
        (20, "👑", "贵族食堂", "gold", "某食堂笔均价 ¥20+"),
    ], "最高 ¥" + str(round(best_avg_val, 1))))

    result.append(_resolve_series("连续活跃", max_streak, [
        (7, "📆", "坚持打卡", "bronze", "连续活跃 7+ 天"),
        (30, "🔥", "持之以恒", "silver", "连续活跃 30+ 天"),
        (100, "🏅", "钢铁意志", "gold", "连续活跃 100+ 天"),
    ], "最长连续 " + str(max_streak) + " 天"))

    result.append(_resolve_series("单日爆发", max_day_total, [
        (50, "💥", "小试牛刀", "bronze", "单日消费 ¥50+"),
        (150, "🔥", "豪掷千金", "silver", "单日消费 ¥150+"),
        (300, "🎆", "破产一日游", "gold", "单日消费 ¥300+"),
    ], "最高 ¥" + str(round(max_day_total))))

    # ===== 可成长系列（原单枚，现多档） =====
    result.append(_resolve_series("早起鸟", early, [
        (10, "🌅", "早起鸟", "bronze", "7点前消费 10+ 次"),
        (30, "🐓", "闻鸡起舞", "silver", "7点前消费 30+ 次"),
        (100, "☀️", "晨曦使者", "gold", "7点前消费 100+ 次"),
    ], str(early) + " 次"))

    result.append(_resolve_series("夜猫子", late, [
        (10, "🌙", "夜猫子", "bronze", "22点后消费 10+ 次"),
        (30, "🦉", "熬夜冠军", "silver", "22点后消费 30+ 次"),
        (100, "🌃", "暗夜行者", "gold", "22点后消费 100+ 次"),
    ], str(late) + " 次"))

    result.append(_resolve_series("单笔爆发", max_amount, [
        (30, "🐬", "海豚一笔", "bronze", "单笔消费 ¥30+"),
        (50, "🐋", "鲸鱼一笔", "silver", "单笔消费 ¥50+"),
        (100, "🐉", "鲸吞四海", "gold", "单笔消费 ¥100+"),
    ], "最大 ¥" + str(round(max_amount))))

    # ===== 单枚勋章（无系列） =====
    result.append(_single_badge("🌱", "第一餐", count >= 1, "bronze", "完成第一笔消费", str(count) + " 笔"))
    result.append(_single_badge("🌃", "夜半食客", midnight >= 1, "gold", "凌晨 0-5 点消费", str(midnight) + " 次"))
    result.append(_single_badge("🦉", "昼伏夜出", early >= 5 and late >= 5, "gold", "清晨&深夜各 5+ 次", "早" + str(early) + "/夜" + str(late)))

    earned_count = sum(1 for b in result if b["earned"])
    return {"badges": result, "count": earned_count, "total": len(result)}



