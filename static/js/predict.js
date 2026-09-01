// 宏观预测容器页：方案卡片 + 实时预览
const { createApp, computed, onMounted, ref } = Vue;

const app = createApp({
  setup() {
    const score = ref(null);
    const zone = ref("");
    const date = ref("");
    const ratio = ref(null);
    const northZone = ref("");
    const northDate = ref("");

    const scoreColor = computed(() => {
      const s = score.value;
      if (s == null) return "#94a3b8";
      if (s >= 80) return "#ef4444";
      if (s >= 60) return "#f97316";
      if (s >= 40) return "#64748b";
      if (s >= 20) return "#3b82f6";
      return "#22c55e";
    });
    const ratioColor = computed(() => {
      const r = ratio.value;
      if (r == null) return "#94a3b8";
      return r >= 0 ? "#ef4444" : "#22c55e";
    });

    function spark(elId, dates, values, color) {
      const el = document.getElementById(elId);
      if (!el || !dates || !dates.length) return;
      const chart = echarts.init(el);
      chart.setOption({
        animation: false,
        grid: { left: 0, right: 0, top: 4, bottom: 0 },
        xAxis: { type: "category", show: false, data: dates },
        yAxis: { show: false, min: "dataMin", max: "dataMax" },
        series: [{
          type: "line", data: values, showSymbol: false,
          lineStyle: { width: 1.5, color },
          areaStyle: { opacity: 0.1 },
        }],
      });
      window.addEventListener("resize", () => chart.resize());
    }

    onMounted(async () => {
      // 市场情绪卡预览
      try {
        const res = await fetch("/api/sentiment/history?days=250");
        const d = await res.json();
        if (d.latest) {
          score.value = d.latest.score;
          date.value = d.latest.trade_date;
          zone.value = d.latest.score >= 80 ? "过热" : d.latest.score >= 60 ? "偏热"
            : d.latest.score >= 40 ? "中性" : d.latest.score >= 20 ? "偏冷" : "冰点";
        }
        spark("spark", d.dates, d.score, "#3b82f6");
      } catch (e) { /* 预览失败不影响入口 */ }

      // 北向/成交额卡预览
      try {
        const res = await fetch("/api/north/overview?days=250");
        const d = await res.json();
        if (d.latest) {
          ratio.value = d.latest.ratio_bp;
          northDate.value = d.latest.trade_date;
          const p = d.latest.pctile;
          northZone.value = p == null ? "" :
            p >= 80 ? "外资高度活跃" : p >= 50 ? "偏活跃"
            : p >= 20 ? "中性" : "外资低迷";
        }
        spark("spark2", d.dates, d.ratio_bp, "#10b981");
      } catch (e) { /* 预览失败不影响入口 */ }
    });

    return { score, zone, date, scoreColor, ratio, northZone, northDate, ratioColor };
  },
});

app.mount("#app");
