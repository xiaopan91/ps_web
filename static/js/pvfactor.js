// 量价综合分页：指标卡 + 多头净值×基准 + 滚动IC + 当日Top20
const { createApp, computed, onMounted, ref, watch } = Vue;

const BLUE = "#3b82f6", GRAY = "#94a3b8", UP = "#ef4444", DOWN = "#22c55e";

const app = createApp({
  setup() {
    const days = ref(new URLSearchParams(location.search).get("days") || "250");
    const loading = ref(false);
    const computing = ref(false);
    const error = ref("");
    const latest = ref(null);
    const data = ref(null);
    const topList = ref([]);
    const dayOptions = [
      { k: "90", label: "3月" }, { k: "250", label: "1年" },
      { k: "750", label: "3年" }, { k: "all", label: "全部" },
    ];
    let charts = {};

    function initCharts() {
      for (const id of ["chart-nav", "chart-ic"]) {
        const el = document.getElementById(id);
        if (el && !charts[id]) charts[id] = echarts.init(el);
      }
    }

    function render() {
      const d = data.value;
      if (!d || !d.dates || !d.dates.length) return;
      initCharts();
      const base = { type: "category", data: d.dates, boundaryGap: false };
      charts["chart-nav"] && charts["chart-nav"].setOption({
        animation: false,
        tooltip: { trigger: "axis", valueFormatter: v => v?.toFixed(3) },
        legend: { data: ["多头Top10%净值", "市场等权基准"], top: 0 },
        grid: { left: 55, right: 20, top: 30, bottom: 46 },
        dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
        xAxis: base,
        yAxis: { scale: true },
        series: [
          { name: "多头Top10%净值", type: "line", data: d.nav_top, showSymbol: false,
            lineStyle: { width: 2, color: UP }, itemStyle: { color: UP },
            areaStyle: { opacity: 0.06 } },
          { name: "市场等权基准", type: "line", data: d.nav_base, showSymbol: false,
            lineStyle: { width: 1, color: GRAY, type: "dashed" },
            itemStyle: { color: GRAY } },
        ],
      }, true);
      charts["chart-ic"] && charts["chart-ic"].setOption({
        animation: false,
        tooltip: { trigger: "axis" },
        grid: { left: 55, right: 20, top: 20, bottom: 46 },
        dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
        xAxis: base,
        yAxis: { scale: true },
        series: [{ type: "bar", data: d.ric.map(v => ({
          value: v, itemStyle: { color: v >= 0 ? BLUE : DOWN } }) ) }],
      }, true);
    }

    async function load() {
      loading.value = true;
      error.value = "";
      computing.value = false;
      const timer = setTimeout(() => { computing.value = true; }, 3000);
      try {
        const res = await fetch(`/api/pvfactor/overview?days=${days.value}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        data.value = await res.json();
        latest.value = data.value.latest;
        topList.value = data.value.top_list || [];
        render();
      } catch (e) {
        error.value = e.message;
      } finally {
        clearTimeout(timer);
        computing.value = false;
        loading.value = false;
      }
    }

    watch(days, () => {
      const p = new URLSearchParams({ days: days.value });
      history.replaceState(null, "", `/predict/pvfactor?${p}`);
      load();
    });
    onMounted(() => {
      initCharts();
      load();
      window.addEventListener("resize",
        () => Object.values(charts).forEach(c => c.resize()));
    });
    return { days, dayOptions, loading, computing, error, latest, topList };
  },
});

app.mount("#app");
