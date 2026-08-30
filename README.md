# ps_web

个人综合 Web 应用（远期以股票交易系统为主）。当前阶段：开发环境骨架。

## 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 前端 | Vue 3（CDN 全局构建） | 免编译，模板直接写在 HTML 里 |
| UI | Bootstrap 5 | 本地 `static/vendor/` |
| 图表 | ECharts 5 | 本地，K 线就绪 |
| 后端 | FastAPI + uvicorn | 端口 8000，同时托管页面与 API |
| 数据库 | MySQL 8.0 + SQLAlchemy ORM | PyMySQL 驱动 |

前端库全部本地化（`static/vendor/`），离线可用，无跨域问题。

## 目录结构

```
app/
  main.py        # FastAPI 入口（挂路由/静态资源/首页）
  config.py      # 读 .env 配置
  database.py    # SQLAlchemy 引擎与会话
  routers/       # API 路由（health.py 为健康检查示例）
  models/        # ORM 模型（按功能添加）
  schemas/       # Pydantic 请求/响应模型（按功能添加）
templates/       # HTML 页面（Vue 免编译写法）
static/
  vendor/        # Vue / Bootstrap / ECharts 本地文件
  js/  css/      # 自己写的前端代码
scripts/
  init_db.py     # 一次性建库建账号脚本
run.py           # 开发服务器启动入口
```

## 首次搭建（已完成的机器可跳过）

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

## 日常开发

0. **一键启动（推荐）**

   双击项目根目录的 `start.bat`。它会自动：

   - 检查虚拟环境是否存在
   - 检查 MySQL80 服务，停了就尝试拉起（权限不足时提示右键管理员运行）
   - 启动开发服务器，服务就绪后自动打开浏览器（端口已被占用则只开浏览器）
   - 窗口就是日志窗口，`Ctrl+C` 停止

1. **激活虚拟环境**

   | 终端 | 命令 |
   |---|---|
   | CMD | `.venv\Scripts\activate` |
   | PowerShell | `.venv\Scripts\Activate.ps1` |
   | Git Bash | `source .venv/Scripts/activate` |

2. **启动**

   ```bash
   python run.py
   ```

3. **访问**

   - 页面：http://127.0.0.1:8001
   - API 文档：http://127.0.0.1:8001/docs
   - 健康检查：http://127.0.0.1:8001/api/health

改代码自动热重载（`--reload` 已开）。开发用 8001，生产服务常驻 8000，互不冲突。

## 生产部署（NSSM Windows 服务）

生产入口 `run_prod.py`（0.0.0.0:8000、无 reload、无颜色码）。已注册为 Windows 服务 `ps_web`：

- **开机自启**（不需要登录），崩溃后 5 秒自动拉起
- 日志：`logs/service.log`（10MB 自动轮转）
- 局域网内其他设备可通过 `http://<本机IP>:8000` 访问

常用命令（管理员终端）：

```bat
sc query ps_web                 :: 查看状态
nssm restart ps_web             :: 重启（改完生产代码后）
nssm stop ps_web                :: 停止
nssm start ps_web               :: 启动
scripts\uninstall_service.bat   :: 卸载服务（含防火墙规则）
```

也可以直接**双击 `prod.bat`**：图形菜单一站式管理（看状态/启停/重启/看日志/健康检查/开页面），
其中启停重启会自动弹一次 UAC，其余操作无需管理员权限。

重新安装服务：右键「以管理员身份运行」`scripts\install_service.bat`（首次安装需先把 nssm.exe 放到 `tools\` 下）。

## 数据库初始化（只需一次）

1. 复制 `.env.example` 为 `.env`（项目里已有一份），填写：
   - `DB_PASSWORD`：你想给应用账号 `ps_web_user` 设置的密码
   - `MYSQL_ROOT_PASSWORD`：MySQL root 密码（仅建库用）
2. 激活虚拟环境后运行：

   ```bash
   python scripts/init_db.py
   ```

3. 建库成功后，把 `.env` 里的 `MYSQL_ROOT_PASSWORD` 一行删掉。
