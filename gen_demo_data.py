"""生成 2024-01-01 ~ 2026-07-11 的伪造数据，用于 README 展示。
运行：python gen_demo_data.py
"""
import random
from datetime import datetime, timedelta

import categorize
import db
import config

START = "2024-01-01"
END = "2026-07-11"

# ── 商户池 ──
MERCHANTS = {
    "食堂": [
        ("紫荆园_一层小吃", "紫荆公寓"), ("紫荆园_二层粤式", "紫荆公寓"),
        ("紫荆园_三层川湘", "紫荆公寓"), ("桃李园_一层东北风味", "桃李园"),
        ("桃李园_二层面食", "桃李园"), ("清芬园_一层主食", "清芬园"),
        ("清芬园_麻辣香锅", "清芬园"), ("听涛园_快餐", "听涛园"),
        ("听涛园_麻辣烫", "听涛园"), ("丁香园_一层", "丁香园"),
        ("观畴园_一层自选", "观畴园"), ("观畴园_二层西餐", "观畴园"),
        ("玉树园_夜宵", "玉树园"), ("玉树园_韩式套餐", "玉树园"),
        ("澜园_一层", "照澜院"), ("寓园_酱骨架", "寓园"),
        ("寓园_铁板烧", "寓园"), ("南园_米线", "南园"),
        ("荷园_自选", "荷园"), ("芝兰园_西域风味", "芝兰园"),
        ("芝兰园_清青小火锅", "芝兰园"), ("家园_一层", "家园"),
        ("熙春园_一层", "熙春园"), ("融园_一层", "融园"),
    ],
    "饮料": [
        ("瑞幸咖啡_清芬店", "清芬园旁"), ("瑞幸咖啡_观畴店", "观畴园"),
        ("蜜雪冰城_观畴店", "观畴园"), ("蜜雪冰城_C楼店", "C楼"),
        ("库迪咖啡_观畴店", "观畴园"), ("么么侠的茶", "照澜院"),
        ("霸王茶姬", "五道口"),
    ],
    "超市购物": [
        ("天猫清芬店", "南区7号楼"), ("天猫观畴店", "观畴园负一"),
        ("天猫紫荆店", "C楼负一"), ("全家便利店", "紫荆公寓"),
        ("罗森便利店", "清华园"),
    ],
    "生活服务": [
        ("紫荆浴室", "紫荆公寓"), ("洗衣房_紫荆", "紫荆公寓"),
        ("C楼理发店", "C楼"),
    ],
    "学习": [
        ("六教打印店", "六教"), ("三教打印店", "三教"),
    ],
}

PRICE_RANGE = {
    "食堂": (6, 28), "饮料": (8, 25),
    "超市购物": (5, 45), "生活服务": (2, 12), "学习": (0.5, 8),
}

CAT_WEIGHTS = {"食堂": 58, "饮料": 10, "超市购物": 16, "生活服务": 8, "学习": 8}
MEAL_HOURS = [7, 8, 9, 11, 12, 13, 17, 18, 19, 20]


def is_holiday(d: datetime) -> bool:
    """粗略判断寒暑假：寒假 1月中-2月中，暑假 7-8月。假期消费减少但不归零。"""
    m, day = d.month, d.day
    if m == 1 and day >= 15:
        return True
    if m == 2 and day <= 20:
        return True
    if m in (7, 8):
        return True
    return False


def generate():
    rng = random.Random(42)
    start_dt = datetime.strptime(START, "%Y-%m-%d")
    end_dt = datetime.strptime(END, "%Y-%m-%d")
    cats = list(MERCHANTS.keys())
    weights = [CAT_WEIGHTS[c] for c in cats]

    rows = []
    pid = 0
    balance = 5000.0
    cur = start_dt
    while cur <= end_dt:
        # 每天交易数：假期 0-3 笔，平时 1-5 笔
        if is_holiday(cur):
            n = rng.choices([0, 1, 2, 3], weights=[30, 35, 25, 10])[0]
        else:
            n = rng.choices([1, 2, 3, 4, 5], weights=[10, 30, 30, 20, 10])[0]

        for _ in range(n):
            cat = rng.choices(cats, weights=weights)[0]
            mername, meraddr = rng.choice(MERCHANTS[cat])
            lo, hi = PRICE_RANGE[cat]
            amount = round(rng.uniform(lo, hi), 2)
            hour = rng.choice(MEAL_HOURS)
            txdate = cur.replace(hour=hour, minute=rng.randint(0, 59), second=rng.randint(0, 59))

            # 食堂价格有小幅季节性波动（冬天贵一点）
            if cat == "食堂" and cur.month in (12, 1, 2):
                amount = round(amount * rng.uniform(1.0, 1.15), 2)

            pid += 1
            balance = round(balance - amount, 2)
            rows.append({
                "id": f"demo_{pid:05d}",
                "txdate": txdate.strftime("%Y-%m-%d %H:%M:%S"),
                "mername": mername,
                "meraddr": meraddr,
                "txname": "消费",
                "summary": f"{mername.split('_')[0]}消费",
                "amount": amount,
                "balance": balance,
                "category": categorize.categorize(mername, "消费", ""),
            })

            # 偶尔充值
            if balance < 50:
                recharge = round(rng.choice([100, 200, 300]), 2)
                balance = round(balance + recharge, 2)
                rows.append({
                    "id": f"demo_charge_{pid:04d}",
                    "txdate": txdate.strftime("%Y-%m-%d %H:%M:%S"),
                    "mername": "圈存机", "meraddr": "紫荆公寓",
                    "txname": "充值", "summary": "校园卡充值",
                    "amount": recharge, "balance": balance,
                    "category": "充值",
                })
                pid += 1

        cur += timedelta(days=1)

    return rows


if __name__ == "__main__":
    config.ensure_dirs()
    db.init_db()

    # 清空旧数据
    with db.get_conn() as conn:
        conn.execute("DELETE FROM transactions")
        conn.execute("DELETE FROM category_rules")
        print("已清空旧数据")

    # 重新写入默认分类规则
    db.init_db()

    rows = generate()
    result = db.upsert_transactions(rows, owner="")
    print(f"已生成 {len(rows)} 条数据 → 新增 {result['inserted']}，更新 {result['updated']}")
    print(f"日期范围: {START} ~ {END}")
    print("现在启动 python app.py 即可看到完整数据。")
