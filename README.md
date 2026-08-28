# AntiSWUST 教务辅助系统

面向西南科技大学教务系统的选课辅助系统。用户通过微信扫码登录，后端抓取并本地缓存 cookie（30 分钟过期），再以该 cookie 代理请求教务系统，抓取可选课程并按类型分类，前端提供多维筛选（课程名/教师/校区/星期/节次/周次）后返回符合条件的课程并提交选课。

## 真实接口（已对接，来源：开源项目抓包验证）

统一身份认证与教务系统域名均经实际探测确认：`jwxt.swust.edu.cn`/`passport.swust.edu.cn` **DNS 不存在**，真实地址如下（来自 `Kelab/auth_swust`、`YDHusky/SWUST-Tools` 抓包代码）：

| 用途 | 真实地址 |
| --- | --- |
| 统一认证 CAS | `https://cas.swust.edu.cn/authserver/login` |
| 验证码 | `https://cas.swust.edu.cn/authserver/captcha` |
| RSA 公钥 | `https://cas.swust.edu.cn/authserver/getKey` |
| 微信回调 | `http://cas.swust.edu.cn/authserver/callback` |
| 教务系统 | `https://matrix.dean.swust.edu.cn/acadmicManager/index.cfm` |
| 学生信息 | `http://myo.swust.edu.cn/mht_shall/a/service/studentInfo` |

### 微信扫码登录流程（已实现）

1. 请求 `open.weixin.qq.com/connect/qrconnect?appid=wx3e5a3c590b52de4d&redirect_uri={callback}&response_type=code&scope=snsapi_login`
2. 解析返回 HTML 中 `.js_qrcode_img` 的 src，拼接图片 URL，末段即 `uuid`
3. 轮询 `open.weixin.qq.com/connect/l/qrconnect?uuid={uuid}`，正则 `wx_code='(.*)'` 提取
4. `wx_code` 非空即扫码确认，请求回调 `{callback}?code={wx_code}&store=` 获取 CAS cookie
5. 带 cookie 访问教务门户 `?event=studentPortal:DEFAULT_EVENT` 换取教务 cookie

### 选课接口（已实现）

教务系统 `matrix.dean.swust.edu.cn` 的 `chooseCourse` 事件：

| 课程类型 | task_type | task_name | 说明 |
| --- | --- | --- | --- |
| 体育课 | `sportTask` | `SportTask` | 已确认 |
| 全校通选课 | `commonTask` | `CommonTask` | 已确认 |
| 专业限选课 | `programTask` | `PlanTask` | 已确认 |
| 补选低年级 | `programTask` | `PlanTask` | 复用，CT 轮次需按学期调整 |
| 重修 | `programTask` | `PlanTask` | 复用，CT 轮次需按学期调整 |

- **课程列表**：`GET ?event=chooseCourse:{task_type}&CT={轮次}` → 解析 `.courseShow`（`.name` + `.trigger[cid]`）
- **教学班详情**：`POST ?event=chooseCourse:api{task_name}Table`，body `CID=xxx` → 解析 `.editRows`，从 `chooseCourse('CID','CIDX','TID','TT','TSK','ST')` 提取选课参数
- **提交选课**：`POST ?event=chooseCourse:apiChoose{task_name}`，body `{CT,TID,CID,CIDX,TSK,TT,ST,seed[,CP=2]}`，返回 `{success: bool}`

## 架构

- 后端：Python + FastAPI + httpx + parsel
- 前端：Vue3 + Vite + Ant Design Vue + Pinia + Vue Router
- 登录：统一身份认证微信扫码（后端代理二维码流程）

```
AntiSWUST/
├─ backend/
│  ├─ app/
│  │  ├─ main.py              FastAPI 入口
│  │  ├─ config.py            真实 URL 配置（.env）
│  │  ├─ api/                 login.py / course.py
│  │  ├─ core/
│  │  │  ├─ cookie_store.py   本地 cookie 持久化 + 30min TTL
│  │  │  ├─ auth_adapter.py   微信扫码登录（真实流程已实现）
│  │  │  └─ swust_client.py   教务系统 HTTP 客户端
│  │  ├─ services/
│  │  │  ├─ course_service.py 五类课程抓取+选课提交（真实接口已实现）
│  │  │  └─ filter_service.py 多维筛选逻辑
│  │  └─ models/course.py     课程/筛选数据模型
│  ├─ requirements.txt
│  └─ .env.example
└─ frontend/
   ├─ src/
   │  ├─ api/ stores/ router/ components/ views/
   │  ├─ App.vue / main.ts
   └─ package.json / vite.config.ts
```

## 启动

### 一键启动（推荐）

在项目根目录执行：

```bash
python run.py
```

会自动检查并安装前后端依赖，同时启动后端 (http://127.0.0.1:8000) 与前端 (http://localhost:5173)，日志以 `[api]`/`[web]`/`[sys]` 彩色前缀区分。按 `Ctrl+C` 停止全部服务。

需要后端代码热重载时：`RUN_RELOAD=1 python run.py`

### 分别启动

后端：

```bash
cd backend
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

前端：

```bash
cd frontend
npm install
npm run dev
```

访问 http://localhost:5173 ，自动跳转登录页扫码。

## 待校内联调确认

> 教务系统 `matrix.dean.swust.edu.cn` 仅校内网/VPN 可访问（外网 ping/TCP 全不可达），以下需在校内实测微调：

1. **选课轮次 CT**：`config.py` 的 `choose_course_ct` 及补选/重修的 `CATEGORY_CT_OVERRIDE`，按学期选课通知调整
2. **教学班表格字段**：`course_service.py` 的 `_parse_class_table` 中表头映射（课程名称/教师/校区/容量/已选/时间）需对照实际 HTML 列名
3. **时间字符串格式**：`_parse_time_str` 当前按 `周一第1-2节{1-16周}` 解析，若实际格式不同需调整正则
4. **补选低年级 / 重修**：真实 event 是否复用 `programTask` 还是单独事件，需抓包确认
5. **学生信息字段**：`auth_adapter._fetch_user_profile` 中 `xm`/`xh` 字段名需对照实际返回
