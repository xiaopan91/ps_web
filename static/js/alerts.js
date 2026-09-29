// 价格报警（/alerts）：通知渠道配置 + 规则 CRUD + 触发历史
document.addEventListener("DOMContentLoaded", function () {

  // 规则参数定义（与后端 alert_engine 对齐）
  const PARAM_DEFS = {
    price_above: [{ key: "threshold", label: "价格" }],
    price_below: [{ key: "threshold", label: "价格" }],
    pct_up: [{ key: "pct", label: "涨幅%" }],
    pct_down: [{ key: "pct", label: "跌幅%" }],
    new_high: [{ key: "days", label: "天数" }],
    new_low: [{ key: "days", label: "天数" }],
    ma_cross_up: [{ key: "window", label: "MA窗口" }],
    ma_cross_down: [{ key: "window", label: "MA窗口" }],
    vol_spike: [{ key: "days", label: "天数" }, { key: "mult", label: "倍数" }],
    pe_below: [{ key: "threshold", label: "PE" }],
    pe_above: [{ key: "threshold", label: "PE" }],
    pe_pct_below: [{ key: "pct", label: "分位%" }, { key: "years", label: "年" }],
    pe_pct_above: [{ key: "pct", label: "分位%" }, { key: "years", label: "年" }],
    streak_up: [{ key: "days", label: "天数" }],
    streak_down: [{ key: "days", label: "天数" }],
  };
  const TYPE_LABELS = { stock: "股票", etf: "ETF", index: "指数", index_ext: "主题指数" };

  window.alApp = Vue.createApp({
    data() {
      return {
        rules: [],
        history: [],
        ruleTypes: [],
        config: { serverchan_key: "" },
        editId: null,
        f: {
          query: "", name: "", ts_code: "", targetType: "stock",
          ruleType: "price_above", params: { threshold: null },
          enabled: true, oneShot: false,
        },
        searchResults: [],
        errMsg: "",
        okMsg: "",
        _searchTimer: null,
      };
    },

    methods: {
      typeLabel(t) { return TYPE_LABELS[t] || t; },
      ruleLabel(t) {
        const r = this.ruleTypes.find(x => x.type === t);
        return r ? r.label : t;
      },
      paramFields(rt) { return PARAM_DEFS[rt] || []; },
      paramsText(r) {
        const defs = this.paramFields(r.rule_type);
        return defs.map(d => `${d.label}${r.params[d.key] ?? "—"}`).join(" / ");
      },
      flash(msg) { this.okMsg = msg; setTimeout(() => { this.okMsg = ""; }, 3000); },

      async getJSON(url, opts) {
        let lastErr = null;
        for (let i = 0; i < 2; i++) {
          try {
            const r = await fetch(url, opts);
            if (!r.ok) throw new Error("HTTP " + r.status + " " + (await r.text()).slice(0, 120));
            return await r.json();
          } catch (e) { lastErr = e; await new Promise(res => setTimeout(res, 400)); }
        }
        throw lastErr || new Error("请求失败");
      },

      async loadAll() {
        try {
          const [rules, history, ruleTypes, config] = await Promise.all([
            this.getJSON("/api/alerts/rules"),
            this.getJSON("/api/alerts/history?limit=100"),
            this.getJSON("/api/alerts/rule_types"),
            this.getJSON("/api/alerts/config"),
          ]);
          this.rules = rules;
          this.history = history;
          this.ruleTypes = ruleTypes;
          this.config = config;
          this.errMsg = "";
        } catch (e) { this.errMsg = "加载失败：" + e.message; }
      },

      // ---------------------------------------- 标的搜索
      searchAsset() {
        clearTimeout(this._searchTimer);
        const q = (this.f.query || "").trim();
        if (!q) { this.searchResults = []; return; }
        this._searchTimer = setTimeout(async () => {
          try {
            const r = await fetch("/api/fin/search_asset?q=" + encodeURIComponent(q));
            this.searchResults = r.ok ? await r.json() : [];
          } catch (e) { this.searchResults = []; }
        }, 250);
      },
      pickAsset(a) {
        this.f.ts_code = a.ts_code;
        this.f.name = a.name;
        if (a.asset_type === "股票") this.f.targetType = "stock";
        else if (a.asset_type === "ETF") this.f.targetType = "etf";
        else this.f.targetType = "index";
        this.f.query = "";
        this.searchResults = [];
      },

      // ---------------------------------------- 规则
      resetForm() {
        this.f = { query: "", name: "", ts_code: "", targetType: "stock",
                   ruleType: this.f.ruleType, params: { threshold: null },
                   enabled: true, oneShot: false };
      },
      async addRule() {
        if (!this.f.ts_code) { this.errMsg = "请先搜索并选择标的"; return; }
        const defs = this.paramFields(this.f.ruleType);
        const params = {};
        for (const d of defs) {
          const v = this.f.params[d.key];
          if (v == null || isNaN(v)) { this.errMsg = `请填写参数：${d.label}`; return; }
          params[d.key] = v;
        }
        try {
          await this.getJSON("/api/alerts/rules", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              name: (this.f.name || "").trim(), target_type: this.f.targetType,
              ts_code: this.f.ts_code, rule_type: this.f.ruleType,
              params, enabled: true, one_shot: this.f.oneShot,
            }),
          });
          this.errMsg = "";
          this.flash("规则已添加");
          this.resetForm();
          await this.loadAll();
        } catch (e) { this.errMsg = "添加规则失败：" + e.message; }
      },
      startEdit(r) {
        this.editId = r.id;
        this.f = {
          query: r.ts_code, name: r.name || "", ts_code: r.ts_code,
          targetType: r.target_type, ruleType: r.rule_type,
          params: Object.assign({}, r.params), enabled: !!r.enabled, oneShot: !!r.one_shot,
        };
      },
      cancelEdit() { this.editId = null; },
      async saveRule(r) {
        const defs = this.paramFields(this.f.ruleType);
        const params = {};
        for (const d of defs) {
          const v = this.f.params[d.key];
          if (v == null || isNaN(v)) { this.errMsg = `请填写参数：${d.label}`; return; }
          params[d.key] = v;
        }
        try {
          await this.getJSON("/api/alerts/rules/" + r.id, {
            method: "PUT", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              name: (this.f.name || "").trim(), target_type: this.f.targetType,
              ts_code: this.f.ts_code, rule_type: this.f.ruleType,
              params, enabled: this.f.enabled, one_shot: this.f.oneShot,
            }),
          });
          this.errMsg = "";
          this.flash("规则已保存");
          this.cancelEdit();
          await this.loadAll();
        } catch (e) { this.errMsg = "保存规则失败：" + e.message; }
      },
      async toggleRule(r) {
        try {
          await this.getJSON(`/api/alerts/rules/${r.id}/enabled`, {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled: !r.enabled }),
          });
          await this.loadAll();
        } catch (e) { this.errMsg = "切换失败：" + e.message; }
      },
      async delRule(r) {
        if (!confirm("删除规则：" + (r.name || r.ts_code + " " + this.ruleLabel(r.rule_type)) + "？\n历史记录保留。")) return;
        try {
          await this.getJSON("/api/alerts/rules/" + r.id, { method: "DELETE" });
          await this.loadAll();
        } catch (e) { this.errMsg = "删除失败：" + e.message; }
      },

      // ---------------------------------------- 渠道与评估
      async saveConfig() {
        try {
          await this.getJSON("/api/alerts/config", {
            method: "PUT", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ serverchan_key: (this.config.serverchan_key || "").trim() }),
          });
          this.flash("SendKey 已保存");
        } catch (e) { this.errMsg = "保存失败：" + e.message; }
      },
      async testPush() {
        try {
          await this.getJSON("/api/alerts/test", {
            method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
          });
          this.flash("测试消息已发送，请查看微信");
        } catch (e) { this.errMsg = e.message; }
      },
      async evaluate() {
        try {
          const r = await this.getJSON("/api/alerts/evaluate", {
            method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
          });
          if (r.skipped) {
            this.flash("今日已评估过（" + r.reason + "），可到任务中心用「忽略当日防重」强制重评");
          } else {
            this.flash(`评估完成：${r.rules} 条规则，触发 ${r.triggered} 条` +
                       (r.errors.length ? `，${r.errors.length} 条出错` : ""));
          }
          await this.loadAll();
        } catch (e) { this.errMsg = "评估失败：" + e.message; }
      },
    },

    mounted() { this.loadAll(); },
  }).mount("#app");
});

window.addEventListener("error", e => {
  document.title = "ERR:" + String(e.message).slice(0, 80);
});
