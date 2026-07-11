"""Eat_stat 后端：Flask 提供 REST API 与静态前端。

仅监听 127.0.0.1，不对外。启动后自动打开浏览器。
"""
import threading
import webbrowser
from datetime import datetime, timedelta

from flask import Flask, jsonify, request, send_from_directory

import auth
import categorize
import config
import db
import mock_data
import stats

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.json.ensure_ascii = False  # 接口中文原样输出，便于调试与可读


# ----------------------------- 工具 -----------------------------

def _owner() -> str:
    """当前活跃帐户的 idserial，用于数据库过滤。"""
    return (config.load_config().get("idserial") or "").strip()


# ----------------------------- 页面 -----------------------------

@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ----------------------------- 配置 -----------------------------

@app.get("/api/config")
def api_get_config():
    cfg = config.load_config()
    return jsonify({
        "idserial": cfg["idserial"],
        "servicehall_masked": config.mask_cookie(cfg["servicehall"]),
        "has_servicehall": bool(cfg["servicehall"]),
        "last_sync_date": cfg["last_sync_date"],
    })


@app.post("/api/config")
def api_set_config():
    body = request.get_json(silent=True) or {}
    cfg = config.load_config()
    if "idserial" in body:
        cfg["idserial"] = (body.get("idserial") or "").strip()
    if "servicehall" in body:
        cfg["servicehall"] = (body.get("servicehall") or "").strip()
    config.save_config(cfg)
    return jsonify({
        "ok": True,
        "idserial": cfg["idserial"],
        "servicehall_masked": config.mask_cookie(cfg["servicehall"]),
        "has_servicehall": bool(cfg["servicehall"]),
    })


# ----------------------------- 同步（爬虫） -----------------------------

def do_sync(cfg: dict, start: str, end: str):
    """执行同步，返回 (result_dict, status_code)。cookie 必须已在 cfg['servicehall']。

    会自动从 API 获取 idserial（若未配置），并将所有数据打上 owner 标记。
    """
    import scraper  # 延迟导入：未装 pycryptodome 时不影响其他功能

    if not cfg.get("servicehall"):
        return {"error": "未配置 Cookie，请先「登录清华」或手动填入 Cookie",
                "code": "no_credential"}, 400

    # 自动获取 idserial（如果还没填）
    idserial = (cfg.get("idserial") or "").strip()
    if not idserial:
        try:
            idserial = scraper.get_login_user(scraper._build_cookies(cfg["servicehall"]))
        except Exception:
            pass  # 获取失败则在 fetch_all 里再试
        if idserial:
            cfg["idserial"] = idserial
        else:
            return {"error": "无法获取用户标识（idserial），请确认 cookie 有效或手动填写学号",
                    "code": "no_idserial"}, 400

    if not start:
        # 增量：从当前帐户库中最新日期（重叠当天，靠 id 去重）；库空则默认一年前
        maxd = db.get_max_txdate(owner=idserial)
        start = (maxd[:10] if maxd
                 else (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d"))
    # 防止 start > end（如 mock 数据中有未来日期时）
    if start > end:
        start = end

    try:
        rows = scraper.fetch_all(idserial, cfg["servicehall"], start, end)
    except scraper.CookieExpiredError as e:
        return {"error": str(e), "code": "cookie_expired"}, 400
    except scraper.ScraperError as e:
        return {"error": str(e), "code": "scraper_error"}, 502
    except Exception as e:  # noqa: BLE001
        return {"error": f"同步失败：{e}", "code": "unknown"}, 500

    res = db.upsert_transactions(rows, owner=idserial)
    # 保存：idserial（可能刚自动获取）、last_sync_date
    config.save_config({**cfg, "idserial": idserial, "last_sync_date": end})
    return {"fetched": len(rows), "idserial": idserial, **res, "range": [start, end]}, 200


@app.post("/api/sync")
def api_sync():
    cfg = config.load_config()
    body = request.get_json(silent=True) or {}
    end = (body.get("end") or datetime.now().strftime("%Y-%m-%d"))[:10]
    start = (body.get("start") or "")[:10]
    result, code = do_sync(cfg, start, end)
    return jsonify(result), code


# ----------------------------- 登录（Playwright 自动捕获会话） -----------------------------

@app.post("/api/login/start")
def api_login_start():
    started = auth.login_session.start()
    return jsonify({"started": started, **auth.login_session.snapshot()})


@app.post("/api/login/auto")
def api_login_auto():
    """自动登录：用学号+密码直接走清华 SSO"""
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = (body.get("password") or "").strip()
    if not username or not password:
        return jsonify({"error": "请输入学号和密码"}), 400
    started = auth.login_session.start_auto(username, password)
    return jsonify({"started": started, **auth.login_session.snapshot()})


@app.get("/api/login/status")
def api_login_status():
    return jsonify(auth.login_session.snapshot())


@app.post("/api/login/cancel")
def api_login_cancel():
    auth.login_session.cancel()
    return jsonify({"ok": True})


@app.post("/api/login/reset")
def api_login_reset():
    """强制重置登录状态（解决残留）"""
    auth.login_session.cancel()
    auth.login_session.status = "idle"
    auth.login_session._thread = None
    return jsonify({"ok": True})


@app.post("/api/login/sync")
def api_login_sync():
    """登录成功后，保存 Cookie 并自动同步数据。"""
    s = auth.login_session
    if s.status != "success" or not s.cookie_str:
        return jsonify({"error": "尚未登录成功，请先点「登录清华」"}), 400
    cfg = config.load_config()
    cfg["servicehall"] = s.cookie_str
    # 不立即保存——do_sync 成功后再保存（含自动获取的 idserial）
    body = request.get_json(silent=True) or {}
    end = (body.get("end") or datetime.now().strftime("%Y-%m-%d"))[:10]
    start = (body.get("start") or "")[:10]
    result, code = do_sync(cfg, start, end)
    return jsonify(result), code


# ----------------------------- 交易明细 -----------------------------

@app.get("/api/transactions")
def api_transactions():
    start = request.args.get("start")
    end = request.args.get("end")
    category = request.args.get("category") or None
    keyword = request.args.get("keyword") or None
    owner = _owner()
    rows = db.query_transactions(
        start=start, end=end, category=category, keyword=keyword,
        limit=request.args.get("limit", type=int),
        offset=request.args.get("offset", 0, type=int),
        owner=owner,
    )
    total = db.count_transactions_filtered(
        start=start, end=end, category=category, keyword=keyword,
        owner=owner,
    )
    total_amount = db.sum_transactions_filtered(
        start=start, end=end, category=category, keyword=keyword,
        owner=owner,
    )
    recharge_amount = db.sum_transactions_filtered(
        start=start, end=end, category="充值", keyword=keyword,
        owner=owner,
    )
    # 消费/充值分离：充值单独列示，消费总额不含充值
    if category == "充值":
        total_amount = 0
    elif not category:
        total_amount = round(total_amount - recharge_amount, 2)
    return jsonify({"rows": rows, "count": total, "total_amount": total_amount, "recharge_amount": recharge_amount})


@app.get("/api/info")
def api_info():
    owner = _owner()
    return jsonify({
        "count": db.count_transactions(owner=owner),
        "max_date": db.get_max_txdate(owner=owner),
    })


# ----------------------------- 统计 -----------------------------

def _rows_from_args():
    return db.get_all_transactions(
        start=request.args.get("start"),
        end=request.args.get("end"),
        exclude_recharge=True,
        owner=_owner(),
    )


@app.get("/api/stats/summary")
def api_summary():
    result = stats.summary(_rows_from_args())
    # 今日 / 本周 / 本年 —— 不受时间筛选影响，始终基于当前帐户全部数据
    owner = _owner()
    all_rows = db.get_all_transactions(exclude_recharge=True, owner=owner)
    today_str = datetime.now().strftime("%Y-%m-%d")
    result["today"] = round(sum(r["amount"] for r in all_rows
                                if (r.get("txdate") or "")[:10] == today_str), 2)
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())
    result["this_week"] = round(sum(
        r["amount"] for r in all_rows
        if monday.strftime("%Y-%m-%d") <= (r.get("txdate") or "")[:10] <= today_str
    ), 2)

    # 本年支出：始终统计当前年份 1月1日至今
    year_start = f"{today.year}-01-01"
    result["this_year"] = round(sum(
        r["amount"] for r in all_rows
        if (r.get("txdate") or "")[:10] >= year_start
    ), 2)
    return jsonify(result)


@app.get("/api/stats/by_time")
def api_by_time():
    granularity = request.args.get("granularity", "day")
    if granularity not in ("day", "week", "month", "year"):
        granularity = "day"
    return jsonify(stats.by_time(_rows_from_args(), granularity))


@app.get("/api/stats/achievements")
def api_achievements():
    """成就系统：清华食堂 + 清青系列 + 校外商户的到访统计。"""
    rows = _rows_from_args()
    canteens = [
        {"name": "紫荆园", "icon": "🍜", "desc": "宿舍区最大食堂，五层涵盖粤菜到川香", "cat": "食堂"},
        {"name": "桃李园", "icon": "🍚", "desc": "四层风味小吃，负一楼清青休闲", "cat": "食堂"},
        {"name": "清芬园", "icon": "🌿", "desc": "生煎包&麻辣香锅，烤鸭出名", "cat": "食堂"},
        {"name": "听涛园", "icon": "🌊", "desc": "赶课首选，快餐麻辣烫面食", "cat": "食堂"},
        {"name": "丁香园", "icon": "🌸", "desc": "学堂路边，特色美食一层搞定", "cat": "食堂"},
        {"name": "观畴园", "icon": "🏛️", "desc": "万人食堂，三层品类极其丰富", "cat": "食堂"},
        {"name": "玉树园", "icon": "🌳", "desc": "韩日风格套餐，夜宵好评", "cat": "食堂"},
        {"name": "澜园", "icon": "💧", "desc": "照澜院教工餐厅，学生可入", "cat": "食堂"},
        {"name": "寓园", "icon": "🏠", "desc": "铁板烧酱骨架，旁有水木麦园面包店", "cat": "食堂"},
        {"name": "南园", "icon": "🏡", "desc": "米线羊杂汤，自制酸梅汤", "cat": "食堂"},
        {"name": "荷园", "icon": "🪷", "desc": "近春园附近，精致自选价格小贵", "cat": "食堂"},
        {"name": "芝兰园", "icon": "🥘", "desc": "西域风味+清青小火锅", "cat": "食堂"},
        {"name": "北园", "icon": "🏘️", "desc": "校外西北社区教工餐厅", "cat": "食堂"},
        {"name": "家园", "icon": "🍽️", "desc": "清华附小附近教工餐厅", "cat": "食堂"},
        {"name": "熙春园", "icon": "🌺", "desc": "荷园往南，近春园、古月堂附近", "cat": "食堂"},
        {"name": "融园", "icon": "🍳", "desc": "五道口金融学院内", "cat": "食堂"},
        # 清青系列（混合验证：数据捕捉到自动解锁，未捕捉可手动解锁）
        {"name": "清青快餐", "icon": "🍟", "desc": "清华版KFC，炸鸡薯条汉堡", "cat": "清青", "manual": True},
        {"name": "清青牛拉", "icon": "🍝", "desc": "牛肉拉面+各式烧烤", "cat": "清青", "manual": True},
        {"name": "清青永和", "icon": "🥟", "desc": "豆浆油条小馄饨中式快餐（刷卡显示观畴园）", "cat": "清青", "manual": True},
        {"name": "清青咖啡", "icon": "☕", "desc": "咖啡饮品&西式简餐", "cat": "清青", "manual": True},
        {"name": "清青小火锅", "icon": "🫕", "desc": "校内单人/多人小火锅", "cat": "清青", "manual": True},
        {"name": "清青披萨", "icon": "🍕", "desc": "各种披萨，对标必胜客", "cat": "清青", "manual": True},
        {"name": "清青休闲", "icon": "🍛", "desc": "咖喱饭奶茶，团建讨论场所", "cat": "清青", "manual": True},
        # 购物
        {"name": "天猫紫荆店", "icon": "🏪", "desc": "C楼负一，7:30-23:30", "cat": "购物"},
        {"name": "天猫清芬店", "icon": "🏪", "desc": "南区7号楼底，8:30-23:30", "cat": "购物"},
        {"name": "天猫观畴店", "icon": "🏪", "desc": "观畴负一楼，9:00-21:00", "cat": "购物"},
        {"name": "照澜院购物中心", "icon": "🎁", "desc": "照澜院，文创纪念品", "cat": "购物", "manual": True},
        # 便利店（手动解锁）
        {"name": "紫荆五号楼便利店", "icon": "🏪", "desc": "紫荆5号楼1单元，8:00-1:00", "cat": "便利店", "manual": True},
        {"name": "紫荆十一号楼便利店", "icon": "🏪", "desc": "紫荆11号楼4单元，10:00-0:00", "cat": "便利店", "manual": True},
        {"name": "紫荆十三号楼便利店", "icon": "🏪", "desc": "紫荆13号楼，8:00-0:00", "cat": "便利店", "manual": True},
        # 水果店（手动解锁）
        {"name": "鲜果园", "icon": "🍎", "desc": "观畴负一，9:00-21:00", "cat": "水果", "manual": True},
        {"name": "鲜果屋", "icon": "🍊", "desc": "南区7号楼底，8:00-23:30", "cat": "水果", "manual": True},
        # 校外餐厅（全部手动解锁）
        {"name": "李先生（牛肉面大王）", "icon": "🍜", "desc": "照澜院，牛肉面经典之选", "cat": "餐厅", "manual": True},
        {"name": "必胜客", "icon": "🍕", "desc": "五道口，披萨意面西式简餐", "cat": "餐厅", "manual": True},
        {"name": "麦当劳", "icon": "🍔", "desc": "五道口/东升大厦，24小时快餐", "cat": "餐厅", "manual": True},
        {"name": "霸王茶姬", "icon": "🍵", "desc": "五道口购物中心，国风鲜奶茶", "cat": "饮品", "manual": True},
        {"name": "蜜雪冰城（观畴店）", "icon": "🍦", "desc": "观畴园，冰淇淋&柠檬水性价比之王", "cat": "饮品", "manual": True},
        {"name": "蜜雪冰城（C楼店）", "icon": "🍦", "desc": "C楼，冰淇淋&柠檬水性价比之王", "cat": "饮品", "manual": True},
        {"name": "么么侠的茶", "icon": "🧋", "desc": "照澜院，奶茶果茶", "cat": "饮品", "manual": True},
        {"name": "库迪咖啡", "icon": "☕", "desc": "观畴园楼下，平价咖啡新选择", "cat": "饮品", "manual": True},
        {"name": "瑞幸咖啡", "icon": "☕", "desc": "清芬园旁边，luckin coffee", "cat": "饮品", "manual": True},
        {"name": "包的（包子铺）", "icon": "🥟", "desc": "照澜院，手工包子早餐铺", "cat": "餐厅", "manual": True},
        {"name": "学霸加油站", "icon": "⛽", "desc": "校内小吃补给站", "cat": "餐厅", "manual": True},
    ]
    from collections import defaultdict
    stats_dict = defaultdict(lambda: {"count": 0, "total": 0.0, "last": ""})
    for r in rows:
        caf = stats._cafeteria_name(r.get("mername") or "")
        stats_dict[caf]["count"] += 1
        stats_dict[caf]["total"] += r["amount"]
        d = (r.get("txdate") or "")[:10]
        if d > stats_dict[caf]["last"]:
            stats_dict[caf]["last"] = d

    result = []
    for c in canteens:
        s = stats_dict.get(c["name"], {"count": 0, "total": 0, "last": ""})
        result.append({
            "name": c["name"], "icon": c["icon"], "desc": c["desc"], "cat": c["cat"],
            "visited": s["count"] > 0,
            "manual": c.get("manual", False),
            "count": s["count"], "total": round(s["total"], 2), "last": s["last"],
        })
    return jsonify(result)


@app.get("/api/stats/heatmap")
def api_heatmap():
    """日历热力图：返回每日支出 [date, total]，用于 ECharts calendar heatmap。"""
    rows = _rows_from_args()
    daily = stats.by_time(rows, "day")
    return jsonify([[d["key"], d["total"]] for d in daily])


@app.get("/api/stats/badges")
def api_badges():
    """勋章架：基于真实消费数据授予的徽章。"""
    rows = _rows_from_args()
    return jsonify(stats.badges(rows))


@app.get("/api/stats/by_category")
def api_by_category():
    return jsonify(stats.by_category(_rows_from_args()))


@app.get("/api/stats/by_location")
def api_by_location():
    top = request.args.get("top", 15, type=int)
    return jsonify(stats.by_location(_rows_from_args(), top))


@app.get("/api/stats/locations")
def api_locations():
    """地点详细统计：全部商户的金额、笔数、笔均、占比、地址、分类。
       支持 ?group=cafeteria 按食堂聚合，默认 ?group=window 按窗口。"""
    rows = _rows_from_args()
    group = request.args.get("group", "window")
    if group == "cafeteria":
        locs = stats.by_location_cafeteria(rows)
    else:
        locs = stats.by_location_detailed(rows)
    return jsonify({
        "locations": locs,
        "total_locations": len(set(r["mername"] for r in rows)),
    })


# ----------------------------- 数据导出 -----------------------------

@app.get("/api/export")
def api_export():
    """导出交易数据为 CSV 文件。支持与交易明细相同的筛选参数。"""
    import csv
    import io

    start = request.args.get("start")
    end = request.args.get("end")
    category = request.args.get("category") or None
    keyword = request.args.get("keyword") or None
    owner = _owner()

    rows = db.query_transactions(
        start=start, end=end, category=category, keyword=keyword,
        limit=None, offset=0, owner=owner,
    )

    output = io.StringIO()
    writer = csv.writer(output)
    # BOM 让 Excel 正确识别 UTF-8
    output.write("﻿")
    writer.writerow(["时间", "商户", "地点", "分类", "金额", "摘要"])
    for r in rows:
        writer.writerow([
            (r.get("txdate") or "")[:19],
            r.get("mername") or "",
            r.get("meraddr") or "",
            r.get("category") or "",
            r.get("amount", 0),
            r.get("summary") or "",
        ])

    csv_content = output.getvalue()
    output.close()

    from flask import Response
    return Response(
        csv_content,
        mimetype="text/csv; charset=utf-8-sig",
        headers={
            "Content-Disposition": "attachment; filename=eat_stat_export.csv",
        },
    )


# ----------------------------- 分类规则 -----------------------------

@app.get("/api/categories/rules")
def api_get_rules():
    return jsonify({"rules": db.get_rules()})


@app.post("/api/categories/rules")
def api_set_rule():
    body = request.get_json(silent=True) or {}
    keyword = (body.get("keyword") or "").strip()
    if not keyword:
        return jsonify({"error": "keyword 不能为空"}), 400
    if body.get("delete"):
        db.delete_rule(keyword)
    else:
        category = (body.get("category") or "").strip()
        if not category:
            return jsonify({"error": "category 不能为空"}), 400
        db.upsert_rule(keyword, category)
    categorize.categorizer.reload()
    return jsonify({"ok": True, "rules": db.get_rules()})


@app.post("/api/categories/rebuild")
def api_rebuild():
    categorize.categorizer.reload()
    res = db.rebuild_categories(categorize.categorizer.categorize)
    return jsonify(res)


# ----------------------------- 模拟数据 / 重置（便于体验） -----------------------------

@app.post("/api/mock")
def api_mock():
    body = request.get_json(silent=True) or {}
    months = int(body.get("months", 4))
    rows = mock_data.generate_mock_transactions(months=months, seed=body.get("seed", 42))
    owner = _owner()
    res = db.upsert_transactions(rows, owner=owner)
    return jsonify({"fetched": len(rows), **res})


@app.post("/api/reset")
def api_reset():
    """清空当前帐户的数据。"""
    owner = _owner()
    with db.get_conn() as conn:
        conn.execute("DELETE FROM transactions WHERE owner = ?", (owner,))
    return jsonify({"ok": True})


def main():
    db.init_db()
    url = "http://127.0.0.1:5000"
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print("=" * 48)
    print("  Eat_stat 已启动 → 浏览器应自动打开：")
    print(f"  {url}")
    print("  若未打开，请手动访问该地址。关闭本窗口停止程序。")
    print("=" * 48)
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()
