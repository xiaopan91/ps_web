// 板块详情页：趋势图 + 成分股清单
const { createApp, computed, nextTick, onMounted, ref, watch } = Vue;

const app = createApp({
  setup() {
    const info = ref({});
    const trend = ref(null);
    const members = ref([]);
    const loading = ref(false);
    const error = ref("");
    const days = ref(250);
    const dayOpts = [120, 250, 500, 1000];
    const keyword = ref("");
    const sortKey = ref("amount");
    const sortAsc = ref(false);
    const charts = {};

    function readUrl() {
      const p = new URLSearchParams(location.search);
      if (p.get("board")) info.value = { board_code: p.get("board") };
      if (p.get("days")) days.value = +p.get("days") || 250;
    }
    readUrl();

    function syncUrl() {
      const p = new URLSearchParams({ board: info.value.board_code, days: days.value });
      history.replaceState(null, "", `/industry/detail?${p}`);
    }

    async function loadAll() {
      loading.value = true;
      error.value = "";
      const code = info.value.board_code;
      try {
        const [tRes, mRes] = await Promise.all([
          fetch(`/api/industry/detail?board_code=${encodeURIComponent(code)}&days=${days.value}`),
          fetch(`/api/industry/members?board_code=${encodeURIComponent(code)}`),
        ]);
        if (!tRes.ok || !mRes.ok) {
          const msg = await (tRes.ok ? mRes : tRes).json().catch(() => ({}));
          throw new Error(msg.detail || `HTTP ${tRes.status}`);
        }
        trend.value = await tRes.json();
        const m = await mRes.json();
        info.value = { board_code: m.board_code, name: m.board_name, type: m.board_type };
        members.value = m.members;
        syncUrl();
        document.title = `${m.board_name} · 板块详情 · ps_web`;
        await nextTick();
        renderCharts();
      } catch (e) {
        error.value = e.message || "加载失败";
      } finally {
        loading.value = false;
      }
    }

    const isTheme = computed(() => info.value.type === "theme");
    const typeName = computed(() => ({
      sw_l1: "申万一级", sw_l2: "申万二级", sw_l3: "申万三级", theme: "主题指数",
    }[info.value.type] || ""));

    const snapCards = computed(() => {
      const d = trend.value;
      if (!d || !d.dates.length) return [];
      const last = d.dates.length - 1;
      const pct = (a, b) => (a == null || b ? null : +((a / b - 1) * 100).toFixed(2));
      const n = d.dates.length;
      const navLast = d.nav_eq[last], nav5 = d.nav_eq[Math.max(0, last - 5)];
      const nav20 = d.nav_eq[Math.max(0, last - 20)];
      const r5 = pct(navLast, nav5), r20 = pct(navLast, nav20);
      const cls = v => (v == null ? "" : (v >= 0 ? "up" : "down"));
      return [
        { label: "5日涨幅", value: r5 == null ? "—" : r5 + "%", cls: cls(r5) },
        { label: "20日涨幅", value: r20 == null ? "—" : r20 + "%", cls: cls(r20) },
        { label: "上涨占比", value: d.up_ratio[last] == null ? "—" : d.up_ratio[last] + "%" },
        { label: "成交占比", value: d.amount_share[last] == null ? "—" : d.amount_share[last] + "%" },
        { label: "换手中位", value: d.turnover_med[last] == null ? "—" : d.turnover_med[last] + "%" },
      ];
    });

    function chart(id) {
      if (!charts[id]) charts[id] = echarts.init(document.getElementById(id));
      return charts[id];
    }

    function renderCharts() {
      const d = trend.value;
      if (!d) return;
      const mk = (name, data, color, extra = {}) => ({
        name, type: "line", data, showSymbol: false,
        lineStyle: { width: 1.3, color, ...extra }, itemStyle: { color },
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
        grid: { left: 55, right: 15, top: 28, bottom: 45 },
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

      // 历史排名曲线（1 = 同类最强，y 轴反转使强者在上）
      if (d.rank_hist && d.rank_hist.length) {
        const maxRank = Math.max(...d.rank_hist.filter(v => v != null), d.hot_n || 10);
        chart("chart-rank").setOption({
          animation: false,
          tooltip: { trigger: "axis", valueFormatter: v => v == null ? "—" : "第 " + v + " 名" },
          grid: { left: 45, right: 15, top: 15, bottom: 40 },
          xAxis: { type: "category", data: d.dates },
          yAxis: { inverse: true, min: 1, max: Math.ceil(maxRank / 10) * 10,
                   splitNumber: 3, name: "名次", nameTextStyle: { fontSize: 10 } },
          dataZoom: [{ type: "inside" }],
          series: [{
            name: "涨幅排名", type: "line", data: d.rank_hist, showSymbol: false,
            connectNulls: false, lineStyle: { width: 1.2, color: "#0ea5e9" },
            itemStyle: { color: "#0ea5e9" },
            areaStyle: { opacity: 0.06, color: "#0ea5e9" },
            markLine: {
              symbol: "none", silent: true,
              data: [{ yAxis: d.hot_n || 10,
                       lineStyle: { type: "dashed", color: "#ef4444" },
                       label: { formatter: "上榜线 " + (d.hot_n || 10), color: "#ef4444", fontSize: 10 } }],
            },
          }],
        }, true);
      }
    }

    const filteredMembers = computed(() => {
      const kw = keyword.value.trim();
      const list = kw
        ? members.value.filter(m => m.ts_code.includes(kw) || (m.name || "").includes(kw))
        : members.value;
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
    function xcls(v) { return v == null ? "" : (v >= 0 ? "up" : "down"); }
    function gotoStock(code) {
      window.open(`/stock?code=${code}`, "_blank");
    }

    watch(days, loadAll);

    onMounted(loadAll);
    window.addEventListener("resize", () =>
      Object.values(charts).forEach(c => c.resize()));

    return {
      info, trend, members, loading, error, days, dayOpts,
      isTheme, typeName, snapCards,
      keyword, filteredMembers, sortBy, fx, xcls, gotoStock,
    };
  },
});

app.mount("#app");
