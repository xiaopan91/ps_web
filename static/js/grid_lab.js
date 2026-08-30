// 网格交易实验室：参数表单 → 回测 API → 指标卡 + 净值曲线 + 交易明细
const { createApp, computed, onMounted, ref } = Vue;

const app = createApp({
  setup() {
    const targets = ref([]);
    const result = ref(null);
    const loading = ref(false);
    const error = ref("");

    // URL 参数 <-> 表单
    const p = new URLSearchParams(location.search);
    const code = ref(p.get("code") || "510300.SH");
    const start = ref(p.get("start") || "2016-01-04");
    const gridPct = ref(parseFloat(p.get("pct")) || 5);
    const nGrids = ref(parseInt(p.get("n")) || 10);
    const cash = ref(parseFloat(p.get("cash")) || 100000);

    const m = computed(() => result.value ? result.value.metrics : null);
    const trades = computed(() => result.value ? result.value.trades : []);

    const pct = v => (v * 100).toFixed(2) + "%";

    let chart = null;

    function render() {
      const r = result.value;
      if (!r) return;
      if (!chart) chart = echarts.init(document.getElementById("chart"));
      chart.setOption({
        animation: false,
        tooltip: { trigger: "axis" },
        legend: { data: ["网格净值", "买入持有"], top: 0 },
        grid: { left: 60, right: 20, top: 32, bottom: 46 },
        dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
        xAxis: { type: "category", data: r.dates, boundaryGap: false },
        yAxis: { scale: true, axisLabel: { formatter: v => (v / 10000).toFixed(1) + "万" } },
        series: [
          { name: "网格净值", type: "line", data: r.equity, showSymbol: false,
            lineStyle: { width: 2, color: "#3b82f6" }, itemStyle: { color: "#3b82f6" },
            areaStyle: { opacity: 0.06 } },
          { name: "买入持有", type: "line", data: r.bh, showSymbol: false,
            lineStyle: { width: 1, color: "#94a3b8" }, itemStyle: { color: "#94a3b8" } },
        ],
      }, true);
    }

    async function run() {
      loading.value = true;
      error.value = "";
      try {
        const s = start.value.replaceAll("-", "");
        const qs = new URLSearchParams({
          code: code.value, start: s,
          grid_pct: gridPct.value, n_grids: nGrids.value, cash: cash.value,
        });
        const res = await fetch(`/api/strategy/grid/backtest?${qs}`);
        if (!res.ok) {
          const msg = await res.json().catch(() => ({}));
          throw new Error(msg.detail || `HTTP ${res.status}`);
        }
        result.value = await res.json();
        const u = new URLSearchParams({
          code: code.value, start: s, pct: gridPct.value,
          n: nGrids.value, cash: cash.value,
        });
        history.replaceState(null, "", `/strategy/grid?${u}`);
        render();
      } catch (e) {
        error.value = e.message;
      } finally {
        loading.value = false;
      }
    }

    onMounted(async () => {
      try {
        const res = await fetch("/api/strategy/grid/targets");
        targets.value = await res.json();
        if (!targets.value.some(t => t.ts_code === code.value) && targets.value.length) {
          code.value = targets.value[0].ts_code;
        }
      } catch (e) { /* 标的列表失败不阻塞 */ }
      run();
      window.addEventListener("resize", () => chart && chart.resize());
    });

    return { targets, code, start, gridPct, nGrids, cash, result, m, trades,
             loading, error, run, pct };
  },
});

app.mount("#app");
