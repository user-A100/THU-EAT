"""Playwright 登录：支持手动浏览器登录和自动账号密码登录。

流程：
  手动模式 — 启动可见浏览器 → 用户手动完成 SSO → 捕获 cookie
  自动模式 — 后台启动 headless 浏览器 → 自动填写学号密码 → 提交 SSO → 捕获 cookie

Playwright 的 sync API 在独立后台线程内使用（不在 Flask 请求线程里直接调用）。
"""
import subprocess
import sys
import threading
import time

LOGIN_URL = "https://card.tsinghua.edu.cn/"
SSO_URL = "https://id.tsinghua.edu.cn/do/off/ui/auth/login/form/eea30cbedcaf97c69d28b2d92f22a259/0?/userindex"
SUCCESS_COOKIE_NAMES = {"servicehall", "JSESSIONID"}
TIMEOUT_SEC = 300


def _safe_close(browser):
    try:
        browser.close()
    except Exception:
        pass


class LoginSession:
    def __init__(self):
        self.status = "idle"
        self.message = ""
        self.cookie_str = ""
        self._thread = None
        self._stop = False
        self._browser = None

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
        self._thread = threading.Thread(target=self._run_auto, args=(username, password), daemon=True)
        self._thread.start()
        return True

    def cancel(self) -> None:
        self._stop = True
        if self._browser is not None:
            _safe_close(self._browser)

    def snapshot(self) -> dict:
        return {"status": self.status, "message": self.message,
                "has_cookie": bool(self.cookie_str)}

    def _run_manual(self) -> None:
        """浏览器登录：用 --app 模式打开无边框登录窗（类似小程序弹窗），关闭后自动捕获 cookie。"""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.status = "error"
            self.message = "未安装 playwright，请运行：pip install playwright"
            return
        try:
            with sync_playwright() as p:
                # 用内置 Chromium，加 --app 参数：无地址栏/标签栏，干净登录窗
                browser = p.chromium.launch(
                    headless=False,
                    args=[
                        "--window-size=520,700",
                        "--window-position=center",
                        "--disable-extensions",
                        "--no-first-run",
                        "--no-default-browser-check",
                    ]
                )
                self._browser = browser
                context = browser.new_context(viewport={"width": 500, "height": 680})
                page = context.new_page()
                # 打开 card 首页
                page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(2000)
                # 检查是否已跳转到 SSO；没有则主动点击登录
                if "id.tsinghua" not in page.url and "auth.tsinghua" not in page.url:
                    try:
                        # 尝试各种登录入口
                        for sel in ['a:has-text("登录")', 'button:has-text("登录")', '[href*="login"]', '[href*="auth"]']:
                            btn = page.locator(sel).first
                            if btn.is_visible():
                                btn.click()
                                page.wait_for_timeout(2000)
                                if "id.tsinghua" in page.url:
                                    break
                    except Exception:
                        pass
                # 如果还没到 SSO，手动导航
                if "id.tsinghua" not in page.url:
                    page.goto(SSO_URL, wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(1000)
                self._wait_login(context, page, browser)
        except Exception as e:
            self.status = "error"
            self.message = f"浏览器启动失败：{e}"

    def _run_auto(self, username: str, password: str) -> None:
        """自动 SSO 登录：直接访问 id.tsinghua.edu.cn，填写学号密码提交。"""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.status = "error"
            self.message = "未安装 playwright，请运行：pip install playwright"
            return
        try:
            with sync_playwright() as p:
                browser = self._launch(p, headless=True)
                self._browser = browser
                context = browser.new_context(viewport={"width": 1100, "height": 820})
                page = context.new_page()

                # 直接访问 SSO 登录页
                page.goto(SSO_URL, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(2000)

                # 填写学号
                username_input = page.locator('input[name="username"], input#username, input[type="text"]').first
                if username_input.is_visible():
                    username_input.fill(username)
                else:
                    # 可能有多步流程：先输入学号点下一步
                    username_input = page.locator('input[type="text"], input[name="j_username"]').first
                    if username_input.is_visible():
                        username_input.fill(username)
                        next_btn = page.locator('button[type="submit"], input[type="submit"], button:has-text("下一")').first
                        if next_btn.is_visible():
                            next_btn.click()
                            page.wait_for_timeout(2000)

                # 填写密码
                password_input = page.locator('input[type="password"]').first
                if password_input.is_visible():
                    password_input.fill(password)
                else:
                    page.wait_for_timeout(1500)
                    password_input = page.locator('input[type="password"]').first
                    if password_input.is_visible():
                        password_input.fill(password)

                # 提交
                submit = page.locator('button[type="submit"], input[type="submit"], button:has-text("登录"), button:has-text("登 录")').first
                if submit.is_visible():
                    submit.click()

                # 等待登录完成，捕获 cookie
                self._wait_login(context, page, browser)
        except Exception as e:
            self.status = "error"
            self.message = f"自动登录失败：{e}"

    def _wait_login(self, context, page, browser=None) -> None:
        """轮询等待 SSO 登录 → card 域 → 捕获 servicehall cookie。"""
        deadline = time.time() + TIMEOUT_SEC
        was_on_sso = False
        success = False
        while time.time() < deadline:
            if self._stop:
                break
            current_url = page.url
            # 只要到过 id.tsinghua 就算经过了 SSO
            if "id.tsinghua" in current_url:
                was_on_sso = True
            # 回到 card 域 → 捕获全部 cookie
            if was_on_sso and "card.tsinghua.edu.cn" in current_url:
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                page.wait_for_timeout(1500)
                # 不区分域，全部 cookie 都拿走
                all_cookies = context.cookies()
                if all_cookies:
                    self.cookie_str = "; ".join(
                        f'{c["name"]}={c["value"]}' for c in all_cookies
                    )
                    # 只要有 servicehall 或 _session 或 JSESSIONID 就算成功
                    names = {c["name"] for c in all_cookies}
                    if names & {"servicehall", "JSESSIONID", "_session"}:
                        success = True
                        break
            time.sleep(1)
        # 登录成功后停留 2 秒让用户看到完成状态
        if success:
            page.wait_for_timeout(2000)
        if browser:
            _safe_close(browser)
        self._browser = None
        if success:
            self.status = "success"
            self.message = "登录成功，已捕获会话，可以开始同步了"
        elif self._stop:
            self.status = "cancelled"
            self.message = "已取消登录"
        else:
            self.status = "error"
            self.message = f"登录超时（{TIMEOUT_SEC // 60} 分钟内未检测到登录成功）"

    @staticmethod
    def _get_default_browser_exe() -> str | None:
        """读取 Windows 注册表获取系统默认浏览器的可执行文件路径。"""
        try:
            import winreg
            # 1. 获取默认浏览器的 ProgId
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice"
            )
            prog_id, _ = winreg.QueryValueEx(key, "ProgId")
            # 2. 从 ProgId 获取可执行文件路径
            cmd_key = winreg.OpenKey(
                winreg.HKEY_CLASSES_ROOT,
                rf"{prog_id}\shell\open\command"
            )
            cmd, _ = winreg.QueryValueEx(cmd_key, "")
            # 命令格式: "C:\...\browser.exe" --args %1
            # 提取 exe 路径（去除引号和参数）
            exe = cmd.strip().split('"')[1] if '"' in cmd else cmd.split()[0]
            return exe if exe.lower().endswith('.exe') else None
        except Exception:
            return None

    def _launch(self, p, headless=False):
        # 自动模式（headless）直接用内置 Chromium
        if headless:
            try:
                return p.chromium.launch(headless=True)
            except Exception:
                subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    check=False,
                )
                return p.chromium.launch(headless=True)

        # 手动模式：优先尝试系统默认浏览器
        exe = self._get_default_browser_exe()
        if exe:
            try:
                browser = p.chromium.launch(headless=False, executable_path=exe)
                test_page = browser.new_page()
                test_page.goto(LOGIN_URL, wait_until="commit", timeout=5000)
                test_page.close()
                return browser
            except Exception:
                try: browser.close()
                except Exception: pass

        for channel in ("msedge", None):
            try:
                kwargs = {"headless": False}
                if channel:
                    kwargs["channel"] = channel
                return p.chromium.launch(**kwargs)
            except Exception:
                if channel is None:
                    subprocess.run(
                        [sys.executable, "-m", "playwright", "install", "chromium"],
                        check=False,
                    )
                    return p.chromium.launch(headless=False)
                continue


login_session = LoginSession()
