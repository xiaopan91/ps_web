// 定投实验室：等额定投 / 等价值定投 / 一次性买入 对比回测
const { createApp, computed, nextTick, onMounted, ref, watch } = Vue;

const C = { dca: "#3b82f6", va: "#a855f7", lump: "#64748b", index: "#f59e0b" };
const SUFFIX = { dca: "等额定投", va: "等价值定投", lump: "一次性买入" };

const app = createApp({
  setup() {
    const indices = ref([]);
    const tab = ref("dca");
    const code = ref("000300.SH");
    const start = ref("2016-01-01");
    const freq = ref("month");
    const amount = ref(2000);
    const pathType = ref("linear");
    const growth = ref(0);
    const allowSell = ref(true);
    const maxK = ref(3);
    const bt = ref(null);          // /pa/backtest 载荷
    const compare = ref(null);     // /pa/compare 载荷
    const loading = ref(false);
    const error = ref("");
    const sortKey = ref("va_xirr");
    const sortAsc = ref(false);
    const charts = {};

    // ---- URL 参数双向同步 ----
    function readUrl() {
      const p = new URLSearchParams(location.search);
      const t = p.get("tab");
      if (["dca", "va", "compare"].includes(t)) tab.value = t;
      if (p.get("code")) code.value = p.get("code");
      if (p.get("start")) start.value = p.get("start");
      if (p.get("freq")) freq.value = p.get("freq");
      if (p.get("amount")) amount.value = +p.get("amount") || 2000;
      if (p.get("path_type")) pathType.value = p.get("path_type");
      if (p.get("growth")) growth.value = +p.get("growth") || 0;
      if (p.get("allow_sell")) allowSell.value = p.get("allow_sell") === "1";
      if (p.get("k") !== null && p.get("k") !== "") maxK.value = +p.get("k");
    }
    readUrl();

    function syncUrl() {
      const p = new URLSearchParams({
        tab: tab.value, code: code.value, start: start.value, freq: freq.value,
        amount: amount.value, path_type: pathType.value, growth: growth.value,
        allow_sell: allowSell.value ? "1" : "0", k: maxK.value,
      });
      history.replaceState(null, "", `/strategy/pa?${p}`);
    }

    function qs() {
      return new URLSearchParams({
        start: start.value, freq: freq.value, amount: amount.value,
        path_type: pathType.value, growth: growth.value,
        allow_sell: allowSell.value ? "1" : "0", k: maxK.value,
      }).toString();
    }

    async function loadBacktest() {
      loading.value = true;
      error.value = "";
      try {
        const res = await fetch(`/api/strategy/pa/backtest?code=${code.value}&${qs()}`);
        if (!res.ok) {
          const msg = await res.json().catch(() => ({}));
          throw new Error(msg.detail || `HTTP ${res.status}`);
        }
        bt.value = await res.json();
        await nextTick();
        renderTab();
      } catch (e) {
        error.value = e.message || "回测失败";
        bt.value = null;
      } finally {
        loading.value = false;
      }
    }

    async function loadCompare() {
      loading.value = true;
      try {
        const res = await fetch(`/api/strategy/pa/compare?${qs()}`);
        compare.value = res.ok ? await res.json() : null;
        await nextTick();
      } catch (e) { /* 对比失败静默 */ }
      finally { loading.value = false; }
    }

    function chart(id) {
      if (!charts[id]) charts[id] = echarts.init(document.getElementById(id));
      return charts[id];
    }

    function retSeries(s) {
      // 账户/累计投入 − 1（百分比收益率线）；投入为 0 的期跳过
      return s.account.map((a, i) => {
        const c = s.contributed[i];
        return c > 0 ? +((a / c - 1) * 100).toFixed(2) : null;
      });
    }

    function axisDates() { return bt.value.index.dates; }

    function renderAccount(id, keys) {
      const series = keys.map(k => ({
        name: SUFFIX[k], type: "line", data: retSeries(bt.value[k]),
        showSymbol: false, lineStyle: { width: 1.4, color: C[k] },
        itemStyle: { color: C[k] },
      }));
      series.push({
        name: "指数", type: "line", data: bt.value.index.dates.map((d, i) =>
          +((bt.value.index.nav[i] - 1) * 100).toFixed(2)),
        showSymbol: false, lineStyle: { width: 1, color: C.index, type: "dashed" },
        itemStyle: { color: C.index },
      });
      chart(id).setOption({
        animation: false,
        tooltip: { trigger: "axis", valueFormatter: v => v + "%" },
        legend: { top: 0, textStyle: { fontSize: 11 } },
        grid: { left: 50, right: 15, top: 28, bottom: 45 },
        xAxis: { type: "category", data: axisDates() },
        yAxis: { splitNumber: 4, axisLabel: { formatter: v => v + "%" } },
        dataZoom: [{ type: "inside" }, { type: "slider", height: 16, bottom: 6 }],
        series,
      }, true);
    }

    function renderFlows(id, key) {
      const s = bt.value[key];
      chart(id).setOption({
        animation: false,
        tooltip: { trigger: "axis", valueFormatter: v => (v / 10000).toFixed(2) + " 万" },
        legend: { top: 0, textStyle: { fontSize: 11 } },
        grid: { left: 60, right: 15, top: 28, bottom: 40 },
        xAxis: { type: "category", data: axisDates() },
        yAxis: { splitNumber: 3, axisLabel: { formatter: v => (v / 10000) + "万" } },
        dataZoom: [{ type: "inside" }],
        series: [
          { name: "累计投入", type: "line", data: s.contributed, showSymbol: false,
            lineStyle: { width: 1.2, color: "#94a3b8" }, itemStyle: { color: "#94a3b8" } },
          { name: "账户总值", type: "line", data: s.account, showSymbol: false,
            areaStyle: { opacity: 0.06, color: C[key] },
            lineStyle: { width: 1.4, color: C[key] }, itemStyle: { color: C[key] } },
        ],
      }, true);
    }

    function renderInvest(id, key) {
      const s = bt.value[key];
      const isVa = key === "va";
      chart(id).setOption({
        animation: false,
        tooltip: { trigger: "axis" },
        grid: { left: 60, right: 15, top: 15, bottom: 40 },
        xAxis: { type: "category", data: s.p_dates },
        yAxis: { splitNumber: 3, axisLabel: { formatter: v => (v / 10000) + "万" } },
        dataZoom: [{ type: "inside" }],
        series: [{
          name: "当期投入", type: "bar", data: s.p_invest.map(v => ({
            value: v, itemStyle: { color: v >= 0 ? (isVa ? C.va : C.dca) : "#22c55e" },
          })),
          barMaxWidth: 10,
        }],
      }, true);
    }

    function renderTab() {
      if (!bt.value) return;
      if (tab.value === "dca") {
        renderAccount("chart-account-dca", ["dca", "lump"]);
        renderFlows("chart-flows-dca", "dca");
        renderInvest("chart-invest-dca", "dca");
      } else if (tab.value === "va") {
        renderAccount("chart-account-va", ["va", "dca", "lump"]);
        renderFlows("chart-flows-va", "va");
        renderInvest("chart-invest-va", "va");
      }
      Object.values(charts).forEach(c => c.resize());
    }

    watch(tab, () => { syncUrl(); nextTick(renderTab); });
    watch([code, start, freq, amount, pathType, growth, allowSell, maxK], () => {
      syncUrl();
      loadBacktest();
      loadCompare();  // 服务端有 TTL 缓存，代价低
    });

    function fmt(v, suf = "", d = 2) {
      return v == null ? "—" : v.toFixed(d) + suf;
    }
    function cardsFor(key, va = false) {
      const m = bt.value?.[key]?.metrics;
      if (!m) return [];
      const pctCls = v => (v == null ? "" : (v >= 0 ? "up" : "down"));
      const cards = [
        { label: "XIRR 年化", value: fmt(m.xirr, "%"), cls: pctCls(m.xirr), sub: "收益对比口径" },
        { label: "累计收益", value: fmt(m.profit_pct, "%"), cls: pctCls(m.profit_pct),
          sub: `${m.profit >= 0 ? "+" : ""}${(m.profit / 10000).toFixed(2)} 万元` },
        { label: "总投入", value: fmt(m.total_in / 10000, " 万", 2) },
        { label: "期末账户", value: fmt(m.final_account / 10000, " 万", 2) },
        { label: "最大回撤", value: fmt(m.max_dd, "%"), sub: "按收益率序列" },
        { label: "平均成本", value: fmt(m.avg_cost), sub: `期末指数 ${m.end_price}` },
      ];
      if (va) {
        cards.push(
          { label: "峰值单期投入", value: fmt(m.max_single_inject / 10000, " 万", 2), sub: "深熊资金压力" },
          { label: "卖出止盈", value: m.n_sells ? `${m.n_sells} 次` : "—",
            sub: m.total_sold ? `${(m.total_sold / 10000).toFixed(2)} 万元` : "" },
        );
      }
      return cards;
    }
    const dcaCards = computed(() => cardsFor("dca"));
    const vaCards = computed(() => cardsFor("va", true));

    // ---- 对比表 ----
    const sortedRows = computed(() => {
      const rows = [...(compare.value?.rows || [])];
      const k = sortKey.value, asc = sortAsc.value;
      rows.sort((a, b) => {
        const va = a[k], vb = b[k];
        if (va == null) return 1;
        if (vb == null) return -1;
        if (typeof va === "string") return asc ? va.localeCompare(vb) : vb.localeCompare(va);
        return asc ? va - vb : vb - va;
      });
      return rows;
    });
    function sortBy(k) {
      if (sortKey.value === k) sortAsc.value = !sortAsc.value;
      else { sortKey.value = k; sortAsc.value = false; }
    }
    function fx(v, suf) { return v == null ? "—" : v.toFixed(2) + suf; }
    function fwan(v) { return v == null ? "—" : (v / 10000).toFixed(2) + "万"; }
    function xcls(v) { return v == null ? "" : (v >= 0 ? "up" : "down"); }
    function bestName(k) { return SUFFIX[k] || k; }

    onMounted(async () => {
      const res = await fetch("/api/index/list");
      indices.value = res.ok ? await res.json() : [];
      if (!indices.value.some(i => i.ts_code === code.value)) {
        code.value = indices.value[0]?.ts_code || "000300.SH";
      }
      loadBacktest();
      loadCompare();
      window.addEventListener("resize", () =>
        Object.values(charts).forEach(c => c.resize()));
    });

    return {
      indices, tab, code, start, freq, amount, pathType, growth, allowSell, maxK,
      bt, compare, loading, error, dcaCards, vaCards,
      sortedRows, sortBy, fx, fwan, xcls, bestName,
    };
  },
});

app.mount("#app");
