// 资产总览与调仓：标的级持仓 + 目标配置 + 余额/移仓 + IRR
const { createApp, computed, nextTick, onMounted, ref, watch } = Vue;

window.addEventListener("error", e => {
  document.title = "ERR:" + e.message;
  window.__errStack = e.error ? e.error.stack : "(无堆栈)";
});
const _ce = console.error;
console.error = (...a) => {
  const e0 = a[0];
  window.__cerr = (e0 && e0.stack) || String(e0);
  document.title = "CERR:" + String(e0).slice(0, 100);
  _ce(...a);
};

const MODULES = ["低风险", "中风险", "高风险"];
const PRESET_SUBS = ["存款", "债基", "红利etf", "宽基etf", "海外etf", "个股", "行业etf"];

const app = createApp({
  setup() {
    const pf = ref({});
    window.__pf = pf;   // 诊断用
    const editTargets = ref({});
    const history = ref({ balances: [], transfers: [] });
    const irr = ref({});
    const irrByItem = ref({});
    const loading = ref(false);
    const error = ref("");
    const formTab = ref("balance");
    const expandedSub = ref("");
    const histSub = ref("");
    const charts = {};

    const balForm = ref({ item_id: null, date: new Date().toISOString().slice(0, 10),
                          amount: null, note: "" });
    const trForm = ref({ date: new Date().toISOString().slice(0, 10),
                         from_item: null, to_item: null, amount: null });
    const itemForm = ref({ module: "高风险", sub: "", name: "", query: "",
                           asset_type: "其他", ts_code: null });
    const searchResults = ref([]);
    let searchTimer = null;

    const itemsFlat = computed(() => pf.value.items || []);
    const targetsSum = computed(() => {
      const vals = Object.values(editTargets.value);
      return +vals.reduce((a, b) => a + (+b || 0), 0).toFixed(1);
    });
    const histSubs = computed(() => {
      const set = new Set();
      (history.value.balances || []).forEach(b => set.add(b.sub));
      (history.value.transfers || []).forEach(t => { set.add(t.from_sub); set.add(t.to_sub); });
      return [...set];
    });
    const filteredHist = computed(() => {
      const all = [
        ...(history.value.balances || []),
        ...(history.value.transfers || []).map(t => ({ ...t, kind: "transfer" })),
      ];
      return histSub.value
        ? all.filter(e => e.sub === histSub.value || e.from_sub === histSub.value
                         || e.to_sub === histSub.value)
        : all;
    });
    const irrByItemMap = computed(() => {
      const map = {};
      (irr.value.items || []).forEach(x => { map[x.item_id] = x.xirr; });
      return map;
    });

    // ---- 数据加载 ----
    async function loadAll() {
      loading.value = true;
      error.value = "";
      try {
        const [pRes, tRes, hRes, iRes] = await Promise.all([
          fetch("/api/fin/portfolio"), fetch("/api/fin/targets"),
          fetch("/api/fin/history?limit=2000"), fetch("/api/fin/irr"),
        ]);
        pf.value = pRes.ok ? await pRes.json() : {};
        editTargets.value = tRes.ok ? await tRes.json() : {};
        history.value = hRes.ok ? await hRes.json() : { balances: [], transfers: [] };
        irr.value = iRes.ok ? await iRes.json() : {};
        await nextTick();
        renderCharts();
      } catch (e) {
        error.value = e.message || "加载失败";
      } finally {
        loading.value = false;
      }
    }

    // ---- 调仓目标 ----
    function targetPct(sub) { return +(editTargets.value[sub] ?? 0); }
    function targetAmt(sub) { return pf.value.total * targetPct(sub) / 100; }
    function subBalance(sub) {
      const s = (pf.value.subs || []).find(x => x.sub === sub);
      return s ? s.balance : 0;
    }
    function diff(sub) { return +(targetAmt(sub) - subBalance(sub)).toFixed(2); }
    function diffCls(sub) {
      const d = diff(sub);
      return d > 0.005 ? "up" : (d < -0.005 ? "down" : "text-muted");
    }

    async function saveTargets() {
      await fetch("/api/fin/targets", {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ targets: editTargets.value }),
      });
      loadAll();
    }

    function expandSub(sub) {
      expandedSub.value = expandedSub.value === sub ? null : sub;
    }
    function subItems(sub) {
      return (pf.value.items || []).filter(i => i.sub === sub);
    }
    function itemIrr(id) {
      const v = irrByItemMap.value[id];
      return v == null ? "—" : (v > 0 ? "+" : "") + v + "%";
    }

    // ---- 录入：余额 / 移仓 ----
    async function submitBalance() {
      if (!balForm.value.item_id || balForm.value.amount == null) {
        alert("选标的并填余额"); return;
      }
      const res = await fetch("/api/fin/balances", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(balForm.value),
      });
      if (!res.ok) { alert((await res.json().catch(() => ({}))).detail || "保存失败"); return; }
      balForm.value.amount = null;
      loadAll();
    }

    async function submitTransfer() {
      if (!trForm.value.from_item || !trForm.value.to_item || !trForm.value.amount) {
        alert("选转出/转入标的并填金额"); return;
      }
      const res = await fetch("/api/fin/transfers", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(trForm.value),
      });
      if (!res.ok) { alert((await res.json().catch(() => ({}))).detail || "移仓失败"); return; }
      trForm.value.amount = null;
      loadAll();
    }

    // ---- 添加标的 ----
    function searchAsset() {
      clearTimeout(searchTimer);
      const q = itemForm.value.query.trim();
      if (!q) { searchResults.value = []; return; }
      searchTimer = setTimeout(async () => {
        try {
          const res = await fetch(`/api/fin/search_asset?q=${encodeURIComponent(q)}`);
          searchResults.value = res.ok ? await res.json() : [];
        } catch (e) { searchResults.value = []; }
      }, 250);
    }
    function pickAsset(a) {
      itemForm.value.name = a.name;
      itemForm.value.ts_code = a.ts_code;
      itemForm.value.asset_type = a.asset_type;
      searchResults.value = [];
      itemForm.value.query = a.name;
    }
    async function addItem() {
      const f = itemForm.value;
      if (!f.module || !f.sub.trim() || !f.name.trim()) {
        alert("大模块/小模块/名称必填"); return;
      }
      const res = await fetch("/api/fin/items", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ module: f.module, sub: f.sub.trim(), name: f.name.trim(),
                               asset_type: f.ts_code ? f.asset_type : "其他",
                               ts_code: f.ts_code }),
      });
      if (!res.ok) { alert((await res.json().catch(() => ({}))).detail || "添加失败"); return; }
      f.name = ""; f.query = ""; f.ts_code = null;
      loadAll();
    }

    // ---- 历史删除 ----
    async function delBalance(e) {
      if (!confirm(`删除 ${e.date} ${e.name} 余额 ${e.amount} 元的记录？`)) return;
      await fetch(`/api/fin/balances/${e.id}`, { method: "DELETE" });
      loadAll();
    }

    // ---- 格式化 ----
    function fmtW(v) { return v == null ? "—" : (v / 10000).toFixed(2) + " 万"; }
    function fmtYuan(v, signed = false) {
      if (v == null) return "—";
      const s = v / 10000;
      return (signed && v > 0 ? "+" : "") + s.toFixed(2) + " 万";
    }
    function irrCls(v) { return v == null ? "text-muted" : (v >= 0 ? "irr-pos" : "irr-neg"); }

    // ---- 图表 ----
    function chart(id) {
      if (!charts[id]) charts[id] = echarts.init(document.getElementById(id));
      return charts[id];
    }

    function totalCurve() {
      // 按日期累计：每日期取各标的"当时最新余额"求和
      const bal = [...(history.value.balances || [])]
        .sort((a, b) => a.date.localeCompare(b.date));
      const latest = {};
      const dates = [], totals = [];
      for (const b of bal) {
        latest[b.item_id] = b.amount;
        const t = Object.values(latest).reduce((a, x) => a + (+x || 0), 0);
        dates.push(b.date); totals.push(+t.toFixed(2));
      }
      return { dates, totals };
    }

    function renderCharts() {
      const tc = totalCurve();
      if (tc.dates.length) {
        chart("chart-total").setOption({
          animation: false,
          tooltip: { trigger: "axis", valueFormatter: v => (v / 10000).toFixed(2) + " 万" },
          grid: { left: 70, right: 20, top: 15, bottom: 45 },
          xAxis: { type: "category", data: tc.dates },
          yAxis: { scale: true, splitNumber: 3, axisLabel: { formatter: v => (v / 10000) + "万" } },
          dataZoom: [{ type: "inside" }, { type: "slider", height: 16, bottom: 6 }],
          series: [{ name: "总资产", type: "line", data: tc.totals, showSymbol: false,
                     lineStyle: { width: 1.6, color: "#3b82f6" }, itemStyle: { color: "#3b82f6" },
                     areaStyle: { opacity: 0.07, color: "#3b82f6" } }],
        }, true);
      }
      const subs = pf.value.subs || [];
      if (subs.length) {
        chart("chart-alloc").setOption({
          animation: false,
          tooltip: { trigger: "axis", valueFormatter: v => (v / 10000).toFixed(2) + " 万" },
          legend: { top: 0, textStyle: { fontSize: 11 } },
          grid: { left: 70, right: 15, top: 28, bottom: 60 },
          xAxis: { type: "category", data: subs.map(s => s.sub),
                   axisLabel: { rotate: 30, fontSize: 10 } },
          yAxis: { axisLabel: { formatter: v => (v / 10000) + "万" } },
          series: [
            { name: "当前", type: "bar", data: subs.map(s => +(s.balance / 10000).toFixed(2)),
              itemStyle: { color: "#3b82f6" }, barMaxWidth: 18 },
            { name: "目标", type: "bar", data: subs.map(s => +(targetAmt(s.sub) / 10000).toFixed(2)),
              itemStyle: { color: "#f59e0b", opacity: 0.7 }, barMaxWidth: 18 },
          ],
        }, true);
      }
      Object.values(charts).forEach(c => c.resize());
    }

    onMounted(loadAll);
    window.addEventListener("resize", () =>
      Object.values(charts).forEach(c => c.resize()));

    return {
      pf, editTargets, targetsSum, saveTargets, targetPct, targetAmt, diff, diffCls,
      expandSub, expandedSub, subItems, itemIrr, irrByItem: irrByItemMap, irr,
      itemsFlat, modules: MODULES, presetSubs: PRESET_SUBS,
      formTab, balForm, trForm, submitBalance, submitTransfer,
      itemForm, searchResults, searchAsset, pickAsset, addItem,
      histSub, histSubs, filteredHist, delBalance,
      fmtW, fmtYuan, fx, irrCls, loading, error,
    };
  },
});

app.config.errorHandler = (err, inst, info) => {
  document.title = "VERR:" + err.message + " @ " + info;
  window.__verrStack = err.stack;
  console.error(err, info);
};
app.mount("#app");
