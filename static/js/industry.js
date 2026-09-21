// 行业观察：行业动量表 + 单行业趋势详情
const { createApp, computed, nextTick, onMounted, ref, watch } = Vue;

const app = createApp({
  setup() {
    const rows = ref([]);
    const summary = ref(null);
    const loading = ref(false);
    const keyword = ref("");
    const sortKey = ref("r20");
    const sortAsc = ref(false);
    const sel = ref(null);
    const days = ref(250);
    const dayOpts = [120, 250, 500, 1000];
    const detail = ref(null);
    const charts = {};

    // ---- URL 参数 ----
    function readUrl() {
      const p = new URLSearchParams(location.search);
      if (p.get("industry")) sel.value = p.get("industry");
      if (p.get("days")) days.value = +p.get("days") || 250;
    }
    readUrl();
    function syncUrl() {
      const p = new URLSearchParams();
      if (sel.value) p.set("industry", sel.value);
      p.set("days", days.value);
      history.replaceState(null, "", `/industry?${p}`);
    }

    async function loadOverview() {
      loading.value = true;
      try {
        const res = await fetch("/api/industry/overview");
        const data = res.ok ? await res.json() : null;
        rows.value = data?.rows || [];
        summary.value = data?.summary || null;
      } catch (e) { /* 静默 */ }
      finally { loading.value = false; }
    }

    async function loadDetail() {
      if (!sel.value) return;
      try {
        const res = await fetch(
          `/api/industry/detail?industry=${encodeURIComponent(sel.value)}&days=${days.value}`);
        detail.value = res.ok ? await res.json() : null;
      } catch (e) { detail.value = null; }
      syncUrl();
      await nextTick();
      renderDetail();
    }

    function selectIndustry(name) {
      sel.value = sel.value === name ? sel.value : name;
      loadDetail();
    }

    const filteredRows = computed(() => {
      const kw = keyword.value.trim();
      const list = kw ? rows.value.filter(r => r.industry.includes(kw)) : rows.value;
      const k = sortKey.value, asc = sortAsc.value;
      return [...list].sort((a, b) => {
        const va = a[k], vb = b[k];
        if (va == null) return 1;
        if (vb == null) return -1;
        if (typeof va === "string") return asc ? va.localeCompare(vb) : vb.localeCompare(va);
        return asc ? va - vb : vb - va;
      });
    });

    function sortBy(k) {
      if (sortKey.value === k) sortAsc.value = !sortAsc.value;
      else { sortKey.value = k; sortAsc.value = false; }
    }

    function fx(v, d = 2) { return v == null ? "—" : v.toFixed(d) + "%"; }
    function fmtYi(v) { return v == null ? "—" : (v / 1e4).toFixed(0); }
    function xcls(v) { return v == null ? "" : (v >= 0 ? "up" : "down"); }

    function chart(id) {
      if (!charts[id]) charts[id] = echarts.init(document.getElementById(id));
      return charts[id];
    }

    function renderDetail() {
      if (!detail.value || !document.getElementById("chart-nav")) return;
      const d = detail.value;
      const mk = (name, data, color, extra = {}) => ({
        name, type: "line", data, showSymbol: false,
        lineStyle: { width: 1.3, color, ...extra }, itemStyle: { color }, ...{},
      });
      chart("chart-nav").setOption({
        animation: false,
        tooltip: { trigger: "axis" },
        legend: { top: 0, textStyle: { fontSize: 11 } },
        grid: { left: 45, right: 15, top: 28, bottom: 45 },
        xAxis: { type: "category", data: d.dates },
        yAxis: { scale: true, splitNumber: 4 },
        dataZoom: [{ type: "inside" }, { type: "slider", height: 16, bottom: 6 }],
        series: [
          mk("等权净值", d.nav_eq, "#3b82f6"),
          mk("加权净值", d.nav_cap, "#a855f7", { type: "dashed", width: 1 }),
          mk("全市场等权", d.mkt_nav, "#f59e0b", { type: "dashed", width: 1 }),
        ],
      }, true);
      chart("chart-rs").setOption({
        animation: false,
        tooltip: { trigger: "axis" },
        grid: { left: 50, right: 15, top: 15, bottom: 40 },
        xAxis: { type: "category", data: d.dates },
        yAxis: { scale: true, splitNumber: 3 },
        dataZoom: [{ type: "inside" }],
        series: [
          mk("RS", d.rs, "#0ea5e9"),
          { name: "100基准", type: "line", data: d.dates.map(() => 100),
            showSymbol: false, lineStyle: { width: 1, type: "dashed", color: "#94a3b8" },
            itemStyle: { color: "#94a3b8" }, tooltip: { show: false } },
        ],
      }, true);
      chart("chart-share").setOption({
        animation: false,
        tooltip: { trigger: "axis", valueFormatter: v => v + "%" },
        legend: { top: 0, textStyle: { fontSize: 11 } },
        grid: { left: 45, right: 15, top: 28, bottom: 40 },
        xAxis: { type: "category", data: d.dates },
        yAxis: [{ scale: true, splitNumber: 3 }, { scale: true, splitNumber: 3, splitLine: { show: false } }],
        dataZoom: [{ type: "inside" }],
        series: [
          { name: "成交占比%", type: "line", data: d.amount_share, showSymbol: false,
            lineStyle: { width: 1.2, color: "#f59e0b" }, itemStyle: { color: "#f59e0b" } },
          { name: "上涨占比%", type: "line", data: d.up_ratio, yAxisIndex: 1, showSymbol: false,
            lineStyle: { width: 1, color: "#94a3b8" }, itemStyle: { color: "#94a3b8" } },
        ],
      }, true);
      Object.values(charts).forEach(c => c.resize());
    }

    watch(days, loadDetail);

    onMounted(async () => {
      await loadOverview();
      if (sel.value) {
        // URL 指定的行业可能不在表里，仅当存在时加载详情
        if (rows.value.some(r => r.industry === sel.value)) loadDetail();
        else sel.value = null;
      }
      window.addEventListener("resize", () =>
        Object.values(charts).forEach(c => c.resize()));
    });

    return {
      rows, summary, loading, keyword, sortBy, filteredRows, sortAsc,
      sel, days, dayOpts, selectIndustry, fx, fmtYi, xcls,
    };
  },
});

app.mount("#app");
