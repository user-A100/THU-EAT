"""清华校园卡消费记录爬虫（Cookie 模式）。

参考已验证的开源实现：
  - https://github.com/leverimmy/THU-Annual-Eat  (main.py)
  - https://github.com/thu-info-community/thu-info-lib  (src/lib/card.ts)

认证：携带 card.tsinghua.edu.cn 登录后的 cookie（支持整行 Cookie 串，最稳）。
流程：cookie → getUserInfoFromToken 拿 loginuser(idserial) → querySelfTradeList 查交易。
返回数据为 AES-ECB 加密：密文前 16 字节为 key，其后为 base64 密文。
"""
import base64
import json
from datetime import datetime

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

import categorize

BASE_URL = "https://card.tsinghua.edu.cn/business/querySelfTradeList"
USER_INFO_URL = "https://card.tsinghua.edu.cn/login/getUserInfoFromToken"
PAGE_SIZE = 5000

# 模拟浏览器请求头，降低被识别为脚本的概率
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Referer": "https://card.tsinghua.edu.cn/",
    "Origin": "https://card.tsinghua.edu.cn",
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
}


class CookieExpiredError(Exception):
    """cookie 未设置、未生效或已过期。"""


class ScraperError(Exception):
    """爬虫其他错误（网络、解析、接口变更）。"""


def decrypt_aes_ecb(encrypted: str) -> str:
    """解密接口返回的 data 字段：前 16 字节为 key，其后 base64 密文。"""
    key = encrypted[:16].encode("utf-8")
    body = base64.b64decode(encrypted[16:])
    cipher = AES.new(key, AES.MODE_ECB)
    return unpad(cipher.decrypt(body), AES.block_size).decode("utf-8")


def _build_cookies(raw: str) -> dict:
    """把用户输入解析成 cookie dict。

    支持输入：
      - 纯 servicehall 值（推荐，最稳）
      - 整行 Cookie 串（"servicehall=xxx; JSESSIONID=yyy; ..."）
      - Network 标签复制的完整行（含 "Cookie: " 前缀）
    """
    cookies: dict = {}
    raw = (raw or "").strip().strip('"').strip("'")
    if not raw:
        return cookies
    # 去掉 "Cookie: " 前缀
    raw = raw.replace("Cookie: ", "").replace("cookie: ", "")
    # cookie 元属性关键字
    _skip = {"domain", "path", "expires", "max-age", "samesite", "secure", "httponly",
             "partitioned", "priority"}
    for part in raw.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, _, v = part.partition("=")
            k, v = k.strip(), v.strip()
            if k and k.lower() not in _skip:
                cookies[k] = v
        # Secure / HttpOnly 等无 = 的跳过
    # 兜底：纯值（无 = 号）
    if not cookies and "=" not in raw:
        cookies["servicehall"] = raw
    # 如果只解析到 servicehall 一个，直接返回（最常见情况）
    if "servicehall" in cookies:
        return {"servicehall": cookies["servicehall"]}
    return cookies


def _to_iso(value) -> str:
    """把 txdate 各种可能格式统一为 'YYYY-MM-DD HH:MM:SS'。无法识别则原样返回。"""
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        v = float(value)
        if v > 1e12:  # 毫秒时间戳
            v /= 1000
        try:
            return datetime.fromtimestamp(v).strftime("%Y-%m-%d %H:%M:%S")
        except (OverflowError, OSError, ValueError):
            return str(value)
    s = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return s


def normalize(raw: dict) -> dict:
    """原始行 → 标准化 dict（金额由分转元，并推断分类）。"""
    mername = raw.get("mername") or ""
    txname = raw.get("txname") or ""
    summary = raw.get("summary") or ""
    return {
        "id": str(raw.get("id")),
        "txdate": _to_iso(raw.get("txdate")),
        "mername": mername,
        "meraddr": raw.get("meraddr") or "",
        "txname": txname,
        "summary": summary,
        "amount": round((raw.get("txamt") or 0) / 100.0, 2),
        "balance": round((raw.get("balance") or 0) / 100.0, 2),
        "category": categorize.categorize(mername, txname, summary),
    }


def _extract_rows(payload) -> list:
    """从解密后的 JSON 中取 rows，兼容几种结构。"""
    if not isinstance(payload, dict):
        return []
    rd = payload.get("resultData")
    if isinstance(rd, dict) and isinstance(rd.get("rows"), list):
        return rd["rows"]
    if isinstance(payload.get("rows"), list):
        return payload["rows"]
    return []


def _diagnose(resp) -> str:
    """生成诊断字符串，帮助定位 cookie / 接口问题。"""
    body = (resp.text or "").strip()
    return (f"HTTP {resp.status_code}，Content-Type={resp.headers.get('Content-Type', '')}，"
            f"返回前 200 字符：{body[:200]!r}")


def _fetch(url: str, cookies: dict, params: dict = None):
    """请求并解密，返回 resultData（dict 或 list）。失败抛带诊断的异常。"""
    if not cookies:
        raise CookieExpiredError("未配置 cookie")
    try:
        resp = requests.post(url, params=params, cookies=cookies,
                             headers=HEADERS, timeout=30)
    except requests.RequestException as e:
        raise ScraperError(f"网络请求失败：{e}") from e

    body = (resp.text or "").strip()
    if not body or body[0] not in "{[":
        # 多半是登录页 HTML（cookie 没带上 / 失效）
        raise CookieExpiredError(
            "返回内容不是 JSON —— cookie 未生效或已过期。\n" + _diagnose(resp)
        )
    try:
        payload = resp.json()
    except ValueError as e:
        raise ScraperError(f"返回的 JSON 无法解析：{e}\n{_diagnose(resp)}") from e

    if isinstance(payload, dict) and payload.get("success") is False:
        raise ScraperError(f"接口返回失败：{payload.get('message') or payload.get('msg')}")

    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, str) and data:
        try:
            decrypted = decrypt_aes_ecb(data)
            parsed = json.loads(decrypted)
        except Exception as e:
            raise ScraperError(f"解密 / 解析失败（接口加密方式可能已变更）：{e}") from e
        return parsed.get("resultData") if isinstance(parsed, dict) else parsed
    # 明文分支
    return payload.get("resultData") if isinstance(payload, dict) else payload


def get_login_user(cookies: dict) -> str:
    """用 cookie 调 getUserInfoFromToken 拿 loginuser（即 idserial）。"""
    rd = _fetch(USER_INFO_URL, cookies)
    if isinstance(rd, dict):
        return rd.get("loginuser") or rd.get("idserial") or rd.get("userid") or ""
    return ""


def fetch_range(idserial: str, cookies: dict, start: str, end: str) -> list:
    """拉取 [start, end] 区间（YYYY-MM-DD）的交易，返回标准化列表。"""
    params = {
        "pageNumber": 0,
        "pageSize": PAGE_SIZE,
        "starttime": start,
        "endtime": end,
        "tradetype": -1,
    }
    if idserial:
        params["idserial"] = idserial
    rd = _fetch(BASE_URL, cookies, params)
    rows = rd.get("rows", []) if isinstance(rd, dict) else (rd if isinstance(rd, list) else [])
    return [normalize(r) for r in rows]


def fetch_all(idserial: str, cookie_raw: str, start: str, end: str) -> list:
    """拉取 [start, end]，按年分段避免单次 pageSize 截断，按 id 去重。

    idserial 为空时自动用 cookie 调 getUserInfoFromToken 获取。
    """
    cookies = _build_cookies(cookie_raw)
    if not cookies:
        raise CookieExpiredError("未配置 cookie")

    if not idserial:
        idserial = get_login_user(cookies)
        if not idserial:
            raise ScraperError("无法从 getUserInfoFromToken 获取用户标识，请确认 cookie 有效")

    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    all_rows: list = []
    seen: set = set()

    seg_start = start_dt
    while seg_start <= end_dt:
        seg_end = min(datetime(seg_start.year, 12, 31), end_dt)
        rows = fetch_range(
            idserial, cookies,
            seg_start.strftime("%Y-%m-%d"),
            seg_end.strftime("%Y-%m-%d"),
        )
        for r in rows:
            if r["id"] and r["id"] not in seen:
                seen.add(r["id"])
                all_rows.append(r)
        seg_start = datetime(seg_end.year + 1, 1, 1)
    return all_rows
