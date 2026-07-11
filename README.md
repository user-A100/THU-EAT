# 🍜 THU Eat — 清华校园卡消费统计

把「清华校园卡」里只能简单翻看的流水，变成一个有**数据看板、成就勋章、地点排行、EATi 个性画像**的本地记账工具。全程数据留在你自己的电脑上。

<p align="center">
  <em>自动抓取 · 零手工录入 · 本地存储 · 清华紫配色</em>
</p>

---

## ✨ 功能

### 📊 数据看板
- **总览卡片**：总支出 / 本月 / 笔均 / 活跃天数 / 最大单笔（支持切换日/月/年） / 统计区间
- **子卡片**：今日 / 本周 / 本月 / 本年支出
- **消费趋势**：按 日/周/月/年 切换的柱状图
- **分类占比**：食堂 / 饮料 / 超市购物 / 生活服务 / 学习… 饼图（分类规则可自定义）
- **日历热力图**：全年每日消费一目了然
- **快速统计**：支持"近 N 天/周/月"快捷筛选 + 自定义日期范围

### 🏆 成就与勋章
- **食堂探索**：16 座清华食堂 + 清青系列 + 校外商户到访记录
- **勋章系统**：消费额度/频次/广度/忠诚度/早起鸟/夜猫子… 多档升级系列
- **EATi 个性画像**：基于消费数据生成你的专属吃货人格（21 种）

### 📍 地点统计
- **窗口 / 食堂双模式**：按窗口详情或按食堂聚合
- **列排序**：支持按金额/笔数/笔均/占比排序
- **搜索筛选**：输入关键词即时过滤

### 📋 消费明细
- 分页浏览 + 关键词搜索 + 分类筛选
- 金额汇总（不受分页影响）
- **CSV 导出**（UTF-8 BOM，Excel 直接打开）

### 🔄 数据同步
- 一键从校园卡系统抓取交易，按 id 去重，重复同步不丢数据
- 支持**增量同步**（自动从上次位置接着拉）
- 自动同步开关（每 30 分钟，状态持久化）
- **Playwright 自动登录**捕获 Cookie（手动/自动两种模式）

### 🎨 体验
- 深浅色模式自动跟随系统
- 响应式布局
- 分帐户数据隔离（多人共用互不干扰）

---

## 🧰 环境要求

### 方式一：直接运行（推荐）
- **Windows** 系统
- 下载 `EatStat.exe`，**无需安装 Python**

### 方式二：源码运行
- **Python 3.8+**
- 首次运行会自动安装依赖

---

## 🚀 快速开始

### 方式一：EXE 双击运行

1. 从 [Releases](../../releases) 下载 `EatStat.exe`
2. 双击运行，浏览器自动打开 `http://127.0.0.1:5000`
3. 关闭命令行窗口即停止程序

> 数据保存在 EXE 同目录下的 `data/` 文件夹。

### 方式二：源码运行

**Windows**：
```bash
双击 start.bat
```

**macOS / Linux**：
```bash
pip install -r requirements.txt
python app.py
# 浏览器打开 http://127.0.0.1:5000
```

---

## 📖 首次使用

打开后是空的，两条路：

### A. 先看效果（无需 Cookie）
切到「**配置与同步**」→「**加载示例数据**」→ 回到「数据看板」即可看到完整统计。

### B. 接入真实校园卡数据

1. 「**配置与同步**」页填好**学号**和 **Cookie**（获取方法见下方）
2. 设置日期范围（首次建议设早一点），点「**开始同步**」
3. 同步完成 → 切回「数据看板」查看

以后更新数据：打开程序 →「配置与同步」→「开始同步」（日期留空则自动增量）。

---

## 🍪 获取 Cookie

### 方法一：一键登录（推荐）
「配置与同步」页点「**🔐 登录清华**」，在弹出的浏览器里走 SSO 登录（含双因子），程序自动捕获会话。**无需手动复制。**

> 需要 Playwright 环境。EXE 用户需先安装：`pip install playwright && playwright install chromium`

### 方法二：手动复制
1. 浏览器打开 https://card.tsinghua.edu.cn/ 并登录
2. <kbd>F12</kbd> → **Network** → 点任意 `card.tsinghua.edu.cn` 请求
3. **Headers** → **Request Headers** → 复制 `Cookie:` 整行值
4. 粘贴到程序的 Cookie 输入框，保存

> Cookie 会过期（几小时到一天），过期后重新获取即可，历史数据不丢失。

---

## 🗂️ 项目结构

```
THU-EAT/
├── app.py              # Flask 后端，REST API
├── auth.py             # Playwright 登录 & Cookie 捕获
├── scraper.py          # 校园卡 API 爬虫，AES 解密
├── db.py               # SQLite 数据层（分帐户隔离）
├── config.py           # 配置管理
├── stats.py            # 统计计算 & 勋章系统
├── categorize.py       # 商户名 → 消费分类
├── mock_data.py        # 模拟数据生成器
├── eat_stat.spec       # PyInstaller 打包配置
├── start.bat           # Windows 启动脚本
├── requirements.txt    # Python 依赖
├── data/               # 运行时数据（自动创建）
│   ├── eat_stat.db     # SQLite 数据库
│   └── config.json     # 用户配置
└── static/
    ├── index.html      # 前端页面
    ├── app.js          # 前端逻辑
    ├── style.css       # 样式（清华紫配色）
    ├── echarts.min.js  # ECharts 图表库（本地内置）
    └── pic/            # EATi 个性画像图片
```

---

## 🏗️ 工作原理

```
浏览器 (ECharts · 前端 SPA)
   ↕  HTTP (仅本机 127.0.0.1:5000)
Flask 后端 (app.py)
   ├── scraper.py    带 Cookie 请求 card.tsinghua.edu.cn，AES-ECB 解密
   ├── auth.py       Playwright 浏览器自动化 → SSO 登录 → 捕获 Cookie
   ├── db.py         SQLite 存储 / 去重 / 查询 / 分类规则
   ├── categorize.py 关键词匹配 → 消费分类
   ├── stats.py      按时间/地点/分类/总览聚合 + 勋章计算
   └── mock_data.py  模拟数据（便于无 Cookie 体验）
```

接口与解密方式参考 [THU-Annual-Eat](https://github.com/leverimmy/THU-Annual-Eat) 与 [thu-info-lib](https://github.com/thu-info-community/thu-info-lib)，致谢。

---

## 🔒 隐私与数据

- 所有数据保存在本机 `data/` 目录，**不上传任何服务器**
- 程序仅在你点击「同步」时访问 `card.tsinghua.edu.cn` 拉取**你自己的**数据
- `data/` 已加入 `.gitignore`，切勿将 Cookie 或学号提交到代码仓库

---

## ❓ 常见问题

<details>
<summary><b>同步报错「cookie 未生效或已过期」</b></summary>
Cookie 过期了。重新登录 card.tsinghua.edu.cn，获取新的 Cookie 值，保存后再同步。
</details>

<details>
<summary><b>同步报错「解密失败，接口加密方式可能已变更」</b></summary>
学校系统接口更新了。需要根据实际返回数据调整 <code>scraper.py</code> 的解析逻辑。欢迎提 Issue。
</details>

<details>
<summary><b>端口 5000 被占用</b></summary>
可能有另一个实例在跑。关掉之前的命令行窗口，或修改 <code>app.py</code> 末尾的端口号。
</details>

<details>
<summary><b>分类不准？</b></summary>
到「分类规则」页增删关键词 → 分类映射，再点「用最新规则重新分类全部数据」。
</details>

<details>
<summary><b>图表空白？</b></summary>
图表库已内置在 <code>static/echarts.min.js</code>，无需联网。如仍空白，按 F12 查看浏览器控制台报错。
</details>

<details>
<summary><b>想清空重来？</b></summary>
「配置与同步」→「清空所有数据」。分类规则会保留。
</details>

<details>
<summary><b>EXE 版怎么用登录功能？</b></summary>
EXE 没打包 Playwright 浏览器。如需一键登录，请另外安装 Python + Playwright，或用「手动复制 Cookie」方式。
</details>

---

## 🛠️ 开发

```bash
# 安装依赖
pip install -r requirements.txt

# 运行
python app.py

# 打包 EXE
pip install pyinstaller
pyinstaller eat_stat.spec --noconfirm
```

- `start.bat` 是 **GBK 编码**，不要用编辑器直接改。修改 `generate_startbat.py` 后运行它重新生成。
- 抓取与解密逻辑在 `scraper.py`（接口变更时调整此处）。
- 分类规则在 `db.py` 的 `DEFAULT_RULES` 及前端「分类规则」页。

---

## ⚖️ 合规说明

本程序用于查询**本人**校园卡消费记录、做个人记账统计，属合理个人用途。请遵守学校相关规定，不要用于获取他人数据或任何破坏系统正常运行的行为。

---

## 📄 License

MIT
