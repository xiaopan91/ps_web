"""任务中心注册表：可通过 HTTP 触发的脚本清单（数据同步类）。

只注册幂等/安全的数据脚本；init_db（需 root、破坏性）与
backtest_grid（参数复杂、不适合定时）不入册。
"""
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"

TASKS = [
    {
        "id": "update", "name": "每日增量更新",
        "desc": "日线/复权/换手/两融前向增量 + 缺口自愈 + 指数/北向补差 + 重算情绪表",
        "script": "sync_data.py", "args": ["update"],
        "params": [], "duration": "约5-10分钟", "long": False,
    },
    {
        "id": "sentiment", "name": "重算市场情绪表",
        "desc": "从底层数据表全量重算 market_sentiment",
        "script": "sync_data.py", "args": ["sentiment"],
        "params": [
            {"key": "start", "label": "起始日期(YYYYMMDD，留空全量)",
             "type": "text", "required": False, "flag": "--start"},
        ],
        "duration": "约4-6分钟", "long": False,
    },
    {
        "id": "pvrank", "name": "重建量价因子排名表",
        "desc": "重算全市场量价综合分（个股预测排名页数据源，增量）",
        "script": "sync_data.py", "args": ["pvrank"],
        "params": [
            {"key": "full", "label": "全量重建",
             "type": "select", "choices": ["增量", "全量"],
             "required": False, "flag_map": {"增量": "", "全量": "--full"}},
        ],
        "duration": "约1-3分钟", "long": False,
    },
    {
        "id": "basic", "name": "同步股票基本信息",
        "desc": "在市股票清单（名称/行业），整表刷新",
        "script": "sync_data.py", "args": ["basic"],
        "params": [], "duration": "约1分钟", "long": False,
    },
    {
        "id": "index", "name": "同步指数日线",
        "desc": "13 只核心/风格指数，各自从最后日期往后补",
        "script": "sync_data.py", "args": ["index"],
        "params": [], "duration": "约1分钟", "long": False,
    },
    {
        "id": "hsgt", "name": "同步北向资金",
        "desc": "沪深港通资金流向，按年分段增量",
        "script": "sync_data.py", "args": ["hsgt"],
        "params": [], "duration": "约1分钟", "long": False,
    },
    {
        "id": "etf", "name": "同步 ETF 日线",
        "desc": "常用网格标的清单，各自从最后日期往后补",
        "script": "sync_data.py", "args": ["etf"],
        "params": [
            {"key": "codes", "label": "ETF代码(逗号分隔，留空用默认清单)",
             "type": "text", "required": False, "flag": "--codes"},
        ],
        "duration": "约1-3分钟", "long": False,
    },
    {
        "id": "cal", "name": "同步交易日历",
        "desc": "上交所日历 2015-2027 整表刷新（接口限流严格，约5分钟）",
        "script": "sync_data.py", "args": ["cal"],
        "params": [], "duration": "约5分钟", "long": False,
    },
    {
        "id": "backfill", "name": "回补历史（长任务）",
        "desc": "指定区间逐日拉取四个接口（日线/复权/换手/两融），幂等可重跑",
        "script": "sync_data.py", "args": ["backfill"],
        "params": [
            {"key": "start", "label": "开始日期 YYYYMMDD",
             "type": "text", "required": True, "flag": "--start"},
            {"key": "end", "label": "结束日期(留空=今天)",
             "type": "text", "required": False, "flag": "--end"},
            {"key": "sleep", "label": "调用间隔秒(默认0.35)",
             "type": "number", "required": False, "flag": "--sleep"},
        ],
        "duration": "小时级", "long": True,
    },
    {
        "id": "db_comments", "name": "数据库注释补齐",
        "desc": "依据模型定义为存量库补/更新表与字段注释",
        "script": "db_comments.py", "args": [],
        "params": [
            {"key": "target", "label": "目标库",
             "type": "select", "choices": ["both", "dev", "prod"],
             "required": False, "positional": True, "default": "both"},
        ],
        "duration": "秒级", "long": False,
    },
]

TASK_INDEX = {t["id"]: t for t in TASKS}
