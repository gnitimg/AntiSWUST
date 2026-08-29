# AntiSWUST 教务辅助系统

面向西南科技大学教务系统的选课辅助系统。微信扫码登录 → 后端代理登录并本地持久化登录态 → 代理请求教务系统抓取可选课程 → 前端多维筛选后提交**选课 / 退课 / 抢课**。

> 完整需求与实现交接见 [HANDOVER.md](./HANDOVER.md)

## 功能

- **所有选课**：体育项目 / 全校通选课 / 计划课程 / 补选低年级课程 / 重新学习（重修），五个分类
  - 两阶段加载：课程列表秒出，教学班详情（教师/时间/余量/选课参数）后台补齐
  - 实时筛选：课程名 / 教师 / 校区 / 星期 / 节次 / 课程组 / 仅看有余量
  - 状态区分：可选 / 已选 / 已满 / 锁定（置灰）/ 详情未加载
  - 每行可直接 **选课**、**退课**（参数自动关联已选清单）、**抢课**（设定频率自动重试）
- **我的选课**：已选课程清单，可退课程一键退课；往期轮次锁定记录明确标注
- **实验功能 · 预置选课**：提前录入/导入选课意向，开始选课后自动匹配提交（支持定时、重试、优先级、同类只选一门）
- **实验功能 · 抢课**：多课程并发抢课任务；请求间隔下限 0.5s、持续时间不限上限（0=不限时）；抢到自动熔断该课程任务；每 5 分钟自动刷新选课参数（ST 哈希时效）
- **实验功能 · 预置选课**：提前导入/录入意向课程（CSV 或手动，主要体育项目），页面内预选启用；开始选课后自动按课程名+教师+课序号+校区+时间匹配真实课程并按优先级提交，失败可自动重试，支持定时开始、同类只选一门
- **实验功能 · 课程组**：自定义名称、自由加课；选课页筛选栏按组快速过滤

## 架构

- 后端：Python + FastAPI + httpx + parsel（同步 Client + asyncio.to_thread，atrust VPN 下 AsyncClient TLS 握手失败）
- 前端：Vue3 + Vite + Element Plus + Pinia（基于 [v3-admin-vite](https://github.com/un-pany/v3-admin-vite) 模板）
- 登录：统一身份认证微信扫码（后端代理二维码流程）；登录态本地持久化，当前**不限制时长**（原 30 分钟，`backend/app/config.py` 注释可恢复）

## 真实接口（已对接，抓包验证）

| 用途 | 真实地址 |
| --- | --- |
| 统一认证 CAS | `https://cas.swust.edu.cn/authserver/login` |
| 微信扫码 | `https://open.weixin.qq.com/connect/qrconnect?appid=wx3e5a3c590b52de4d&...` |
| 教务系统 | `https://matrix.dean.swust.edu.cn/acadmicManager/index.cfm` |
| 学生信息 | `http://myo.swust.edu.cn/mht_shall/a/service/studentInfo` |

教务 `chooseCourse` 事件族：

| 课程类型 | task_type（列表） | table_api（教学班） | choose_api（选课） |
| --- | --- | --- | --- |
| 体育课 | `sportTask` | `apiSportTaskTable` | `apiChooseSportTask` |
| 全校通选课 | `commonTask` | `apiCommonTaskTable` | `apiChooseCommonTask` |
| 专业限选课 | `programTask` | `apiPlanTaskTable` | `apiChoosePlanTask` |
| 补选低年级 | `fixupTask` | `apiFixupPlanTaskTable` | `apiFixupPlanTask`（无 Choose 前缀） |
| 重修 | `retakeTask` | `apiRetakePlanTaskTable` | `apiRetakePlanTask`（无 Choose 前缀） |

- **课程列表**：`GET ?event=chooseCourse:{task_type}&CT={轮次}` → 解析 `.courseShow`；页面内嵌已选课程清单（`div#Choosen`），退课所需的 `chooserId`（SCC）即来自其中 `removeTask(...)` 调用
- **教学班详情**：`POST ?event=chooseCourse:{table_api}`，body `TID/CID/seed` → 解析 `.editRows`（表头列名跨分类有差异，后端按别名归一化）
- **提交选课**：`POST ?event=chooseCourse:{choose_api}`，body `{CT,TID,CID,CIDX,TSK,TT,ST,seed[,CP]}` → `{success, reason?}`
- **取消选课**：`POST ?event=chooseCourse:apiCancelTask`（五类统一），body 同上 + `SCC`

## 启动

### 一键启动（推荐）

```bash
python3 run.py
```

自动检查并安装前后端依赖，同时启动后端 (http://127.0.0.1:8000) 与前端 (http://localhost:5173)。按 `Ctrl+C` 停止全部。禁用后端热重载：`RUN_NO_RELOAD=1 python3 run.py`

### 分别启动

后端：

```bash
cd backend
pip install -r requirements.txt
copy .env.example .env   # Windows；Linux 为 cp
uvicorn app.main:app --reload --port 8000
```

前端：

```bash
cd frontend
npm install
npm run dev
```

访问 http://localhost:5173 （hash 路由），微信扫码登录。

### 解析单测

```bash
python3 backend/tests/test_parsing.py
```

使用内联 fixture 与 `captures/five2/` 实测抓包数据验证解析逻辑（已选清单 / 课程列表 / 教学班表格 / 表头别名 / 时间格式）。

## 注意事项

- 教务系统仅校内网 / atrust VPN 可达；matrix 门户页渲染很慢（>15s），登录流程已做超时容错
- 教务系统对同一会话的请求近似串行（老 CFM 应用），并发抓取/抢课任务过多会互相排队
- 抢课请求间隔下限 0.5 秒（后端强制），请勿过低以免触发限流
- 登录态 cookie、auth jar、课程组均存于 `backend/data/`（已 gitignore），勿提交
- 选课轮次 CT 当前为 2，按学期选课通知在 `backend/app/config.py` 调整
