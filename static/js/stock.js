// 个股行情页：搜索 + 日线 K 线图（K线/成交量/MA，三档复权）+ 个股分析区
const { createApp, computed, nextTick, onMounted, ref, watch } = Vue;

const UP = "#ef4444";    // A股红涨
const DOWN = "#22c55e";  // 绿跌
const BLUE = "#3b82f6";
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

    // ---- 个股分析区（折叠，懒加载） ----
    const anaOpen = ref(false);
    const anaLoading = ref(false);
    const anaError = ref("");
    const anaLoaded = ref(false);
    const metrics = ref(null);  // /api/stock/metrics
    const factor = ref(null);   // /api/pvfactor/stock
    const anaCharts = {};       // id -> echarts 实例

    async function loadAnalysis() {
      anaLoading.value = true;
      anaError.value = "";
      try {
        const [mRes, fRes] = await Promise.all([
          fetch(`/api/stock/metrics?code=${code.value}&range=${range.value}`),
          fetch(`/api/pvfactor/stock?code=${code.value}&days=500`),
        ]);
        if (!mRes.ok) {
          const msg = await mRes.json().catch(() => ({}));
          throw new Error(msg.detail || `HTTP ${mRes.status}`);
        }
        metrics.value = await mRes.json();
        factor.value = fRes.ok ? await fRes.json() : null;
        anaLoaded.value = true;
        render(barsCache);          // 主图叠加相对强弱
        await nextTick();
        renderAnalysis();
      } catch (e) {
        anaError.value = e.message || "分析数据加载失败";
      } finally {
        anaLoading.value = false;
      }
    }

    watch(anaOpen, open => {
      if (open && !anaLoaded.value) loadAnalysis();
      else if (open) nextTick(() => resizeAna());
    });

    const stats = computed(() => metrics.value?.stats || null);

    const statCards = computed(() => {
      const s = stats.value;
      const f = factor.value?.summary;
      if (!s) return [];
      const fmt = (v, d = 2, suf = "") => (v == null ? "—" : v.toFixed(d) + suf);
      return [
        { label: "量价综合分", value: f ? f.score.toFixed(3) : "—",
          sub: f ? `第 ${f.rank} / ${f.total} · 进前10% ${f.top10_pct}% 天` : "因子表重建中" },
        { label: "年初至今", value: fmt(s.ytd, 2, "%"),
          cls: s.ytd == null ? "" : (s.ytd >= 0 ? "up" : "down"),
          sub: s.ann_vol != null ? `年化波动 ${s.ann_vol}%` : "" },
        { label: "52周区间", value: `${s.low_52w} ~ ${s.high_52w}`,
          sub: s.pos60 != null ? `60日位置 ${s.pos60}%` : "" },
        { label: "PE(TTM)", value: fmt(s.pe), sub: s.pe == null ? "亏损或缺失" : "" },
        { label: "换手率(流通)", value: fmt(s.turnover_f, 2, "%"),
          sub: s.amp20 != null ? `20日均振幅 ${s.amp20}%` : "" },
        { label: "量比", value: fmt(s.volume_ratio) },
        { label: "流通市值", value: fmt(s.circ_mv, 1, "亿"),
          sub: s.total_mv != null ? `总市值 ${s.total_mv} 亿` : "" },
        { label: "ATR20", value: fmt(s.atr20, 2, "%"), sub: "格距/止损参考" },
      ];
    });

    function anaChart(id) {
      if (!anaCharts[id]) anaCharts[id] = echarts.init(document.getElementById(id));
      return anaCharts[id];
    }

    function resizeAna() {
      Object.values(anaCharts).forEach(c => c.resize());
    }

    function tsAxis(dates) {
      return { type: "category", data: dates, boundaryGap: true,
               axisLabel: { formatter: v => v.slice(2) } };
    }

    function renderAnalysis() {
      const m = metrics.value;
      if (!m) return;
      const d = m.dates;

      // 量价因子综合分
      const f = factor.value;
      const factorEmpty = !f || !f.dates || !f.dates.length;
      anaChart("chart-factor").setOption({
        animation: false,
        tooltip: { trigger: "axis" },
        grid: { left: 45, right: 15, top: 20, bottom: 45 },
        xAxis: tsAxis(factorEmpty ? [] : f.dates),
        yAxis: { min: 0, max: 1, splitNumber: 4 },
        dataZoom: [{ type: "inside" }],
        title: factorEmpty ? {
          text: "暂无因子数据（pv_rank 可能重建中）", left: "center", top: "middle",
          textStyle: { color: "#94a3b8", fontSize: 13, fontWeight: "normal" },
        } : undefined,
        series: factorEmpty ? [] : [{
          name: "综合分", type: "line", data: f.scores, showSymbol: false,
          lineStyle: { width: 1.2, color: BLUE }, itemStyle: { color: BLUE },
          areaStyle: { opacity: 0.06, color: BLUE },
          markLine: { symbol: "none", silent: true, label: { show: false },
            data: [{ yAxis: 0.5, lineStyle: { type: "dashed", color: "#94a3b8" } }] },
          markArea: { silent: true, itemStyle: { color: "rgba(239,68,68,.06)" },
            data: [[{ yAxis: 0.9 }, { yAxis: 1 }]] },
        }],
      }, true);

      // 波动与位置：振幅(柱) × pos60(线)
      anaChart("chart-vol").setOption({
        animation: false,
        tooltip: { trigger: "axis" },
        legend: { top: 0, textStyle: { fontSize: 11 }, itemWidth: 14,
                  data: ["日振幅%", "60日位置%"] },
        grid: { left: 45, right: 45, top: 26, bottom: 45 },
        xAxis: tsAxis(d),
        yAxis: [
          { splitNumber: 3 },
          { gridIndex: 0, min: 0, max: 100, splitNumber: 3, splitLine: { show: false } },
        ],
        dataZoom: [{ type: "inside" }],
        series: [
          { name: "日振幅%", type: "bar", data: m.amp, yAxisIndex: 0,
            itemStyle: { color: "#cbd5e1" }, barMaxWidth: 4 },
          { name: "60日位置%", type: "line", data: m.pos60, yAxisIndex: 1,
            showSymbol: false, lineStyle: { width: 1.2, color: BLUE },
            itemStyle: { color: BLUE } },
        ],
      }, true);

      // 换手与量比
      anaChart("chart-turnover").setOption({
        animation: false,
        tooltip: { trigger: "axis" },
        legend: { top: 0, textStyle: { fontSize: 11 }, itemWidth: 14,
                  data: ["换手率%", "量比"] },
        grid: { left: 45, right: 45, top: 26, bottom: 45 },
        xAxis: tsAxis(d),
        yAxis: [
          { splitNumber: 3 },
          { splitNumber: 3, splitLine: { show: false } },
        ],
        dataZoom: [{ type: "inside" }],
        series: [
          { name: "换手率%", type: "line", data: m.turnover_f, showSymbol: false,
            lineStyle: { width: 1.2, color: "#f59e0b" }, itemStyle: { color: "#f59e0b" } },
          { name: "量比", type: "bar", data: m.volume_ratio, yAxisIndex: 1,
            itemStyle: { color: "rgba(148,163,184,.5)" }, barMaxWidth: 4 },
        ],
      }, true);

      // 估值：PE × 流通市值
      anaChart("chart-val").setOption({
        animation: false,
        tooltip: { trigger: "axis" },
        legend: { top: 0, textStyle: { fontSize: 11 }, itemWidth: 14,
                  data: ["PE(TTM)", "流通市值(亿)"] },
        grid: { left: 50, right: 55, top: 26, bottom: 45 },
        xAxis: tsAxis(d),
        yAxis: [
          { splitNumber: 3 },
          { splitNumber: 3, splitLine: { show: false } },
        ],
        dataZoom: [{ type: "inside" }],
        series: [
          { name: "PE(TTM)", type: "line", data: m.pe, showSymbol: false, connectNulls: false,
            lineStyle: { width: 1.2, color: "#a855f7" }, itemStyle: { color: "#a855f7" } },
          { name: "流通市值(亿)", type: "line", data: m.circ_mv, yAxisIndex: 1,
            showSymbol: false, lineStyle: { width: 1.2, color: "#f59e0b" },
            itemStyle: { color: "#f59e0b" } },
        ],
      }, true);
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

      // 主图布局：K线 / 成交量 / 相对沪深300（metrics 加载后有第三格）
      const m = metrics.value;
      const hasRs = !!(m && m.rs && m.rs.some(v => v != null));
      const grids = hasRs
        ? [
            { left: 60, right: 20, top: 35, height: "48%" },
            { left: 60, right: 20, top: "62%", height: "9%" },
            { left: 60, right: 20, top: "76%", height: "11%" },
          ]
        : [
            { left: 60, right: 20, top: 35, height: "58%" },
            { left: 60, right: 20, top: "76%", height: "14%" },
          ];
      const rsSeries = hasRs ? [{
        name: "相对沪深300",
        type: "line",
        data: m.rs,
        xAxisIndex: 2, yAxisIndex: 2,
        showSymbol: false,
        lineStyle: { width: 1.2, color: "#0ea5e9" },
        itemStyle: { color: "#0ea5e9" },
        areaStyle: { opacity: 0.05, color: "#0ea5e9" },
        markLine: { symbol: "none", silent: true, label: { show: false },
          data: [{ yAxis: 1, lineStyle: { type: "dashed", color: "#94a3b8" } }] },
      }] : [];
      const zoomIndex = hasRs ? [0, 1, 2] : [0, 1];

      chart.setOption({
        animation: false,
        tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
        axisPointer: { link: [{ xAxisIndex: "all" }] },
        legend: { top: 5, data: [...maSeries.map(s => s.name),
                                 ...(hasRs ? ["相对沪深300"] : [])] },
        grid: grids,
        xAxis: hasRs ? [
          { type: "category", data: dates, boundaryGap: true },
          { type: "category", gridIndex: 1, data: dates, boundaryGap: true, axisLabel: { show: false } },
          { type: "category", gridIndex: 2, data: dates, boundaryGap: true, axisLabel: { show: false } },
        ] : [
          { type: "category", data: dates, boundaryGap: true },
          { type: "category", gridIndex: 1, data: dates, boundaryGap: true, axisLabel: { show: false } },
        ],
        yAxis: hasRs ? [
          { scale: true, splitArea: { show: true } },
          { gridIndex: 1, axisLabel: { formatter: v => (v / 10000).toFixed(0) + "万" }, splitNumber: 2 },
          { gridIndex: 2, scale: true, splitNumber: 2,
            axisLabel: { formatter: v => v.toFixed(2) } },
        ] : [
          { scale: true, splitArea: { show: true } },
          { gridIndex: 1, axisLabel: { formatter: v => (v / 10000).toFixed(0) + "万" }, splitNumber: 2 },
        ],
        dataZoom: [
          { type: "inside", xAxisIndex: zoomIndex, start: 40, end: 100 },
          { type: "slider", xAxisIndex: zoomIndex, top: "92%", start: 40, end: 100 },
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
          ...rsSeries,
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
    // 分析区随股票/区间联动刷新（adjust 不影响分析口径，不必重拉）
    watch([code, range], () => {
      if (anaOpen.value || anaLoaded.value) loadAnalysis();
    });

    onMounted(() => {
      load();
      window.addEventListener("resize", () => {
        if (chart) chart.resize();
        resizeAna();
      });
    });

    return { query, suggests, code, range, adjust, info, latest, loading, error,
             ranges, adjusts, onInput, pick,
             anaOpen, anaLoading, anaError, stats, statCards, factor };
  },
});

app.mount("#app");
