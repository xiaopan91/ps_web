# ps_web

个人综合 Web 应用（远期以股票交易系统为主）。

## 双环境格局

| | 开发环境 | 生产环境 |
|---|---|---|
| 目录 | `D:\claude\ps_web` | `D:\deploy\ps_web` |
| 启动 | 双击 `start.bat`（8001） | NSSM 服务常驻（8000） |
| 数据库 | `ps_web_dev` | `ps_web` |
| venv / .env | 各自独立 | 各自独立 |

**发布流程**：开发目录改码 → `git push` → 到生产目录双击 `prod.bat` 选 `[8] deploy latest code`（git pull + 重启服务）。

开发环境怎么折腾（改代码、删表、试功能）都不影响生产；生产只通过 git 同步更新。

## 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 前端 | Vue 3（CDN 全局构建） | 免编译，模板直接写在 HTML 里 |
| UI | Bootstrap 5 | 本地 `static/vendor/` |
| 图表 | ECharts 5 | 本地，K 线就绪 |
| 后端 | FastAPI + uvicorn | 统一托管页面与 API |
| 数据库 | MySQL 8.0 + SQLAlchemy ORM | PyMySQL 驱动 |

前端库全部本地化（`static/vendor/`），离线可用，无跨域问题。

## 目录结构

```
app/
  main.py        # FastAPI 入口（挂路由/静态资源/首页）
  config.py      # 按项目根目录读各自 .env（两环境天然隔离的关键）
  database.py    # SQLAlchemy 引擎与会话
  routers/       # API 路由（health.py 为健康检查示例）
  models/        # ORM 模型（按功能添加）
  schemas/       # Pydantic 请求/响应模型（按功能添加）
templates/       # HTML 页面（Vue 免编译写法）
static/
  vendor/        # Vue / Bootstrap / ECharts 本地文件
  js/  css/      # 自己写的前端代码
scripts/
  init_db.py     # 建库建账号脚本（读 .env，在哪个目录跑就建哪个库）
  install_service.bat / uninstall_service.bat
run.py           # 开发入口（127.0.0.1:8001，热重载）
run_prod.py      # 生产入口（0.0.0.0:8000，无 reload）
start.bat        # 开发一键启动
prod.bat         # 生产管理台（状态/启停/日志/发布）
```

## 日常开发（D:\claude\ps_web）

双击 `start.bat`，或手动：

```bash
.venv\Scripts\activate       # CMD；Git Bash 用 source .venv/Scripts/activate
python run.py                # http://127.0.0.1:8001
```

改代码自动热重载。连的是 `ps_web_dev` 开发库。

## 生产环境（D:\deploy\ps_web）

NSSM Windows 服务 `ps_web`（开机自启、崩溃 5 秒自动拉起）：

- 本机：http://127.0.0.1:8000
- 局域网：`http://<本机IP>:8000`（防火墙规则已配）
- 日志：`logs/service.log`（10MB 轮转）

双击 `prod.bat` 打开管理菜单：状态/启停/重启/日志/健康检查/一键发布 `[8]`。
启停、重启、发布会弹一次 UAC，其余操作无需管理员。

改完代码发布：开发目录 `git push` → 生产目录 `prod.bat` 选 `[8]`。

## 个股行情页

浏览器打开 `http://127.0.0.1:8001/stock`（开发）或 `http://127.0.0.1:8000/stock`（生产）：

- 搜索框支持代码/名称模糊搜索（依赖 `stock_basic` 表）
- K 线 + 成交量副图 + MA5/10/20/60 均线，滚轮缩放 / 滑块拖动
- 区间切换（3月/6月/1年/3年/全部）与复权切换（前复权/不复权/后复权）
- URL 带参数可分享：`/stock?code=600519.SH&range=all&adjust=hfq`
- API：`/api/stock/search?q=`、`/api/stock/daily?code=&range=&adjust=`

## 市场情绪页

浏览器打开 `/sentiment`（URL 参数 `?days=90|250|750|all`）：

- 合成情绪分（0-100）：涨跌比/涨停数/连板高度/量能比/换手/两融/北向/离散度
  八因子各自按 3 年滚动历史分位数标准化后等权合成
- 指标卡片 + 五张图：情绪分×上证、涨跌家数、涨停×连板、总成交额、两融×北向
- 涨跌停为自算（主板 10% / 创业板科创板 20% / 北交所 30% / ST 5%）
- API：`/api/sentiment/history?days=`

## 行情数据同步（tushare）

数据源：tushare（token 填在 `.env` 的 `TUSHARE_TOKEN`）。全市场 A 股日线 + 复权因子 + 交易日历，
按交易日批量拉取（一次调用返回全市场当天约 5500 只）。

```bash
python scripts/sync_data.py cal                        # 交易日历（首次必跑，一次性）
python scripts/sync_data.py basic                      # 股票基本信息（偶尔刷新）
python scripts/sync_data.py index                      # 13 只指数日线（范围式）
python scripts/sync_data.py hsgt                       # 北向资金（按年分段）
python scripts/sync_data.py backfill --start 20160101  # 回补：日线/复权/换手/两融
python scripts/sync_data.py update                     # 每日增量（收盘后跑，全量+重算情绪）
python scripts/sync_data.py sentiment                  # 重算市场情绪表
```

- 幂等：按日先删后插，重跑无害；接口限流自动重试等待
- 校验：逐日落库行数与接口返回行数比对，不符告警
- 表：`daily_bar`（日线）、`adj_factor`（复权因子）、`stock_basic`（股票信息）、
  `index_daily`（13 指数）、`daily_basic`（换手/市值）、`margin_daily`（两融）、
  `hsgt_flow`（北向）、`market_sentiment`（情绪聚合缓存）
- 注意：`moneyflow_hsgt` 单次调用约 300 行上限，脚本已按年分段规避；
  `trade_cal` 限流严格（约 1 次/分钟级），分段+重试自适应

## 数据库初始化（新机器/新库时）

1. 复制 `.env.example` 为 `.env`，填写 `DB_PASSWORD` 和临时 `MYSQL_ROOT_PASSWORD`
2. `python scripts/init_db.py`（在哪个目录跑，就按那个目录的 .env 建库）
3. 成功后删掉 `.env` 里的 `MYSQL_ROOT_PASSWORD` 行

当前账号 `ps_web_user` 同时授权 `ps_web`（生产）和 `ps_web_dev`（开发）两个库。
