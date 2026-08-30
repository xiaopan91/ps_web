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
    const loading = ref(false);
    const error = ref("");
    const latest = ref(null);
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

    const scoreColor = computed(() => {
      const s = latest.value ? latest.value.score : null;
      if (s == null) return GRAY;
      if (s >= 80) return UP;
      if (s >= 60) return "#f97316";
      if (s >= 40) return "#64748b";
      if (s >= 20) return BLUE;
      return DOWN;
    });
    const zoneLabel = computed(() => {
      const s = latest.value ? latest.value.score : null;
      if (s == null) return "";
      if (s >= 80) return "过热";
      if (s >= 60) return "偏热";
      if (s >= 40) return "中性";
      if (s >= 20) return "偏冷";
      return "冰点";
    });

    const factorCards = computed(() => {
      const l = latest.value;
      if (!l) return [];
      const fs = l.factors || {};
      const defs = [
        ["breadth", `${l.up} 涨 / ${l.down} 跌`],
        ["limit_up", `${l.limit_up ?? '—'} 家（跌停 ${l.limit_down ?? '—'}）`],
        ["max_streak", l.max_streak != null ? `${l.max_streak} 连板` : "—"],
        ["amount_ratio", `量比 ${l.amount_ratio ?? '—'}`],
        ["avg_turnover_f", `成交 ${l.total_amount_yi ? (l.total_amount_yi/10000).toFixed(2) : '—'} 万亿`],
        ["margin_net_buy", `两融余额 ${l.margin_balance_yi ?? '—'} 亿`],
        ["north_net", `北向 ${l.north_net_yi != null ? (l.north_net_yi>0?'+':'')+l.north_net_yi : '—'} 亿`],
        ["std_pct", `中位涨跌 ${l.median_pct != null ? (l.median_pct>0?'+':'')+l.median_pct+'%' : '—'}`],
      ];
      return defs.map(([key, value]) => {
        const pct = fs[key] ?? null;
        return { key, label: FACTOR_LABELS[key] || key, value, pct,
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
            areaStyle: { opacity: 0.08 } },
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
        latest.value = data.value.latest;
        render();
      } catch (e) {
        error.value = e.message;
      } finally {
        loading.value = false;
      }
    }

    watch(days, () => {
      const p = new URLSearchParams({ days: days.value });
      history.replaceState(null, "", `/sentiment?${p}`);
      load();
    });
    onMounted(() => {
      initCharts();
      load();
      window.addEventListener("resize",
        () => Object.values(charts).forEach(c => c.resize()));
    });

    return { days, dayOptions, loading, error, latest, factorCards,
             scoreColor, zoneLabel };
  },
});

app.mount("#app");
