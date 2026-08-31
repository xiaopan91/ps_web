// 任务中心：脚本运行 / 定时规则 / 历史记录
const { createApp, onMounted, onUnmounted, ref } = Vue;

const app = createApp({
  setup() {
    const tasks = ref([]);
    const cur = ref(null);
    const runs = ref([]);
    const schedules = ref([]);
    const logView = ref(null);
    const paramVals = ref({});
    const msg = ref("");
    const newRule = ref({ task_id: "", run_time: "16:35", weekdays: [1, 2, 3, 4, 5] });
    const editing = ref(null);

    function startEdit(s) {
      editing.value = { id: s.id, run_time: s.run_time, weekdays: [...s.weekdays] };
    }

    async function saveEdit() {
      const e = editing.value;
      if (!e.weekdays.length) { alert("至少选择一个星期"); return; }
      const res = await fetch(`/api/tasks/schedules/${e.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_time: e.run_time, weekdays: e.weekdays }),
      });
      if (!res.ok) {
        const m = await res.json().catch(() => ({}));
        alert(m.detail || `HTTP ${res.status}`);
        return;
      }
      editing.value = null;
      loadSchedules();
    }
    let timer = null;

    const fmtDur = s => {
      if (s == null) return "—";
      if (s < 60) return s + "秒";
      if (s < 3600) return Math.floor(s / 60) + "分" + (s % 60) + "秒";
      return Math.floor(s / 3600) + "时" + Math.floor(s % 3600 / 60) + "分";
    };
    const fmtWeek = ws => ws.map(w => "一二三四五六日"[w - 1]).join("");
    const statusText = s => ({ running: "运行中", success: "成功", failed: "失败" }[s] || s);

    async function loadTasks() {
      tasks.value = await (await fetch("/api/tasks")).json();
      for (const t of tasks.value) {
        const vals = {};
        for (const p of t.params) vals[p.key] = p.default ?? "";
        paramVals.value[t.id] = vals;
      }
    }

    async function loadCurrent() {
      const wasRunning = !!cur.value;
      cur.value = await (await fetch("/api/tasks/current")).json();
      if (wasRunning && !cur.value) loadRuns();  // 刚结束，刷新历史
    }

    async function loadRuns() {
      runs.value = await (await fetch("/api/tasks/runs?limit=50")).json();
    }

    async function loadSchedules() {
      schedules.value = await (await fetch("/api/tasks/schedules")).json();
    }

    async function runTask(t) {
      if (t.long && !confirm(`「${t.name}」是长任务（${t.duration}），确认运行？`)) return;
      const params = {};
      for (const p of t.params) {
        const v = paramVals.value[t.id]?.[p.key];
        if (v !== "" && v != null) params[p.key] = v;
      }
      const res = await fetch(`/api/tasks/${t.id}/run`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ params }),
      });
      if (!res.ok) {
        const m = await res.json().catch(() => ({}));
        alert(m.detail || `HTTP ${res.status}`);
        return;
      }
      loadCurrent();
    }

    async function addSchedule() {
      const body = {
        task_id: newRule.value.task_id,
        run_time: newRule.value.run_time,
        weekdays: newRule.value.weekdays,
        params: {},
      };
      const res = await fetch("/api/tasks/schedules", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const m = await res.json().catch(() => ({}));
        alert(m.detail || `HTTP ${res.status}`);
        return;
      }
      newRule.value.task_id = "";
      loadSchedules();
    }

    async function toggleSchedule(s) {
      await fetch(`/api/tasks/schedules/${s.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !s.enabled }),
      });
      loadSchedules();
    }

    async function delSchedule(s) {
      if (!confirm(`删除定时规则「${s.task_name} ${s.run_time}」？`)) return;
      await fetch(`/api/tasks/schedules/${s.id}`, { method: "DELETE" });
      loadSchedules();
    }

    async function showLog(r) {
      const res = await fetch(`/api/tasks/runs/${r.id}/log`);
      const d = await res.json();
      logView.value = { id: r.id, name: r.task_name, content: d.log || "(空)" };
    }

    function tick() {
      loadCurrent();
      if (!cur.value) loadRuns();
    }

    onMounted(async () => {
      await loadTasks();
      await Promise.all([loadCurrent(), loadRuns(), loadSchedules()]);
      timer = setInterval(tick, 4000);
    });
    onUnmounted(() => clearInterval(timer));

    return { tasks, cur, runs, schedules, logView, paramVals, msg, newRule,
             editing, startEdit, saveEdit,
             runTask, addSchedule, toggleSchedule, delSchedule, showLog,
             fmtDur, fmtWeek, statusText };
  },
});

app.mount("#app");
