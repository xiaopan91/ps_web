// 北向/成交额 因子页：当日指标卡 + 比值×上证 + 北向柱×成交额线
const { createApp, computed, onMounted, ref, watch } = Vue;

const UP = "#ef4444", DOWN = "#22c55e", BLUE = "#3b82f6", GRAY = "#94a3b8";

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

    let charts = {};
    function initCharts() {
      for (const id of ["chart-ratio", "chart-north"]) {
        const el = document.getElementById(id);
        if (el) charts[id] = echarts.init(el);
      }
    }

    const ratioColor = computed(() => {
      const r = latest.value ? latest.value.ratio_bp : null;
      if (r == null) return GRAY;
      return r >= 0 ? UP : DOWN;
    });
    const pctileColor = computed(() => {
      const p = latest.value ? latest.value.pctile : null;
      if (p == null) return GRAY;
      return p >= 80 ? UP : p >= 50 ? "#f97316" : p >= 20 ? BLUE : DOWN;
    });

    function render() {
      const d = data.value;
      if (!d || !d.dates || !d.dates.length) return;
      const base = { type: "category", data: d.dates, boundaryGap: false };

      charts["chart-ratio"] && charts["chart-ratio"].setOption({
        animation: false,
        tooltip: { trigger: "axis" },
        legend: { data: ["北向/成交额", "上证指数"], top: 0 },
        grid: { left: 55, right: 55, top: 30, bottom: 46 },
        dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
        xAxis: base,
        yAxis: [{ name: "bp", scale: true },
                { name: "上证", scale: true, splitLine: { show: false } }],
        series: [
          { name: "北向/成交额", type: "line", data: d.ratio_bp, showSymbol: false,
            lineStyle: { width: 1.8, color: BLUE }, itemStyle: { color: BLUE },
            areaStyle: { opacity: 0.08 } },
          { name: "上证指数", type: "line", yAxisIndex: 1, data: d.sh_close,
            showSymbol: false, lineStyle: { width: 1, color: GRAY },
            itemStyle: { color: GRAY } },
        ],
      }, true);

      charts["chart-north"] && charts["chart-north"].setOption({
        animation: false,
        tooltip: { trigger: "axis" },
        legend: { data: ["北向净买入(亿)", "两市成交额(万亿)"], top: 0 },
        grid: { left: 55, right: 60, top: 30, bottom: 46 },
        dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
        xAxis: base,
        yAxis: [{ name: "亿" },
                { name: "万亿", scale: true, splitLine: { show: false },
                  axisLabel: { formatter: v => (v / 10000).toFixed(1) } }],
        series: [
          { name: "北向净买入(亿)", type: "bar", data: d.north_yi,
            itemStyle: { color: p => (p.value >= 0 ? UP : DOWN) } },
          { name: "两市成交额(万亿)", type: "line", yAxisIndex: 1,
            data: d.amount_yi, showSymbol: false,
            lineStyle: { width: 1.2, color: "#f59e0b" },
            itemStyle: { color: "#f59e0b" } },
        ],
      }, true);
    }

    async function load() {
      loading.value = true;
      error.value = "";
      try {
        const res = await fetch(`/api/north/overview?days=${days.value}`);
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
      history.replaceState(null, "", `/predict/north?${p}`);
      load();
    });
    onMounted(() => {
      initCharts();
      load();
      window.addEventListener("resize",
        () => Object.values(charts).forEach(c => c.resize()));
    });

    return { days, dayOptions, loading, error, latest, ratioColor, pctileColor };
  },
});

app.mount("#app");
