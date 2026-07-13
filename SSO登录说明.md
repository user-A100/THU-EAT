# 🔐 THU-EAT 清华 SSO 登录 — 技术说明

## 概述

THU-EAT 通过 Playwright 自动化浏览器，实现了清华统一身份认证（SSO）的一键登录。用户点击按钮 → 弹出浏览器窗口 → 完成身份验证 → 窗口自动关闭 → 系统自动同步数据。全程无需手动复制 Cookie。

## 致谢

本项目的 SSO 登录方案参考了 **[leverimmy/Table-Tennis-Checkin-Helper](https://github.com/leverimmy/Table-Tennis-Checkin-Helper)** 的清华统一身份认证登录实现。

感谢大佬开源的乒乓球签到助手项目，其 `persistent browser context` 模式为本项目提供了关键参考：

- **持久化浏览器 Profile**：将 Cookie / localStorage / "下次不再验证此浏览器"的 2FA 信任状态保存在本地，实现重新登录免二次验证
- **SingletonLock 守护**：检测并清理浏览器崩溃后残留的 profile 锁文件，防止 profile 被锁死
- **轮询捕获模式**：goto 服务入口 → 轮询认证产物的整体架构

> 两个项目的差异：Table-Tennis-Checkin-Helper 登录 `sports.tsinghua.edu.cn`，捕获 JWT token；THU-EAT 登录 `card.tsinghua.edu.cn`，捕获 `servicehall` cookie。因此移植的是**模式**而非照搬代码。

---

## 登录流程

### 用户视角

```
点击「🔑 一键登录清华」
       ↓
弹出 Chromium 浏览器窗口（清华统一身份认证页面）
       ↓
输入学号 + 密码 + 双因子验证（首次；再次登录通常免 2FA）
       ↓
认证成功 → 窗口自动关闭
       ↓
系统自动同步消费数据
       ↓
切回「数据看板」即可查看
```

### 技术流程

```
┌──────────────────────────────────────────────────────┐
│ 1. launch_persistent_context                         │
│    启动持久化 Chromium，profile 保存在               │
│    data/.browser_profile/                            │
│    包含：Cookie / localStorage / 2FA 信任标记         │
└──────────────────┬───────────────────────────────────┘
                   ↓
┌──────────────────────────────────────────────────────┐
│ 2. 清理 card 域旧 cookie + 清理 stale profile 锁      │
│    - 清掉 card.tsinghua.edu.cn 的失效 servicehall      │
│    - 保留 id.tsinghua.edu.cn 的 2FA 信任态            │
│    - 检测 SingletonLock，崩溃残留则自动清理            │
└──────────────────┬───────────────────────────────────┘
                   ↓
┌──────────────────────────────────────────────────────┐
│ 3. goto card 受保护页 /userinfo                       │
│    card 的 CAS 过滤器检测未登录 → 服务端 302 跳 IdP   │
│    关键：从 card 受保护页进入，让 card 自己发起        │
│    带正确回调 (service=card) 的 SSO 往返              │
└──────────────────┬───────────────────────────────────┘
                   ↓
┌──────────────────────────────────────────────────────┐
│ 4. 用户在 IdP 页面完成认证（学号 + 密码 + 2FA）        │
│    id.tsinghua.edu.cn/.../auth/login/...             │
└──────────────────┬───────────────────────────────────┘
                   ↓
┌──────────────────────────────────────────────────────┐
│ 5. 轮询等待 + 「物化」兜底                             │
│    检测到 SSO 已完成但 card 域还没 servicehall →       │
│    主动访问 card 受保护页触发 CAS 票据往返             │
│    让 card 在自己域种下 servicehall                    │
└──────────────────┬───────────────────────────────────┘
                   ↓
┌──────────────────────────────────────────────────────┐
│ 6. getUserInfoFromToken 权威校验                      │
│    拿到 loginuser 才算真正登录成功                     │
│    （仅凭 servicehall 存在会误报）                     │
└──────────────────┬───────────────────────────────────┘
                   ↓
┌──────────────────────────────────────────────────────┐
│ 7. 捕获 cookie → 关闭浏览器 → 自动同步数据             │
│    前端轮询 /api/login/status → success →            │
│    调用 /api/login/sync 拉取消fei数据                  │
└──────────────────────────────────────────────────────┘
```

---

## 关键技术点

### 1. Persistent Browser Context（持久化浏览器上下文）

Playwright 的 `launch_persistent_context` 是核心。与普通 `launch()` + `new_context()` 不同：

| 特性 | 普通模式 | Persistent Context |
|------|---------|-------------------|
| Cookie 持久化 | 进程结束即丢失 | 自动写入磁盘 |
| localStorage | 不持久化 | 自动写入磁盘 |
| 2FA "信任此浏览器" | 每次都要重新验证 | 一次信任，长期有效 |
| Profile 位置 | 无 | `data/.browser_profile/` |

**这是"重新登录免二次验证"的关键**——清华 SSO 的"下次不再验证此浏览器"标记存在 localStorage 里，persistent context 将其保留在磁盘。

### 2. CAS 重定向链与「物化」

这是整个实现中最棘手的部分。

**正常 CAS 流程：**
```
用户访问 card 受保护页 → card 302 跳 IdP → 用户登录 → IdP 带 ticket 回跳 card → card 种 cookie
```

**实际遇到的情况：**
card 的 CAS 受保护页重定向到 IdP 时，回调 URL 是 IdP 自己的 `/userindex`（而非带回 card 的回调）。结果：用户在 IdP 登录成功后，浏览器**停在 id.tsinghua.edu.cn，永远不会回到 card.tsinghua.edu.cn**，因此 card 域永远种不下 servicehall。

**解决方案——「物化」（Materialization）：**
轮询检测到"用户已完成 SSO 但 card 域没有 servicehall"时，主动 `goto(card/userinfo)`，此时 card 的 CAS 过滤器会发起一次**新的票据往返**（带 `service=card` 的回调），把浏览器带回 card 并在 card 域种下 servicehall。

```
检测条件：
  - 密码框不可见（已离开登录表单）
  - card 域无 servicehall
  - 浏览器在 id.tsinghua 域（/userindex 或离开登录表单 >15s）
  - 距上次物化 >6s

物化候选（轮流尝试）：
  1. https://card.tsinghua.edu.cn/userinfo
  2. https://card.tsinghua.edu.cn/
  3. https://card.tsinghua.edu.cn/login/login
```

### 3. 权威 Cookie 校验

`card.tsinghua.edu.cn` 在**未登录时也可能下发 servicehall**。如果只看 servicehall 是否存在，会在用户还没输完密码时就"秒判成功"。

因此采用**两步校验**：

1. **预筛**：card 域出现 servicehall（快速过滤明显未登录的情况）
2. **权威校验**：调用 `getUserInfoFromToken`（校园卡系统的用户信息接口），能拿到 `loginuser` 才算真正登录成功

### 4. Profile 锁守护

persistent context 使用 Chromium 的 `SingletonLock` 防止多个进程同时使用同一个 profile。如果浏览器崩溃，锁文件残留会导致下次启动失败。

移植自参考项目的解决方案：
- 启动前检查 `SingletonLock` 指向的进程是否存活
- 进程已死 → 清理 `SingletonLock` / `SingletonCookie` / `SingletonSocket`
- Windows 上 `SingletonLock` 不是符号链接，无法读 PID → 保守处理（线程互斥保证不同时开两个登录窗口）

### 5. 实时诊断反馈

`_wait_login` 全程将观测数据写入 `snapshot().debug`，前端轮询时实时显示：

```
🔍 on_login_form · 离开登录页 3s · 物化 1次 · servicehall 无
```

超时时也会输出完整诊断信息，包括阶段、URL、离开登录页时间、物化次数、servicehall 有无、校验错误——方便定位"卡在哪一步"。

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `auth.py` | Playwright 登录引擎：persistent context、SSO 跳转、轮询捕获、profile 锁管理 |
| `scraper.py` | 校园卡 API 爬虫：`getUserInfoFromToken` 权威校验、AES 解密、数据拉取 |
| `app.py` | Flask API 层：`/api/login/start` `/api/login/status` `/api/login/sync` 等端点 |
| `static/app.js` | 前端轮询与 UI：按钮交互、状态轮询、登录后自动同步 |
| `static/index.html` | 登录面板 UI：一键登录按钮、学号密码登录表单、状态显示 |

---

## 两种登录模式

| 模式 | 按钮 | 浏览器 | 适用场景 |
|------|------|--------|---------|
| 手动模式 | 🔑 一键登录清华 | 可见窗口 | **推荐**，需完成 2FA |
| 自动模式 | 🤖 学号密码登录 | 后台 headless | 已信任本机、免 2FA 时可用（有验证码则失败） |

> 自动模式会在后台填写学号密码并提交。但 SSO 表单带图形验证码（`i_captcha`），自动模式多半会被验证码拦下。推荐使用手动模式。

---

## 踩坑记录

详见 [CHANGELOG.md](./CHANGELOG.md) 中 2026-07-12 至 2026-07-13 的开发日志，主要问题包括：

1. **"弹窗登录成功但 EAT 没反应"** — 裸 SSO URL 回调是 `/userindex`，浏览器永不回 card → 改为从 card 受保护页进入 + 物化兜底
2. **"来不及输入就秒判登录成功"** — 失效 cookie 残留 → 登录前清 card 域 cookie + 用 `getUserInfoFromToken` 权威校验
3. **"物化永不触发"** — URL 子串判定 `auth/login` 在登录后仍匹配 → 改为密码框可见判定 + `/userindex` 信号
4. **"id 域同名 cookie 压平覆盖"** — id.tsinghua 和 card.tsinghua 都有 `JSESSIONID` → 校验只用 card 域 cookie

---

## 参考

- [leverimmy/Table-Tennis-Checkin-Helper](https://github.com/leverimmy/Table-Tennis-Checkin-Helper) — 清华 SSO persistent context 登录模式参考实现
- [Playwright: Persistent Context](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context) — 官方文档
- 清华统一身份认证（IdP）：`id.tsinghua.edu.cn`
- 清华校园卡系统：`card.tsinghua.edu.cn`
