// 市场情绪页：指标卡片 + 情绪分/广度/涨停/量能/杠杆外资图表
const { createApp, computed, onMounted, ref, watch } = Vue;

const UP = "#ef4444", DOWN = "#22c55e", BLUE = "#3b82f6", GRAY = "#94a3b8";
const FACTOR_LABELS = {
  breadth: "涨跌比", limit_up: "涨停数", max_streak: "连板高度",
  amount_ratio: "量能比", avg_turnover_f: "换手率", margin_net_buy: "两融净买",
  north_net: "北向净买", std_pct: "离散度(反)",
};

const app = createApp({
  setup() {
    const days = ref(new URLSearchParams(location.search).get("days") || "250");
    const selectedDate = ref(new URLSearchParams(location.search).get("date") || "");
    const loading = ref(false);
    const error = ref("");
    const data = ref(null);
    const dayOptions = [
      { k: "90", label: "3月" }, { k: "250", label: "1年" },
      { k: "750", label: "3年" }, { k: "all", label: "全部" },
    ];

    const charts = {};
    function initCharts() {
      for (const id of ["chart-score", "chart-breadth", "chart-limit",
                        "chart-amount", "chart-margin"]) {
        const el = document.getElementById(id);
        if (el) charts[id] = echarts.init(el);
      }
    }

    // ---- 任意历史日期快照 ----
    const snapIndex = computed(() => {
      const d = data.value;
      if (!d || !d.dates.length) return -1;
      if (!selectedDate.value) return d.dates.length - 1;
      let i = d.dates.length - 1;
      while (i > 0 && d.dates[i] > selectedDate.value) i--;  // 非交易日回退到上一交易日
      return i;
    });
    const minDate = computed(() => (data.value && data.value.dates.length)
      ? data.value.dates[0] : "");
    const maxDate = computed(() => (data.value && data.value.dates.length)
      ? data.value.dates[data.value.dates.length - 1] : "");
    const snap = computed(() => {
      const d = data.value;
      const i = snapIndex.value;
      if (!d || i < 0) return null;
      const at = (arr) => (arr ? arr[i] : null);
      const num = (v, div = 1, digits = 0) =>
        v == null ? null : +(v / div).toFixed(digits);
      return {
        trade_date: d.dates[i],
        score: at(d.score) == null ? null : +at(d.score).toFixed(1),
        up: at(d.up), down: at(d.down),
        limit_up: at(d.limit_up), limit_down: at(d.limit_down),
        max_streak: at(d.max_streak),
        total_amount_yi: num(at(d.total_amount), 1e8),
        amount_ratio: at(d.amount_ratio) == null ? null : +at(d.amount_ratio).toFixed(3),
        median_pct: at(d.median_pct) == null ? null : +at(d.median_pct).toFixed(2),
        margin_balance_yi: num(at(d.margin_balance), 1e8),
        north_net_yi: num(at(d.north_net), 1e4, 1),
        sh_close: at(d.sh_close) == null ? null : +at(d.sh_close).toFixed(1),
        factors: Object.fromEntries(
          Object.entries(d.factor_scores || {}).map(([k, arr]) => [k, at(arr)])),
      };
    });

    const scoreColor = computed(() => {
      const s = snap.value ? snap.value.score : null;
      if (s == null) return GRAY;
      if (s >= 80) return UP;
      if (s >= 60) return "#f97316";
      if (s >= 40) return "#64748b";
      if (s >= 20) return BLUE;
      return DOWN;
    });
    const zoneLabel = computed(() => {
      const s = snap.value ? snap.value.score : null;
      if (s == null) return "";
      if (s >= 80) return "过热";
      if (s >= 60) return "偏热";
      if (s >= 40) return "中性";
      if (s >= 20) return "偏冷";
      return "冰点";
    });

    const factorCards = computed(() => {
      const l = snap.value;
      if (!l) return [];
      const fs = l.factors || {};
      const defs = [
        ["breadth", `${l.up} 涨 / ${l.down} 跌`,
         "涨跌比：上涨家数÷下跌家数，衡量市场普涨普跌的广度，越高情绪越暖"],
        ["limit_up", `${l.limit_up ?? '—'} 家（跌停 ${l.limit_down ?? '—'}）`,
         "涨停家数：当日封死涨停的股票数（自算阈值：主板10%/创业板科创板20%/北交所30%/ST 5%），短线情绪的核心温度计"],
        ["max_streak", l.max_streak != null ? `${l.max_streak} 连板` : "—",
         "连板高度：当日最高的连续涨停天数（空间板），越高说明短线情绪越亢奋、题材越疯狂"],
        ["amount_ratio", `量比 ${l.amount_ratio ?? '—'}`,
         "量能比：5日平均成交额÷20日平均成交额，大于1为放量，小于1为缩量；量是情绪的燃料"],
        ["avg_turnover_f", `成交 ${l.total_amount_yi ? (l.total_amount_yi/10000).toFixed(2) : '—'} 万亿`,
         "换手率：全市场流通盘换手率均值，衡量交投活跃度（卡片显示当日总成交额）"],
        ["margin_net_buy", `两融余额 ${l.margin_balance_yi ?? '—'} 亿`,
         "两融净买入：融资买入额减偿还额（杠杆资金当日净流入），余额为其存量；杠杆加得越猛情绪越高"],
        ["north_net", `北向 ${l.north_net_yi != null ? (l.north_net_yi>0?'+':'')+l.north_net_yi : '—'} 亿`,
         "北向净买：沪深股通（外资）当日净买入金额，代表外资方向"],
        ["std_pct", `中位涨跌 ${l.median_pct != null ? (l.median_pct>0?'+':'')+l.median_pct+'%' : '—'}`,
         "离散度(反)：当日全市场个股涨跌幅的标准差，越大说明个股表现分化越严重、市场分歧越大；反向计入分数（分歧大→扣分）"],
      ];
      return defs.map(([key, value, tip]) => {
        const pct = fs[key] ?? null;
        return { key, label: FACTOR_LABELS[key] || key, value, pct, tip,
                 color: pct == null ? GRAY : (pct >= 60 ? UP : pct >= 40 ? "#64748b" : DOWN) };
      });
    });

    function render() {
      const d = data.value;
      if (!d || !d.dates.length) return;
      const base = { type: "category", data: d.dates, boundaryGap: false };

      charts["chart-score"] && charts["chart-score"].setOption({
        animation: false,
        tooltip: { trigger: "axis" },
        legend: { data: ["情绪分", "上证指数"], top: 0 },
        grid: { left: 50, right: 55, top: 30, bottom: 50 },
        dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 10 }],
        xAxis: base,
        yAxis: [{ name: "情绪分", min: 0, max: 100 },
                { name: "上证", scale: true, splitLine: { show: false }}],
        series: [
          { name: "情绪分", type: "line", data: d.score, showSymbol: false,
            lineStyle: { width: 2, color: BLUE }, itemStyle: { color: BLUE },
            areaStyle: { opacity: 0.08 },
            markLine: selectedDate.value ? {
              symbol: "none", silent: true,
              lineStyle: { color: BLUE, type: "dashed", opacity: 0.7 },
              label: { formatter: selectedDate.value, position: "insideEndTop",
                       fontSize: 10 },
              data: [{ xAxis: selectedDate.value }],
            } : undefined },
          { name: "上证指数", type: "line", yAxisIndex: 1, data: d.sh_close,
            showSymbol: false, lineStyle: { width: 1, color: GRAY },
            itemStyle: { color: GRAY } },
        ],
      }, true);

      charts["chart-breadth"] && charts["chart-breadth"].setOption({
        animation: false,
        tooltip: { trigger: "axis" },
        legend: { data: ["上涨", "下跌"], top: 0 },
        grid: { left: 50, right: 20, top: 30, bottom: 40 },
        dataZoom: [{ type: "inside" }],
        xAxis: base,
        yAxis: {},
        series: [
          { name: "上涨", type: "bar", stack: "ad", data: d.up,
            itemStyle: { color: UP } },
          { name: "下跌", type: "bar", stack: "ad", data: d.down.map(v => v == null ? null : -v),
            itemStyle: { color: DOWN } },
        ],
      }, true);

      charts["chart-limit"] && charts["chart-limit"].setOption({
        animation: false,
        tooltip: { trigger: "axis" },
        legend: { data: ["涨停家数", "最高连板"], top: 0 },
        grid: { left: 50, right: 50, top: 30, bottom: 40 },
        dataZoom: [{ type: "inside" }],
        xAxis: base,
        yAxis: [{}, { min: 0, splitLine: { show: false } }],
        series: [
          { name: "涨停家数", type: "bar", data: d.limit_up,
            itemStyle: { color: UP } },
          { name: "最高连板", type: "line", yAxisIndex: 1, data: d.max_streak,
            showSymbol: false, connectNulls: true,
            lineStyle: { width: 1.5, color: "#a855f7" },
            itemStyle: { color: "#a855f7" } },
        ],
      }, true);

      charts["chart-amount"] && charts["chart-amount"].setOption({
        animation: false,
        tooltip: { trigger: "axis" },
        grid: { left: 60, right: 20, top: 20, bottom: 40 },
        dataZoom: [{ type: "inside" }],
        xAxis: base,
        yAxis: { axisLabel: { formatter: v => (v / 10000).toFixed(1) + "万亿" } },
        series: [{ type: "bar", data: d.total_amount.map(v => v == null ? null : v / 1e8),
                   itemStyle: { color: BLUE } }],
      }, true);

      charts["chart-margin"] && charts["chart-margin"].setOption({
        animation: false,
        tooltip: { trigger: "axis" },
        legend: { data: ["两融余额", "北向净买"], top: 0 },
        grid: { left: 60, right: 60, top: 30, bottom: 40 },
        dataZoom: [{ type: "inside" }],
        xAxis: base,
        yAxis: [{ axisLabel: { formatter: v => (v / 1e8).toFixed(0) + "亿" } },
                { axisLabel: { formatter: v => (v / 1e8).toFixed(0) + "亿" },
                  splitLine: { show: false } }],
        series: [
          { name: "两融余额", type: "line", data: d.margin_balance, showSymbol: false,
            lineStyle: { width: 1.5, color: "#f59e0b" },
            itemStyle: { color: "#f59e0b" } },
          { name: "北向净买", type: "bar", yAxisIndex: 1,
            data: d.north_net.map(v => v == null ? null : v * 10000),  // 万元→元
            itemStyle: { color: p => (p.value >= 0 ? UP : DOWN) } },
        ],
      }, true);
    }

    async function load() {
      loading.value = true;
      error.value = "";
      try {
        const res = await fetch(`/api/sentiment/history?days=${days.value}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        data.value = await res.json();
        if (!selectedDate.value && data.value.dates.length) {
          selectedDate.value = data.value.dates[data.value.dates.length - 1];
        }
        render();
      } catch (e) {
        error.value = e.message;
      } finally {
        loading.value = false;
      }
    }

    function syncUrl() {
      const p = new URLSearchParams({ days: days.value });
      if (selectedDate.value && selectedDate.value !== maxDate.value) {
        p.set("date", selectedDate.value);
      }
      history.replaceState(null, "", `/sentiment?${p}`);
    }

    watch(days, () => { syncUrl(); load(); });
    watch(selectedDate, () => { syncUrl(); render(); });
    onMounted(() => {
      initCharts();
      load();
      window.addEventListener("resize",
        () => Object.values(charts).forEach(c => c.resize()));
    });

    return { days, dayOptions, loading, error, selectedDate, minDate, maxDate,
             snap, factorCards, scoreColor, zoneLabel };
  },
});

app.mount("#app");
