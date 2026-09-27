// 资产快照：录入 + 明细 + 净资产/配置/月度回顾
const { createApp, computed, nextTick, onMounted, ref, watch } = Vue;

const app = createApp({
  setup() {
    const rows = ref([]);
    const summary = ref(null);
    const categories = ref([]);
    const keyword = ref("");
    const formError = ref("");
    const submitting = ref(false);
    const form = ref({
      date: new Date().toISOString().slice(0, 10),
      category: "存款", amount: null, note: "",
    });
    const charts = {};

    function today() {
      return new Date().toISOString().slice(0, 10);
    }

    async function loadAll() {
      try {
        const [cRes, sRes, sumRes] = await Promise.all([
          fetch("/api/fin/categories"),
          fetch("/api/fin/snapshots"),
          fetch("/api/fin/summary"),
        ]);
        if (cRes.ok) categories.value = await cRes.json();
        if (sRes.ok) rows.value = await sRes.json();
        summary.value = sumRes.ok ? await sumRes.json() : null;
        if (!categories.value.includes(form.value.category)) {
          form.value.category = categories.value[0] || "存款";
        }
        await nextTick();
        renderCharts();
      } catch (e) { /* 静默 */ }
    }

    const filteredRows = computed(() => {
      const kw = keyword.value.trim();
      return kw
        ? rows.value.filter(r => r.category.includes(kw) || (r.note || "").includes(kw))
        : rows.value;
    });

    async function submit() {
      formError.value = "";
      const f = form.value;
      if (!f.date || !f.category || !f.amount) {
        formError.value = "日期、分类、金额都不能为空";
        return;
      }
      submitting.value = true;
      try {
        const res = await fetch("/api/fin/snapshots", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ snap_date: f.date, category: f.category,
                                 amount: f.amount, note: f.note }),
        });
        if (!res.ok) {
          const msg = await res.json().catch(() => ({}));
          formError.value = msg.detail || `HTTP ${res.status}`;
          return;
        }
        f.amount = null; f.note = "";
        await loadAll();
      } catch (e) {
        formError.value = e.message || "保存失败";
      } finally {
        submitting.value = false;
      }
    }

    async function delRow(r) {
      if (!confirm(`删除 ${r.snap_date} ${r.category} ${r.amount} 元这条快照？`)) return;
      await fetch(`/api/fin/snapshots/${r.id}`, { method: "DELETE" });
      await loadAll();
    }

    function chart(id) {
      if (!charts[id]) charts[id] = echarts.init(document.getElementById(id));
      return charts[id];
    }

    function renderCharts() {
      const s = summary.value;
      if (!s || !s.dates || !s.dates.length) return;

      chart("chart-net").setOption({
        animation: false,
        tooltip: { trigger: "axis", valueFormatter: v => (v / 10000).toFixed(2) + " 万" },
        grid: { left: 70, right: 20, top: 15, bottom: 45 },
        xAxis: { type: "category", data: s.dates },
        yAxis: { scale: true, splitNumber: 4,
                 axisLabel: { formatter: v => (v / 10000) + "万" } },
        dataZoom: [{ type: "inside" }, { type: "slider", height: 16, bottom: 6 }],
        series: [
          { name: "净资产", type: "line", data: s.net, showSymbol: false,
            lineStyle: { width: 1.6, color: "#3b82f6" }, itemStyle: { color: "#3b82f6" },
            areaStyle: { opacity: 0.07, color: "#3b82f6" } },
          { name: "资产合计", type: "line", data: s.assets, showSymbol: false,
            lineStyle: { width: 1, type: "dashed", color: "#94a3b8" },
            itemStyle: { color: "#94a3b8" } },
          { name: "负债", type: "line", data: s.debt, showSymbol: false,
            lineStyle: { width: 1, type: "dashed", color: "#ef4444" },
            itemStyle: { color: "#ef4444" } },
        ],
      }, true);

      const alloc = s.alloc || [];
      chart("chart-pie").setOption({
        animation: false,
        tooltip: { trigger: "item",
                   valueFormatter: v => (v / 10000).toFixed(2) + " 万" },
        legend: { orient: "vertical", right: 5, top: "middle",
                  textStyle: { fontSize: 11 } },
        series: [{
          name: "配置", type: "pie", radius: ["38%", "68%"],
          center: ["38%", "50%"],
          data: alloc.map(a => ({ name: a.category, value: a.amount })),
          label: { formatter: "{d}%" },
        }],
      }, true);

      const m = s.monthly || [];
      chart("chart-monthly").setOption({
        animation: false,
        tooltip: { trigger: "axis",
                   valueFormatter: v => (v / 10000).toFixed(2) + " 万" },
        legend: { top: 0, textStyle: { fontSize: 11 } },
        grid: { left: 70, right: 15, top: 28, bottom: 40 },
        xAxis: { type: "category", data: m.map(x => x.month) },
        yAxis: { splitNumber: 3, axisLabel: { formatter: v => (v / 10000) + "万" } },
        dataZoom: [{ type: "inside" }],
        series: [
          { name: "月末净资产", type: "line", data: m.map(x => x.net), showSymbol: false,
            lineStyle: { width: 1.2, color: "#3b82f6" }, itemStyle: { color: "#3b82f6" } },
          { name: "当月变化", type: "bar", data: m.map(x => x.chg),
            itemStyle: { color: p => (p.value >= 0 ? "#ef4444" : "#22c55e") },
            barMaxWidth: 14 },
        ],
      }, true);
      Object.values(charts).forEach(c => c.resize());
    }

    onMounted(loadAll);
    window.addEventListener("resize", () =>
      Object.values(charts).forEach(c => c.resize()));

    return {
      rows, summary, categories, keyword, filteredRows,
      form, formError, submitting, submit, delRow,
    };
  },
});

app.mount("#app");
