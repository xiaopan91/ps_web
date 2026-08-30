// 宏观预测容器页：方案卡片 + 实时预览
const { createApp, computed, onMounted, ref } = Vue;

const app = createApp({
  setup() {
    const score = ref(null);
    const zone = ref("");
    const date = ref("");

    const scoreColor = computed(() => {
      const s = score.value;
      if (s == null) return "#94a3b8";
      if (s >= 80) return "#ef4444";
      if (s >= 60) return "#f97316";
      if (s >= 40) return "#64748b";
      if (s >= 20) return "#3b82f6";
      return "#22c55e";
    });

    onMounted(async () => {
      try {
        const res = await fetch("/api/sentiment/history?days=250");
        const d = await res.json();
        if (d.latest) {
          score.value = d.latest.score;
          date.value = d.latest.trade_date;
          zone.value = d.latest.score >= 80 ? "过热" : d.latest.score >= 60 ? "偏热"
            : d.latest.score >= 40 ? "中性" : d.latest.score >= 20 ? "偏冷" : "冰点";
        }
        // 迷你走势线（无轴）
        const el = document.getElementById("spark");
        if (el && d.dates.length) {
          const chart = echarts.init(el);
          chart.setOption({
            animation: false,
            grid: { left: 0, right: 0, top: 4, bottom: 0 },
            xAxis: { type: "category", show: false, data: d.dates },
            yAxis: { show: false, min: "dataMin", max: "dataMax" },
            series: [{
              type: "line", data: d.score, showSymbol: false,
              lineStyle: { width: 1.5, color: "#3b82f6" },
              areaStyle: { opacity: 0.1 },
            }],
          });
          window.addEventListener("resize", () => chart.resize());
        }
      } catch (e) { /* 预览失败不影响入口 */ }
    });

    return { score, zone, date, scoreColor };
  },
});

app.mount("#app");
