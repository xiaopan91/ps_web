// 量价因子排名：按日期计算全市场因子并排序展示
const { createApp, computed, onMounted, ref } = Vue;

const app = createApp({
  setup() {
    const date = ref(new URLSearchParams(location.search).get("date") || "");
    const actual = ref("");
    const loading = ref(false);
    const slow = ref(false);
    const error = ref("");
    const rows = ref([]);
    const stats = ref(null);
    const keyword = ref("");
    const onlyST = ref(false);
    const page = ref(1);
    const sortKey = ref("rank");
    const sortAsc = ref(true);
    const PAGE_SIZE = 100;
    let timer = null;

    async function load() {
      if (!date.value) { error.value = "请先选择日期"; return; }
      loading.value = true;
      error.value = "";
      slow.value = false;
      timer = setTimeout(() => { slow.value = true; }, 4000);
      try {
        const res = await fetch(`/api/pvfactor/rank?date=${date.value}`);
        if (!res.ok) {
          const m = await res.json().catch(() => ({}));
          throw new Error(m.detail || `HTTP ${res.status}`);
        }
        const d = await res.json();
        rows.value = d.rows;
        stats.value = { total: d.total, top10_next_avg: d.top10_next_avg,
                        market_next_avg: d.market_next_avg };
        actual.value = d.date;
        page.value = 1;
        const p = new URLSearchParams({ date: date.value });
        history.replaceState(null, "", `/stockpredict/rank?${p}`);
      } catch (e) {
        error.value = e.message;
      } finally {
        clearTimeout(timer);
        loading.value = false;
      }
    }

    const filtered = computed(() => {
      let r = rows.value;
      const k = keyword.value.trim().toUpperCase();
      if (k) r = r.filter(x => x.ts_code.includes(k) ||
                              (x.name || "").toUpperCase().includes(k) ||
                              (x.industry || "").toUpperCase().includes(k));
      if (!onlyST.value) r = r.filter(x => !(x.name || "").includes("ST"));
      if (sortKey.value === "rank") {
        r = [...r].sort((a, b) => sortAsc.value ? a.rank - b.rank : b.rank - a.rank);
      } else {
        r = [...r].sort((a, b) => {
          const va = a[sortKey.value] ?? -Infinity;
          const vb = b[sortKey.value] ?? -Infinity;
          return sortAsc.value ? va - vb : vb - va;
        });
      }
      return r;
    });
    const totalPages = computed(() => Math.max(1, Math.ceil(filtered.value.length / PAGE_SIZE)));
    const paged = computed(() => {
      const p = Math.min(page.value, totalPages.value);
      return filtered.value.slice((p - 1) * PAGE_SIZE, p * PAGE_SIZE);
    });

    function sortBy(key) {
      if (sortKey.value === key) { sortAsc.value = !sortAsc.value; }
      else { sortKey.value = key; sortAsc.value = key === "rank"; }
      page.value = 1;
    }

    const excess = computed(() => {
      const s = stats.value;
      if (!s || s.top10_next_avg == null || s.market_next_avg == null) return null;
      return +(s.top10_next_avg - s.market_next_avg).toFixed(2);
    });

    onMounted(async () => {
      if (!date.value) {
        // 默认最近一个有数据的交易日
        try {
          const res = await fetch("/api/pvfactor/overview?days=5");
          const d = await res.json();
          if (d.latest) date.value = d.latest.trade_date;
        } catch (e) { /* 忽略 */ }
      }
      if (date.value) load();
    });

    return { date, actual, loading, slow, error, rows, stats, keyword, onlyST,
             page, totalPages, paged, sortBy, load, excess };
  },
});

app.mount("#app");
