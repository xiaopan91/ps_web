// 个股行情页：搜索 + 日线 K 线图（K线/成交量/MA，三档复权）
const { createApp, onMounted, ref, watch } = Vue;

const UP = "#ef4444";    // A股红涨
const DOWN = "#22c55e";  // 绿跌
const MA_COLORS = { 5: "#f59e0b", 10: "#3b82f6", 20: "#a855f7", 60: "#64748b" };

const app = createApp({
  setup() {
    const query = ref("");
    const suggests = ref([]);
    const info = ref(null);
    const latest = ref(null);
    const loading = ref(false);
    const error = ref("");

    const ranges = [
      { k: "3m", label: "3月" }, { k: "6m", label: "6月" }, { k: "1y", label: "1年" },
      { k: "3y", label: "3年" }, { k: "all", label: "全部" },
    ];
    const adjusts = [
      { k: "qfq", label: "前复权" }, { k: "none", label: "不复权" }, { k: "hfq", label: "后复权" },
    ];

    // ---- URL 参数 <-> 页面状态 双向同步（方便分享/收藏） ----
    function readUrl() {
      const p = new URLSearchParams(location.search);
      const code = p.get("code") || "000001.SZ";
      const range = ranges.some(r => r.k === p.get("range")) ? p.get("range") : "1y";
      const adjust = adjusts.some(a => a.k === p.get("adjust")) ? p.get("adjust") : "qfq";
      return { code, range, adjust };
    }
    const init = readUrl();
    const code = ref(init.code);
    const range = ref(init.range);
    const adjust = ref(init.adjust);

    function syncUrl() {
      const p = new URLSearchParams({
        code: code.value, range: range.value, adjust: adjust.value,
      });
      history.replaceState(null, "", `/stock?${p}`);
    }

    let searchTimer = null;
    function onInput() {
      clearTimeout(searchTimer);
      const q = query.value.trim();
      if (!q) { suggests.value = []; return; }
      searchTimer = setTimeout(async () => {
        try {
          const res = await fetch(`/api/stock/search?q=${encodeURIComponent(q)}`);
          suggests.value = await res.json();
        } catch (e) { /* 忽略搜索失败 */ }
      }, 250);
    }

    function pick(s) {
      code.value = s.ts_code;
      query.value = `${s.name}`;
      suggests.value = [];
    }

    let chart = null;
    let barsCache = [];

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
      // ECharts K线数据顺序：[开盘, 收盘, 最低, 最高]
      const candles = bars.map(b => [b.o, b.c, b.l, b.h]);
      const closes = bars.map(b => b.c);
      const vols = bars.map((b, i) => ({
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
        xAxisIndex: 0, yAxisIndex: 0,
      }));

      chart.setOption({
        animation: false,
        tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
        axisPointer: { link: [{ xAxisIndex: "all" }] },
        legend: { top: 5, data: maSeries.map(s => s.name) },
        grid: [
          { left: 60, right: 20, top: 35, height: "58%" },
          { left: 60, right: 20, top: "76%", height: "14%" },
        ],
        xAxis: [
          { type: "category", data: dates, boundaryGap: true },
          { type: "category", gridIndex: 1, data: dates, boundaryGap: true, axisLabel: { show: false } },
        ],
        yAxis: [
          { scale: true, splitArea: { show: true } },
          { gridIndex: 1, axisLabel: { formatter: v => (v / 10000).toFixed(0) + "万" }, splitNumber: 2 },
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
          { name: "成交量", type: "bar", data: vols, xAxisIndex: 1, yAxisIndex: 1 },
        ],
      }, true);
    }

    async function load() {
      loading.value = true;
      error.value = "";
      try {
        const res = await fetch(
          `/api/stock/daily?code=${code.value}&range=${range.value}&adjust=${adjust.value}`);
        if (!res.ok) {
          const msg = await res.json().catch(() => ({}));
          throw new Error(msg.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        info.value = data.info;
        latest.value = data.latest;
        barsCache = data.bars;
        if (data.info && data.info.name) {
          query.value = data.info.name;
          document.title = `${data.info.name} ${data.info.ts_code} · ps_web`;
        }
        if (!data.bars.length) error.value = "该区间没有数据（回补可能还在进行中）";
        render(data.bars);
      } catch (e) {
        error.value = e.message;
      } finally {
        loading.value = false;
      }
    }

    watch([code, range, adjust], () => { syncUrl(); load(); });
    onMounted(() => {
      load();
      window.addEventListener("resize", () => chart && chart.resize());
    });

    return { query, suggests, code, range, adjust, info, latest, loading, error,
             ranges, adjusts, onInput, pick };
  },
});

app.mount("#app");
