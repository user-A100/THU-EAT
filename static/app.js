"use strict";
/* Eat_stat 前端：数据加载 + ECharts 图表 + 交互。
   颜色遵循 dataviz 方法论：分类用固定色相映射（不随排名变），单系列趋势/排行用 slot-1。 */

const API = (path, opts) => fetch(path, opts).then(r => r.json());

// ---------- 主题色（从 CSS 变量读取，随深浅模式切换） ----------
const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function themeColors() {
  return {
    ink: cssVar("--ink-primary"),
    secondary: cssVar("--ink-secondary"),
    muted: cssVar("--ink-muted"),
    gridline: cssVar("--gridline"),
    baseline: cssVar("--baseline"),
    accent: cssVar("--accent"),
    surface: cssVar("--surface"),
    series: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => cssVar(`--series-${i}`)),
  };
}
// 分类 → 固定色相槽（稳定映射，不随筛选/排名变化）
const CAT_SLOT = { "食堂": 0, "饮料": 7, "冷饮": 7, "超市": 2, "生活服务": 3, "学习": 4, "交通": 6, "娱乐": 1 };
const _dynamicCat = {};
let _nextSlot = 6;
function catColor(name) {
  const c = themeColors();
  if (name in CAT_SLOT) return c.series[CAT_SLOT[name]];
  if (name === "其他" || name === "合计") return c.series[5]; // 红，留给"其他"
  if (!(name in _dynamicCat)) _dynamicCat[name] = (_nextSlot++) % 8;
  return c.series[_dynamicCat[name]];
}

// ---------- 全局状态 ----------
const state = { start: "", end: "", gran: "month", page: 0, pageSize: 8, total: 0, maxType: "single", locGroup: "window", locSort: { key: "total", dir: "desc" }, locPage: 0, locPageSize: 25, trendGran: "month", trendN: 10 };
const charts = {};

// ---------- 工具 ----------
const $ = (id) => document.getElementById(id);
function toast(msg, kind = "") {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast " + kind;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), 2600);
}
// 主题化确认对话框，返回 Promise<boolean>
function confirmDialog(opts) {
  opts = opts || {};
  var icon = opts.icon || "❓";
  var title = opts.title || "提示";
  var msg = opts.message || "";
  var okText = opts.okText || "确定";
  var cancelText = opts.cancelText || "取消";
  var okKind = opts.okKind || "primary";  // primary | danger
  return new Promise(function (resolve) {
    var overlay = $("modal");
    var box = overlay.querySelector(".modal-box");
    if (box) box.classList.remove("wide");
    $("modal-icon").textContent = icon;
    $("modal-title").textContent = title;
    $("modal-msg").textContent = msg;
    var okBtn = $("modal-ok");
    var cancelBtn = $("modal-cancel");
    cancelBtn.style.display = "";
    okBtn.textContent = okText;
    cancelBtn.textContent = cancelText;
    okBtn.className = "btn modal-ok " + (okKind === "danger" ? "danger" : "primary");
    overlay.classList.remove("hidden");
    function cleanup(result) {
      overlay.classList.add("hidden");
      okBtn.removeEventListener("click", onOk);
      cancelBtn.removeEventListener("click", onCancel);
      overlay.removeEventListener("click", onOverlay);
      document.removeEventListener("keydown", onKey);
      resolve(result);
    }
    function onOk() { cleanup(true); }
    function onCancel() { cleanup(false); }
    function onOverlay(e) { if (e.target === overlay) cleanup(false); }
    function onKey(e) { if (e.key === "Escape") cleanup(false); if (e.key === "Enter") cleanup(true); }
    okBtn.addEventListener("click", onOk);
    cancelBtn.addEventListener("click", onCancel);
    overlay.addEventListener("click", onOverlay);
    document.addEventListener("keydown", onKey);
    okBtn.focus();
  });
}
const fmtMoney = (n) => "¥" + (Number(n) || 0).toFixed(2);
const fmtDate = (s) => (s || "").replace("T", " ").slice(0, 16);

// 主题化信息展示对话框（自定义 HTML 内容 + 单个关闭按钮）
function showInfoModal(opts) {
  opts = opts || {};
  var overlay = $("modal");
  var box = overlay.querySelector(".modal-box");
  if (box) box.classList.toggle("wide", !!opts.wide);
  $("modal-icon").textContent = opts.icon || "ℹ️";
  $("modal-title").textContent = opts.title || "";
  $("modal-msg").innerHTML = opts.html || "";
  var okBtn = $("modal-ok");
  var cancelBtn = $("modal-cancel");
  cancelBtn.style.display = "none";
  okBtn.textContent = opts.okText || "关闭";
  okBtn.className = "btn modal-ok primary";
  overlay.classList.remove("hidden");
  function close() {
    overlay.classList.add("hidden");
    cancelBtn.style.display = "";
    okBtn.removeEventListener("click", close);
    overlay.removeEventListener("click", onOverlay);
    document.removeEventListener("keydown", onKey);
  }
  function onOverlay(e) { if (e.target === overlay) close(); }
  function onKey(e) { if (e.key === "Escape") close(); }
  okBtn.addEventListener("click", close);
  overlay.addEventListener("click", onOverlay);
  document.addEventListener("keydown", onKey);
  okBtn.focus();
}

// ---------- 食堂地图灯箱 ----------
(function () {
  var m = $("map-lightbox"), close = $("map-close"), btn = $("map-btn");
  if (!m || !btn) return;
  btn.addEventListener("click", function () { m.classList.remove("hidden"); });
  function closeMap() { m.classList.add("hidden"); }
  if (close) close.addEventListener("click", closeMap);
  m.addEventListener("click", function (e) { if (e.target === m) closeMap(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeMap(); });
})();

// ---------- 标签切换 ----------
function switchTab(tabName) {
  var btn = document.querySelector('.tab[data-tab="' + tabName + '"]');
  if (btn) btn.click();
  else {
    // 配置/规则等无顶部 tab 的页面，手动切换
    document.querySelectorAll(".page").forEach((p) => p.classList.add("hidden"));
    $("page-" + tabName).classList.remove("hidden");
  }
}
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    document.querySelectorAll(".page").forEach((p) => p.classList.add("hidden"));
    $("page-" + btn.dataset.tab).classList.remove("hidden");
    if (btn.dataset.tab === "locations") loadLocations();
    if (btn.dataset.tab === "achievements") { loadBadges(); loadWheel(); loadAchievements(); }
    if (btn.dataset.tab === "dashboard") { fillCategoryFilter(); refresh(); }
    if (btn.dataset.tab === "ebti") { EBTI.currentQ = 0; EBTI.answers = []; _ebtiRenderQuestion(); }
  });
});
// logo 点击回到数据看板（事件委托，图标和文字都可点）
document.addEventListener("click", function (e) {
  var brand = e.target.closest && e.target.closest(".brand");
  if (brand) switchTab("dashboard");
});

// 用户菜单：点击头像展开/收起，点击下拉项切换页面
(function () {
  var uBtn = $("user-btn");
  var uDrop = $("user-dropdown");
  // 头像持久化
  var savedAvatar = localStorage.getItem("thueat_avatar") || "👤";
  uBtn.textContent = savedAvatar;

  if (uBtn && uDrop) {
    uBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      uDrop.classList.toggle("hidden");
    });
    document.addEventListener("click", function () {
      uDrop.classList.add("hidden");
    });
    uDrop.addEventListener("click", function (e) { e.stopPropagation(); });
    // 头像选择
    uDrop.querySelectorAll(".avatar-opt").forEach(function (opt) {
      opt.addEventListener("click", function () {
        var emoji = this.dataset.emoji;
        uBtn.textContent = emoji;
        localStorage.setItem("thueat_avatar", emoji);
        // 高亮当前选中
        uDrop.querySelectorAll(".avatar-opt").forEach(function (o) { o.classList.remove("active"); });
        this.classList.add("active");
      });
    });
    // 初始化高亮
    var cur = uDrop.querySelector('.avatar-opt[data-emoji="' + savedAvatar + '"]');
    if (cur) cur.classList.add("active");
    uDrop.querySelectorAll(".dropdown-item").forEach(function (item) {
      item.addEventListener("click", function () {
        var tab = this.dataset.tab;
        document.querySelectorAll(".tab").forEach(function (b) { b.classList.remove("active"); });
        document.querySelectorAll(".page").forEach(function (p) { p.classList.add("hidden"); });
        $("page-" + tab).classList.remove("hidden");
        uDrop.classList.add("hidden");
        if (tab === "sync") loadConfig();
        if (tab === "rules") loadRules();
      });
    });
  }
})();

// ---------- 看板：加载与渲染 ----------
async function refresh() {
  const q = new URLSearchParams();
  if (state.start) q.set("start", state.start);
  if (state.end) q.set("end", state.end);
  const qs = q.toString();
  const base = qs ? "?" + qs : "";

  var sum, cat, heat, time, detail;
  try {
    [sum, cat, heat, time, detail] = await Promise.all([
      API("/api/stats/summary" + base),
      API("/api/stats/by_category" + base),
      API("/api/stats/heatmap" + base),
      API("/api/stats/by_time" + base + (base ? "&" : "?") + "granularity=" + state.trendGran),
      API("/api/transactions" + base + (base ? "&" : "?") + "limit=1"),
    ]);
  } catch (e) {
    console.error("refresh error:", e);
    toast("数据加载失败，请检查后端服务", "error");
    return;
  }
  if (!sum) return;
  renderCards(sum);
  state._lastSummary = sum;
  if (time) renderTime(time);
  if (cat) renderCategory(cat);
  if (heat) {
    // 填充年份下拉
    var years = [];
    heat.forEach(function (d) { var y = d[0].slice(0, 4); if (years.indexOf(y) === -1) years.push(y); });
    years.sort();
    var hy = $("heat-year");
    if (hy && hy.options.length <= 1) {
      years.forEach(function (y) {
        var opt = document.createElement("option");
        opt.value = y; opt.textContent = y + " 年";
        hy.appendChild(opt);
      });
    }
    state._heatData = heat;
    var mode = (hy && hy.value) || "12m";
    renderHeatmap(heat, mode);
  }
  if (detail) {
    state.total = detail.count || 0;
    var dc = $("detail-count");
    var ds = $("detail-sum");
    var dr = $("detail-recharge");
    if (dc) dc.textContent = "（共 " + (detail.count || 0) + " 条）";
    if (ds) ds.textContent = "· 消费 " + fmtMoney(detail.total_amount || 0);
    if (dr) dr.textContent = "· 充值 " + fmtMoney(detail.recharge_amount || 0);
  }
  loadDetail();
}

function renderCards(s) {
  // 12 列网格：上下两行精确对齐
  // Row1: [总支出 4/12] [活跃天数 2/12] [最大支出(可切换) 3/12] [统计区间 3/12]
  // Row2: [今日 3/12] [本周 3/12] [本月 3/12] [本年 3/12]

  const maxType = state.maxType || "single";
  let maxVal, maxSub;
  if (maxType === "day") {
    maxVal = fmtMoney(s.max_day.amount);
    maxSub = `${s.max_day.date} · ${s.max_day.count} 笔`;
  } else if (maxType === "month") {
    maxVal = fmtMoney(s.max_month.amount);
    maxSub = `${s.max_month.month} · ${s.max_month.count} 笔`;
  } else if (maxType === "year") {
    maxVal = fmtMoney(s.max_year.amount);
    maxSub = `${s.max_year.year} · ${s.max_year.count} 笔`;
  } else {
    maxVal = fmtMoney(s.max.amount);
    maxSub = (s.max.mername || "—");
  }

  // 日期标注：今日=几月几日周几, 本周=W周数, 本月=几月, 本年=年份
  var now = new Date();
  var weekdays = ["日","一","二","三","四","五","六"];
  var todayLabel = (now.getMonth()+1) + "月" + now.getDate() + "日 周" + weekdays[now.getDay()];
  // ISO week number
  var d = new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
  d.setUTCDate(d.getUTCDate() + 3 - (d.getUTCDay() + 6) % 7);
  var w1 = new Date(Date.UTC(d.getUTCFullYear(), 0, 4));
  var weekNum = Math.round(((d - w1) / 86400000 - 3 + (w1.getUTCDay() + 6) % 7) / 7);
  var weekLabel = "W" + weekNum;
  var monthLabel = (now.getMonth()+1) + "月";
  var yearLabel = String(now.getFullYear());

  const row1 = [
    { k: "总支出", v: fmtMoney(s.total), sub: `${s.count} 笔 · 笔均 ${fmtMoney(s.avg)}`, cls: "wide-3" },
    { k: "活跃天数", v: s.days + " 天", sub: `日均 ${fmtMoney(s.daily_avg)}`, cls: "wide-3" },
    { k: "max-selector", cls: "wide-3", raw: true },
    { k: "统计区间", v: `${s.date_from || "—"} ~ ${s.date_to || "—"}`, sub: `共 ${s.days} 天`, cls: "wide-3", vCls: "date-range" },
  ];
  const row2 = [
    { k: "今日支出", v: fmtMoney(s.today || 0), sub: todayLabel, cls: "wide-3" },
    { k: "本周支出", v: fmtMoney(s.this_week || 0), sub: weekLabel, cls: "wide-3" },
    { k: "本月支出", v: fmtMoney(s.this_month || 0), sub: monthLabel, cls: "wide-3" },
    { k: "本年支出", v: fmtMoney(s.this_year || 0), sub: yearLabel, cls: "wide-3" },
  ];

  // 点击跳转属性（日/月/年 可点击跳转下方明细）
  var jumpAttr = "";
  if (maxType === "day") {
    jumpAttr = ' data-jump="' + s.max_day.date + '" data-jump-gran="day" title="点击查看当日明细"';
  } else if (maxType === "month") {
    jumpAttr = ' data-jump="' + s.max_month.month + '" data-jump-gran="month" title="点击查看当月明细"';
  } else if (maxType === "year") {
    jumpAttr = ' data-jump="' + s.max_year.year + '" data-jump-gran="year" title="点击查看当年明细"';
  }

  var maxSelectHTML = '<div class="card wide-3">' +
    '<div class="k-row">' +
      '<span class="label-text">最大支出</span>' +
      '<select class="max-select" id="max-type-select" onchange="window._switchMaxType(this.value)">' +
        '<option value="single"' + (maxType === "single" ? " selected" : "") + '>单笔</option>' +
        '<option value="day"' + (maxType === "day" ? " selected" : "") + '>日</option>' +
        '<option value="month"' + (maxType === "month" ? " selected" : "") + '>月</option>' +
        '<option value="year"' + (maxType === "year" ? " selected" : "") + '>年</option>' +
      '</select>' +
    '</div>' +
    '<div class="v' + (jumpAttr ? ' jumpable' : '') + '"' + jumpAttr + ' onclick="window._jumpFromMax(this)">' + maxVal + '</div>' +
    '<div class="sub">' + maxSub + '</div>' +
  '</div>';

  $("cards").innerHTML =
    row1.map(function(c) {
      if (c.raw) return maxSelectHTML;
      return '<div class="card ' + (c.cls || "") + '">' +
        '<div class="k">' + c.k + '</div>' +
        '<div class="v' + (c.vCls ? " " + c.vCls : "") + '">' + c.v + '</div>' +
        (c.sub ? '<div class="sub">' + c.sub + '</div>' : "") +
      '</div>';
    }).join("") +
    '<div class="card-row-2">' +
    row2.map(function(c) {
      return '<div class="card ' + (c.cls || "") + '">' +
        '<div class="k">' + c.k + '</div>' +
        '<div class="v">' + c.v + '</div>' +
        (c.sub ? '<div class="sub">' + c.sub + '</div>' : "") +
      '</div>';
    }).join("") +
    '</div>';
}

function axisStyle() {
  const c = themeColors();
  return {
    color: c.secondary,
    textStyle: { color: c.secondary },
    axisLine: { lineStyle: { color: c.baseline } },
    axisTick: { show: false },
    splitLine: { lineStyle: { color: c.gridline } },
  };
}
function tooltipStyle() {
  const c = themeColors();
  return {
    backgroundColor: c.surface, borderColor: c.baseline, borderWidth: 1,
    textStyle: { color: c.ink },
    valueFormatter: (v) => fmtMoney(v),
  };
}

function renderTime(data) {
  const n = state.trendN || 10;
  const sliced = data.length > n ? data.slice(data.length - n) : data;
  const c = themeColors();
  const ch = charts.time || (charts.time = echarts.init($("chart-time")));
  ch.setOption({
    grid: { left: 50, right: 24, top: 24, bottom: 56, containLabel: true },
    tooltip: { trigger: "axis", ...tooltipStyle() },
    xAxis: { type: "category", data: sliced.map((d) => d.key), ...axisStyle(), axisLabel: { ...axisStyle().axisLabel, rotate: sliced.length > 10 ? 40 : 0 } },
    yAxis: { type: "value", ...axisStyle(), axisLabel: { color: c.muted } },
    series: [{
      type: "bar", data: sliced.map((d) => d.total), barMaxWidth: 38, itemStyle: { color: c.series[0], borderRadius: [4, 4, 0, 0] },
      label: { show: sliced.length <= 12, position: "top", color: c.secondary, formatter: (p) => p.value.toFixed(0), fontSize: 11 },
    }],
  });
  // 点击柱 → 跳转该时段消费明细
  ch.off("click");
  ch.on("click", function (params) {
    var key = params.name;
    if (!key) return;
    var start, end;
    var gran = state.trendGran || "month";
    if (gran === "day") { start = end = key; }
    else if (gran === "week") { var parts = key.split("-W"); var y = parseInt(parts[0]), w = parseInt(parts[1]); var d = new Date(y, 0, 1 + (w - 1) * 7); d.setDate(d.getDate() - d.getDay() + 1); start = d.toISOString().slice(0, 10); d.setDate(d.getDate() + 6); end = d.toISOString().slice(0, 10); }
    else if (gran === "month") { start = key + "-01"; var m = parseInt(key.split("-")[1]); var yr = parseInt(key.split("-")[0]); end = key + "-" + new Date(yr, m, 0).getDate(); }
    else if (gran === "year") { start = key + "-01-01"; end = key + "-12-31"; }
    _jumpDetail(start, end);
  });
}

function renderCategory(data) {
  const items = data.filter((d) => d.category !== "合计");
  const c = themeColors();
  const ch = charts.cat || (charts.cat = echarts.init($("chart-cat")));
  ch.setOption({
    tooltip: { trigger: "item", ...tooltipStyle(), formatter: (p) => `${p.name}<br/>${fmtMoney(p.value)} (${p.percent}%)` },
    legend: { bottom: 0, type: "scroll", textStyle: { color: c.secondary } },
    series: [{
      type: "pie", radius: ["42%", "68%"], center: ["50%", "44%"],
      avoidLabelOverlap: true,
      itemStyle: { borderColor: c.surface, borderWidth: 2 },
      label: { color: c.secondary, formatter: "{b}\n{d}%" },
      data: items.map((d) => ({ name: d.category, value: d.total, itemStyle: { color: catColor(d.category) } })),
    }],
  });
  // 点击饼块 → 跳转该分类消费明细
  ch.off("click");
  ch.on("click", function (params) {
    var cat = params.name;
    if (!cat || cat === "合计") return;
    var catEl = $("d-category");
    if (catEl) catEl.value = cat;
    state.page = 0;
    loadDetail();
    var table = $("table");
    if (table) table.scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

// 跳转明细（设日期范围+加载）
function _jumpDetail(start, end) {
  // 仅设置明细栏自定义范围并跳转，不改动顶部主筛选的统计范围
  var ds = $("d-start"), de = $("d-end");
  if (ds) ds.value = toUIDate(start);
  if (de) de.value = toUIDate(end);
  var dToggle = $("d-custom-toggle");
  if (dToggle) dToggle.checked = true;
  var dWrap = $("d-custom-wrap");
  if (dWrap) dWrap.classList.remove("hidden");
  state.page = 0;
  loadDetail();
  var table = $("table");
  if (table) table.scrollIntoView({ behavior: "smooth", block: "start" });
}

// 地点排行柱状图（在地点统计页，可按窗口/食堂切换）
async function renderLocChart() {
  var groupEl = $("loc-chart-group");
  var group = (groupEl && groupEl.value) || "window";
  var q = new URLSearchParams({ group: group });
  if (state.start) q.set("start", state.start);
  if (state.end) q.set("end", state.end);
  var data;
  try { data = await API("/api/stats/locations?" + q.toString()); } catch (e) { return; }
  var isCaf = group === "cafeteria";
  var locs = (data.locations || []).slice(0, isCaf ? 10 : 15);
  var topLabel = $("loc-top-label");
  if (topLabel) topLabel.textContent = "Top " + (isCaf ? 10 : 15);
  var sorted = [...locs].reverse();
  var c = themeColors();
  var ch = charts.locChart || (charts.locChart = echarts.init($("chart-loc")));
  ch.setOption({
    grid: { left: 8, right: 50, top: 10, bottom: 10, containLabel: true },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, ...tooltipStyle() },
    xAxis: { type: "value", axisLabel: { color: c.secondary }, axisLine: { lineStyle: { color: c.baseline } }, axisTick: { show: false }, splitLine: { lineStyle: { color: c.gridline } } },
    yAxis: { type: "category", data: sorted.map(function (d) { return d.name; }), axisLabel: { color: c.ink }, axisLine: { show: false }, axisTick: { show: false } },
    series: [{
      type: "bar", data: sorted.map(function (d) { return d.total; }), barMaxWidth: 20,
      itemStyle: { color: c.series[0], borderRadius: [0, 4, 4, 0] },
      label: { show: true, position: "right", color: c.ink, formatter: function (p) { return fmtMoney(p.value); }, fontSize: 11 },
    }],
  });
  charts.locChart = ch;
  // 左下角统计范围注释
  var note = $("loc-range-note");
  if (note) {
    note.textContent = "当前统计范围：" + (state.start
      ? (toUIDate(state.start) + " ~ " + toUIDate(state.end))
      : "全部数据");
  }
}

// GitHub 风格日历热力图（仪表板，紫色系）
function renderHeatmap(data, mode) {
  var c = themeColors();
  var ch = charts.heat || (charts.heat = echarts.init($("chart-heat")));
  mode = mode || "12m";
  var rangeStart, rangeEnd;
  if (mode === "12m") {
    var now = new Date();
    var end = new Date(now.getFullYear(), now.getMonth() + 1, 0);
    var start = new Date(now.getFullYear(), now.getMonth() - 11, 1);
    rangeStart = start.toISOString().slice(0, 10);
    rangeEnd = end.toISOString().slice(0, 10);
  } else {
    rangeStart = mode + "-01-01";
    rangeEnd = mode + "-12-31";
  }
  ch.setOption({
    tooltip: {
      position: "top", borderColor: c.baseline, backgroundColor: c.surface,
      textStyle: { color: c.ink, fontSize: 12 },
      formatter: function (p) { return p.value[0] + "<br/>" + fmtMoney(p.value[1]); }
    },
    visualMap: {
      type: "piecewise", orient: "horizontal", left: "center", bottom: 0,
      itemWidth: 11, itemHeight: 11,
      pieces: [
        { min: 0, max: 20, color: "#f3e8f7" },
        { min: 20, max: 30, color: "#d4b8e8" },
        { min: 30, max: 40, color: "#b28ad8" },
        { min: 40, max: 60, color: "#7a3db8" },
        { min: 60, color: "#5b1e96" },
      ],
      textStyle: { color: c.secondary, fontSize: 10 },
      itemGap: 3,
    },
    calendar: {
      top: 12, left: 26, right: 12, bottom: 48,
      range: [rangeStart, rangeEnd],
      cellSize: 13,
      yearLabel: { show: false },
      monthLabel: { color: c.secondary, fontSize: 10, margin: 2 },
      dayLabel: { color: c.muted, fontSize: 8, firstDay: 1, margin: 2 },
      itemStyle: { borderColor: c.surface, borderWidth: 2.5, borderRadius: 6 },
      splitLine: { lineStyle: { color: c.surface, width: 2.5 } },
    },
    series: [{
      type: "heatmap", coordinateSystem: "calendar",
      data: data,
    }],
  });
  // 点击日期 → 跳转当天消费明细
  ch.off("click");
  ch.on("click", function (params) {
    if (params.value && params.value[0]) {
      _jumpDetail(params.value[0], params.value[0]);
    }
  });
}

// ---------- 明细表 ----------
async function loadDetail() {
  // 明细栏优先读取自身的日期输入（如有值），否则用全局 state
  var ds = $("d-start"), de = $("d-end");
  var dStart = (ds && ds.value.trim()) ? toISODate(ds.value.trim()) : state.start;
  var dEnd = (de && de.value.trim()) ? toISODate(de.value.trim()) : state.end;
  const q = new URLSearchParams({ limit: String(state.pageSize), offset: String(state.page * state.pageSize) });
  if (dStart) q.set("start", dStart);
  if (dEnd) q.set("end", dEnd);
  const kwEl = $("d-keyword");
  const catEl = $("d-category");
  const kw = kwEl ? kwEl.value.trim() : "";
  const cat = catEl ? catEl.value : "";
  if (kw) q.set("keyword", kw);
  if (cat) q.set("category", cat);
  var data;
  try {
    data = await API("/api/transactions?" + q.toString());
  } catch (e) {
    return;
  }
  state.total = data.count || 0;
  const table = $("table");
  if (!table) return;
  const tbody = table.querySelector("tbody");
  if (!tbody) return;
  tbody.innerHTML = data.rows.map(function (r) {
    return '<tr>' +
      '<td>' + fmtDate(r.txdate) + '</td>' +
      '<td>' + (r.mername || "—") + '</td>' +
      '<td class="muted">' + (r.meraddr || "—") + '</td>' +
      '<td><span class="cat-tag" style="border-left:3px solid ' + catColor(r.category) + '">' + (r.category || "") + '</span></td>' +
      '<td class="amount num">' + fmtMoney(r.amount) + '</td>' +
      '<td class="muted">' + (r.summary || "") + '</td>' +
    '</tr>';
  }).join("") || '<tr><td colspan="6" class="muted" style="text-align:center;padding:24px">没有数据</td></tr>';
  const pages = Math.max(1, Math.ceil(state.total / state.pageSize));
  const pageEl = $("d-page");
  if (pageEl) pageEl.textContent = "第 " + (state.page + 1) + " / " + pages + " 页 · 共 " + state.total + " 条";
  // 筛选汇总金额（消费 + 充费分开；若当前筛选=充值则仅显示充值）
  var sumEl = $("detail-sum");
  var rechargeEl = $("detail-recharge");
  if (sumEl) {
    if (cat === "充值") { sumEl.textContent = ""; }
    else { sumEl.textContent = "· 消费 " + fmtMoney(data.total_amount || 0); }
  }
  if (rechargeEl) rechargeEl.textContent = (data.recharge_amount > 0) ? "· 充值 " + fmtMoney(data.recharge_amount) : "";
}

// 明细分类下拉填充
async function fillCategoryFilter() {
  var data;
  try { data = await API("/api/stats/by_category"); } catch (e) { return; }
  const cats = data.filter(function (d) { return d.category !== "合计"; }).map(function (d) { return d.category; });
  // 确保"充值"始终在分类下拉中（充值数据被统计排除，需手动追加）
  if (cats.indexOf("充值") === -1) cats.push("充值");
  const sel = $("d-category");
  if (!sel) return;
  sel.innerHTML = '<option value="">全部分类</option>' +
    cats.map(function (c0) { return '<option value="' + c0 + '">' + c0 + '</option>'; }).join("");
}

// ---------- 数据导出 ----------
(function () {
  const btn = $("btn-export");
  if (btn) btn.addEventListener("click", () => {
    const q = new URLSearchParams();
    if (state.start) q.set("start", state.start);
    if (state.end) q.set("end", state.end);
    const kw = ($("d-keyword") && $("d-keyword").value || "").trim();
    const cat = $("d-category") && $("d-category").value || "";
    if (kw) q.set("keyword", kw);
    if (cat) q.set("category", cat);
    const a = document.createElement("a");
    a.href = "/api/export?" + q.toString();
    a.download = "eat_stat_export.csv";
    a.click();
    toast("正在导出…", "ok");
  });
})();

// 初始化 maxType 默认值
state.maxType = state.maxType || "single";

// 最大支出下拉切换（全局函数，供 inline onchange 调用）
window._switchMaxType = function (val) {
  state.maxType = val;
  if (state._lastSummary) renderCards(state._lastSummary);
};

// 点击最大日/月/年支出 → 跳转下方明细
window._jumpFromMax = function (el) {
  var dateStr = el.getAttribute("data-jump");
  var gran = el.getAttribute("data-jump-gran");
  if (!dateStr || !gran) return;
  var start, end;
  if (gran === "day") {
    start = end = dateStr;
  } else if (gran === "month") {
    var parts = dateStr.split("-");
    start = dateStr + "-01";
    var lastDay = new Date(parseInt(parts[0]), parseInt(parts[1]), 0).getDate();
    end = dateStr + "-" + (lastDay < 10 ? "0" : "") + lastDay;
  } else if (gran === "year") {
    start = dateStr + "-01-01";
    end = dateStr + "-12-31";
  }
  state.start = start;
  state.end = end;
  // 同步到主筛选栏和明细栏的日期输入框
  var uidStart = toUIDate(start);
  var uidEnd = toUIDate(end);
  var fs = $("f-start"), fe = $("f-end");
  if (fs) fs.value = uidStart;
  if (fe) fe.value = uidEnd;
  // 明细栏日期输入框
  var ds = $("d-start"), de = $("d-end");
  if (ds) ds.value = uidStart;
  if (de) de.value = uidEnd;
  // 明细栏也切到自定义模式（显示日期范围）
  var dToggle = $("d-custom-toggle");
  if (dToggle) dToggle.checked = true;
  var dWrap = $("d-custom-wrap");
  if (dWrap) dWrap.classList.remove("hidden");
  // 切换到自定义日期模式
  var toggle = $("f-custom-toggle");
  if (toggle) toggle.checked = true;
  var wrap = $("f-custom-wrap");
  if (wrap) wrap.classList.remove("hidden");
  var hint = $("range-hint");
  if (hint) hint.textContent = uidStart + " ~ " + uidEnd;
  state.page = 0;
  loadDetail();
  // 滚动到明细表
  var table = $("table");
  if (table) table.scrollIntoView({ behavior: "smooth", block: "start" });
};

// ---------- 看板筛选事件 ----------

// 趋势粒度由单位推导：天→日, 周→周, 月→月, 年→年
function unitToGran(unit) {
  return { day: "day", week: "week", month: "month", year: "year" }[unit] || "month";
}

// 日期格式互转：用户界面 yyyy/MM/dd ↔ API yyyy-MM-dd
function toISODate(s) { return (s || "").replace(/\//g, "-"); }
function toUIDate(s) { return (s || "").replace(/-/g, "/"); }

function applyFilter() {
  if ($("f-custom-toggle").checked) {
    // 自定义日期范围：输入为 yyyy/MM/dd，转为 ISO 存储
    state.start = toISODate(($("f-start") && $("f-start").value) || "");
    state.end = toISODate(($("f-end") && $("f-end").value) || "");
    state.gran = "month";
    if ($("range-hint")) $("range-hint").textContent = state.start ? toUIDate(state.start) + " ~ " + toUIDate(state.end) : "全部数据";
  } else {
    const unit = ($("f-unit") && $("f-unit").value) || "month";
    if (unit === "all") {
      state.start = "";
      state.end = "";
      state.gran = "month";
      if ($("f-start")) $("f-start").value = "";
      if ($("f-end")) $("f-end").value = "";
      if ($("range-hint")) $("range-hint").textContent = "全部数据";
    } else {
      const n = parseInt(($("f-num") && $("f-num").value) || 3, 10) || 3;
      const end = new Date();
      const start = new Date(end);
      switch (unit) {
        case "day": start.setDate(start.getDate() - n + 1); break;
        case "week": start.setDate(start.getDate() - n * 7 + 1); break;
        case "month": start.setMonth(start.getMonth() - n); break;
        case "year": start.setFullYear(start.getFullYear() - n); break;
      }
      state.start = start.toISOString().slice(0, 10);
      state.end = end.toISOString().slice(0, 10);
      state.gran = unitToGran(unit);
      if ($("f-start")) $("f-start").value = toUIDate(state.start);
      if ($("f-end")) $("f-end").value = toUIDate(state.end);
      if ($("range-hint")) $("range-hint").textContent = toUIDate(state.start) + " ~ " + toUIDate(state.end);
    }
  }
  // 同步明细栏日期（主筛选变更后，明细栏跟随）
  var ds = $("d-start"), de = $("d-end");
  if (ds) ds.value = "";
  if (de) de.value = "";
  var dc = $("d-custom-toggle");
  if (dc) dc.checked = false;
  var dw = $("d-custom-wrap");
  if (dw) dw.classList.add("hidden");
  state.page = 0;
  refresh();
}

// 明细栏独立的快速日期筛选（仅影响明细表，不改主看板）
function applyDetailFilter() {
  var ds = $("d-start"), de = $("d-end");
  var customToggle = $("d-custom-toggle");
  if (customToggle && customToggle.checked) {
    // 自定义：直接读 d-start/d-end
    if (ds) ds.value = ds.value.trim();
    if (de) de.value = de.value.trim();
  } else {
    var unit = ($("d-unit") && $("d-unit").value) || "month";
    if (unit === "all") {
      if (ds) ds.value = "";
      if (de) de.value = "";
    } else {
      var n = parseInt(($("d-num") && $("d-num").value) || 3, 10) || 3;
      var end = new Date();
      var start = new Date(end);
      switch (unit) {
        case "day": start.setDate(start.getDate() - n + 1); break;
        case "week": start.setDate(start.getDate() - n * 7 + 1); break;
        case "month": start.setMonth(start.getMonth() - n); break;
        case "year": start.setFullYear(start.getFullYear() - n); break;
      }
      if (ds) ds.value = toUIDate(start.toISOString().slice(0, 10));
      if (de) de.value = toUIDate(end.toISOString().slice(0, 10));
    }
  }
  state.page = 0;
  loadDetail();
}

// f-num 现在是 input[type=number]，用 input 事件监听
(function () {
  const numEl = $("f-num");
  if (numEl) numEl.addEventListener("change", applyFilter);
  const unitEl = $("f-unit");
  if (unitEl) unitEl.addEventListener("change", function () {
    if ($("f-num")) $("f-num").style.display = this.value === "all" ? "none" : "";
    applyFilter();
  });
  const allBtn = $("f-all-data");
  if (allBtn) allBtn.addEventListener("click", function () {
    if ($("f-custom-toggle")) $("f-custom-toggle").checked = false;
    if ($("f-custom-wrap")) $("f-custom-wrap").classList.add("hidden");
    if ($("f-unit")) $("f-unit").value = "all";
    if ($("f-num")) $("f-num").style.display = "none";
    state.start = "";
    state.end = "";
    state.gran = "month";
    state.page = 0;
    if ($("range-hint")) $("range-hint").textContent = "全部数据";
    // 同步明细栏：清空自定义范围，显示全部数据
    if ($("d-start")) $("d-start").value = "";
    if ($("d-end")) $("d-end").value = "";
    if ($("d-custom-toggle")) $("d-custom-toggle").checked = false;
    if ($("d-custom-wrap")) $("d-custom-wrap").classList.add("hidden");
    refresh();
    loadDetail();
  });
  const toggleEl = $("f-custom-toggle");
  if (toggleEl) toggleEl.addEventListener("change", function () {
    if ($("f-custom-wrap")) $("f-custom-wrap").classList.toggle("hidden", !this.checked);
    applyFilter();
  });
  const startEl = $("f-start");
  if (startEl) startEl.addEventListener("change", applyFilter);
  const endEl = $("f-end");
  if (endEl) endEl.addEventListener("change", applyFilter);
})();

// 明细表事件（全部 null-safe）
(function () {
  const sBtn = $("d-search");
  if (sBtn) sBtn.addEventListener("click", () => { state.page = 0; applyDetailFilter(); });
  const pBtn = $("d-prev");
  if (pBtn) pBtn.addEventListener("click", () => { if (state.page > 0) { state.page--; loadDetail(); } });
  const nBtn = $("d-next");
  if (nBtn) nBtn.addEventListener("click", () => { state.page++; loadDetail(); });
  const kwEl = $("d-keyword");
  if (kwEl) kwEl.addEventListener("keydown", (e) => { if (e.key === "Enter") { state.page = 0; applyDetailFilter(); } });

  // 明细栏快速日期筛选（与顶部逻辑相同）
  const dNum = $("d-num");
  if (dNum) dNum.addEventListener("change", applyDetailFilter);
  const dUnit = $("d-unit");
  if (dUnit) dUnit.addEventListener("change", function () {
    if ($("d-num")) $("d-num").style.display = this.value === "all" ? "none" : "";
    applyDetailFilter();
  });
  const dToggle = $("d-custom-toggle");
  if (dToggle) dToggle.addEventListener("change", function () {
    if ($("d-custom-wrap")) $("d-custom-wrap").classList.toggle("hidden", !this.checked);
    applyDetailFilter();
  });
  var dsEl = $("d-start"), deEl = $("d-end");
  if (dsEl) dsEl.addEventListener("change", applyDetailFilter);
  if (deEl) deEl.addEventListener("change", applyDetailFilter);

  // 页码跳转
  const jumpBtn = $("d-jump-btn");
  const jumpPage = $("d-jump-page");
  if (jumpBtn && jumpPage) {
    jumpBtn.addEventListener("click", () => {
      const pages = Math.max(1, Math.ceil(state.total / state.pageSize));
      const target = parseInt(jumpPage.value, 10);
      if (isNaN(target) || target < 1 || target > pages) {
        toast("请输入 1 ~ " + pages + " 之间的页码", "error");
        return;
      }
      state.page = target - 1;
      jumpPage.value = "";
      loadDetail();
    });
    jumpPage.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && $("d-jump-btn")) $("d-jump-btn").click();
    });
  }
})();

// 方向键翻页（仅看板标签可见 + 不在输入框中时生效）
document.addEventListener("keydown", function (e) {
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;
  if ($("page-dashboard").classList.contains("hidden")) return;
  var pages = Math.max(1, Math.ceil(state.total / state.pageSize));
  if (e.key === "ArrowLeft") {
    e.preventDefault();
    if (state.page > 0) { state.page--; loadDetail(); }
  } else if (e.key === "ArrowRight") {
    e.preventDefault();
    if (state.page < pages - 1) { state.page++; loadDetail(); }
  }
});

// ---------- 配置 / 同步 ----------
async function loadConfig() {
  const cfg = await API("/api/config");
  $("c-idserial").value = cfg.idserial || "";
  $("c-current").textContent = "当前 servicehall：" + (cfg.has_servicehall ? cfg.servicehall_masked : "未设置");
}
$("c-save").addEventListener("click", async () => {
  const res = await API("/api/config", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ idserial: $("c-idserial").value, servicehall: $("c-servicehall").value }),
  });
  if (res.error) return toast(res.error, "error");
  $("c-current").textContent = "当前 servicehall：" + res.servicehall_masked;
  $("c-servicehall").value = "";
  toast("配置已保存", "ok");
});

// ---------- 登出 ----------
$("c-logout").addEventListener("click", async () => {
  const ok = await confirmDialog({
    icon: "🚪",
    title: "退出登录？",
    message: "将清除已保存的 Cookie 和学号。\n当前帐户数据保留在本地但不再展示。",
    okText: "退出登录",
    okKind: "danger"
  });
  if (!ok) return;
  const res = await API("/api/config", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ servicehall: "", idserial: "" }),
  });
  if (res.error) return toast(res.error, "error");
  $("c-current").textContent = "当前 servicehall：未设置";
  $("c-idserial").value = "";
  $("c-login-status").textContent = "已退出登录，可登录其他账号";
  $("s-status").textContent = "";
  toast("已退出登录", "ok");
  fillCategoryFilter();
});

// 同步快捷按钮
async function doQuickSync(daysBack) {
  const body = {};
  if (daysBack > 0) {
    const d = new Date();
    body.end = d.toISOString().slice(0, 10);
    d.setDate(d.getDate() - daysBack);
    body.start = d.toISOString().slice(0, 10);
  }
  $("s-result").textContent = "同步中…"; $("s-status").textContent = "";
  document.querySelectorAll("#page-sync .btn").forEach(b => b.disabled = true);
  const res = await API("/api/sync", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  document.querySelectorAll("#page-sync .btn").forEach(b => b.disabled = false);
  $("s-result").textContent = "";
  if (res.error) {
    $("s-status").textContent = res.error;
    return toast(res.error, "error");
  }
  $("s-status").textContent = `完成：拉取 ${res.fetched} 条 → 新增 ${res.inserted}，更新 ${res.updated}（区间 ${res.range[0]} ~ ${res.range[1]}）`;
  toast(`同步完成，新增 ${res.inserted} 条`, "ok");
  fillCategoryFilter();
  loadConfig();
}

$("s-sync-all").addEventListener("click", () => doQuickSync(0));      // 空 start，后端默认一年
$("s-sync-year").addEventListener("click", () => doQuickSync(365));
$("s-sync-month").addEventListener("click", () => doQuickSync(30));

// ---------- 自动同步定时器 ----------
let _autoSyncTimer = null;
const AUTO_SYNC_INTERVAL = 30 * 60 * 1000;  // 30 分钟

function startAutoSync() {
  if (_autoSyncTimer) return;
  $("s-auto-status").textContent = "已开启，每 30 分钟自动同步";
  _autoSyncTimer = setInterval(async () => {
    const now = new Date().toLocaleTimeString();
    $("s-auto-status").textContent = `上次同步：${now}`;
    try {
      const res = await API("/api/sync", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),  // 空 = 增量同步
      });
      if (res.error) {
        if (res.code === "cookie_expired" || res.code === "no_credential") {
          $("s-auto-status").textContent = "⚠️ 登录已过期，请重新登录";
          toast("登录会话已过期，请重新登录", "error");
          stopAutoSync();
        } else {
          $("s-auto-status").textContent = `同步失败：${res.error}`;
        }
      } else {
        $("s-auto-status").textContent = `自动同步完成（${now}）：+${res.inserted} 条`;
        fillCategoryFilter();
        // 如果用户在看板页面，静默刷新
        if (!$("page-dashboard").classList.contains("hidden")) {
          refresh();
        }
      }
    } catch (e) {
      $("s-auto-status").textContent = "同步异常";
    }
  }, AUTO_SYNC_INTERVAL);
}

function stopAutoSync() {
  if (_autoSyncTimer) { clearInterval(_autoSyncTimer); _autoSyncTimer = null; }
  $("s-auto-status").textContent = "";
}

$("s-auto-sync").addEventListener("change", function () {
  if (this.checked) {
    startAutoSync();
    // 持久化：保存到 localStorage
    try { localStorage.setItem("eat_stat_auto_sync", "1"); } catch (e) {}
  } else {
    stopAutoSync();
    try { localStorage.removeItem("eat_stat_auto_sync"); } catch (e) {}
  }
});

// 页面加载时恢复自动同步状态
(function restoreAutoSync() {
  try {
    if (localStorage.getItem("eat_stat_auto_sync") === "1") {
      $("s-auto-sync").checked = true;
      startAutoSync();
    }
  } catch (e) {}
})();

$("m-load").addEventListener("click", async () => {
  const res = await API("/api/mock", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  if (res.error) return toast(res.error, "error");
  toast(`已加载 ${res.inserted} 条示例数据`, "ok");
  fillCategoryFilter();
  refresh();  // 立即刷新看板
});
$("m-reset").addEventListener("click", async () => {
  const ok = await confirmDialog({
    icon: "⚠️",
    title: "清空所有数据？",
    message: "此操作不可撤销，将删除全部交易记录。\n（分类规则会保留）",
    okText: "清空数据",
    okKind: "danger"
  });
  if (!ok) return;
  const res = await API("/api/reset", { method: "POST" });
  if (res.error) return toast(res.error, "error");
  toast("已清空数据", "ok");
});

// ---------- 地点统计 ----------
let _allLocations = [];  // 缓存全部商户数据，供搜索和自动补全

async function loadLocations() {
  const q = new URLSearchParams();
  if (state.start) q.set("start", state.start);
  if (state.end) q.set("end", state.end);
  const groupEl = $("loc-group");
  const group = (groupEl && groupEl.value) || "window";
  state.locGroup = group;
  q.set("group", group);
  renderLocChart();  // 同时渲染柱状图（独立数据，不受表格切换影响）
  const qs = q.toString();
  const base = qs ? "?" + qs : "";
  try {
    const data = await API("/api/stats/locations" + base);
    _allLocations = data.locations || [];
  } catch (e) {
    _allLocations = [];
  }
  const dl = $("loc-datalist");
  if (dl) dl.innerHTML = _allLocations.map(function (l) { return '<option value="' + l.name + '">' + (l.addr || "") + '</option>'; }).join("");
  state.locPage = 0;
  renderLocationTable(_allLocations);
}

// 列排序：可按 name / window_count / count / avg / total / pct 排序
let _locLastSet = [];  // 当前正在渲染的集合（全量或搜索过滤后），供点击表头重排
function sortLocations(arr) {
  var s = state.locSort || { key: "total", dir: "desc" };
  var dir = s.dir === "asc" ? 1 : -1;
  return arr.slice().sort(function (a, b) {
    var va, vb;
    if (s.key === "name") {
      va = (a.name || "").toLowerCase(); vb = (b.name || "").toLowerCase();
    } else {
      va = Number(a[s.key]) || 0; vb = Number(b[s.key]) || 0;
    }
    if (va < vb) return -dir;
    if (va > vb) return dir;
    return 0;
  });
}

// 生成可点击表头：data-sort 标记可排序列，当前排序列显示 ▲/▼
function locHeaders(isCafeteria) {
  var s = state.locSort;
  function th(label, key, extra) {
    var cls = (extra ? extra + " " : "") + (key ? "sortable" : "");
    var caret = (key && s && s.key === key) ? (s.dir === "asc" ? " ▲" : " ▼") : "";
    return '<th class="' + cls + '"' + (key ? ' data-sort="' + key + '"' : "") + ">" + label + caret + "</th>";
  }
  if (isCafeteria) {
    return "<tr>" + th("#") + th("食堂", "name") + th("窗口数", "window_count", "ctr") + th("分类") +
      th("笔数", "count", "num") + th("笔均", "avg", "num") + th("总额", "total", "num") + th("占比", "pct", "num") + "</tr>";
  }
  return "<tr>" + th("#") + th("商户", "name") + th("地址") + th("分类") +
    th("笔数", "count", "num") + th("笔均", "avg", "num") + th("总额", "total", "num") + th("占比", "pct", "num") + "</tr>";
}

function renderLocationTable(locs) {
  _locLastSet = locs;
  const table = $("loc-table");
  if (!table) return;
  const tbody = table.querySelector("tbody");
  const thead = table.querySelector("thead");
  if (!tbody || !thead) return;
  const isCafeteria = state.locGroup === "cafeteria";
  const sorted = sortLocations(locs);
  // 分页
  state.locPage = Math.min(state.locPage, Math.max(0, Math.ceil(sorted.length / state.locPageSize) - 1));
  var pageStart = state.locPage * state.locPageSize;
  var pageRows = sorted.slice(pageStart, pageStart + state.locPageSize);
  var totalPages = Math.max(1, Math.ceil(sorted.length / state.locPageSize));
  var grandTotal = locs.reduce(function (s, l) { return s + l.total; }, 0);
  var countEl = $("loc-count");
  if (countEl) countEl.textContent = "（" + locs.length + " 个" + (isCafeteria ? "食堂" : "商户") + " · 合计 " + fmtMoney(grandTotal) + "）";
  tbody.innerHTML = pageRows.map(function (l, i) {
    var globalIdx = pageStart + i;
    var col2 = isCafeteria ? ((l.window_count || 0) + " 个窗口") : (l.addr || "—");
    var catName = isCafeteria ? (l.category || "食堂") : (l.category || "其他");
    return '<tr>' +
      '<td class="rank-num' + (globalIdx < 3 ? ' rank-' + (globalIdx + 1) : '') + '">' + (globalIdx + 1) + '</td>' +
      '<td>' + l.name + '</td>' +
      '<td class="' + (isCafeteria ? "muted ctr" : "muted") + '">' + col2 + '</td>' +
      '<td><span class="cat-tag" style="border-left:3px solid ' + catColor(catName) + '">' + catName + '</span></td>' +
      '<td class="num">' + l.count + '</td>' +
      '<td class="num">' + fmtMoney(l.avg) + '</td>' +
      '<td class="num" style="font-weight:600">' + fmtMoney(l.total) + '</td>' +
      '<td class="num">' + l.pct + '%</td>' +
    '</tr>';
  }).join("") || '<tr><td colspan="8" class="muted" style="text-align:center;padding:24px">没有数据</td></tr>';
  thead.innerHTML = locHeaders(isCafeteria);
  // 更新分页
  var locPageEl = $("loc-page");
  if (locPageEl) locPageEl.textContent = "第 " + (state.locPage + 1) + " / " + totalPages + " 页 · 共 " + sorted.length + " 条";
}

function doLocationSearch() {
  const kwEl = $("loc-keyword");
  const kw = (kwEl && kwEl.value || "").trim().toLowerCase();
  state.locPage = 0;
  if (!kw) { renderLocationTable(_allLocations); return; }
  const filtered = _allLocations.filter(function (l) {
    return l.name.toLowerCase().indexOf(kw) !== -1 ||
      ((l.addr || "").toLowerCase().indexOf(kw) !== -1);
  });
  renderLocationTable(filtered);
}

// 地点搜索事件 + 食堂/窗口切换（防御性绑定）
(function bindLocationEvents() {
  const searchBtn = $("loc-search");
  const searchInput = $("loc-keyword");
  if (searchBtn && searchInput) {
    searchBtn.addEventListener("click", doLocationSearch);
    searchInput.addEventListener("keydown", function (e) { if (e.key === "Enter") doLocationSearch(); });
    searchInput.addEventListener("input", doLocationSearch);
  }
  const groupSel = $("loc-group");
  if (groupSel) {
    groupSel.addEventListener("change", () => {
      state.locPage = 0;
      loadLocations();
    });
  }
  // 柱状图窗口/食堂切换
  const chartGroupSel = $("loc-chart-group");
  if (chartGroupSel) {
    chartGroupSel.addEventListener("change", function () {
      renderLocChart();
    });
  }
  // 地点统计翻页
  var locPrev = $("loc-prev"), locNext = $("loc-next");
  if (locPrev) locPrev.addEventListener("click", function () { if (state.locPage > 0) { state.locPage--; renderLocationTable(_locLastSet); } });
  if (locNext) locNext.addEventListener("click", function () { state.locPage++; renderLocationTable(_locLastSet); });
  // 点击表头排序（事件委托，thead 元素常驻，innerHTML 重建不影响）
  const locTable = $("loc-table");
  const locThead = locTable && locTable.querySelector("thead");
  if (locThead) {
    locThead.addEventListener("click", function (e) {
      var th = e.target && e.target.closest ? e.target.closest("th[data-sort]") : null;
      if (!th) return;
      var key = th.getAttribute("data-sort");
      var cur = state.locSort || { key: "total", dir: "desc" };
      if (cur.key === key) {
        state.locSort = { key: key, dir: cur.dir === "asc" ? "desc" : "asc" };
      } else {
        // 文本列默认升序，数值列默认降序
        state.locSort = { key: key, dir: key === "name" ? "asc" : "desc" };
      }
      state.locPage = 0;
      renderLocationTable(_locLastSet);
    });
  }
})();

// ---------- 转盘系统 ----------
var _wheelCanteens = [];
var _canteenData = {};  // name -> {icon, visited} for card icons
var _wheelAngle = 0;
var _wheelSpinning = false;

// 渲染某食堂的推荐菜品 + 更新标题
function _showDishes(canteen) {
  var titleEl = $("wheel-side-title");
  var cloudEl = $("wheel-dishes");
  if (titleEl) {
    titleEl.innerHTML = canteen
      ? '📋 <span class="canteen-name">' + canteen + '</span> 推荐菜品'
      : "📋 推荐菜品";
  }
  if (cloudEl) {
    var recs = (canteen && _dishes[canteen]) || [];
    cloudEl.innerHTML = recs.length
      ? recs.map(function (d) { return "<span>" + d + "</span>"; }).join("")
      : "<span>暂无推荐</span>";
  }
}

function initWheel() {
  var canvas = $("wheel-canvas");
  if (!canvas) return;
  var ctx = canvas.getContext("2d");
  var c = themeColors();
  // 颜色池
  var colors = [c.series[0], c.series[2], "#e34948", "#eb6834", c.series[3], c.series[6], "#5ba3d9", "#1baf7a"];
  var cx = 170, cy = 170, r = 155;
  var n = _wheelCanteens.length;
  if (n === 0) return;
  var slice = (2 * Math.PI) / n;
  ctx.clearRect(0, 0, 340, 340);
  // 绘制扇形
  for (var i = 0; i < n; i++) {
    var startAngle = _wheelAngle + i * slice;
    var endAngle = startAngle + slice;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, r, startAngle, endAngle);
    ctx.closePath();
    ctx.fillStyle = colors[i % colors.length];
    ctx.fill();
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = 2;
    ctx.stroke();
    // 文字
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(startAngle + slice / 2);
    ctx.textAlign = "right";
    ctx.fillStyle = "#fff";
    ctx.font = "bold 12px system-ui";
    var text = _wheelCanteens[i].replace("园","");
    ctx.fillText(text, r - 14, 4);
    ctx.restore();
  }
  // 中心圆
  ctx.beginPath();
  ctx.arc(cx, cy, 24, 0, 2 * Math.PI);
  ctx.fillStyle = "#fff";
  ctx.fill();
  ctx.fillStyle = c.accent;
  ctx.font = "bold 13px system-ui";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("THU", cx, cy);
}

// 食堂推荐菜
var _dishes = {
  "紫荆园": ["烧鹅饭","酸菜鱼","麻辣香锅","海南鸡饭","铁板烧","干锅","麻辣烫","米线","荷叶粥","榴莲酥","炸牛奶","水果捞","健身餐","灌汤包","卷饼","竹荪三鲜汤","肉末茄子","醋溜白菜","蚝油生菜","清炒芥蓝","煎饼","小鸡腿肉","自选快餐","冰糖葫芦","南瓜酥","云南米线"],
  "桃李园": ["芝士猪排饭","意大利面","滑蛋炒饭","日式烧鸡饭","热狗","拉面","夜宵小吃","草莓沙冰","蓝柑气泡水","拿铁咖啡","煎蛋","福州拌面","蔬菜沙拉","水煮青菜"],
  "清芬园": ["生煎包","麻辣香锅","烤鸭","重庆小面","豆腐脑","黑豆豆奶","花生浆","南瓜粥","素菜小炒"],
  "听涛园": ["麻辣烫","面食","快餐","豆浆","烤肉拌饭"],
  "丁香园": ["烤肉拌饭","香菇西兰花","包子","特色小吃"],
  "观畴园": ["滑蛋饭","油泼面","拉面","菠菜鸡蛋汤","自选快餐","点菜包房","清青永和"],
  "玉树园": ["韩日套餐","夜宵","盖饭","石锅拌饭"],
  "澜园": ["清炒莴笋叶","教工自选","家常菜"],
  "寓园": ["铁板烧","酱骨架","鲈鱼","馄饨","水木麦园面包"],
  "南园": ["米线","羊杂汤","酸梅汤","淮扬菜"],
  "荷园": ["麻酱拌面","精致自选","点菜"],
  "芝兰园": ["西域风味","清青小火锅","家常菜"],
  "北园": ["教工自选"],
  "家园": ["教工自选"],
  "熙春园": ["中式点菜"],
  "融园": ["金融学院餐厅"],
};

function spinWheel() {
  if (_wheelSpinning || _wheelCanteens.length === 0) return;
  _wheelSpinning = true;
  $("wheel-spin").disabled = true;
  $("wheel-result").textContent = "";
  var n = _wheelCanteens.length;
  var targetIdx = Math.floor(Math.random() * n);
  var slice = (2 * Math.PI) / n;
  var targetAngle = 3 * Math.PI / 2 - targetIdx * slice - slice / 2 + Math.random() * slice * 0.8;
  var totalSpin = 6 * 2 * Math.PI + targetAngle - (_wheelAngle % (2 * Math.PI));
  var duration = 3000 + Math.random() * 1500;
  var startAngle = _wheelAngle;
  var startTime = performance.now();

  function animate(now) {
    var elapsed = now - startTime;
    var progress = Math.min(elapsed / duration, 1);
    var eased = 1 - Math.pow(1 - progress, 3);
    _wheelAngle = startAngle + totalSpin * eased;
    initWheel();
    if (progress < 1) {
      requestAnimationFrame(animate);
    } else {
      _wheelSpinning = false;
      $("wheel-spin").disabled = false;
      var result = _wheelCanteens[targetIdx];
      _showDishes(result);
      $("wheel-result").innerHTML = "🎉 今天去吃 <b>" + result + "</b>！";
    }
  }
  requestAnimationFrame(animate);
}

// 加载转盘数据
async function loadWheel() {
  try {
    var data = await API("/api/stats/achievements");
    var canteens = data.filter(function (d) { return d.cat === "食堂"; });
    _wheelCanteens = canteens.map(function (d) { return d.name; });
    // 缓存图标和状态，供抽卡使用
    _canteenData = {};
    canteens.forEach(function (d) {
      _canteenData[d.name] = { icon: d.icon, visited: d.visited };
    });
  } catch (e) {
    _wheelCanteens = ["紫荆园","桃李园","清芬园","听涛园","丁香园","观畴园","玉树园","澜园","寓园","南园","荷园","芝兰园","北园","家园","熙春园","融园"];
  }
  initWheel();
  // 初始显示第一个食堂的推荐
  if (_wheelCanteens.length) {
    _showDishes(_wheelCanteens[0]);
  }
}

// 模式切换
var _drawMode = "wheel"; // wheel | card
(function () {
  document.querySelectorAll(".mode-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll(".mode-btn").forEach(function (b) { b.classList.remove("active"); });
      this.classList.add("active");
      _drawMode = this.dataset.mode;
      // 显示/隐藏对应区域
      var isCard = _drawMode === "card";
      $("wheel-center").style.display = isCard ? "none" : "";
      $("card-area").classList.toggle("hidden", !isCard);
      $("wheel-result").textContent = "";
      $("wheel-dishes").innerHTML = "";
      // 切换离开卡牌模式时，重置抽卡状态
      if (!isCard) {
        _cardTarget = null;
        _cardShuffling = false;
        $("card-reveal").disabled = true;
      } else {
        // 切换到抽卡模式时，自动生成 3×3 卡片
        startCardDraw();
      }
      // 更新按钮文字
      var label = _drawMode === "card" ? "🃏 开始抽卡" : "🎰 开始转";
      $("wheel-spin").textContent = label;
    });
  });

  // 统一触发按钮
  $("wheel-spin").addEventListener("click", function () {
    if (_drawMode === "card") startCardDraw();
    else spinWheel();
  });

  var revealBtn = $("card-reveal");
  if (revealBtn) revealBtn.addEventListener("click", revealCard);
})();

var _cardTarget = null;
var _cardShuffling = false;

function startCardDraw() {
  if (_cardShuffling) return;
  if (_wheelCanteens.length === 0) { toast("食堂数据加载中，请稍后再试"); return; }
  _cardShuffling = true;
  _cardTarget = null;
  $("card-area").classList.remove("hidden");
  $("wheel-result").textContent = "";
  _showDishes(null);
  $("card-reveal").disabled = true;
  // 随机选 9 张卡（含目标）
  var n = _wheelCanteens.length;
  _cardTarget = _wheelCanteens[Math.floor(Math.random() * n)];
  var pool = [_cardTarget];
  var maxCards = Math.min(9, n);
  while (pool.length < maxCards) {
    var r = _wheelCanteens[Math.floor(Math.random() * n)];
    if (pool.indexOf(r) === -1) pool.push(r);
  }
  // shuffle
  for (var i = pool.length - 1; i > 0; i--) { var j = Math.floor(Math.random() * (i + 1)); var t = pool[i]; pool[i] = pool[j]; pool[j] = t; }
  var grid = $("card-grid");
  grid.innerHTML = pool.map(function (name, idx) {
    var info = _canteenData[name];
    var visited = info && info.visited;
    var icon = visited ? info.icon : "🔒";
    var cls = visited ? "" : " locked-card";
    return '<div class="draw-card' + cls + '" data-idx="' + idx + '" data-name="' + name + '">' +
      '<div class="draw-card-inner">' +
        '<div class="draw-card-front">?</div>' +
        '<div class="draw-card-back"><div class="card-icon">' + icon + '</div><div class="card-name">' + name + '</div></div>' +
      '</div></div>';
  }).join("");
  // 快速切换高亮动画
  var cards = grid.querySelectorAll(".draw-card");
  var highlightIdx = 0;
  var interval = setInterval(function () {
    cards.forEach(function (c) { c.classList.remove("selected"); });
    cards[highlightIdx % cards.length].classList.add("selected");
    highlightIdx++;
  }, 120);
  setTimeout(function () {
    clearInterval(interval);
    cards.forEach(function (c) { c.classList.remove("selected"); });
    _cardShuffling = false;
    $("card-reveal").disabled = false;
  }, 2000);
}

function revealCard() {
  if (_cardShuffling || !_cardTarget) return;
  $("card-reveal").disabled = true;
  var cards = document.querySelectorAll("#card-grid .draw-card");
  // 先翻几张错的
  var flipped = 0;
  cards.forEach(function (card) {
    if (card.dataset.name !== _cardTarget) {
      setTimeout(function () { card.classList.add("flipped"); }, flipped * 200);
      flipped++;
    }
  });
  // 最后翻目标卡
  setTimeout(function () {
    cards.forEach(function (card) {
      if (card.dataset.name === _cardTarget) {
        card.classList.add("flipped", "winner");
        _showDishes(_cardTarget);
        $("wheel-result").innerHTML = "🎉 抽到了 <b>" + _cardTarget + "</b>！";
      }
    });
  }, flipped * 200 + 300);
}

// ---------- 成就系统 ----------
var _manualUnlocks = {};
// 加载手动解锁状态
(function () {
  try { _manualUnlocks = JSON.parse(localStorage.getItem("thueat_manual_unlocks") || "{}"); } catch (e) { _manualUnlocks = {}; }
})();

function _saveManualUnlocks() {
  localStorage.setItem("thueat_manual_unlocks", JSON.stringify(_manualUnlocks));
}

async function _toggleManualUnlock(name) {
  if (_manualUnlocks[name]) {
    // 已解锁 → 确认重新上锁
    var ok = await confirmDialog({
      icon: "🔒",
      title: "重新锁定？",
      message: "确定要重新锁定「" + name + "」吗？\n\n锁定后将恢复到未探索状态。",
      okText: "重新锁定",
      okKind: "danger"
    });
    if (!ok) return;
    delete _manualUnlocks[name];
  } else {
    // 未解锁 → 确认是否已在此就餐
    var ok2 = await confirmDialog({
      icon: "🎉",
      title: "解锁成就",
      message: "你已经去「" + name + "」就餐探索过了吗？\n\n确认后将解锁该成就。",
      okText: "已探索，解锁"
    });
    if (!ok2) return;
    _manualUnlocks[name] = true;
  }
  _saveManualUnlocks();
  loadAchievements();
  loadWheel();
  loadBadges();
}

var _badgeAll = [];
var _badgeExpanded = false;

// 将成就数据合并手动解锁状态（loadAchievements 与 loadBadges 共用）
function _applyManual(data) {
  (data || []).forEach(function (d) {
    if (d.manual && _manualUnlocks[d.name]) {
      d.visited = true;
      d.manualUnlocked = true;
    }
  });
  return data;
}

// 计算各分类收集勋章（依赖成就目录 + 手动解锁），名字活泼有趣
function _computeZhibaBadges(achData) {
  var defs = [
    { cat: "食堂", name: "制霸食堂", icon: "🏫", hint: "食堂" },
    { cat: "清青", name: "清青通吃", icon: "🌿", hint: "清青系列" },
    { cat: "餐厅", name: "校外猎手", icon: "🍽️", hint: "校外餐厅" },
    { cat: "饮品", name: "奶茶鉴定家", icon: "🥤", hint: "饮品店" },
    { cat: "购物", name: "扫货达人", icon: "🛒", hint: "购物点" },
    { cat: "便利店", name: "便利店之友", icon: "🏪", hint: "便利店" },
    { cat: "水果", name: "水果自由", icon: "🍎", hint: "水果店" },
  ];
  var out = [];
  defs.forEach(function (def) {
    var items = achData.filter(function (d) { return d.cat === def.cat; });
    if (!items.length) return;
    var visited = items.filter(function (d) { return d.visited; }).length;
    var earned = visited === items.length;
    var rows = items.map(function (d) {
      return {
        icon: d.visited ? (d.icon || "✅") : "🔒",
        name: d.name,
        desc: d.desc || "",
        status: d.visited ? "done" : "locked",
      };
    });
    out.push({
      series: def.cat + "收集",
      icon: earned ? "🏅" : def.icon,
      name: def.name,
      tier: earned ? "gold" : "",
      level: earned ? 1 : 0,
      maxLevel: 1,
      desc: earned ? "集齐全部 " + items.length + " 个" + def.hint + "！" : "探索全部 " + items.length + " 个" + def.hint,
      progress: visited + "/" + items.length,
      earned: earned,
      family: { title: def.name, progress: visited + "/" + items.length + " 已探索", rows: rows },
    });
  });
  return out;
}

function _badgeCard(b, idx) {
  var tierCls = b.tier ? " tier-" + b.tier : "";
  var cls = "badge-item " + (b.earned ? "earned" : "locked") + tierCls;
  var ribbon = b.earned ? '<div class="badge-ribbon"></div>' : "";
  var icon = b.earned ? b.icon : "🔒";
  // 等级点（升级系列）
  var dots = "";
  if (b.maxLevel > 1) {
    for (var i = 0; i < b.maxLevel; i++) {
      dots += '<span class="dot ' + (i < b.level ? "on" : "") + '"></span>';
    }
    dots = '<div class="badge-dots">' + dots + '</div>';
  }
  var prog = b.progress ? '<div class="badge-progress">' + b.progress + '</div>' : "";
  return '<div class="' + cls + '" data-idx="' + idx + '">' +
    '<div class="badge-medal">' + icon + ribbon + '</div>' +
    '<div class="badge-name">' + b.name + '</div>' +
    dots +
    '<div class="badge-desc">' + b.desc + '</div>' +
    prog +
  '</div>';
}

// 渲染徽章家族弹窗（升级路线 / 分类地点清单）
function _familyRowHtml(r) {
  var tag = r.status === "current" ? '<span class="fam-tag current">当前</span>'
          : r.status === "done" ? '<span class="fam-tag done">已达成 ✓</span>'
          : '<span class="fam-tag locked">未达成</span>';
  var icon = r.status === "locked" ? "🔒" : r.icon;
  return '<div class="fam-row ' + r.status + '">' +
    '<div class="fam-icon">' + icon + '</div>' +
    '<div class="fam-info"><div class="fam-name">' + r.name + '</div>' +
    '<div class="fam-desc">' + r.desc + '</div></div>' +
    tag + '</div>';
}

function _showBadgeFamily(b) {
  var f = b.family;
  if (!f) return;
  var multi = f.rows.length > 6;  // 项数多时改多列展示
  var html = '<div class="fam-progress">当前进度：' + f.progress + '</div>';
  html += '<div class="fam-list' + (multi ? " multi" : "") + '">' + f.rows.map(_familyRowHtml).join("") + '</div>';
  showInfoModal({ icon: b.earned ? b.icon : "🎖️", title: b.name + " · 勋章家族", html: html, wide: multi });
}

function _renderBadges() {
  var shelf = $("badge-shelf");
  if (!shelf) return;
  var all = _badgeAll;
  var earned = all.filter(function (b) { return b.earned; });
  var locked = all.filter(function (b) { return !b.earned; });
  var countEl = $("badge-count");
  if (countEl) countEl.textContent = "（" + earned.length + "/" + all.length + " 已获得）";
  // data-idx 需映射到 _badgeAll 的真实下标
  function idxOf(b) { return _badgeAll.indexOf(b); }
  var html = "";
  if (_badgeExpanded) {
    // 展开：显示全部（已获得 + 未获得，含解锁条件）
    html = all.map(function (b) { return _badgeCard(b, idxOf(b)); }).join("");
    if (locked.length) {
      html += '<div class="badge-item more-tile" id="badge-less">' +
        '<div class="badge-medal">▲</div>' +
        '<div class="badge-name">收起</div>' +
        '<div class="badge-desc">只看已获得 (' + earned.length + ' 枚)</div>' +
      '</div>';
    }
  } else {
    // 收起：只显示已获得勋章
    if (earned.length) {
      html = earned.map(function (b) { return _badgeCard(b, idxOf(b)); }).join("");
    } else {
      html = '<p class="muted" style="grid-column:1/-1;text-align:center;margin:12px 0">还没有获得勋章，点击下方查看解锁条件</p>';
    }
    if (locked.length) {
      html += '<div class="badge-item more-tile" id="badge-more">' +
        '<div class="badge-medal">···</div>' +
        '<div class="badge-name">查看未获得</div>' +
        '<div class="badge-desc">还有 ' + locked.length + ' 枚可解锁</div>' +
        '<div class="badge-progress">点击展开 ▼</div>' +
      '</div>';
    }
  }
  shelf.innerHTML = html;
  var moreBtn = $("badge-more");
  if (moreBtn) moreBtn.addEventListener("click", function () {
    _badgeExpanded = true; _renderBadges();
    var title = $("badge-shelf");
    if (title) title.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  var lessBtn = $("badge-less");
  if (lessBtn) lessBtn.addEventListener("click", function () {
    _badgeExpanded = false; _renderBadges();
  });
}

async function loadBadges() {
  var data, ach;
  try {
    data = await API("/api/stats/badges");
    ach = await API("/api/stats/achievements");
  } catch (e) { return; }
  var shelf = $("badge-shelf");
  if (!shelf) return;
  _applyManual(ach);
  var zhiba = _computeZhibaBadges(ach);
  _badgeAll = (data.badges || []).concat(zhiba);
  _renderBadges();
  // 点击徽章查看家族（事件委托）
  if (!shelf._famBound) {
    shelf._famBound = true;
    shelf.addEventListener("click", function (e) {
      var card = e.target.closest(".badge-item[data-idx]");
      if (!card) return;
      var idx = parseInt(card.dataset.idx, 10);
      if (isNaN(idx) || !_badgeAll[idx]) return;
      _showBadgeFamily(_badgeAll[idx]);
    });
  }
}

async function loadAchievements() {
  var data;
  try { data = await API("/api/stats/achievements"); } catch (e) { return; }
  var grid = $("ach-grid");
  if (!grid) return;
  // 合并手动解锁：manual 项若 localStorage 标记则视为 visited
  _applyManual(data);
  var visited = data.filter(function (d) { return d.visited; });
  var countEl = $("ach-count");
  if (countEl) countEl.textContent = "（" + visited.length + "/" + data.length + " 已解锁）";
  // 按分类分组
  var cats = ["食堂","清青","餐厅","饮品","购物","便利店","水果"];
  var html = "";
  cats.forEach(function (cat) {
    var items = data.filter(function (d) { return d.cat === cat; });
    if (!items.length) return;
    html += '<div class="ach-group">';
    var catUnlocked = items.filter(function(d){return d.visited;}).length;
    html += '<h4 class="ach-cat-title">' + cat + ' <em>' + catUnlocked + '/' + items.length + '</em></h4>';
    html += '<div class="ach-row">';
    items.forEach(function (d) {
      if (d.visited) {
        var statText = d.manualUnlocked ? "🙌 手动解锁" : (d.count + " 次 · " + fmtMoney(d.total));
        var lastHtml = d.manualUnlocked ? "" : '<div class="ach-last">最近：' + (d.last || "—") + '</div>';
        var extraAttr = d.manualUnlocked ? ' data-name="' + d.name + '"' : '';
        html += '<div class="ach-card unlocked' + (d.manualUnlocked ? ' manual-unlocked' : '') + '"' + extraAttr + '>' +
          '<div class="ach-icon">' + d.icon + '</div>' +
          '<div class="ach-name">' + d.name + '</div>' +
          '<div class="ach-desc">' + d.desc + '</div>' +
          '<div class="ach-stat">' + statText + '</div>' +
          lastHtml +
        '</div>';
      } else if (d.manual) {
        html += '<div class="ach-card locked manual" data-name="' + d.name + '" title="点击解锁">' +
          '<div class="ach-icon">🔓</div>' +
          '<div class="ach-name">' + d.name + '</div>' +
          '<div class="ach-desc">' + d.desc + '</div>' +
          '<div class="ach-stat" style="color:var(--accent)">👆 点击解锁</div>' +
        '</div>';
      } else {
        html += '<div class="ach-card locked">' +
          '<div class="ach-icon">🔒</div>' +
          '<div class="ach-name">' + d.name + '</div>' +
          '<div class="ach-desc">' + d.desc + '</div>' +
          '<div class="ach-stat">尚未探索</div>' +
        '</div>';
      }
    });
    html += '</div></div>';
  });
  grid.innerHTML = html;
  // 手动解锁卡片：点击锁定的 → 解锁
  grid.querySelectorAll(".ach-card.locked.manual").forEach(function (card) {
    card.addEventListener("click", function () {
      _toggleManualUnlock(this.dataset.name);
    });
  });
  // 已手动解锁的卡片：点击 → 重新上锁
  grid.querySelectorAll(".ach-card.manual-unlocked").forEach(function (card) {
    card.addEventListener("click", function () {
      _toggleManualUnlock(this.dataset.name);
    });
    card.style.cursor = "pointer";
    card.title = "点击重新锁定";
  });
  // 隐藏称号：全部食堂解锁后随机授予
  var allCanteens = data.filter(function (d) { return d.cat === "食堂"; });
  var allUnlocked = allCanteens.every(function (d) { return d.visited; });
  var titleEl = $("ach-title");
  if (titleEl) {
    if (allUnlocked) {
      var storedTitle = localStorage.getItem("thueat_title");
      if (!storedTitle) {
        var titles = ["🍽️ 美食家","🍜 大胃王","🏆 食堂猎人","👑 清华食神","🥢 扫荡者","🍳 饕餮传人","🎖️ 干饭王","🔥 舌尖霸主"];
        storedTitle = titles[Math.floor(Math.random() * titles.length)];
        localStorage.setItem("thueat_title", storedTitle);
      }
      titleEl.textContent = "🏅 隐藏称号解锁：" + storedTitle;
      titleEl.classList.remove("hidden");
    } else {
      var remain = data.filter(function(d){return !d.visited;}).length;
      titleEl.textContent = "🔮 解锁全部 " + data.length + " 个成就可获得神秘称号（" + remain + " 个待探索）";
      titleEl.classList.remove("hidden");
      titleEl.classList.add("ach-hint");
    }
  }
}

// ---------- 分类规则 ----------
async function loadRules() {
  const data = await API("/api/categories/rules");
  const tbody = $("rules-table").querySelector("tbody");
  tbody.innerHTML = data.rules.map((r) => `
    <tr><td><code>${r.keyword}</code></td><td><span class="cat-tag" style="border-left:3px solid ${catColor(r.category)}">${r.category}</span></td>
    <td class="num"><button class="btn" data-kw="${r.keyword}">删除</button></td></tr>`).join("");
  $("rules-count").textContent = `（${data.rules.length} 条）`;
  tbody.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => delRule(b.dataset.kw)));
}
$("r-add").addEventListener("click", async () => {
  const kw = $("r-keyword").value.trim(), cat = $("r-category").value.trim();
  if (!kw || !cat) return toast("关键词和分类都不能为空", "error");
  const res = await API("/api/categories/rules", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ keyword: kw, category: cat }) });
  if (res.error) return toast(res.error, "error");
  $("r-keyword").value = ""; $("r-category").value = "";
  loadRules(); toast("已添加规则", "ok");
});
async function delRule(kw) {
  const res = await API("/api/categories/rules", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ keyword: kw, delete: true }) });
  if (res.error) return toast(res.error, "error");
  loadRules(); toast("已删除", "ok");
}
$("r-rebuild").addEventListener("click", async () => {
  const res = await API("/api/categories/rebuild", { method: "POST" });
  if (res.error) return toast(res.error, "error");
  toast(`已重新分类 ${res.rebuilt} 条`, "ok");
});

// ---------- 初始化 ----------
function todayStr() { return new Date().toISOString().slice(0, 10); }
function resizeCharts() { Object.values(charts).forEach((c) => c && c.resize()); }
window.addEventListener("resize", resizeCharts);
// 深浅模式切换时重绘（颜色变化）
// 趋势图粒度/数量控件
var tg = $("trend-gran"), tn = $("trend-n");
if (tg) tg.addEventListener("change", function () { state.trendGran = this.value; refresh(); });
if (tn) tn.addEventListener("change", function () { state.trendN = parseInt(this.value) || 10; refresh(); });

// 热力图年份切换（不需要重取数据，只切显示范围）
var hy = $("heat-year");
if (hy) hy.addEventListener("change", function () {
  if (state._heatData) renderHeatmap(state._heatData, this.value);
});

matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { refresh(); });

// ==================== EATi 饮食人格测试 ====================

var EBTI_QUESTIONS = [
  // 维度1：认知决策（Decisiveness）— 点餐时的果断性
  { dim: "果断性", dimKey: "decisive", q: "你走进食堂，面对十多个窗口，你通常？", opts: ["快速锁定目标，毫不犹豫","看两三遍后决定","逛完一圈再做决定","反复比较，很难决定","最后随便点一个，常常后悔"], scores: [5,4,3,2,1] },
  { dim: "果断性", dimKey: "decisive", q: "面对一份没见过的陌生菜单窗口时？", opts: ["扫一眼凭直觉直接点","快速找到感兴趣的几个再挑","选一个没吃过的，当开盲盒","要问同伴或阿姨推荐","详细看完每个菜再决定"], scores: [5,4,3,2,1] },
  { dim: "果断性", dimKey: "decisive", q: "发现点了一份不喜欢的菜，你会？", opts: ["立刻换掉，重新点别的","吃两口看看值不值得吃完","不吃这个菜了，只吃剩下的菜","勉强吃完但心里不爽","不能浪费，坚持吃完"], scores: [5,4,3,2,1] },
  // 维度2：秩序感（Orderliness）— 对饮食规则的倾向
  { dim: "秩序感", dimKey: "orderly", q: "对于自己的饮食规则（定时吃饭／不吃某种食物）？", opts: ["严格遵守，极少破例","大多数时候能遵守","看情况，有时会破个例","有规则但经常坚持不住","没什么固定的饮食规则"], scores: [5,4,3,2,1] },
  { dim: "秩序感", dimKey: "orderly", q: "吃饭时你习惯的进食顺序是怎样的？", opts: ["严格按顺序，先菜后饭绝不混","大致有个大顺序但不死板","混着吃，夹到什么吃什么","什么方便先吃什么","完全没注意过这个问题"], scores: [5,4,3,2,1] },
  { dim: "秩序感", dimKey: "orderly", q: "对于每顿吃多少的控制？", opts: ["精确控制，按需定量搭配","大致控制，差不多就可以","看心情，时多时少","好吃就多吃，不饿就少吃","吃饱为止，从不考虑分量"], scores: [5,4,3,2,1] },
  // 维度3：开放性（Openness）— 尝试新食物的意愿
  { dim: "开放性", dimKey: "openness", q: "在食堂看到一个从没吃过的窗口／新菜式？", opts: ["立刻去试，超爱新鲜感","挺有兴趣，下次会去试试","先看看别人点的怎么样","等朋友推荐过后再说","还是选自己吃惯的，稳妥第一"], scores: [5,4,3,2,1] },
  { dim: "开放性", dimKey: "openness", q: "遇到异国风味或从未接触过的菜系？", opts: ["超感兴趣，主动搜攻略去试新","身边有人约就跟着去尝尝","不主动，但被拉去也不会拒绝","先观望，看别人评价好坏再说","不太感兴趣，基本只吃中餐"], scores: [5,4,3,2,1] },
  { dim: "开放性", dimKey: "openness", q: "你平时随身带零食吗？", opts: ["包里永远有吃的，像移动小卖部","经常带，以防随时会饿","偶尔带，看当天心情","很少带，只有出远门才备一点","从不带零食，只吃正顿"], scores: [5,4,3,2,1] },
  // 维度4：社交性（Sociability）— 饮食中的社交行为
  { dim: "社交性", dimKey: "social", q: "朋友突然约你一起去吃饭？", opts: ["秒回复好呀走了走了","通常都会答应一起去","看心情，也看和谁约","嘴上答应，其实更想一个人吃","婉拒，我习惯自己安静吃"], scores: [5,4,3,2,1] },
  { dim: "社交性", dimKey: "social", q: "聚餐时你一般扮演什么角色？", opts: ["我是发起人，张罗选地儿点菜","积极参与讨论去哪吃点什么","跟着大家，随大流就好","默默参与，不太发言","能不去就不去，社恐现场"], scores: [5,4,3,2,1] },
  { dim: "社交性", dimKey: "social", q: "一个人吃饭的时候你的感受？", opts: ["觉得孤单，特别想找人一起吃","可以接受但更喜欢有人一起","还行吧，没什么特别的感觉","挺自在的，享受不需要说话的清净","最喜欢一个人，不用跟任何人说话"], scores: [5,4,3,2,1] },
  // 维度5：意志力（Willpower）— 饮食计划与克制力
  { dim: "意志力", dimKey: "willpower", q: "面前摆着高热量又特别诱人的食物？", opts: ["完全不碰，严格控制着","偶尔破例一次可以原谅自己","内心斗争好久，然后吃一点","经常看完忍不住，吃完再后悔","从不克制，想吃就吃，开心最重要"], scores: [5,4,3,2,1] },
  { dim: "意志力", dimKey: "willpower", q: "压力大或情绪低落的时候，你的食欲？", opts: ["完全不受影响，照常吃饭","轻微影响但还在可控范围","有时会靠吃更多来缓解","疯狂暴食发泄情绪","完全没胃口，什么都吃不下"], scores: [5,4,3,2,1] },
  { dim: "意志力", dimKey: "willpower", q: "关于饮食计划的执行（减脂／增肌／养生等）？", opts: ["有详细计划而且严格执行","有计划但会根据实际灵活调整","偶尔做计划，但坚持不下来","很少做饮食计划","随心所欲，从不计划"], scores: [5,4,3,2,1] },
  // ===== 第二组（第 16-30 题，每维度各 3 题）=====
  // 果断性 — 16-18
  { dim: "果断性", dimKey: "decisive", q: "和朋友一起去食堂，两人对吃什么意见不一时？", opts: ["立刻提个方案一拍即合","快速协商很快达成一致","各吃各的，互不耽误","让对方决定，自己都可以","纠结半天最后还是随对方"], scores: [5,4,3,2,1] },
  { dim: "果断性", dimKey: "decisive", q: "点外卖时的决策习惯是？", opts: ["打开App直奔常点店铺秒下单","快速浏览推荐后直接下单","对比两三家再决定","反复看评论翻来覆去定不下","常常选了又取消换成别的"], scores: [5,4,3,2,1] },
  { dim: "果断性", dimKey: "decisive", q: "排长队等餐时旁边的窗口突然开了？", opts: ["毫不犹豫立刻换到新窗口","观察一下大概在卖什么再决定","看别人换不换，跟风","纠结要换还是要继续等","坚持继续等，不想冒险"], scores: [5,4,3,2,1] },
  // 秩序感 — 19-21
  { dim: "秩序感", dimKey: "orderly", q: "今天吃饭时间被突发事件打乱了？", opts: ["尽快调整，恢复原来的节奏","今天随便，明天一定恢复","无所谓，有饭吃就行","干脆今天就不按点吃了","我从来就没有固定饭点"], scores: [5,4,3,2,1] },
  { dim: "秩序感", dimKey: "orderly", q: "关于餐前洗手与用餐卫生的习惯？", opts: ["严格流程，每次必然做到","基本都会注意清洁","看情况，有时会省略","想起来了才会做","不太在意这些细节"], scores: [5,4,3,2,1] },
  { dim: "秩序感", dimKey: "orderly", q: "吃饭的时候你会同时做其他事情吗？", opts: ["从不，专心吃饭是对食物的尊重","偶尔瞥一眼手机消息","经常边吃边刷视频","基本都在边吃边工作/看书","吃饭就是背景音，一直在忙别的"], scores: [5,4,3,2,1] },
  // 开放性 — 22-24
  { dim: "开放性", dimKey: "openness", q: "朋友盛情推荐一道你看着觉得不太好吃的菜？", opts: ["一定试试，朋友推荐的不会差","试试看吧，万一真的好吃呢","犹豫一下尝一小口","敷衍答应下次再说","坚决不试，看着就没胃口"], scores: [5,4,3,2,1] },
  { dim: "开放性", dimKey: "openness", q: "对于奇特的搭配（甜咸混搭、水果入菜等）？", opts: ["超喜欢，我经常自己发明奇怪搭配","愿意尝试别人推荐的创新搭配","有点保守但偶尔会好奇","觉得奇怪，不太想试","传统搭配才是正道"], scores: [5,4,3,2,1] },
  { dim: "开放性", dimKey: "openness", q: "在自助餐或自选模式餐厅你的策略是？", opts: ["每种没吃过的都来一小份尝鲜","以喜欢的为主夹一点新菜","主要还是拿自己熟悉的","只夹自己确定好吃的东西","雷打不动永远吃那几样"], scores: [5,4,3,2,1] },
  // 社交性 — 25-27
  { dim: "社交性", dimKey: "social", q: "吃到一道特别惊艳的菜你会？", opts: ["立刻拍照发群里/朋友圈疯狂安利","告诉身边的人推荐他们去","下次约朋友一起来吃","自己默默记住这个窗口","不会特别做什么，吃了就过了"], scores: [5,4,3,2,1] },
  { dim: "社交性", dimKey: "social", q: "和不熟的人坐在一起吃饭？", opts: ["很快就能聊开，社交无压力","可以正常客气交流","有点小尴尬但能应付","默默低头快吃不太说话","浑身不自在只想快点吃完跑路"], scores: [5,4,3,2,1] },
  { dim: "社交性", dimKey: "social", q: "你的「饭搭子」情况最接近？", opts: ["有一个大圈子经常换不同人吃","有两三个固定饭搭子","有一个固定饭搭子","偶尔会找认识的熟人一起吃","基本没有饭搭子，习惯自己吃"], scores: [5,4,3,2,1] },
  // 意志力 — 28-30
  { dim: "意志力", dimKey: "willpower", q: "深夜饿了但已经刷过牙准备睡了？", opts: ["坚决不吃，这是原则问题","喝点水忍忍就过去了","内心斗争一下看饿的程度","吃一点健康的东西垫垫","刷牙算什么，吃饱了再刷一次"], scores: [5,4,3,2,1] },
  { dim: "意志力", dimKey: "willpower", q: "别人在你面前吃你最爱的食物但你正在控制饮食？", opts: ["完全不为所动，目标第一","觉得馋但能管住自己","看对方吃一点解馋","忍了一会儿没忍住也去吃了","瞬间破防，控制什么的一会儿再说"], scores: [5,4,3,2,1] },
  { dim: "意志力", dimKey: "willpower", q: "别人在你旁边咔咔吃零食，而你正在控制饮食？", opts: ["完全不为所动，目标最重要","有点馋但能管住自己","内心挣扎一下，讨一小口尝尝","忍了一会儿后伸手过去要了一点","瞬间破防，一起大吃特吃"], scores: [5,4,3,2,1] },
];

// 维度得分 → 文字等级
// SBTI 风格玩梗维度等级标签
var EATI_LEVELS = {
  decisive:  { lo: "选择困难",  mid: "正常人",     hi: "三秒锁定" },
  orderly:   { lo: "随性自由",  mid: "差不多先生",  hi: "强迫症犯了" },
  openness:  { lo: "只吃那几样", mid: "试试就试试", hi: "新窗口雷达" },
  social:    { lo: "独食是信仰", mid: "随缘搭饭",   hi: "不组局会死" },
  willpower: { lo: "管不住这嘴", mid: "偶尔挣扎",   hi: "铁胃自律侠" },
};

// 18 基础饮食人格档案 + 3 隐藏人格（SBTI 风格：4-字母缩写，写实自嘲，玩梗）
var EATI_ARCHETYPES = [
  { id:"FOMO", name:"FOMO吃货", icon:"📱", d:18,o:16,p:24,s:22,w:12, desc:"别人排队你跟，朋友打卡你必到。FOMO（Fear Of Missing Out）是你的底层驱动力，你享受探索新窗口的快感，也乐于把第一手情报在群里广播。规则在你这里略等于参考，但你的嗅觉总能精准锁定下一个排队目标。" },
  { id:"MONK", name:"苦行僧",  icon:"🧘", d:20,o:24,p:12,s:14,w:24, desc:"吃饭是一场修行，什么时候吃什么、吃多少克全有精确的账本。你不会被香味或广告语动摇，也不需要靠食物社交。自律是你选择的生活方式，再嘈杂也与你无关。" },
  { id:"GOBL", name:"哥布林",  icon:"👹", d:18,o:12,p:23,s:18,w:11, desc:"第一个窗口还没吃完，你已经盯上隔壁窗口的下一份。你对食物的态度像哥布林抢宝箱：抓了再说，炫了再悔，悔了再抓。你敢于尝试各种新奇搭配，饭后摩挲着圆滚滚的肚子，那是你征服食堂的战绩。" },
  { id:"SOLO", name:"独食侠",  icon:"🥡", d:24,o:16,p:14,s:11,w:18, desc:"点餐三秒，吃饭十分钟，全程不说一句多余的话。独自用餐的高效与安静让你舒服，不等别人也不被别人等。对外面的新餐厅兴趣不大，但常吃那几家的菜单你已了如指掌。吃饭这件事本来就不需要搭子。" },
  { id:"LOOP", name:"循环侠",  icon:"🔁", d:18,o:24,p:11,s:16,w:20, desc:"你的饮食节奏像一首单曲循环的歌，只要今天不太糟，明天就继续同样的菜谱。变化对你没有吸引力，重复带来的秩序感才可靠。你不太主动社交，但也不排斥别人坐过来一起吃。你知道什么时候该停筷子，从不过量。" },
  { id:"CTRL", name:"CTRL人",  icon:"🎮", d:24,o:20,p:14,s:16,w:24, desc:"你的饮食决策不需要第二个人点头，你自己就是权威。快速决定、严格量控、每日按时，每一步都在预设轨道上运行。对新窗口兴趣有限，除非它出现在你提前规划的时间表里。旁人觉得你过得克制，你自己知道那是高效。" },
  { id:"CAVE", name:"穴居人",  icon:"🕳️", d:14,o:16,p:11,s:11,w:16, desc:"食堂不起眼的角落就是你的专属安全区。你在那儿安静地吃着万年不变的几道菜，不赶潮流，不看推荐，对外界保持礼貌的距离。你不觉得寂寞，自己陪自己就很好。食物的意义是吃饱，不出错比什么都重要。" },
  { id:"SHEP", name:"跟风狗",  icon:"🐑", d:12,o:14,p:16,s:22,w:11, desc:"你最大的点餐焦虑不是选什么，而是轮到你来决定的那个瞬间。所以你建立了完美的防御机制：跟着朋友走就对了。你从来不是组织者，却是最忠实的参与者，别人挑地方你背书。从不主动决定意味着从不内疚，吃开心了还会顺手拍一张发群里。" },
  { id:"DASH", name:"速通食客", icon:"🏃", d:24,o:16,p:24,s:18,w:16, desc:"别人还在看菜单，你已经坐在位子上吃上了。从决定到下单只需几秒，从吃完到决定下一顿也同步发生。你把每顿饭当成一个速通任务，又快又准。你喜欢跟人分享通关心得，也不介意一个人冲。怕的不是踩雷，是吃得太慢。" },
  { id:"HOST", name:"组局王",  icon:"🎪", d:18,o:24,p:16,s:22,w:18, desc:"你手机群聊里永远有两三个饭搭子群。提前敲人数、选窗口、安排时间——这些你觉得是基础操作，对朋友来说你已是一个行走的餐厅调度系统。你对菜单的掌控不止来自频率，更来自你把每个朋友的偏好记得比课表还清楚。" },
  { id:"CHON-G", name:"炫就完了", icon:"🍖", d:14,o:11,p:20,s:18,w:11, desc:"规则和计划对你来说是浮云，你不纠结选择，因为你什么都想试。你的攻击力全点在胃的容量上，不管多大碗都相信自己的实力。偶尔吃撑到后悔，但这份毫无保留的随性就是你的魅力：吃饭嘛，开心才是第一标准。旁边有人一起炫，节奏更佳。" },
  { id:"YEEE", name:"耶耶耶",  icon:"💨", d:24,o:11,p:20,s:16,w:14, desc:"点菜瞬间你已经付完款了，嘴里还喊着耶耶耶。冲动比理性更适合食堂，看上了就冲，吃完了就撤，不在意别人怎么看。偶尔叫上一个人跟你高效扫荡，但快节奏让你更享受单枪匹马的爽快。没时间挑，也不想挑。" },
  { id:"COPY", name:"复读鸡",  icon:"🐔", d:11,o:16,p:16,s:23,w:16, desc:"看同桌点什么你就点什么，看群友夸哪个你下次就去那个。这种复读式选菜是你把社交信任外包给了朋友圈。你喜欢和别人吃一样的饭，因为这让你们聊得更多。同步的口感给你心安，也让你远离踩雷。" },
  { id:"ST-uCK", name:"卡住了",  icon:"🔒", d:10,o:24,p:11,s:16,w:20, desc:"排队到你的那一刻才是真正考验的开始。菜单在你眼中不是信息，是一道没有标准答案的考题。你反复比较每一行菜名，用排除法、打分法、对比法，最终在阿姨催促的眼光下颤颤地指一道菜。每一个选择都必须有理有据，对得起自己。" },
  { id:"IRON", name:"铁胃侠",  icon:"🦾", d:18,o:18,p:11,s:14,w:24, desc:"面对滋滋作响的铁板烧也能面无波澜，你靠日积月累的克制修炼。很少踏进新开的窗口，从不跟风排队，时间和规则比味道重要。独自进食是最高效的补给方式，社交是附属选项，节律才是主线。" },
  { id:"OOOO", name:"哦哦哦", icon:"🤷", d:18,o:14,p:18,s:20,w:16, desc:"哦哦哦，随便，都可以。你是全食堂最快乐的人：去哪儿吃？都行。吃啥？随意。好不好吃？还行。你把偏好磨合成了不纠结，在别人为一顿饭争论时你已经端上了自己的盘子。一个人安静吃也行，被拉进任何局也行，你跟谁都合得来。佛系的核心不是放弃选择，是选择不纠结。" },
  { id:"PICK", name:"赛博挑食", icon:"🥦", d:12,o:18,p:11,s:12,w:16, desc:"你有一张外人看不见的可食用清单，清单外的菜碰都不会碰。你清楚自己的胃对某些东西天然排斥，所以果断远离。不喜欢跟人拼桌，这会分散你对食物质量的关注。几个懂你口味的人值得留着，每一口都不降低标准，吃饭也要按原则来。" },
  { id:"MOU-se", name:"仓鼠人",  icon:"🐹", d:14,o:12,p:24,s:22,w:11, desc:"你的书包里永远有一个零食分区。三餐之外还有无数个小餐：课间、宵夜、刷剧、写作业，几乎没有不吃的时候。你喜欢跟身边人分享库存，也热衷收集新奇口味囤起来慢慢嚼。唯一的烦恼是嘴巴停不下来的时候，钱包和胃同时发出警告。" },
];
// 隐藏人格（优先判定）
var EATI_HIDDEN = [
  { id:"DARK", name:"暗夜食者", icon:"🌛", cond:function(s){return s.willpower<=10 && s.social<=14;}, desc:"凌晨食堂是你一个人的私密仪式。不需要任何人在场，你只在黑暗中进食，这是你独有的深夜仪式感。白天属于人群，夜晚和食物只属于你自己。" },
  { id:"A-WUU", name:"食堂暴龙", icon:"🦖", cond:function(s){return s.decisive>=24&&s.orderly>=24&&s.openness>=24&&s.social>=24&&s.willpower>=24;}, desc:"啊呜，恐龙来了。五维全满，没有弱点。你决定得快、执行得稳、试得广、吃得欢、管得住，食堂在你面前不是场地而是食材市场。你一人即军团，午餐即是征伐。A-WUU，暴龙咆哮。" },
  { id:"VIBE", name:"纯靠感受", icon:"✨", cond:function(s){return s.social>=23&&s.openness>=23&&s.orderly<=14;}, desc:"你不做计划，直觉比你见过的任何菜单都准。跟着人流走、跟着香味走，总能歪打正着撞见当天最好吃的一顿。自由散漫是你特有的方法论。" },
];

// 欧氏距离 → 匹配最近的基础人格（无隐藏触发时）
function _eatMatch(scores) {
  var dims = ["decisive","orderly","openness","social","willpower"];
  var best = null, bestDist = Infinity;
  for (var a = 0; a < EATI_ARCHETYPES.length; a++) {
    var arch = EATI_ARCHETYPES[a];
    var dist = 0;
    for (var i = 0; i < dims.length; i++) {
      var d = scores[dims[i]] - arch[dims[i].charAt(0)]; // d,o,p,s,w 简写
      dist += d * d;
    }
    dist = Math.sqrt(dist);
    // OOOO 仅限真正"都行"的极端平局，给予 25% 距离罚分
    if (arch.id === "OOOO") dist *= 1.25;
    if (dist < bestDist) { bestDist = dist; best = arch; }
  }
  return { id: best.id, icon: best.icon, name: best.name + " · " + best.id, desc: best.desc };
}

var EBTI = { answers: [], currentQ: 0 };

function _ebtiRenderQuestion() {
  if (EBTI.currentQ >= EBTI_QUESTIONS.length) { _ebtiShowResult(); return; }
  var q = EBTI_QUESTIONS[EBTI.currentQ];
  $("ebti-q-title").textContent = "Q" + (EBTI.currentQ + 1) + ". " + q.q + "（" + q.dim + "）";
  var optsHtml = q.opts.map(function (txt, i) {
    var sel = (EBTI.answers[EBTI.currentQ] === i) ? " selected" : "";
    return '<div class="ebti-option' + sel + '" data-idx="' + i + '" data-keynum="' + (i+1) + '">' + txt + '</div>';
  }).join("");
  $("ebti-options").innerHTML = optsHtml;
  // 点击选项
  document.querySelectorAll("#ebti-options .ebti-option").forEach(function (el) {
    el.addEventListener("click", function () {
      document.querySelectorAll("#ebti-options .ebti-option").forEach(function (o) { o.classList.remove("selected"); });
      this.classList.add("selected");
      EBTI.answers[EBTI.currentQ] = parseInt(this.dataset.idx);
    });
  });
  // 恢复选中
  if (typeof EBTI.answers[EBTI.currentQ] === "number") {
    document.querySelectorAll("#ebti-options .ebti-option").forEach(function (el) {
      if (parseInt(el.dataset.idx) === EBTI.answers[EBTI.currentQ]) el.classList.add("selected");
    });
  }
  $("ebti-q-num").textContent = (EBTI.currentQ + 1) + " / " + EBTI_QUESTIONS.length;
  $("ebti-progress-bar").style.width = ((EBTI.currentQ + 1) / EBTI_QUESTIONS.length * 100) + "%";
  $("ebti-prev").style.display = EBTI.currentQ === 0 ? "none" : "";
  if (EBTI.currentQ === EBTI_QUESTIONS.length - 1) {
    $("ebti-next").textContent = "查看结果 →";
  } else {
    $("ebti-next").textContent = "下一题 →";
  }
}

(function () {
  var prev = $("ebti-prev"), next = $("ebti-next"), restart = $("ebti-restart"), re = $("ebti-retest");
  if (prev && next) {
    prev.addEventListener("click", function () { if (EBTI.currentQ > 0) { EBTI.currentQ--; _ebtiRenderQuestion(); } });
    next.addEventListener("click", function () {
      if (typeof EBTI.answers[EBTI.currentQ] === "undefined") { toast("请先选择一个选项", "error"); return; }
      EBTI.currentQ++;
      _ebtiRenderQuestion();
    });
  }
  if (restart) restart.addEventListener("click", function () {
    if (confirm("确定要重新开始吗？当前答题进度将被清空。")) _ebtiReset();
  });
  if (re) re.addEventListener("click", _ebtiReset);
})();

// EATi 键盘导航：←→ 翻页，↑↓ 选项，1-5 快速选，Enter 确认
document.addEventListener("keydown", function (e) {
  var quiz = $("ebti-quiz");
  if (!quiz || quiz.classList.contains("hidden")) return;
  var tag = (document.activeElement || {}).tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
  var opts = document.querySelectorAll("#ebti-options .ebti-option");
  var k = e.key;
  // 数字键 1-5：直接选择并前进
  if (k >= "1" && k <= "5" && opts.length) {
    e.preventDefault();
    var idx = parseInt(k) - 1;
    if (opts[idx]) {
      opts.forEach(function (o) { o.classList.remove("selected", "focused"); });
      opts[idx].classList.add("selected");
      EBTI.answers[EBTI.currentQ] = idx;
      EBTI.currentQ++;
      _ebtiRenderQuestion();
    }
    return;
  }
  // ← 上一题
  if (k === "ArrowLeft" && EBTI.currentQ > 0) {
    e.preventDefault(); EBTI.currentQ--; _ebtiRenderQuestion();
    return;
  }
  // → / Enter：下一题（若有关注项先自动选中）
  if (k === "ArrowRight" || k === "Enter") {
    e.preventDefault();
    // 先检查是否有聚焦项未选中 → 自动选中再前进
    for (var j = 0; j < opts.length; j++) {
      if (opts[j].classList.contains("focused") && !opts[j].classList.contains("selected")) {
        opts[j].classList.add("selected");
        EBTI.answers[EBTI.currentQ] = j;
        break;
      }
    }
    if (typeof EBTI.answers[EBTI.currentQ] === "undefined") return;
    EBTI.currentQ++; _ebtiRenderQuestion();
    return;
  }
  // ↑↓ 在选项间移动聚焦
  if (k === "ArrowUp" || k === "ArrowDown") {
    e.preventDefault();
    var focused = -1;
    for (var i = 0; i < opts.length; i++) {
      if (opts[i].classList.contains("focused")) { focused = i; break; }
    }
    if (focused === -1 && typeof EBTI.answers[EBTI.currentQ] !== "undefined") {
      focused = EBTI.answers[EBTI.currentQ];
    }
    opts.forEach(function (o) { o.classList.remove("focused"); });
    var next = focused + (k === "ArrowDown" ? 1 : -1);
    if (next < 0) next = opts.length - 1;
    if (next >= opts.length) next = 0;
    opts[next].classList.add("focused");
  }
});

function _ebtiReset() {
  EBTI = { answers: [], currentQ: 0 };
  $("ebti-quiz").classList.remove("hidden");
  $("ebti-result").classList.add("hidden");
  _ebtiRenderQuestion();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function _ebtiShowResult() {
  $("ebti-quiz").classList.add("hidden");
  $("ebti-result").classList.remove("hidden");
  // 计分
  var dimScores = {}, dimCounts = {};
  EBTI_QUESTIONS.forEach(function (q, i) {
    var ans = EBTI.answers[i];
    dimScores[q.dimKey] = (dimScores[q.dimKey] || 0) + (q.scores[ans] || 3);
    dimCounts[q.dimKey] = (dimCounts[q.dimKey] || 0) + 1;
  });
  // 雷达图（echarts）
  var dims = ["果断性","秩序感","开放性","社交性","意志力"];
  var keys = ["decisive","orderly","openness","social","willpower"];
  var vals = keys.map(function (k) { return dimScores[k] || 9; });
  var radarEl = $("ebti-radar");
  if (radarEl) {
    var ch = echarts.init(radarEl);
    ch.setOption({
      radar: {
        shape: "polygon",
        indicator: dims.map(function (d, i) { return { name: d + " (" + vals[i] + ")", max: 30 }; }),
        center: ["50%", "52%"], radius: "75%",
        axisName: { color: "#52514e", fontSize: 12 },
        splitArea: { areaStyle: { color: ["rgba(123,45,142,0.03)","rgba(123,45,142,0.06)"] } },
      },
      series: [{
        type: "radar",
        data: [{ value: vals, name: "你的得分", areaStyle: { color: "rgba(123,45,142,0.2)" }, lineStyle: { color: "#7B2D8E" } }],
        symbol: "circle", symbolSize: 6,
        itemStyle: { color: "#7B2D8E" },
      }],
    });
  }
  // 先检测隐藏人格触发条件
  var arch = null;
  for (var h = 0; h < EATI_HIDDEN.length; h++) {
    if (EATI_HIDDEN[h].cond(dimScores)) { arch = EATI_HIDDEN[h]; break; }
  }
  if (!arch) arch = _eatMatch(dimScores);
  // 左上画像：显示对应 AI 生成的人物画像
  var portrait = $("ebti-portrait");
  if (portrait) {
    portrait.innerHTML =
      '<img class="ebti-portrait-img" src="/static/pic/' + encodeURIComponent(arch.id) + '.jpg" alt="' + arch.name + '" ' +
      'onerror="this.style.display=\'none\';this.parentElement.innerHTML=\'<div class=\\\'ebti-portrait-icon\\\'>🤖</div><div class=\\\'ebti-portrait-label\\\'>AI 饮食性格画像</div>\'">' +
      '<div class="ebti-portrait-label">' + arch.name + ' 画像</div>';
  }
  // 右上类型标识
  if ($("ebti-type-icon")) $("ebti-type-icon").textContent = arch.icon;
  if ($("ebti-type-en")) $("ebti-type-en").innerHTML =
    '<div class="ebti-type-cn">' + arch.name + '</div>' +
    '<div class="ebti-type-abbr">' + arch.id + '</div>';
  // 人格简单解读
  if ($("ebti-interp")) $("ebti-interp").textContent = arch.desc;
  // 维度特征卡片
  var traitsHtml = dims.map(function (d, i) {
    var k = keys[i], score = vals[i], lv = EATI_LEVELS[k];
    var label = score >= 25 ? lv.hi : (score <= 14 ? lv.lo : lv.mid);
    return '<div class="ebti-trait-card"><div class="ebti-trait-name">' + d + '</div><div class="ebti-trait-level">' + label + '</div><div class="ebti-trait-desc">得分 ' + score + '/30</div></div>';
  }).join("");
  if ($("ebti-profile")) $("ebti-profile").innerHTML = '<div class="ebti-traits">' + traitsHtml + '</div>';
  $("ebti-result").scrollIntoView({ behavior: "smooth", block: "start" });
}


// ==================== 初始化 ====================

(async function init() {
  const info = await API("/api/info");
  if (info.count === 0) {
    toast("暂无数据，可在「配置与同步」加载示例数据或同步校园卡", "");
  }
  applyFilter();     // 使用默认「3个月」快速统计
  fillCategoryFilter();
})();
