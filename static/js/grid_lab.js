// 网格交易实验室：参数表单 → 回测 API → 指标卡 + 净值曲线 + 交易明细
const { createApp, computed, nextTick, onMounted, ref } = Vue;

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
      const el = document.getElementById("chart");
      if (!el) return;  // v-if 尚未渲染（防御）
      if (!chart) chart = echarts.init(el);

      const { dates, prices, adj, base_hfq, grid_pct, grid_jrange, trades } = r;
      const g = grid_pct / 100;
      // 每条格线的原始价格序列（除权日跳变，符合实际网格重划）
      const gridSeries = [];
      for (let j = grid_jrange[0]; j <= grid_jrange[1]; j++) {
        gridSeries.push({
          type: "line", xAxisIndex: 0, yAxisIndex: 0,
          data: adj.map(a => +(base_hfq * Math.pow(1 + g, j) / a).toFixed(4)),
          showSymbol: false, silent: true, z: 1,
          lineStyle: { width: 0.8, type: "dashed", color: "#cbd5e1" },
          itemStyle: { color: "#cbd5e1" },
        });
      }
      const buys = trades.filter(t => t.side === "买");
      const sells = trades.filter(t => t.side === "卖");

      chart.setOption({
        animation: false,
        axisPointer: { link: [{ xAxisIndex: "all" }] },
        tooltip: {
          trigger: "axis",
          formatter: params => {
            let out = `<b>${params[0].axisValue}</b>`;
            for (const p of params) {
              if (p.seriesName === "价格") out += `<br/>价格 ${p.value}`;
              else if (p.seriesName === "买入")
                out += `<br/><span style="color:#ef4444">▲ 买入 ${Number(p.value[2]).toLocaleString()} 份 @ ${p.value[1]}</span>`;
              else if (p.seriesName === "卖出")
                out += `<br/><span style="color:#22c55e">▼ 卖出 ${Number(p.value[2]).toLocaleString()} 份 @ ${p.value[1]}</span>`
                     + (p.value[3] != null ? `（盈亏 ${p.value[3]}）` : "");
              else if (p.seriesName === "网格净值")
                out += `<br/>网格净值 ${(p.value / 10000).toFixed(2)}万`;
              else if (p.seriesName === "买入持有")
                out += `<br/>持有净值 ${(p.value / 10000).toFixed(2)}万`;
            }
            return out;
          },
        },
        legend: { data: ["价格", "买入", "卖出", "网格净值", "买入持有"], top: 0 },
        grid: [
          { left: 60, right: 20, top: 32, height: "50%" },
          { left: 60, right: 20, top: "68%", height: "20%" },
        ],
        xAxis: [
          { type: "category", data: dates, boundaryGap: false,
            axisLabel: { show: false } },
          { type: "category", gridIndex: 1, data: dates, boundaryGap: false },
        ],
        yAxis: [
          { scale: true },
          { gridIndex: 1, scale: true,
            axisLabel: { formatter: v => (v / 10000).toFixed(1) + "万" },
            splitLine: { show: false } },
        ],
        dataZoom: [
          { type: "inside", xAxisIndex: [0, 1] },
          { type: "slider", xAxisIndex: [0, 1], height: 18, bottom: 8 },
        ],
        series: [
          { name: "价格", type: "line", xAxisIndex: 0, yAxisIndex: 0,
            data: prices, showSymbol: false, z: 3,
            lineStyle: { width: 1.6, color: "#334155" }, itemStyle: { color: "#334155" } },
          ...gridSeries,
          { name: "买入", type: "scatter", xAxisIndex: 0, yAxisIndex: 0, z: 5,
            data: buys.map(t => [t.date, t.price, t.qty]),
            symbol: "triangle", symbolSize: 10,
            itemStyle: { color: "#ef4444" } },
          { name: "卖出", type: "scatter", xAxisIndex: 0, yAxisIndex: 0, z: 5,
            data: sells.map(t => [t.date, t.price, t.qty, t.pnl]),
            symbol: "triangle", symbolRotate: 180, symbolSize: 10,
            itemStyle: { color: "#22c55e" } },
          { name: "网格净值", type: "line", xAxisIndex: 1, yAxisIndex: 1,
            data: r.equity, showSymbol: false,
            lineStyle: { width: 2, color: "#3b82f6" }, itemStyle: { color: "#3b82f6" } },
          { name: "买入持有", type: "line", xAxisIndex: 1, yAxisIndex: 1,
            data: r.bh, showSymbol: false,
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
        await nextTick();  // 等 v-if 的图表容器进入 DOM
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
