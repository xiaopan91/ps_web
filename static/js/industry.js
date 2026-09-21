// 板块观察：申万层级 / 主题指数的动量表 + 单板块趋势详情
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
    const boardTypes = [
      { k: "sw_l2", label: "申万二级" }, { k: "sw_l1", label: "申万一级" },
      { k: "sw_l3", label: "申万三级" }, { k: "theme", label: "主题指数" },
    ];
    const type = ref("sw_l2");

    // ---- URL 参数 ----
    function readUrl() {
      const p = new URLSearchParams(location.search);
      if (p.get("type") && boardTypes.some(t => t.k === p.get("type"))) type.value = p.get("type");
      if (p.get("industry")) sel.value = p.get("industry");
      if (p.get("days")) days.value = +p.get("days") || 250;
    }
    readUrl();
    function syncUrl() {
      const p = new URLSearchParams({ type: type.value, days: days.value });
      if (sel.value) p.set("industry", sel.value);
      history.replaceState(null, "", `/industry?${p}`);
    }

    let ovSeq = 0;   // 请求序号：快速切换类型时丢弃慢返回的旧响应
    async function loadOverview() {
      const seq = ++ovSeq;
      loading.value = true;
      detail.value = null;
      try {
        const res = await fetch(`/api/industry/overview?type=${type.value}`);
        const data = res.ok ? await res.json() : null;
        if (seq !== ovSeq) return;
        rows.value = data?.rows || [];
        summary.value = data?.summary || null;
        // 类型切换后原选中板块可能不在新列表里，此时才清空
        if (sel.value && !rows.value.some(r => r.industry === sel.value)) sel.value = null;
      } catch (e) { /* 静默 */ }
      finally { if (seq === ovSeq) loading.value = false; }
    }

    async function loadDetail() {
      if (!sel.value) return;
      try {
        const res = await fetch(
          `/api/industry/detail?board_code=${encodeURIComponent(sel.value)}&days=${days.value}`);
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
      const list = kw
        ? rows.value.filter(r => (r.name || "").includes(kw) || (r.industry || "").includes(kw))
        : rows.value;
      const k = sortKey.value, asc = sortAsc.value;
      return [...list].sort((a, b) => {
        const va = a[k], vb = b[k];
        if (va == null) return 1;
        if (vb == null) return -1;
        if (typeof va === "string") return asc ? va.localeCompare(vb) : vb.localeCompare(va);
        return asc ? va - vb : vb - va;
      });
    });

    const detailName = computed(() =>
      detail.value?.board_name || sel.value || "");
    const isTheme = computed(() => detail.value?.board_type === "theme");
    const showCode = computed(() => type.value !== "sw_l1");

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
      const series = isTheme.value
        ? [mk("官方指数净值", d.nav_eq, "#3b82f6"),
           mk("全市场等权", d.mkt_nav, "#f59e0b", { type: "dashed", width: 1 })]
        : [mk("等权净值", d.nav_eq, "#3b82f6"),
           mk("加权净值", d.nav_cap, "#a855f7", { type: "dashed", width: 1 }),
           mk("全市场等权", d.mkt_nav, "#f59e0b", { type: "dashed", width: 1 })];
      chart("chart-nav").setOption({
        animation: false,
        tooltip: { trigger: "axis" },
        legend: { top: 0, textStyle: { fontSize: 11 } },
        grid: { left: 45, right: 15, top: 28, bottom: 45 },
        xAxis: { type: "category", data: d.dates },
        yAxis: { scale: true, splitNumber: 4 },
        dataZoom: [{ type: "inside" }, { type: "slider", height: 16, bottom: 6 }],
        series,
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
    watch(type, () => { syncUrl(); loadOverview(); });

    onMounted(async () => {
      await loadOverview();
      if (sel.value) {
        // URL 指定的板块可能不在当前类型里，仅当存在时加载详情
        if (rows.value.some(r => r.industry === sel.value)) loadDetail();
        else sel.value = null;
      }
      window.addEventListener("resize", () =>
        Object.values(charts).forEach(c => c.resize()));
    });

    return {
      rows, summary, loading, keyword, sortBy, filteredRows, sortAsc,
      boardTypes, type, detailName, isTheme, showCode,
      sel, days, dayOpts, selectIndustry, fx, fmtYi, xcls,
    };
  },
});

app.mount("#app");
