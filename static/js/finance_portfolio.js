// 资产总览与调仓（/finance/portfolio）：标的级持仓 + 目标配置 + 余额/移仓 + 余额法 XIRR
// Options API：与 finance_portfolio.html 内联模板逐名对齐（pf / editTargets / balForm / trForm / itemForm ...）
document.addEventListener("DOMContentLoaded", function () {
  const MODULES = ["低风险", "中风险", "高风险"];
  const PRESET_SUBS = ["存款", "债基", "红利etf", "宽基etf", "海外etf", "个股", "行业etf"];

  window.fpApp = Vue.createApp({
    data() {
      return {
        pf: { total: 0, items: [], subs: [], modules: [] },
        editTargets: {},
        irr: { items: [], subs: [], modules: [] },
        hist: { balances: [], transfers: [] },
        irrByItem: {},
        expandedSub: "",
        formTab: "balance",
        balForm: { item_id: null, date: "", amount: null, note: "" },
        trForm: { date: "", from_item: null, to_item: null, amount: null, note: "" },
        itemForm: { module: "中风险", sub: "", name: "", query: "", asset_type: "其他", ts_code: "" },
        searchResults: [],
        histSub: "",
        charts: {},
        loading: false,
        errMsg: "",
        _searchTimer: null,
      };
    },

    computed: {
      modules: () => MODULES,
      presetSubs: () => PRESET_SUBS,
      itemsFlat() { return this.pf.items || []; },
      targetsSum() {
        const vals = Object.values(this.editTargets).map(v => +v || 0);
        return vals.length ? +vals.reduce((a, b) => a + b, 0).toFixed(1) : 0;
      },
      histSubs() {
        const s = new Set();
        (this.hist.balances || []).forEach(b => s.add(b.sub));
        (this.hist.transfers || []).forEach(t => { s.add(t.from_sub); s.add(t.to_sub); });
        return Array.from(s).sort();
      },
      filteredHist() {
        const all = [
          ...(this.hist.balances || []),
          ...(this.hist.transfers || []),
        ].sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : b.id - a.id));
        if (!this.histSub) return all;
        return all.filter(e =>
          e.sub === this.histSub || e.from_sub === this.histSub || e.to_sub === this.histSub);
      },
    },

    methods: {
      fmtW(v) { return v == null ? "—" : (v / 10000).toFixed(2) + " 万"; },
      fmtYuan(v, signed) {
        if (v == null) return "—";
        const w = v / 10000;
        return (signed && v > 0 ? "+" : "") + w.toFixed(2) + " 万";
      },
      fx(v, suffix) {
        if (v == null) return "—";
        return (v > 0 ? "+" : "") + v + (suffix || "");
      },
      irrCls(v) { return v == null ? "text-muted" : (v >= 0 ? "irr-pos" : "irr-neg"); },

      targetAmt(sub) {
        const pct = +this.editTargets[sub] || 0;
        return (this.pf.total || 0) * pct / 100;
      },
      diff(sub) {
        const s = (this.pf.subs || []).find(x => x.sub === sub);
        return +(this.targetAmt(sub) - (s ? s.balance : 0)).toFixed(2);
      },
      diffCls(sub) {
        const d = this.diff(sub);
        return d > 0.005 ? "up" : (d < -0.005 ? "down" : "text-muted");
      },
      subItems(sub) { return (this.pf.items || []).filter(i => i.sub === sub); },
      expandSub(sub) { this.expandedSub = this.expandedSub === sub ? "" : sub; },
      itemIrr(id) {
        const v = this.irrByItem[id];
        return v == null ? "—" : this.fx(v, "%");
      },

      // 统一取数：非 2xx 或网络抖动重试一次，仍失败则抛错（不静默降级成空对象）
      async getJSON(url) {
        let lastErr = null;
        for (let i = 0; i < 2; i++) {
          try {
            const r = await fetch(url);
            if (!r.ok) throw new Error(url + " HTTP " + r.status);
            return await r.json();
          } catch (e) {
            lastErr = e;
            await new Promise(res => setTimeout(res, 400));
          }
        }
        throw lastErr || new Error(url + " 请求失败");
      },

      async loadAll() {
        this.loading = true;
        this.errMsg = "";
        try {
          const pf = await this.getJSON("/api/fin/portfolio");
          const targets = await this.getJSON("/api/fin/targets");
          const hist = await this.getJSON("/api/fin/history?limit=2000");
          const irr = await this.getJSON("/api/fin/irr");
          this.pf = pf;
          if (targets && typeof targets === "object" && !Array.isArray(targets)) {
            this.editTargets = Object.assign({}, targets);
          }
          this.hist = hist;
          this.irr = irr;
          const map = {};
          (irr.items || []).forEach(it => { map[it.item_id] = it.xirr; });
          this.irrByItem = map;
          if (!this.balForm.date) this.balForm.date = this.today();
          if (!this.trForm.date) this.trForm.date = this.today();
          if (!this.balForm.item_id && this.itemsFlat.length) this.balForm.item_id = this.itemsFlat[0].id;
          this.$nextTick(() => this.renderCharts());
        } catch (e) {
          this.errMsg = "加载失败：" + e.message;
        } finally {
          this.loading = false;
        }
      },

      today() {
        const d = new Date();
        const p = n => String(n).padStart(2, "0");
        return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
      },

      async saveTargets() {
        try {
          const r = await fetch("/api/fin/targets", {
            method: "PUT", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ targets: this.editTargets }),
          });
          if (!r.ok) throw new Error(await r.text());
          await this.loadAll();
        } catch (e) { this.errMsg = "保存目标失败：" + e.message; }
      },

      async submitBalance() {
        const f = this.balForm;
        if (!f.item_id || !f.date || f.amount == null) { this.errMsg = "余额录入：请补全标的/日期/金额"; return; }
        try {
          const r = await fetch("/api/fin/balances", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ item_id: +f.item_id, date: f.date, amount: +f.amount, note: f.note || "" }),
          });
          if (!r.ok) throw new Error(await r.text());
          f.amount = null; f.note = "";
          await this.loadAll();
        } catch (e) { this.errMsg = "保存余额失败：" + e.message; }
      },

      async submitTransfer() {
        const f = this.trForm;
        if (!f.date || !f.from_item || !f.to_item || !f.amount) { this.errMsg = "移仓：请补全日期/双方/金额"; return; }
        if (+f.from_item === +f.to_item) { this.errMsg = "移仓双方不能相同"; return; }
        try {
          const r = await fetch("/api/fin/transfers", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ date: f.date, from_item: +f.from_item, to_item: +f.to_item, amount: +f.amount, note: f.note || "" }),
          });
          if (!r.ok) throw new Error(await r.text());
          f.amount = null; f.note = "";
          await this.loadAll();
        } catch (e) { this.errMsg = "移仓失败：" + e.message; }
      },

      searchAsset() {
        clearTimeout(this._searchTimer);
        const q = (this.itemForm.query || "").trim();
        if (!q) { this.searchResults = []; return; }
        this._searchTimer = setTimeout(async () => {
          try {
            const r = await fetch("/api/fin/search_asset?q=" + encodeURIComponent(q));
            this.searchResults = r.ok ? await r.json() : [];
          } catch (e) { this.searchResults = []; }
        }, 250);
      },
      pickAsset(a) {
        this.itemForm.ts_code = a.ts_code;
        this.itemForm.asset_type = a.asset_type;
        this.itemForm.name = a.name;
        this.itemForm.query = "";
        this.searchResults = [];
      },
      async addItem() {
        const f = this.itemForm;
        if (!f.module || !f.sub.trim() || !f.name.trim()) { this.errMsg = "添加标的：大模块/小模块/名称必填"; return; }
        try {
          const r = await fetch("/api/fin/items", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              module: f.module, sub: f.sub.trim(), name: f.name.trim(),
              asset_type: f.ts_code ? f.asset_type : "其他",
              ts_code: f.ts_code || null, note: "",
            }),
          });
          if (!r.ok) throw new Error(await r.text());
          this.itemForm = { module: f.module, sub: f.sub, name: "", query: "", asset_type: "其他", ts_code: "" };
          await this.loadAll();
        } catch (e) { this.errMsg = "添加标的失败：" + e.message; }
      },

      async delBalance(e) {
        if (!confirm("删除该余额记录 " + e.date + " " + e.name + "？")) return;
        try {
          const r = await fetch("/api/fin/balances/" + e.id, { method: "DELETE" });
          if (!r.ok) throw new Error(await r.text());
          await this.loadAll();
        } catch (er) { this.errMsg = "删除失败：" + er.message; }
      },

      async delItem(it) {
        if (!confirm("删除标的「" + it.name + "」？\n其余额记录与移仓记录将一并删除，不可恢复。")) return;
        try {
          const r = await fetch("/api/fin/items/" + it.id, { method: "DELETE" });
          if (!r.ok) throw new Error(await r.text());
          await this.loadAll();
        } catch (er) { this.errMsg = "删除标的失败：" + er.message; }
      },

      initChart(id) {
        if (this.charts[id]) return this.charts[id];
        const el = document.getElementById(id);
        if (!el) return null;
        const c = echarts.init(el);
        this.charts[id] = c;
        return c;
      },
      renderCharts() {
        // 总资产曲线：按余额记录日期滚动合计（同标的同时点取最新一条）
        const bal = [...(this.hist.balances || [])].sort((a, b) =>
          a.date < b.date ? -1 : a.date > b.date ? 1 : a.id - b.id);
        const latest = {}; const dates = []; const totals = [];
        for (const b of bal) {
          latest[b.item_id] = +b.amount || 0;
          dates.push(b.date);
          totals.push(+Object.values(latest).reduce((a, v) => a + v, 0).toFixed(2));
        }
        const c1 = this.initChart("chart-total");
        if (c1) {
          c1.setOption({
            animation: false,
            tooltip: { trigger: "axis", valueFormatter: v => this.fmtW(v) },
            grid: { left: 70, right: 20, top: 15, bottom: 45 },
            xAxis: { type: "category", data: dates },
            yAxis: { scale: true, axisLabel: { formatter: v => (v / 10000).toFixed(1) + "万" } },
            dataZoom: [{ type: "inside" }, { type: "slider", height: 16, bottom: 6 }],
            series: [{
              name: "总资产", type: "line", data: totals, showSymbol: false,
              lineStyle: { width: 1.6, color: "#3b82f6" }, itemStyle: { color: "#3b82f6" },
              areaStyle: { opacity: 0.07, color: "#3b82f6" },
            }],
          }, true);
        }
        // 小模块 当前 vs 目标
        const subs = this.pf.subs || [];
        const c2 = this.initChart("chart-alloc");
        if (c2 && subs.length) {
          c2.setOption({
            animation: false,
            legend: { top: 0, textStyle: { fontSize: 11 } },
            grid: { left: 70, right: 15, top: 28, bottom: 60 },
            xAxis: { type: "category", data: subs.map(s => s.sub), axisLabel: { rotate: 30, fontSize: 10 } },
            yAxis: { axisLabel: { formatter: v => (v / 10000).toFixed(0) + "万" } },
            series: [
              { name: "当前", type: "bar", barMaxWidth: 18, itemStyle: { color: "#3b82f6" },
                data: subs.map(s => +(s.balance / 10000).toFixed(2)) },
              { name: "目标", type: "bar", barMaxWidth: 18, itemStyle: { color: "#f59e0b", opacity: 0.75 },
                data: subs.map(s => +(this.targetAmt(s.sub) / 10000).toFixed(2)) },
            ],
          }, true);
        }
      },
    },

    mounted() { this.loadAll(); },
  }).mount("#app");

  window.addEventListener("resize", () => {
    if (window.fpApp) Object.values(window.fpApp.charts || {}).forEach(c => c && c.resize());
  });
});

// 调试辅助：页面报错时写入标题，便于远程定位
window.addEventListener("error", e => {
  document.title = "ERR:" + String(e.message).slice(0, 80);
});
