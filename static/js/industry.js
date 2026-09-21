// 板块观察：申万层级 / 主题指数动量表（点击板块进入详情页）
const { createApp, computed, onMounted, ref, watch } = Vue;

const app = createApp({
  setup() {
    const rows = ref([]);
    const summary = ref(null);
    const loading = ref(false);
    const keyword = ref("");
    const sortKey = ref("r20");
    const sortAsc = ref(false);
    const boardTypes = [
      { k: "sw_l2", label: "申万二级" }, { k: "sw_l1", label: "申万一级" },
      { k: "sw_l3", label: "申万三级" }, { k: "theme", label: "主题指数" },
    ];
    const type = ref("sw_l2");

    // ---- URL 参数 ----
    function readUrl() {
      const p = new URLSearchParams(location.search);
      if (p.get("type") && boardTypes.some(t => t.k === p.get("type"))) type.value = p.get("type");
    }
    readUrl();
    function syncUrl() {
      history.replaceState(null, "", `/industry?type=${type.value}`);
    }

    let ovSeq = 0;   // 请求序号：快速切换类型时丢弃慢返回的旧响应
    async function loadOverview() {
      const seq = ++ovSeq;
      loading.value = true;
      try {
        const res = await fetch(`/api/industry/overview?type=${type.value}`);
        const data = res.ok ? await res.json() : null;
        if (seq !== ovSeq) return;
        rows.value = data?.rows || [];
        summary.value = data?.summary || null;
      } catch (e) { /* 静默 */ }
      finally { if (seq === ovSeq) loading.value = false; }
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

    function sortBy(k) {
      if (sortKey.value === k) sortAsc.value = !sortAsc.value;
      else { sortKey.value = k; sortAsc.value = false; }
    }

    function fx(v, d = 2) { return v == null ? "—" : v.toFixed(d) + "%"; }
    function fmtYi(v) { return v == null ? "—" : (v / 1e4).toFixed(0); }
    function xcls(v) { return v == null ? "" : (v >= 0 ? "up" : "down"); }

    function gotoDetail(code) {
      location.href = `/industry/detail?board=${encodeURIComponent(code)}&type=${type.value}`;
    }

    watch(type, () => { syncUrl(); loadOverview(); });

    onMounted(() => { loadOverview(); });

    return {
      rows, summary, loading, keyword, sortBy, filteredRows, sortAsc,
      boardTypes, type, fx, fmtYi, xcls, gotoDetail,
    };
  },
});

app.mount("#app");
