// 页面逻辑：Vue 应用 + 后端健康检查 + ECharts 示例图
const { createApp, computed, onMounted, ref } = Vue;

const app = createApp({
  setup() {
    const message = ref("开发环境已就绪");
    const backendStatus = ref("检测中…");
    const dbStatus = ref("检测中…");

    const backendOk = computed(() => backendStatus.value === "ok");
    const dbOk = computed(() => dbStatus.value === "connected");

    async function refresh() {
      backendStatus.value = "检测中…";
      dbStatus.value = "检测中…";
      try {
        const res = await fetch("/api/health");
        const data = await res.json();
        backendStatus.value = data.status;
        dbStatus.value = data.database;
      } catch (e) {
        backendStatus.value = "无法连接";
        dbStatus.value = "无法连接";
      }
    }

    onMounted(() => {
      refresh();
      initChart();
    });

    return { message, backendStatus, dbStatus, backendOk, dbOk, refresh };
  },
});

app.mount("#app");

// ECharts 演示：一段随机走势的 K 线，验证图表库可用（后续换真实行情数据）
function initChart() {
  const el = document.getElementById("chart");
  if (!el || typeof echarts === "undefined") return;

  // 生成 60 根模拟日 K
  const dates = [];
  const candles = [];
  let price = 100;
  for (let i = 0; i < 60; i++) {
    const d = new Date(2026, 0, 1 + i);
    dates.push(`${d.getMonth() + 1}/${d.getDate()}`);
    const open = price;
    const close = open + (Math.random() - 0.48) * 4;
    const low = Math.min(open, close) - Math.random() * 2;
    const high = Math.max(open, close) + Math.random() * 2;
    candles.push([open, close, low, high]);
    price = close;
  }

  const chart = echarts.init(el);
  chart.setOption({
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: dates },
    yAxis: { scale: true },
    series: [{ type: "candlestick", data: candles, itemStyle: { color: "#ef4444", color0: "#22c55e", borderColor: "#ef4444", borderColor0: "#22c55e" } }],
    grid: { left: 50, right: 20, top: 20, bottom: 30 },
  });
  window.addEventListener("resize", () => chart.resize());
}
