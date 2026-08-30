// 指数行情页：下拉选择 + K线（MA/成交额副图）+ 区间切换 + URL 参数
const { createApp, onMounted, ref, watch } = Vue;

const UP = "#ef4444";    // 红涨
const DOWN = "#22c55e";  // 绿跌
const MA_COLORS = { 5: "#f59e0b", 10: "#3b82f6", 20: "#a855f7", 60: "#64748b" };

const app = createApp({
  setup() {
    const indices = ref([]);
    const info = ref(null);
    const latest = ref(null);
    const loading = ref(false);
    const error = ref("");

    const ranges = [
      { k: "3m", label: "3月" }, { k: "6m", label: "6月" }, { k: "1y", label: "1年" },
      { k: "3y", label: "3年" }, { k: "all", label: "全部" },
    ];

    // URL 参数 <-> 状态（分享/收藏）
    function readUrl() {
      const p = new URLSearchParams(location.search);
      const range = ranges.some(r => r.k === p.get("range")) ? p.get("range") : "1y";
      return { code: p.get("code") || "000001.SH", range };
    }
    const init = readUrl();
    const code = ref(init.code);
    const range = ref(init.range);

    function syncUrl() {
      const p = new URLSearchParams({ code: code.value, range: range.value });
      history.replaceState(null, "", `/index?${p}`);
    }

    let chart = null;

    function ma(closes, n) {
      const out = [];
      let sum = 0;
      for (let i = 0; i < closes.length; i++) {
        sum += closes[i];
        if (i >= n) sum -= closes[i - n];
        out.push(i >= n - 1 ? +(sum / n).toFixed(3) : null);
      }
      return out;
    }

    function render(bars) {
      if (!chart) chart = echarts.init(document.getElementById("chart"));
      const dates = bars.map(b => b.d);
      const candles = bars.map(b => [b.o, b.c, b.l, b.h]);
      const closes = bars.map(b => b.c);
      const amounts = bars.map(b => ({
        value: b.v,
        itemStyle: { color: b.c >= b.o ? UP : DOWN },
      }));
      const maSeries = Object.keys(MA_COLORS).map(n => ({
        name: `MA${n}`,
        type: "line",
        data: ma(closes, +n),
        showSymbol: false,
        smooth: true,
        lineStyle: { width: 1, color: MA_COLORS[n] },
        itemStyle: { color: MA_COLORS[n] },
      }));

      chart.setOption({
        animation: false,
        tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
        axisPointer: { link: [{ xAxisIndex: "all" }] },
        legend: { top: 5, data: maSeries.map(s => s.name) },
        grid: [
          { left: 70, right: 20, top: 35, height: "58%" },
          { left: 70, right: 20, top: "76%", height: "14%" },
        ],
        xAxis: [
          { type: "category", data: dates, boundaryGap: true },
          { type: "category", gridIndex: 1, data: dates, boundaryGap: true, axisLabel: { show: false } },
        ],
        yAxis: [
          { scale: true, splitArea: { show: true } },
          { gridIndex: 1, axisLabel: { formatter: v => v.toFixed(0) + "亿" }, splitNumber: 2 },
        ],
        dataZoom: [
          { type: "inside", xAxisIndex: [0, 1], start: 40, end: 100 },
          { type: "slider", xAxisIndex: [0, 1], top: "93%", start: 40, end: 100 },
        ],
        series: [
          {
            name: "K线",
            type: "candlestick",
            data: candles,
            itemStyle: { color: UP, color0: DOWN, borderColor: UP, borderColor0: DOWN },
          },
          ...maSeries,
          { name: "成交额", type: "bar", data: amounts, xAxisIndex: 1, yAxisIndex: 1 },
        ],
      }, true);
    }

    async function load() {
      loading.value = true;
      error.value = "";
      try {
        const res = await fetch(`/api/index/daily?code=${code.value}&range=${range.value}`);
        if (!res.ok) {
          const msg = await res.json().catch(() => ({}));
          throw new Error(msg.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        info.value = data.info;
        latest.value = data.latest;
        if (data.info && data.info.name) {
          document.title = `${data.info.name} ${data.info.ts_code} · ps_web`;
        }
        if (!data.bars.length) error.value = "该区间没有数据";
        render(data.bars);
      } catch (e) {
        error.value = e.message;
      } finally {
        loading.value = false;
      }
    }

    watch([code, range], () => { syncUrl(); load(); });
    onMounted(async () => {
      try {
        const res = await fetch("/api/index/list");
        indices.value = await res.json();
        if (!indices.value.some(i => i.ts_code === code.value) && indices.value.length) {
          code.value = indices.value[0].ts_code;
        }
      } catch (e) { /* 下拉加载失败不影响图表 */ }
      load();
      window.addEventListener("resize", () => chart && chart.resize());
    });

    return { indices, code, range, info, latest, loading, error, ranges };
  },
});

app.mount("#app");
