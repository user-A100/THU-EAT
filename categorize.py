"""商户名 / 交易类型 → 分类。

分类逻辑：
  1. 先看交易类型(txname)/摘要(summary)：命中「充值」类关键词 → 归"充值"（不计入支出）。
  2. 否则按商户名(mername) 匹配分类规则，按关键词长度倒序匹配（更具体的优先）。
  3. 都未命中 → "其他"。

规则来自 db.category_rules 表，可在前端增删；改后调用 reload() / rebuild_categories()。
"""
import threading

import db


class Categorizer:
    def __init__(self):
        self._lock = threading.Lock()
        self._recharge: list[str] = []
        self._names: list[tuple] = []
        self.reload()

    def reload(self) -> None:
        """从数据库重新加载规则。"""
        rules = db.get_rules()
        recharge = sorted(
            (r["keyword"] for r in rules if r["category"] == "充值"),
            key=len, reverse=True,
        )
        names = sorted(
            ((r["keyword"], r["category"]) for r in rules if r["category"] != "充值"),
            key=lambda x: len(x[0]), reverse=True,
        )
        # 整体替换引用，读侧无需加锁（迭代的是旧引用）
        with self._lock:
            self._recharge = recharge
            self._names = names

    def categorize(self, mername: str, txname: str = "", summary: str = "") -> str:
        text = f"{txname or ''} {summary or ''}"
        for kw in self._recharge:
            if kw and kw in text:
                return "充值"
        name = mername or ""
        # 在所有命中的关键词里挑「最长的」；等长时「非食堂优先于食堂」，
        # 再按「出现位置更早」的优先。
        # 例：清芬园_冷饮 同时命中"清芬"(食堂,pos0)与"冷饮"(冷饮,pos4)，
        # 二者等长，取非食堂的"冷饮"。天猫清芬店同理，"天猫"(超市,pos0)直接最早。
        best = None  # (length, not_canteen, -position, category)
        for kw, cat in self._names:
            if kw and kw in name:
                pos = name.find(kw)
                score = (len(kw), 1 if cat != "食堂" else 0, -pos, cat)
                if best is None or score[:3] > best[:3]:
                    best = score
        return best[3] if best else "其他"


# 模块级默认实例
categorizer = Categorizer()


def categorize(mername: str, txname: str = "", summary: str = "") -> str:
    """便捷入口：对单条记录分类。"""
    return categorizer.categorize(mername, txname, summary)
