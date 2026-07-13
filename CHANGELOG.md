# THU Eat 开发日志

## 2026-07-13

### 真正修复一键登录回传：对照参考项目，从 card 受保护页进入 + 修复物化触发
- **问题**：浏览器里 SSO 已显示登录成功，但 EAT 拿不到 token（一直 waiting → 超时）。
- **对照参考实现** `leverimmy/Table-Tennis-Checkin-Helper`（已成功跑通清华 SSO→捕获会话）的 `login_via_browser`：
  - goto **服务自己的登录入口**（不是 IdP 本身），登录后由浏览器 CAS 跳转链自然回服务、认证产物自动出现；轮询捕获即可
  - 但 sports 的 `toLoginPage` 编码了"回到 sports"的回调；而 card 的 CAS 受保护页重定向到 IdP 时回调是 IdP 自己的 `/userindex`（见下 2026-07-12 实测），登录后浏览器**不回 card**——所以 card 不能照搬"只轮询"，必须保留物化兜底
- **根因（代码层面）**：之前 `_run_manual`/`_run_auto` 直接 `goto(裸 SSO_URL=…?/userindex)`，且回调是 `/userindex`，登录后浏览器停在 id.tsinghua 永远不回 card；物化本应救场，但触发条件 `on_login_form = "auth/login" in url` 是纯子串判定——IdP 登录后落地 URL 仍带 `auth/login` 时，物化**永不触发**
- **修复**：
  - `_run_manual`/`_run_auto` 改为 `goto(CARD_AUTH_PAGE=card/userinfo)`：card 的 CAS 过滤器服务端 302 跳 IdP（不走首页那个时序不稳的 JS 登录按钮），既稳定弹到登录表单、又让 card 自己发起 SSO 往返；删除裸 `SSO_URL` 常量
  - 物化触发改为 `密码框可见` 判定登录态 + `userindex`/离开登录页 15s 信号，不再用脆弱 URL 子串；物化候选轮流试 `/userinfo`、`/`、`/login/login`
  - 校验只用 card 域 cookie（避免与 id 域同名 `JSESSIONID` 压平覆盖误判）
  - `_wait_login` 全程把 阶段/url/物化次数/servicehall 有无/校验错误 写入 `snapshot().debug`，前端等待时实时显示一行 🔍，超时信息里也带完整读数——以后再卡能直接看出卡在哪步

## 2026-07-12

### 彻底修复一键登录：直达 SSO + 登录后物化 card 会话（实测摸清真实流程）
- **实测摸清 card 登录真实流程**（之前几版都在猜）：
  - card 首页"登录"是 JS 触发的空 `<a>`，时序不稳 → 之前"开 card 首页再点登录"经常**不跳 SSO**
  - 该"登录"按钮跳到的 SSO：`id.tsinghua.edu.cn/.../auth/login/form/<hash>/0?/userindex`，标题"您即将登录 校园卡系统"
  - **关键：SSO 登录成功后 IdP 把浏览器停在它自己的 `/userindex` 页，根本不回 card.tsinghua.edu.cn** —— 所以光"等回到 card"永远等不到 servicehall（"登录了也无法返回 thu-eat"的根因）
  - 即便 CAS 受保护页 `/userinfo`、`/function` 未登录时也都重定向到同一个 `?/userindex` 回调
- **修复一（直达 SSO）**：`_run_manual`/`_run_auto` 直接 `goto(SSO_URL)`，不再开 card 首页点 JS 按钮——稳定弹到 SSO 登录表单
- **修复二（登录后物化）**：`_wait_login` 检测到 IdP 登录后停在 `/userindex`（或离开登录表单 >12s），主动 `goto(card/userinfo)` 触发 CAS 往返、让 card 在自己域种下 servicehall；每 8s 可重试
- **修复三（权威校验保留）**：仍用 `getUserInfoFromToken` 拿到 loginuser 才算成功，避免 servicehall 误报
- 移除已无用的 `_attach_sso_watcher`（不再依赖 was_on_sso）
- **验证**：mock 路由模拟"登录后停在 /userindex"→ `_wait_login` 自动跳 /userinfo 物化 servicehall → getUserInfoFromToken 校验通过 → success

---

### 修复一键登录"来不及输入就秒判登录成功"（误报）
- **现象**：点一键登录后，浏览器还没等用户输入就关闭、显示"登录成功"
- **根因**：上一轮遗留的失效 card cookie + CAS 跳转本身会让 `was_on_sso` 为真（card→id→card 一跳即真），叠加"card 登录前就下发 servicehall"，于是 `was_on_sso + servicehall` 在**未真正登录**时也命中 → 秒判成功。`was_on_sso` 只能说明"CAS 跳转经过过 id.tsinghua"，不是"已认证"的可靠信号
- **修复（权威校验）**：成功判定改为用 `scraper.get_login_user`（即 `getUserInfoFromToken`）校验捕获的 cookie——能拿到 loginuser 才算真正登录成功（这正是 scraper 校验会话的同一接口）。`was_on_sso` 仅作预筛、减少无效接口请求；接口校验节流 ≥2s
- **配套**：登录前 `_clear_card_cookies` 清掉 card.tsinghua.edu.cn 的失效 cookie（保留 id.tsinghua 的二次验证信任态），让 card 干净地跳到 SSO 登录表单，用户能正常输入
- **验证**：mock `getUserInfoFromToken`——VALID cookie→success、STALE cookie→不误报（等到超时）；`_clear_card_cookies` 清 card 域、保留 id.tsinghua 域

---

### 修复一键登录"弹窗登录成功但本程序不完成"
- **现象**：一键登录弹出验证窗口，用户输入账号密码后弹窗显示"登录成功"，但 THU-EAT 页面一直不完成、不同步
- **根因**：`_run_manual`/`_run_auto` 在 card 没秒跳 SSO 时会强跳裸 `SSO_URL`，而该 URL 的回调是 `/userindex`——登录后浏览器停在 `id.tsinghua.edu.cn`，**永远回不到 card.tsinghua.edu.cn**，于是 `_wait_login`（要求回到 card 域）一直等到超时
- **修复（对齐参考仓库 intent）**：从 `card.tsinghua.edu.cn/`（CAS 客户端入口，相当于参考仓库的 `AUTH_URL`）进入，让 card 自己发起带正确回调的 SSO 往返，登录后自然回到 card 并种下 servicehall；删除裸 `SSO_URL` 常量与强跳逻辑
- **可靠性增强**：`was_on_sso` 改用 `framenavigated` 主帧监听（`_attach_sso_watcher`）维护，能捕捉 IdP 仍有效时的秒级 `card→id→card` 往返——"免二次验证"的重新登录也能被识别（1s 轮询会漏掉一闪而过的 id.tsinghua）
- **验证**：用 Playwright route mock 模拟往返——正向（经 SSO 回到 card + servicehall）正确捕获；反向（仅 card 域、pre-auth servicehall、未过 SSO）不误报（守住历史"登录闪退"防线）

---

### 移植清华 SSO persistent-context 登录模式 + 前端接入一键登录
- **背景**：参考 `leverimmy/Table-Tennis-Checkin-Helper`，把清华统一身份认证登录升级为 persistent browser context 模式；并真正把登录接入前端（此前 `/api/login/*` 接口存在但前端零调用，只能手动 F12 复制 cookie）
- **`auth.py`**：`launch` + `new_context` → `launch_persistent_context`，profile 落在 `data/.browser_profile/`
  - 持久化 cookie / localStorage / "下次不再验证此浏览器" 的二次验证信任态 → 重新登录可免 2FA
  - 移植 `SingletonLock` 守护：`is_browser_profile_in_use` / `clear_stale_profile_locks`，浏览器崩溃后自动清理 stale 锁、不再锁死
  - 移除"优先系统默认浏览器(Edge)"分支，统一用 Playwright 自带 Chromium（persistent profile 兼容性）
  - 保留 manual / auto 两条路径与公开契约；`snapshot()` 新增 `has_saved_state`
  - 成功判定回归"必须 was_on_sso"（历史登录闪退 Bug 的防线：card 域登录前就会下发 servicehall，不能只看它）
- **前端 `index.html` / `app.js`**：「配置与同步」新增「🔑 一键登录清华」+「🤖 学号密码登录」面板
  - 轮询 `/api/login/status`，成功后自动调 `/api/login/sync` 同步并刷新；密码用完即清
  - 修复：原退出登录 handler 写入的 `c-login-status` 元素此前在 HTML 中并不存在（隐含 Bug），随本次登录面板新增一并修复
  - 手动复制 cookie 降级为"备用"
- **`README.md`**：一键登录作为主路径，手动复制 cookie 降为备用；更新 Mac / cookie 过期 FAQ

---

### 第十次迭代：修复地点搜索 + 卡片对齐 + 搜索栏美化
- **地点搜索修复**：
  - 事件监听器加防御性检查（`bindLocationEvents` IIFE），防止元素未渲染时静默失败
  - 输入即搜、回车搜索、点击搜索三管齐下
- **卡片对齐**：主网格 6 列 → **12 列**，子网格同步 12 列
  - Row1: 总支出(4) | 活跃天数(2) | 最大单笔(3) | 统计区间(3)
  - Row2: 今日(3) | 本周(3) | 本月(3) | 本年(3)
  - 最大单笔右边缘精确对齐本月，统计区间右边缘精确对齐本年
- **搜索栏美化**：`.location-search` 样式，输入框加大（15px, padding 10px 16px），按钮加大，搜索图标

---

## 2026-07-10

### 第一次迭代：修复同步、添加登录按钮
- **问题**：前端缺失 Playwright 登录按钮，README 已宣传但未实现
- **修复**：`index.html` / `app.js` 添加「🔐 登录清华」按钮及轮询逻辑
- **修复**：`app.py` `/api/login/sync` 新增 `save_only` 参数
- **修复**：`loadConfig()` 同步日期范围显示错误（空 last_sync_date 时直接 return）
- **修复**：`do_sync()` 中 `start > end` 边界保护
- **修复**：`start.bat` GBK 编码问题，用 `generate_startbat.py` 重新生成

### 第二次迭代：同步后看板不刷新
- **问题**：同步成功后切到"数据看板"标签不会自动加载数据
- **修复**：切换 dashboard 标签时改为调用 `fillCategoryFilter() + refresh()`
- **修复**：同步成功后自动调用 `fillCategoryFilter()` + `loadConfig()`

### 第三次迭代：清空示例数据，真实同步
- **操作**：清空 432 条 mock 数据，重置 `last_sync_date`

### 第四次迭代：修复分页 + 登录窗口闪退
- **分页 Bug**：`/api/transactions` 的 `count` 返回 `len(rows)`（当前页行数）而非总数
  - `db.py`：新增 `count_transactions_filtered()` 返回真实 `COUNT(*)`
  - `app.py`：API 改为返回 `total`
- **登录闪退 Bug**：`card.tsinghua.edu.cn` 登录前就会设置 `servicehall` cookie
  - `auth.py`：改为结合 `page.url` 判断（必须回到 card 域 + 曾到过 SSO 页面）
  - 自动点击门户「登录」链接触发 SSO 跳转

### 第五次迭代：退出登录功能
- `index.html`：新增「退出登录」按钮（红色 danger 样式）
- `app.js`：退出时清空 `servicehall` 和 `idserial`，刷新看板

### 第六次迭代：分帐户数据存储 + 登录后自动同步
- **分帐户存储**：
  - `db.py`：`transactions` 表新增 `owner` 列，所有查询按 owner 过滤
  - `app.py`：`_owner()` 获取当前 idserial，传递给所有 DB 操作
  - 退出登录后看板为空，换账号登录后各自数据隔离
- **登录后自动同步**：
  - `app.js`：`pollLoginStatus` 登录成功后直接调用 `/api/login/sync`（不再 `save_only`）
  - `app.py`：`do_sync` 自动从 API 获取 idserial 并保存
  - `scraper.py`：`get_login_user()` 通过 cookie 获取用户标识

### 第七次迭代：UI 大改版
- **品牌**：`Eat_stat` → `THU Eat`
- **筛选栏**：删除趋势粒度，改为「数字 + 单位」快捷统计（如"3 月"）
  - 支持自定义日期范围（勾选 checkbox 显示日期选择器）
  - 图表粒度由单位自动推导
- **统计卡片**：
  - 第一行：总支出 | 活跃天数 | 最大单笔 | 统计区间（共 X 天）
  - 第二行（sub-grid）：今日支出 | 本周支出 | 本月支出 | 本年支出
  - `app.py` / `stats.py`：summary 新增 `today` / `this_week` / `this_year`
- **同步页**：日期选择器改为三个快捷按钮（全部导入 / 近一年 / 近一月）
- **配色**：蓝色 → 清华紫（`#7B2D8E` 浅色 / `#B87FD9` 暗色）
- **标题**：`THU Eat` 字号 18px → 22px，粗体 800

### 第八次迭代：修复日期比较 + 浏览器 + 字体
- **SQL 日期比较 Bug**：`"2026-07-10 12:30:00" <= "2026-07-10"` 在 SQLite 中为 False
  - `db.py`：所有 `end` 日期追加 `" 23:59:59"`
- **浏览器选择**：
  - `auth.py`：读取 Windows 注册表检测默认浏览器（ProgId → exe）
  - 默认浏览器可执行路径启动 + HTTPS 兼容性测试
  - 不兼容（如夸克崩 HTTPS）→ 自动回退 Edge
- **最大单笔字体**：去掉 `small-v` 类，与其他卡片一致

### 第九次迭代：地点统计 + 自动同步
- **地点统计页**：
  - 新增「地点统计」标签页
  - `stats.py`：`by_location_detailed()` 含地址、笔均、占比
  - `app.py`：`/api/stats/locations` 端点
  - 前端：表格展示全部商户排名，搜索框 + datalist 自动补全，输入实时筛选
- **自动同步**：
  - 同步页新增「自动同步」开关（每 30 分钟增量拉取）
  - 开关状态持久化到 `localStorage`，重启恢复
  - Cookie 过期自动提示
  - 看板页面自动刷新

---

## 2026-07-10（下午 · 第十一次迭代）大规模功能增强

### 一、最大支出卡片改为下拉选择
- **`stats.py`**：`summary()` 新增 `max_day`（最大日支出）、`max_month`（最大月支出）、`max_year`（最大年支出），各自包含金额/日期/笔数
- **`app.js`**：卡片标题行改为 `<select>` 下拉：单笔 | 日 | 月 | 年
  - 切换时从缓存的 `state._lastSummary` 即时重绘，无需重新请求 API
  - 使用 **inline `onchange="window._switchMaxType(this.value)"`** 保证事件可靠触发（解决 DOM 重建后事件丢失的 Bug）

### 二、数据导出 CSV
- **`app.py`**：新增 `/api/export` 端点，UTF-8 BOM 编码，Excel 直接打开
  - 支持与明细表相同的筛选参数（start/end/category/keyword）
- **`index.html`** + **`app.js`**：筛选栏右侧新增「📥 导出数据」按钮

### 三、日期格式统一 yyyy/MM/dd
- **`index.html`**：日期输入框从 `type="date"`（格式随浏览器/OS 变化）改为 `type="text" placeholder="yyyy/MM/dd"`
- **`app.js`**：新增 `toISODate()` / `toUIDate()` 转换函数
  - 用户界面始终 yyyy/MM/dd，API 自动转 yyyy-MM-dd
  - 范围提示 `range-hint` 同步统一格式

### 四、页码跳转
- **`index.html`**：分页栏新增「跳至 [输入框] 页 [GO]」
- **`app.js`**：自动校验页码范围（1 ~ 总页数），支持回车键快捷跳转

### 五、地点统计：食堂汇总 + 窗口/食堂双模式
- **`stats.py`**：
  - `_cafeteria_name()`：提取食堂名（`_` 前部分为食堂，"天猫*" → "天猫校园"）
  - `_window_name()`：提取窗口名
  - `by_location_cafeteria()`：食堂级聚合（含窗口数统计）
  - `by_location_detailed()`：窗口级统计（新增 `cafeteria` / `window` 字段）
- **`app.py`**：`/api/stats/locations?group=cafeteria|window`
- **前端**：地点统计页新增「窗口统计 / 食堂统计」下拉切换
  - 食堂模式：表头变更为「食堂 | 窗口数 | …」
  - 天猫清芬店 / 天猫紫荆店 → 归入「天猫校园」，不混入各食堂

### 六、快速统计增强
- **"全部"选项**：`f-unit` 新增 `<option value="all">全部</option>`，选择后隐藏数字框，不设日期范围
- **一键全部数据按钮**：「📊 全部数据」位于快速统计与自定义范围之间
- **手动输入数字**：`<select id="f-num">`（限 1-10）→ `<input type="number" min="1">`（任意数字）

### 七、本年支出修复（大一新生场景）
- **`app.py`** `api_summary()`：最早数据距今不足 365 天 → 统计全部数据；否则统计今年 1 月 1 日起

### 八、分类规则补充
- **`db.py`** `DEFAULT_RULES`：新增 `"澜园": "食堂"`
- **`db.py`** `init_db()`：每次启动 `INSERT OR IGNORE` 全部默认规则，已有数据库自动补录新规则
- **`app.js`** `fillCategoryFilter()`：分类下拉强制追加"充值"选项（充值数据被统计排除，需手动补上）

### 九、消费明细金额汇总
- **`db.py`**：新增 `sum_transactions_filtered()` — `COALESCE(SUM(amount),0)`
- **`app.py`**：`/api/transactions` 响应新增 `total_amount`
- **前端**：标题栏显示「· 合计 ¥xxx.xx」（紫色加粗），不受分页影响

### 十、卡片日期标注
- **`app.js`** `renderCards()`：第二行四个卡片增加 `sub` 标注
  - 今日支出 → "7月10日 周四"
  - 本周支出 → "W28"（ISO 周数）
  - 本月支出 → "7月"
  - 本年支出 → "2026"

### 十一、全面 JS 加固（防止崩溃连锁反应）
- **根因**：之前 `$("xxx").addEventListener(...)` 若元素不存在会抛出 `TypeError`，**中止全部后续 JS 执行**
- **修复**：所有依赖 DOM 元素的顶层代码用 IIFE 包裹 + null 检查
  - 涉及：导出按钮、筛选控件、明细按钮、页码跳转、地点搜索等
- **模板字面量 → 字符串拼接**：避免潜在的注入/解析风险

### 十二、最大支出动态变化 Bug 彻底修复
- **问题**：`renderCards` 每次重建 DOM 后，旧元素上的事件监听器随销毁丢失，新元素的事件可能绑不上
- **方案**：inline `onchange` 属性 + 全局函数 `window._switchMaxType`，事件 100% 可靠
- 配合 `refresh()` 的 try-catch 错误处理，API 失败时 toast 提示而非静默崩溃

---

## 2026-07-10（晚 · 第十二次迭代）地点排序 + 天猫分类根因修复

### 一、地点统计列排序
- **`app.js`**：
  - `state` 新增 `locGroup` / `locSort`（默认按总额倒序，与后端一致）
  - 新增 `sortLocations()`（name 文本比较、其余数值比较，方向可逆）
  - 新增 `locHeaders()` 生成可点击表头：可排序列带 `data-sort`，当前列显示 ▲/▼
  - `renderLocationTable` 重写：渲染前先排序，缓存 `_locLastSet` 供重排；空表 colspan 修正为 8
  - `bindLocationEvents` 加表头事件委托：同列点切方向，新列按 name=升序/数值=降序
  - 可排序列：食堂/商户名、窗口数（食堂模式）、笔数、笔均、总额、占比
- **`style.css`**：`th.sortable` 手型指针 + 悬停紫色高亮

### 二、天猫标签 食堂 → 超市购物（根因修复，全应用生效）
- **根因**：真实商户名是「天猫清芬店/天猫观畴店」，里面嵌着「清芬/观畴」→ 命中食堂规则；
  而原规则关键词「天猫校园」根本不是这些名字的子串，天猫规则从未生效。
- **`db.py`**：`DEFAULT_RULES` 新增 `"天猫": "超市购物"`（「天猫校园」保留兼容模拟数据）
- **`categorize.py`**：匹配逻辑由「排序后取首个命中」改为「取最长命中；等长取商户名中位置最早」，
  使「天猫清芬店」里 pos0 的「天猫」胜过 pos2 的「清芬」。仅影响多关键词等长命中的边界场景。
- **`stats.py`**：`by_location_cafeteria` 分类标签不再写死「食堂」，改为按金额取该分组主导交易分类
  （天猫校园 → 超市购物，其余食堂 → 食堂）
- **`app.js`**：食堂模式 `catName` 改用后端返回的 `l.category`
- **数据重建**：用 `db.rebuild_categories` 重算，库中 10 条天猫交易（清芬店 9 + 观畴店 1）
  由「食堂」改为「超市购物」；看板分类「超市购物」新增 10 笔 ¥93.5，「食堂」相应减少

---


## 项目结构参考

```
Eat_stat/
├── app.py              # Flask 后端，REST API
├── auth.py             # Playwright 登录，Cookie 捕获
├── scraper.py          # 校园卡 API 爬虫，AES 解密
├── db.py               # SQLite 数据层（owner 分帐户）
├── config.py           # 配置管理（idserial, cookie, last_sync_date）
├── stats.py            # 统计计算（总览 / 时间 / 分类 / 地点）
├── categorize.py       # 商户分类器
├── mock_data.py        # 模拟数据生成
├── generate_startbat.py # 生成 GBK 编码的 start.bat
├── start.bat           # Windows 启动脚本（GBK 编码）
├── requirements.txt    # 依赖
├── data/
│   ├── eat_stat.db     # SQLite 数据库
│   └── config.json     # 用户配置
└── static/
    ├── index.html      # 前端页面
    ├── app.js          # 前端逻辑
    ├── style.css       # 样式（清华紫配色）
    └── echarts.min.js  # ECharts 图表库
```
