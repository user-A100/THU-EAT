"""SQLite 数据访问层。

表：
  transactions(id, txdate, mername, meraddr, txname, summary, amount, balance, category, owner, synced_at)
  category_rules(keyword, category)

owner 字段实现分帐户数据隔离：同步时打上当前 idserial，查询时按 owner 过滤。
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Callable, Optional

from config import DB_PATH, ensure_dirs

# 默认分类规则（商户名/交易名包含关键词 → 分类）。首次建库写入，可由用户在前端修改。
DEFAULT_RULES = {
    # 食堂
    "食堂": "食堂", "紫荆": "食堂", "桃李": "食堂", "听涛": "食堂", "丁香": "食堂",
    "清芬": "食堂", "寓园": "食堂", "玉树": "食堂", "涛声": "食堂", "闻馨": "食堂",
    "风味": "食堂", "南园": "食堂", "荷园": "食堂", "观畴": "食堂",
    "澜园": "食堂", "芝兰": "食堂", "北园": "食堂", "家园": "食堂",
    "熙春": "食堂", "融园": "食堂",
    "清青": "食堂", "玉树": "食堂",
    # 饮料 / 冷饮
    "咖啡": "饮料", "瑞幸": "饮料", "星巴克": "饮料", "Costa": "饮料",
    "奶茶": "饮料", "CoCo": "饮料", "蜜雪": "饮料", "书亦": "饮料",
    "冷饮": "冷饮",
    # 超市（"天猫" 独立成规则：真实商户名为"天猫清芬店/天猫观畴店"，
    # 不含"天猫校园"四字，否则会因嵌入"清芬/观畴"被食堂规则误判）
    "超市": "超市", "天猫": "超市", "天猫校园": "超市", "便利店": "超市",
    "全家": "超市", "罗森": "超市", "711": "超市",
    # 生活服务
    "浴室": "生活服务", "洗澡": "生活服务", "热水": "生活服务",
    "水费": "生活服务", "理发": "生活服务", "洗衣": "生活服务",
    # 学习
    "打印": "学习", "复印": "学习",
    # 充值（不计入支出统计）
    "充值": "充值", "圈存": "充值", "补助": "充值", "领取": "充值", "退费": "充值",
}

_initialized = False


@contextmanager
def get_conn():
    """连接上下文：正常退出 commit，异常回滚，最后关闭。不自动建表（避免与 init_db 递归）。"""
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """建表、索引，并写入默认分类规则（仅当规则表为空时）。幂等。"""
    global _initialized
    if _initialized:
        return
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id        TEXT PRIMARY KEY,
                txdate    TEXT NOT NULL,
                mername   TEXT,
                meraddr   TEXT,
                txname    TEXT,
                summary   TEXT,
                amount    REAL,
                balance   REAL,
                category  TEXT,
                synced_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_txdate   ON transactions(txdate);
            CREATE INDEX IF NOT EXISTS idx_category ON transactions(category);
            CREATE INDEX IF NOT EXISTS idx_mername  ON transactions(mername);

            CREATE TABLE IF NOT EXISTS category_rules (
                keyword  TEXT PRIMARY KEY,
                category TEXT NOT NULL
            );
            """
        )
        # 兼容旧库：如果 transactions 表缺少 owner 列则添加（在已有表上 ALTER）
        cur = conn.execute("PRAGMA table_info(transactions)")
        cols = {row[1] for row in cur.fetchall()}
        if "owner" not in cols:
            conn.execute("ALTER TABLE transactions ADD COLUMN owner TEXT NOT NULL DEFAULT ''")
        # 确保 owner 索引存在
        conn.execute("CREATE INDEX IF NOT EXISTS idx_owner ON transactions(owner)")

        cur = conn.execute("SELECT COUNT(*) FROM category_rules")
        if cur.fetchone()[0] == 0:
            conn.executemany(
                "INSERT OR IGNORE INTO category_rules(keyword, category) VALUES(?,?)",
                list(DEFAULT_RULES.items()),
            )
        # 补录：确保新增的默认规则在已有数据库中也生效
        conn.executemany(
            "INSERT OR IGNORE INTO category_rules(keyword, category) VALUES(?,?)",
            list(DEFAULT_RULES.items()),
        )
    _initialized = True


def _ensure() -> None:
    """任何数据库操作前确保表已建（自愈，容忍调用顺序）。"""
    global _initialized
    if not _initialized:
        init_db()


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ----------------------------- 查询条件构建 -----------------------------

def _build_where(start, end, category, keyword, owner):
    """构建 WHERE 子句和参数，供查询和计数复用。

    owner 始终参与过滤：
      - 有值时只看该帐户的数据
      - 为空时只看 owner='' 的历史数据（新架构下不会有新数据写入空 owner）
    """
    clauses = ["1=1"]
    params: list = []
    if start:
        clauses.append("txdate >= ?"); params.append(start)
    if end:
        # SQLite 字符串比较：txdate 含时间 (2026-07-10 12:30:00)，
        # end 只有日期 (2026-07-10) → '...12:30:00' > '...10' 导致今天数据被排除
        clauses.append("txdate <= ?"); params.append(end + " 23:59:59")
    if category:
        clauses.append("category = ?"); params.append(category)
    if keyword:
        clauses.append("(mername LIKE ? OR summary LIKE ? OR meraddr LIKE ?)")
        kw = f"%{keyword}%"; params += [kw, kw, kw]
    clauses.append("owner = ?"); params.append(owner or "")
    return " AND ".join(clauses), params


# ----------------------------- 交易写入 -----------------------------

def upsert_transactions(rows: list[dict], owner: str = "") -> dict:
    """批量写入交易（按 id 去重），返回 {inserted, updated}。

    每条 row 应含：id, txdate, mername, meraddr, txname, summary, amount, balance, category
    owner 为当前帐户标识（idserial）。
    """
    _ensure()
    if not rows:
        return {"inserted": 0, "updated": 0}
    now = _now_iso()
    ids = [str(r["id"]) for r in rows]
    placeholder = ",".join("?" * len(ids))
    with get_conn() as conn:
        existing = {
            row[0]
            for row in conn.execute(
                f"SELECT id FROM transactions WHERE id IN ({placeholder})", ids
            )
        }
        to_insert, to_update = [], []
        for r in rows:
            rid = str(r["id"])
            tup = (
                rid, r["txdate"], r.get("mername", ""), r.get("meraddr", ""),
                r.get("txname", ""), r.get("summary", ""),
                float(r.get("amount", 0) or 0), float(r.get("balance", 0) or 0),
                r.get("category", "其他"), owner, now,
            )
            (to_update if rid in existing else to_insert).append(tup)

        if to_insert:
            conn.executemany(
                "INSERT INTO transactions "
                "(id,txdate,mername,meraddr,txname,summary,amount,balance,category,owner,synced_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                to_insert,
            )
        if to_update:
            conn.executemany(
                "UPDATE transactions SET txdate=?,mername=?,meraddr=?,txname=?,summary=?,"
                "amount=?,balance=?,category=?,owner=?,synced_at=? WHERE id=?",
                [(t[1], t[2], t[3], t[4], t[5], t[6], t[7], t[8], t[9], t[10], t[0]) for t in to_update],
            )
    return {"inserted": len(to_insert), "updated": len(to_update)}


# ----------------------------- 交易查询 -----------------------------

def count_transactions_filtered(start: Optional[str] = None, end: Optional[str] = None,
                                 category: Optional[str] = None, keyword: Optional[str] = None,
                                 owner: str = "") -> int:
    """返回符合条件的交易总数（不受分页 limit 影响）。"""
    _ensure()
    where, params = _build_where(start, end, category, keyword, owner)
    with get_conn() as conn:
        row = conn.execute(f"SELECT COUNT(*) FROM transactions WHERE {where}", params).fetchone()
    return row[0] if row else 0


def sum_transactions_filtered(start: Optional[str] = None, end: Optional[str] = None,
                               category: Optional[str] = None, keyword: Optional[str] = None,
                               owner: str = "") -> float:
    """返回符合条件的交易金额总和（不受分页 limit 影响）。"""
    _ensure()
    where, params = _build_where(start, end, category, keyword, owner)
    with get_conn() as conn:
        row = conn.execute(f"SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE {where}", params).fetchone()
    return round(row[0], 2) if row else 0.0


def query_transactions(start: Optional[str] = None, end: Optional[str] = None,
                       category: Optional[str] = None, keyword: Optional[str] = None,
                       limit: Optional[int] = None, offset: int = 0,
                       owner: str = "") -> list:
    """明细查询（时间倒序），供前端明细表使用。"""
    _ensure()
    where, params = _build_where(start, end, category, keyword, owner)
    sql = f"SELECT * FROM transactions WHERE {where} ORDER BY txdate DESC, id DESC"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"; params += [int(limit), int(offset)]
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_all_transactions(start: Optional[str] = None, end: Optional[str] = None,
                         exclude_recharge: bool = True, owner: str = "") -> list:
    """获取全部交易（时间升序），供统计使用。默认排除充值类。"""
    _ensure()
    where, params = _build_where(start, end, None, None, owner)
    sql = f"SELECT * FROM transactions WHERE {where}"
    if exclude_recharge:
        sql += " AND category != '充值'"
    sql += " ORDER BY txdate ASC"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_max_txdate(owner: str = "") -> Optional[str]:
    """返回当前帐户库中最新的交易时间，供增量同步用。"""
    _ensure()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT MAX(txdate) FROM transactions WHERE owner = ?", (owner or "",)
        ).fetchone()
    return row[0] if row and row[0] else None


def count_transactions(owner: str = "") -> int:
    """返回当前帐户的交易总数。"""
    _ensure()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE owner = ?", (owner or "",)
        ).fetchone()
    return row[0] if row else 0


# ----------------------------- 分类规则 -----------------------------

def get_rules() -> list:
    _ensure()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT keyword, category FROM category_rules ORDER BY category, keyword"
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_rule(keyword: str, category: str) -> None:
    _ensure()
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO category_rules(keyword, category) VALUES(?,?)",
            (keyword, category),
        )


def delete_rule(keyword: str) -> None:
    _ensure()
    with get_conn() as conn:
        conn.execute("DELETE FROM category_rules WHERE keyword=?", (keyword,))


def rebuild_categories(categorize_fn: Callable[..., str]) -> dict:
    """用给定的分类函数重新计算所有交易的 category。

    categorize_fn(mername, txname, summary) -> category
    """
    _ensure()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, mername, txname, summary FROM transactions"
        ).fetchall()
        updates = [
            (categorize_fn(r["mername"], r["txname"], r["summary"]), r["id"])
            for r in rows
        ]
        conn.executemany(
            "UPDATE transactions SET category=? WHERE id=?", updates
        )
    return {"rebuilt": len(updates)}
