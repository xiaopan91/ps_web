// 小模块详情页（/finance/sub?sub=...）：标的 + 余额曲线 + 超文本笔记
// 笔记走通用 /api/notes（scope=fin_sub, key=小模块名），后续个股/指数/ETF 直接复用
document.addEventListener("DOMContentLoaded", function () {

  window.fsApp = Vue.createApp({
    data() {
      return {
        subName: "",
        info: null,          // /api/fin/sub/{name} 返回
        fatal: "",
        notes: [],
        curId: null,         // 当前编辑的笔记 id
        curTitle: "",
        dirty: false,
        itemForm: { name: "", query: "", asset_type: "其他", ts_code: "" },
        searchResults: [],
        balEditId: null,   // 双击改余额：当前编辑的标的
        balEditVal: null,  // 双击改余额：输入的金额（元）
        charts: {},
        errMsg: "",
        infoErr: "",
        _searchTimer: null,
        _loadingNote: false,
      };
    },

    computed: {
      diffCls() {
        if (!this.info) return "text-muted";
        const d = this.info.diff;
        return d > 0.005 ? "up" : (d < -0.005 ? "down" : "text-muted");
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

      today() {
        const d = new Date();
        const p = n => String(n).padStart(2, "0");
        return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
      },

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

      async loadInfo() {
        try {
          this.info = await this.getJSON("/api/fin/sub/" + encodeURIComponent(this.subName));
          this.infoErr = "";
          this.$nextTick(() => this.renderChart());
        } catch (e) {
          this.fatal = "加载小模块失败：" + e.message;
        }
      },

      async loadNotes() {
        try {
          this.notes = await this.getJSON(
            "/api/notes?scope=fin_sub&key=" + encodeURIComponent(this.subName));
        } catch (e) {
          this.errMsg = "笔记加载失败：" + e.message;
        }
      },

      // ------------------------------------------------ 标的
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
        if (!f.name.trim()) { this.errMsg = "添加标的：请填写标的名称（或先选择关联行情）"; return; }
        try {
          const r = await fetch("/api/fin/items", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              module: this.info.module, sub: this.subName, name: f.name.trim(),
              asset_type: f.ts_code ? f.asset_type : "其他",
              ts_code: f.ts_code || null, note: "",
            }),
          });
          if (!r.ok) throw new Error(await r.text());
          this.itemForm = { name: "", query: "", asset_type: "其他", ts_code: "" };
          await this.loadInfo();
        } catch (e) { this.errMsg = "添加标的失败：" + e.message; }
      },
      async delItem(it) {
        if (!confirm("删除标的「" + it.name + "」？\n其余额记录与移仓记录将一并删除，不可恢复。")) return;
        try {
          const r = await fetch("/api/fin/items/" + it.id, { method: "DELETE" });
          if (!r.ok) throw new Error(await r.text());
          await this.loadInfo();
        } catch (e) { this.errMsg = "删除标的失败：" + e.message; }
      },

      // 双击余额 → 行内编辑 → 确认后直接录入一条余额（当日）
      startBalEdit(it) {
        this.balEditId = it.id;
        this.balEditVal = it.amount;
        this.$nextTick(() => {
          const ref = this.$refs.balInput;
          const el = Array.isArray(ref) ? ref[ref.length - 1] : ref;
          if (el) { el.focus(); el.select && el.select(); }
        });
      },
      cancelBalEdit() { this.balEditId = null; this.balEditVal = null; },
      async confirmBalEdit() {
        if (this.balEditVal == null || isNaN(this.balEditVal)) { this.errMsg = "请输入有效金额（元）"; return; }
        try {
          const r = await fetch("/api/fin/balances", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ item_id: this.balEditId, date: this.today(),
                                   amount: +this.balEditVal, note: "双击快速录入" }),
          });
          if (!r.ok) throw new Error(await r.text());
          this.cancelBalEdit();
          await this.loadInfo();
        } catch (e) { this.errMsg = "录入余额失败：" + e.message; }
      },

      // ------------------------------------------------ 笔记
      newNote() {
        this.curId = "new";
        this.curTitle = "";
        this.dirty = false;
        this.$nextTick(() => {
          const el = this.$refs.editor;
          if (el) el.innerHTML = "";
        });
      },
      selectNote(n) {
        this.curId = n.id;
        this.curTitle = n.title;
        this.dirty = false;
        this._loadingNote = true;
        this.$nextTick(() => {
          const el = this.$refs.editor;
          if (el) el.innerHTML = n.content || "";
          this._loadingNote = false;
        });
      },
      exec(cmd, val) {
        document.execCommand(cmd, false, val || null);
        this.dirty = true;
        this.$refs.editor && this.$refs.editor.focus();
      },
      addLink() {
        const url = prompt("链接地址（https://...）");
        if (url) this.exec("createLink", url);
      },
      // 粘贴一律转纯文本：外部（IDE/网页暗色主题等）带样式粘贴会让文字在
      // 白底编辑器里"隐形"，且结构混乱
      onPaste(e) {
        e.preventDefault();
        const text = (e.clipboardData || window.clipboardData).getData("text/plain") || "";
        document.execCommand("insertText", false, text);
        this.dirty = true;
      },
      async saveNote() {
        if (!this.curId) return;
        const el = this.$refs.editor;
        const content = el ? el.innerHTML : "";
        const title = (this.curTitle || "").trim();
        if (!title && !el.textContent.trim()) { this.errMsg = "笔记内容为空"; return; }
        try {
          let r;
          if (this.curId === "new") {
            r = await fetch("/api/notes", {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ scope: "fin_sub", key: this.subName, title, content }),
            });
          } else {
            r = await fetch("/api/notes/" + this.curId, {
              method: "PUT", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ scope: "fin_sub", key: this.subName, title, content }),
            });
          }
          if (!r.ok) throw new Error(await r.text());
          this.dirty = false;
          // 刷新列表并保持选中（新建后定位到最新一条）
          await this.loadNotes();
          const saved = this.curId === "new"
            ? this.notes.find(n => n.title === title && (n.content || "") === content)
            : this.notes.find(n => n.id === this.curId);
          if (saved) {
            this.curId = saved.id;
            this.curTitle = saved.title;
          }
        } catch (e) { this.errMsg = "保存笔记失败：" + e.message; }
      },
      async delNote(n) {
        if (!confirm("删除笔记「" + (n.title || "无标题") + "」？不可恢复。")) return;
        try {
          const r = await fetch("/api/notes/" + n.id, { method: "DELETE" });
          if (!r.ok) throw new Error(await r.text());
          if (this.curId === n.id) { this.curId = null; this.curTitle = ""; }
          await this.loadNotes();
        } catch (e) { this.errMsg = "删除笔记失败：" + e.message; }
      },

      // ------------------------------------------------ 图表
      initChart(id) {
        if (this.charts[id]) return this.charts[id];
        const el = document.getElementById(id);
        if (!el) return null;
        const c = echarts.init(el);
        this.charts[id] = c;
        return c;
      },
      renderChart() {
        // 按日期聚合（同日多条记录只留该日最终状态），一天一个点
        const hist = (this.info && this.info.history) || [];
        const sorted = [...hist].sort((a, b) =>
          a.date < b.date ? -1 : a.date > b.date ? 1 : a.item_id - b.item_id);
        const latest = {}; const dates = []; const totals = [];
        let cur = null;
        for (const b of sorted) {
          if (b.date !== cur) {
            if (cur !== null) {
              dates.push(cur);
              totals.push(+Object.values(latest).reduce((a, v) => a + v, 0).toFixed(2));
            }
            cur = b.date;
          }
          latest[b.item_id] = +b.amount || 0;
        }
        if (cur !== null) {
          dates.push(cur);
          totals.push(+Object.values(latest).reduce((a, v) => a + v, 0).toFixed(2));
        }
        const c = this.initChart("chart-sub");
        if (!c) return;
        c.setOption({
          animation: false,
          tooltip: { trigger: "axis", valueFormatter: v => this.fmtW(v) },
          grid: { left: 70, right: 20, top: 15, bottom: 45 },
          xAxis: { type: "category", data: dates },
          yAxis: { scale: true, axisLabel: { formatter: v => (v / 10000).toFixed(1) + "万" } },
          dataZoom: [{ type: "inside" }, { type: "slider", height: 16, bottom: 6 }],
          series: [{
            name: this.subName, type: "line", data: totals, showSymbol: false,
            lineStyle: { width: 1.6, color: "#10b981" }, itemStyle: { color: "#10b981" },
            areaStyle: { opacity: 0.07, color: "#10b981" },
          }],
        }, true);
      },
    },

    async mounted() {
      const p = new URLSearchParams(location.search);
      this.subName = p.get("sub") || "";
      if (!this.subName) { this.fatal = "缺少小模块参数（?sub=小模块名）"; return; }
      document.title = this.subName + " · 个人理财 · ps_web";
      await Promise.all([this.loadInfo(), this.loadNotes()]);
    },
  }).mount("#app");

  window.addEventListener("resize", () => {
    if (window.fsApp) Object.values(window.fsApp.charts || {}).forEach(c => c && c.resize());
  });
});

window.addEventListener("error", e => {
  document.title = "ERR:" + String(e.message).slice(0, 80);
});
