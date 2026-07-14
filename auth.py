"""Playwright 登录：persistent browser context 模式。

参考 leverimmy/Table-Tennis-Checkin-Helper 的清华 SSO 登录模式：用
``launch_persistent_context`` 把 cookie / localStorage / "下次不再验证此浏览器" 的
二次验证(2FA)信任态保存在本地 profile 目录 ``data/.browser_profile/``，从而：

  - 重新登录可跳过 2FA（浏览器已被清华 SSO 标记为可信设备）
  - cookie 未过期时可直接复用、跳过整个 SSO 流程
  - 配合 SingletonLock 检测与清理，浏览器崩溃后 profile 不会锁死

两条登录路径：
  手动模式 — 弹出可见浏览器 → 用户手动完成 SSO（含双因子）→ 捕获 servicehall cookie
  自动模式 — 后台 headless → 自动填学号密码 → 提交 SSO → 捕获 cookie（已信任时可免 2FA）

THU-EAT 登录目标是 card.tsinghua.edu.cn，捕获的是 **servicehall cookie**（参考仓库
捕获的是 JWT token），因此移植的是 persistent context + profile 锁守护 + 轮询捕获的
**模式**，而非照搬 token/JWT 解码。

Playwright 的 sync API 在独立后台线程内使用（不在 Flask 请求线程里直接调用）。
"""
import os
import re
import subprocess
import sys
import threading
import time

import config

# 登录入口：card 的 CAS 受保护页。未登录访问它，card 的 CAS 过滤器会服务端 302 跳清华
# IdP 登录页；用户完成 SSO（含双因子）后，IdP 携 ticket 回跳 card，card 在自己域种下
# servicehall。这样"回传"由浏览器自身的 CAS 跳转链完成——对照参考实现
# leverimmy/Table-Tennis-Checkin-Helper 的 login_via_browser（goto 服务自己的 toLoginPage
# 入口、再轮询 token），这里等价地 goto card 受保护页、轮询 servicehall cookie。
#
# 关键：不要 goto 裸 IdP URL（.../auth/login/.../0?/userindex）。那条 URL 的回调是 IdP
# 自己的 /userindex，登录后浏览器停在 id.tsinghua.edu.cn 永远不回 card，servicehall 种不
# 下——这正是"完成身份验证但结果回传不到 EAT"的根因。从 card 受保护页进入，让 card 自己
# 发起带正确回调（service=card）的 SSO 往返，登录后自然回到 card。card 首页那个"登录"
# 按钮是 JS 触发、时序不稳，所以不走首页、直访问受保护页让服务端 302。
CARD_AUTH_PAGE = "https://card.tsinghua.edu.cn/userinfo"
SUCCESS_COOKIE_NAMES = {"servicehall", "JSESSIONID", "_session"}
TIMEOUT_SEC = 300

# persistent browser profile：保存登录态 + 2FA 信任。
# 放在 data/ 下 —— 已被 gitignore 覆盖，且自动遵循 PyInstaller 打包后的 BASE_DIR。
PROFILE_DIR = config.DATA_DIR / ".browser_profile"
PROFILE_LOCKS = ("SingletonLock", "SingletonCookie", "SingletonSocket")
LOCK_PID_RE = re.compile(r"-(\d+)$")

# 打包后把 chromium 装到 exe 同目录的 .browsers/（用户可写、重启不丢）；
# 开发态不设此变量，沿用系统缓存 ~/AppData/Local/ms-playwright，避免重复下 400MB。
# 必须在 playwright 被导入前设置——auth 在 app 启动时即导入，登录才懒加载 playwright，时序满足。
if getattr(sys, "frozen", False):
    BROWSERS_DIR = config.BASE_DIR / ".browsers"
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(BROWSERS_DIR))
else:
    BROWSERS_DIR = None


def _safe_close(context):
    try:
        context.close()
    except Exception:
        pass


def _clear_card_cookies(context) -> None:
    """登录前清掉 card.tsinghua.edu.cn 的旧 cookie。

    servicehall 会过期/失效。残留旧值会让后续"物化"步骤（访问 /userinfo）拿到的仍是
    失效 cookie、getUserInfoFromToken 校验不过。清掉 card 域 cookie 后，物化会拿到
    全新的 servicehall。保留 id.tsinghua 域 cookie——那是"本浏览器可信"的二次验证
    信任态，丢了就要重新 2FA。
    """
    try:
        for c in context.cookies():
            dom = c.get("domain") or ""
            if "card.tsinghua.edu.cn" in dom:
                try:
                    context.clear_cookies(name=c["name"], domain=c["domain"])
                except Exception:
                    pass
    except Exception:
        pass


# ---------------- profile 锁守护（移植自参考仓库 api.py）----------------
# Mac/Linux 上 SingletonLock 是 hostname-PID 的符号链接，能精确判定占用进程；
# Windows 上它是普通文件、读不出 PID，这里保守返回"无法判定"，由 LoginSession
# 的线程互斥保证不会同时开两个登录浏览器，崩溃残留的锁则由 clear_stale 清掉。


def _get_profile_lock_pid() -> int | None:
    lock = PROFILE_DIR / "SingletonLock"
    if not lock.exists() and not lock.is_symlink():
        return None
    try:
        target = os.readlink(lock)
    except OSError:
        return None  # Windows：非符号链接，读不出 PID
    m = LOCK_PID_RE.search(str(target))
    return int(m.group(1)) if m else None


def is_browser_profile_in_use() -> bool:
    """profile 是否正被某个浏览器进程占用。无法判定（Windows/无锁）时返回 False。"""
    pid = _get_profile_lock_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except OSError as exc:
        # EPERM(1)：进程存在但无权限判定；其它 OSError 视为进程已退出
        return getattr(exc, "errno", None) == 1
    return True


def clear_stale_profile_locks() -> None:
    """清理已退出进程留下的 stale lock（仅当 profile 没被占用时）。"""
    if is_browser_profile_in_use():
        return
    for name in PROFILE_LOCKS:
        lock = PROFILE_DIR / name
        try:
            if lock.exists() or lock.is_symlink():
                lock.unlink(missing_ok=True)
        except Exception:
            pass


def has_saved_browser_state() -> bool:
    """profile 是否已有保存的登录态（用于前端"重新登录可免二次验证"提示）。"""
    return PROFILE_DIR.exists() and any(PROFILE_DIR.iterdir())


class LoginSession:
    def __init__(self):
        self.status = "idle"
        self.message = ""
        self.cookie_str = ""
        self._thread = None
        self._stop = False
        self._context = None  # launch_persistent_context 返回的是 BrowserContext
        self._dbg = {}  # _wait_login 的实时观测，经 snapshot 暴露给前端便于定位

    def start(self) -> bool:
        """手动模式：弹出可见浏览器让用户自行登录。"""
        # 如果上次线程还在跑但已结束（daemon 残留），先强制清理
        if self._thread and self._thread.is_alive():
            if self.status in ("error", "cancelled", "success"):
                self._thread = None  # 状态已结束但线程引用还在
            else:
                return False
        self._stop = False
        self.status = "waiting"
        self.message = "浏览器已打开，请在弹出窗口完成登录（含双因子验证）……"
        self.cookie_str = ""
        self._dbg = {}
        self._thread = threading.Thread(target=self._run_manual, daemon=True)
        self._thread.start()
        return True

    def start_auto(self, username: str, password: str) -> bool:
        """自动模式：后台 headless 自动填写学号密码登录。"""
        if self._thread and self._thread.is_alive():
            return False
        self._stop = False
        self.status = "waiting"
        self.message = "正在自动登录清华统一身份认证……"
        self.cookie_str = ""
        self._dbg = {}
        self._thread = threading.Thread(target=self._run_auto, args=(username, password), daemon=True)
        self._thread.start()
        return True

    def cancel(self) -> None:
        self._stop = True
        if self._context is not None:
            _safe_close(self._context)

    def snapshot(self) -> dict:
        return {
            "status": self.status,
            "message": self.message,
            "has_cookie": bool(self.cookie_str),
            "has_saved_state": has_saved_browser_state(),
            "debug": dict(self._dbg),
        }

    # ---------------- 内部：启动 persistent context ----------------

    def _install_chromium(self) -> bool:
        """首次使用：用 playwright 自带 node 驱动下载 chromium 到 PLAYWRIGHT_BROWSERS_PATH。

        冻结态下 sys.executable 是 exe 本身，旧的 ``python -m playwright install`` 走不通；
        改为直接调 driver/package/cli.js（PyInstaller 已把它打进来）。下载约 150MB、可能耗时
        数分钟，期间把进度提示写进 self.message 供前端轮询展示。
        """
        try:
            from playwright._impl._driver import compute_driver_executable, get_driver_env
        except Exception as e:
            self.message = f"无法准备浏览器组件：{e}"
            return False
        self.message = "首次登录：正在下载浏览器组件 chromium（约 150MB），请耐心等待……"
        node, cli = compute_driver_executable()
        try:
            subprocess.run(
                [node, cli, "install", "chromium"],
                env=get_driver_env(),
                check=False,
                timeout=600,
            )
            return True
        except subprocess.TimeoutExpired:
            self.message = "浏览器组件下载超时，请检查网络后重试"
            return False
        except Exception as e:
            self.message = f"浏览器组件下载失败：{e}"
            return False

    def _launch_persistent(self, p, headless: bool):
        """launch_persistent_context：清理 stale 锁 + 缺 chromium 时自动安装兜底。"""
        clear_stale_profile_locks()
        if is_browser_profile_in_use():
            raise RuntimeError("上次的登录浏览器窗口还开着，请先关闭弹出的 Chromium 窗口后再试。")
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)

        common_args = ["--disable-extensions", "--no-first-run", "--no-default-browser-check"]
        kwargs = dict(
            user_data_dir=str(PROFILE_DIR),
            headless=headless,
            accept_downloads=False,
        )
        if headless:
            kwargs["viewport"] = {"width": 1100, "height": 820}
            kwargs["args"] = common_args
        else:
            kwargs["viewport"] = {"width": 500, "height": 680}
            kwargs["args"] = common_args + ["--window-size=520,700", "--window-position=center"]

        try:
            return p.chromium.launch_persistent_context(**kwargs)
        except Exception:
            # 可能未装 chromium：装一次再重试；装失败则抛出，由调用方报真实错误
            if not self._install_chromium():
                raise
            return p.chromium.launch_persistent_context(**kwargs)

    # ---------------- 内部：两条登录路径 ----------------

    def _run_manual(self) -> None:
        """浏览器登录：弹出持久化 Chromium，打开 card 受保护页（自动跳 IdP）让用户登录。"""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.status = "error"
            self.message = "未安装 playwright，请运行：pip install playwright"
            return
        try:
            with sync_playwright() as p:
                context = self._launch_persistent(p, headless=False)
                self._context = context
                _clear_card_cookies(context)  # 清失效的 card cookie，拿干净的 servicehall
                page = context.pages[0] if context.pages else context.new_page()
                # 从 card 受保护页进入：CAS 服务端 302 跳 IdP 登录页，登录后 IdP 回跳 card
                # 种 servicehall。不直接 goto 裸 IdP URL（回调是 /userindex，回不到 card）。
                page.goto(CARD_AUTH_PAGE, wait_until="domcontentloaded", timeout=30000)
                self._wait_login(context, page)
        except Exception as e:
            self.status = "error"
            self.message = f"浏览器启动失败：{e}"

    def _run_auto(self, username: str, password: str) -> None:
        """自动登录：从 card 受保护页进入（自动跳 IdP），填 i_user/i_pass 并提交。

        注意：SSO 表单带图形验证码（i_captcha），自动模式多半会被验证码拦下而失败，
        失败就超时——所以推荐用手动模式；自动模式只在已免验证码时可能成功。
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.status = "error"
            self.message = "未安装 playwright，请运行：pip install playwright"
            return
        try:
            with sync_playwright() as p:
                context = self._launch_persistent(p, headless=True)
                self._context = context
                _clear_card_cookies(context)
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(CARD_AUTH_PAGE, wait_until="domcontentloaded", timeout=30000)
                # CAS 跳到 IdP 登录表单需要一点时间；等学号输入框出现再填
                try:
                    page.wait_for_selector(
                        'input#i_user, input[name="i_user"]', timeout=15000)
                except Exception:
                    pass  # 没等到（已登录直接回 card / 被拦）→ 交给 _wait_login 判定
                page.wait_for_timeout(800)

                # IdP 表单字段：i_user(学号/账号) / i_pass(密码)
                user_input = page.locator('input#i_user, input[name="i_user"]').first
                if user_input.is_visible():
                    user_input.fill(username)
                pass_input = page.locator('input#i_pass, input[type="password"]').first
                if pass_input.is_visible():
                    pass_input.fill(password)
                # 提交"登录"
                submit = page.locator(
                    'a:has-text("登录"), button:has-text("登录"), '
                    'button:has-text("登 录"), input[type="submit"]').first
                if submit.is_visible():
                    submit.click()

                self._wait_login(context, page)
        except Exception as e:
            self.status = "error"
            self.message = f"自动登录失败：{e}"

    @staticmethod
    def _cookies_valid(cookies) -> tuple[bool, str]:
        """用 getUserInfoFromToken 权威判定 cookie 是否真正有效。

        card.tsinghua.edu.cn 登录前/会话失效时也可能带 servicehall，只看它会"秒判
        成功"误报。getUserInfoFromToken 能拿到 loginuser 才算真正登录成功——这正是
        scraper 校验会话的同一接口。

        cookies 应为已过滤到 card.tsinghua.edu.cn 域的 cookie 列表——避免与 id.tsinghua
        同名 cookie（如 JSESSIONID）按 name 压平后互相覆盖，导致校验一直失败。

        返回 (是否有效, 失败原因)，原因用于诊断回传。
        """
        try:
            import scraper
        except Exception:
            return True, ""  # scraper 不可用时退化为信任预筛（不应发生，它是同步硬依赖）
        cookies_dict = {c["name"]: c["value"] for c in cookies}
        if not cookies_dict.get("servicehall"):
            return False, "无 servicehall"
        try:
            if scraper.get_login_user(cookies_dict):
                return True, ""
            return False, "getUserInfoFromToken 未返回 loginuser"
        except Exception as e:
            return False, f"校验异常：{e}"

    def _wait_login(self, context, page) -> None:
        """轮询 servicehall；登录后若浏览器停在 IdP（card 的 CAS 不原生回 card），主动
        goto card 受保护页"物化"出 servicehall，再用 getUserInfoFromToken 权威校验。

        照参考实现 leverimmy/Table-Tennis-Checkin-Helper 的 login_via_browser：goto 服务自己
        的入口 + 轮询认证产物。但 sports 的 toLoginPage 会编码"回到 sports"的回调，登录后
        浏览器自然回 sports、token 自动出现；而 card 的 CAS 受保护页重定向到 IdP 时回调是
        IdP 自己的 /userindex（见 CHANGELOG 实测），**登录后浏览器停在 id.tsinghua、不回
        card**。所以 card 额外需要一步"物化"：登录后主动访问 card 受保护页，此时 card 的
        CAS 过滤器带 service=card 发起新的票据往返，把浏览器带回 card 并种 servicehall。

        全程把观测写入 self._dbg（经 snapshot 暴露），定位残留问题。
        """
        try:
            import scraper
        except Exception:
            scraper = None
        from urllib.parse import urlparse

        # 物化候选：card 受保护页，轮流试，直到在 card 域种下 servicehall。
        MAT_TARGETS = [
            CARD_AUTH_PAGE,                         # https://card.tsinghua.edu.cn/userinfo
            "https://card.tsinghua.edu.cn/",
            "https://card.tsinghua.edu.cn/login/login",
        ]

        def card_cookies():
            return [c for c in context.cookies()
                    if "card.tsinghua.edu.cn" in (c.get("domain") or "")]

        deadline = time.time() + TIMEOUT_SEC
        last_check = 0.0
        last_materialize = 0.0
        left_login_at = None
        saw_login_form = False
        mat_idx = 0
        mat_attempts = 0
        val_error = ""
        success = False
        while time.time() < deadline:
            if self._stop:
                break
            try:
                current_url = page.url
            except Exception:
                current_url = ""
            parsed = urlparse(current_url)
            host, path = parsed.netloc, parsed.path

            # 登录表单判定：URL 含 "auth/login" 不足以判定仍在表单（登录后 IdP 落地 URL
            # 可能仍带 auth/login 段，会让物化永不触发——曾表现为"已登录但 EAT 没反应"）。
            # 叠加"密码框可见"才算仍在登录表单。
            try:
                pw_visible = page.locator('input[type=password]').first.is_visible()
            except Exception:
                pw_visible = False
            if pw_visible:
                saw_login_form = True
            on_login_form = ("auth/login" in current_url) and pw_visible
            if not on_login_form and left_login_at is None and (
                    saw_login_form or "id.tsinghua" in host):
                left_login_at = time.time()
            left_for = (time.time() - left_login_at) if left_login_at else 0

            cc = card_cookies()
            has_sh = any(c["name"] == "servicehall" for c in cc)
            stage = ("on_login_form" if pw_visible
                     else "on_card" if "card.tsinghua" in host
                     else "on_idp" if "id.tsinghua" in host
                     else "navigating")

            # 物化兜底：SSO 已完成但 card 域还没 servicehall——主动跳 card 受保护页触发带
            # service=card 的票据往返。id 域用 userindex 精确信号 + left_for>15s 兜底（避免
            # 双因子进行中过早跳走打断）；已在 card 域却没 servicehall 也重试下一个候选。
            need_materialize = (
                not pw_visible and not has_sh
                and time.time() - last_materialize > 6
                and (("id.tsinghua" in host and ("userindex" in path or left_for > 15))
                     or "card.tsinghua" in host)
            )
            if need_materialize:
                last_materialize = time.time()
                target = MAT_TARGETS[mat_idx % len(MAT_TARGETS)]
                mat_idx += 1
                mat_attempts += 1
                stage = f"materialize→{target}"
                try:
                    page.goto(target, wait_until="domcontentloaded", timeout=20000)
                except Exception as e:
                    stage = f"materialize 失败：{e}"

            # card 域出现 servicehall（含刚物化回 card）→ 权威校验
            if "card.tsinghua.edu.cn" in host:
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                page.wait_for_timeout(1200)
                cc = card_cookies()
                if has_sh or any(c["name"] == "servicehall" for c in cc):
                    if scraper is None or time.time() - last_check >= 2:
                        last_check = time.time()
                        ok, val_error = self._cookies_valid(cc)
                        if ok:
                            self.cookie_str = "; ".join(
                                f'{c["name"]}={c["value"]}' for c in cc)
                            success = True
                            break

            self._dbg = {
                "stage": stage,
                "url": current_url[:140],
                "on_login_form": pw_visible,
                "saw_login_form": saw_login_form,
                "left_login_for_s": int(left_for),
                "mat_attempts": mat_attempts,
                "has_servicehall": has_sh,
                "val_error": val_error,
            }
            time.sleep(1)
        # 登录成功后停留 2 秒让用户看到完成状态
        if success:
            try:
                page.wait_for_timeout(2000)
            except Exception:
                pass
        _safe_close(context)
        self._context = None
        if success:
            self.status = "success"
            self.message = "登录成功，已捕获会话，可以开始同步了"
            self._dbg = {"stage": "success"}
        elif self._stop:
            self.status = "cancelled"
            self.message = "已取消登录"
        else:
            self.status = "error"
            d = self._dbg
            self.message = (
                f"登录超时（{TIMEOUT_SEC // 60} 分钟内未拿到 servicehall）。"
                f"诊断：阶段={d.get('stage')}｜url={d.get('url')}｜"
                f"离开登录页 {d.get('left_login_for_s')}s｜物化 {d.get('mat_attempts')} 次｜"
                f"servicehall={'有' if d.get('has_servicehall') else '无'}｜"
                f"校验={d.get('val_error') or '未执行'}"
            )


login_session = LoginSession()
