"""模拟数据生成器：生成符合接口格式的校园卡交易，用于离线演示与验证。

不依赖第三方库（仅 random/datetime），可在未安装依赖、未配置 cookie 时
直接看到完整的统计效果。运行： python mock_data.py
"""
import random
from datetime import datetime, timedelta

import categorize

# 商户池：分类 → [(商户名, 地址)]
MERCHANTS = {
    "食堂": [
        ("紫荆食堂", "紫荆公寓"), ("桃李园", "桃李园"), ("听涛园", "听涛园"),
        ("丁香园", "丁香园"), ("清芬园", "清芬园"), ("寓园", "寓园"),
        ("玉树园", "玉树园"), ("观畴园", "观畴园"),
    ],
    "饮料": [
        ("瑞幸咖啡", "紫荆公寓"), ("星巴克", "清华科技园"),
        ("蜜雪冰城", "五道口"), ("CoCo奶茶", "紫荆公寓"),
    ],
    "超市购物": [
        ("天猫校园超市", "紫荆公寓"), ("全家便利店", "紫荆公寓"),
        ("罗森便利店", "清华园"),
    ],
    "生活服务": [("紫荆浴室", "紫荆公寓"), ("洗衣房", "紫荆公寓")],
    "学习": [("打印店", "六教")],
}

PRICE_RANGE = {
    "食堂": (8, 25), "饮料": (12, 30), "超市购物": (5, 50),
    "生活服务": (2, 10), "学习": (1, 5),
}

# 各分类出现权重（食堂占大头，符合学生消费习惯）
CATEGORY_WEIGHTS = {
    "食堂": 55, "饮料": 12, "超市购物": 15, "生活服务": 10, "学习": 8,
}
MEAL_HOURS = [7, 8, 9, 11, 12, 13, 17, 18, 19, 20]


def generate_mock_transactions(months: int = 4, seed: int = 42) -> list:
    """生成模拟交易（已标准化、含 category），可直接 upsert 入库。"""
    rng = random.Random(seed)
    end = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=30 * months)
    cats = list(MERCHANTS.keys())
    weights = [CATEGORY_WEIGHTS[c] for c in cats]

    rows: list = []
    pid = 0
    cur = start
    while cur <= end:
        n = rng.choices([0, 1, 2, 3, 4, 5], weights=[5, 20, 30, 25, 15, 5])[0]
        for _ in range(n):
            cat = rng.choices(cats, weights=weights)[0]
            mername, meraddr = rng.choice(MERCHANTS[cat])
            lo, hi = PRICE_RANGE[cat]
            amount = round(rng.uniform(lo, hi), 2)
            txdate = cur.replace(
                hour=rng.choice(MEAL_HOURS),
                minute=rng.randint(0, 59),
                second=rng.randint(0, 59),
            )
            pid += 1
            rows.append({
                "id": f"mock_{pid}",
                "txdate": txdate.strftime("%Y-%m-%d %H:%M:%S"),
                "mername": mername,
                "meraddr": meraddr,
                "txname": "消费",
                "summary": f"{mername}消费",
                "amount": amount,
                "balance": round(200 - (pid % 100), 2),
                "category": categorize.categorize(mername, "消费", mername),
            })
        cur += timedelta(days=1)

    # 每月一笔充值（应被统计排除）
    for i in range(months + 1):
        pid += 1
        rdate = start + timedelta(days=30 * i + 1)
        rows.append({
            "id": f"mock_recharge_{i}",
            "txdate": rdate.replace(hour=10, minute=0, second=0).strftime("%Y-%m-%d %H:%M:%S"),
            "mername": "圈存机",
            "meraddr": "紫荆公寓",
            "txname": "充值",
            "summary": "校园卡充值",
            "amount": round(rng.choice([50, 100, 200]), 2),
            "balance": 250.0,
            "category": "充值",
        })
    return rows


if __name__ == "__main__":
    import db
    db.init_db()
    rows = generate_mock_transactions(months=4, seed=42)
    res = db.upsert_transactions(rows)
    print(f"已生成并写入模拟数据：共 {len(rows)} 条 → 新增 {res['inserted']}，更新 {res['updated']}")
    print("提示：再次运行 start.bat 或 python app.py 即可在网页上看到统计效果。")
    print("      如需清空模拟数据，删除 data/eat_stat.db 后重新运行。")
