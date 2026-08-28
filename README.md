# AntiSWUST 教务辅助系统

面向西南科技大学教务系统的选课辅助系统。用户通过微信扫码登录，后端抓取并本地缓存 cookie（30 分钟过期），再以该 cookie 代理请求教务系统，抓取可选课程并按类型分类，前端提供多维筛选（课程名/教师/校区/星期/节次/周次）后返回符合条件的课程并提交选课。

> 完整需求与实现交接见 [HANDOVER.md](./HANDOVER.md)

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

后端默认开启代码热重载；需要禁用时：`RUN_NO_RELOAD=1 python run.py`

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


教务系统登陆：http://cas.swust.edu.cn/authserver/login?service=https%3A%2F%2Fmatrix%2Edean%2Eswust%2Eedu%2Ecn%2FacadmicManager%2Findex%2Ecfm%3Fevent%3DstudentPortal%3ADEFAULT%5FEVENT

登陆二维码请求：
https://open.weixin.qq.com/connect/qrconnect?appid=wx3e5a3c590b52de4d&redirect_uri=http://cas.swust.edu.cn/authserver/callback&response_type=code&scope=snsapi_login

二维码元素：<img class="js_qrcode_img web_qrcode_img" src="/connect/qrcode/081izoc22mqZGa1b">；<img class="js_qrcode_img web_qrcode_img" src="/connect/qrcode/041wKElz08gTFa11">
每次qrcode/后内容都不一样。

二维码扫描后：https://lp.open.weixin.qq.com/connect/l/qrconnect?uuid=0310ADVe0ZlCFa1o&last=404

体育项目课：https://matrix.dean.swust.edu.cn/acadmicManager/index.cfm?event=chooseCourse:sportTask&CT=2
补选低年级课程：https://matrix.dean.swust.edu.cn/acadmicManager/index.cfm?event=chooseCourse:fixupTask&CT=2
重新学习：https://matrix.dean.swust.edu.cn/acadmicManager/index.cfm?event=chooseCourse:retakeTask&CT=2
计划课程：https://matrix.dean.swust.edu.cn/acadmicManager/index.cfm?event=chooseCourse:programTask&CT=2
全校通选课：https://matrix.dean.swust.edu.cn/acadmicManager/index.cfm?event=chooseCourse:commonTask&CT=2

## 二级目录课程列表请求方法与格式（已实测）

> 通过 Chrome DevTools Protocol 在已登录态下对五个分类列表页实测抓取（2026-08-28，CT=2，校园 VPN 环境）。五个分类均成功拿到完整响应 HTML。全部原始数据（DOM、网络请求清单、cookie）存于 `captures/five2/`。

### 请求方法

- **HTTP 方法**：`GET`
- **URL 模板**：`https://matrix.dean.swust.edu.cn/acadmicManager/index.cfm?event=chooseCourse:{task_type}&CT={轮次}`
- **参数**：
  - `event` = `chooseCourse:{task_type}`，`task_type` 见下表
  - `CT` = 选课轮次（当前学期为 `2`，需按学期通知调整）
- **返回**：`text/html`，含全部课程的 `<div class="courseShow">` 列表（非 AJAX，单次 GET 即全量）
- **依赖**：需携带有效的 matrix.dean.swust.edu.cn session cookie（通过 CAS 登录换取）；session 失效会 302 回跳 CAS 登录页

### 五个分类的 task_type 与实测结果

| 分类 | task_type | 列表请求 URL | 课程总数 | 可选(trigger) | 锁定 |
| --- | --- | --- | --- | --- | --- |
| 体育项目课 | `sportTask` | `?event=chooseCourse:sportTask&CT=2` | 25 | 25 | 0 |
| 补选低年级课程 | `fixupTask` | `?event=chooseCourse:fixupTask&CT=2` | 1 | 1 | 0 |
| 重新学习（重修） | `retakeTask` | `?event=chooseCourse:retakeTask&CT=2` | 11 | 11 | 0 |
| 计划课程（专业限选） | `programTask` | `?event=chooseCourse:programTask&CT=2` | 8 | 3 | 5 |
| 全校通选课 | `commonTask` | `?event=chooseCourse:commonTask&CT=2` | 179 | 179 | 0 |

### 响应 HTML 结构

**可选课程**（有教学班入口）：

```html
<div class="courseShow clearfix" cid="121299" prop="1">
  <div class="UIChooser">
    <div class="title">
      <a cid="121299" class="trigger close"></a>          <!-- trigger: 展开/折叠教学班，cid 即课程 ID -->
      <span class="name">大学体育3-保健体育</span>         <!-- 课程名 -->
      <span class="numeric">1.00</span>                    <!-- 学分 -->
      <span>学分</span>
      <span class="type t1">必修</span>                    <!-- 课程性质：t1=必修 t2=限选 -->
    </div>
    <div class="courseDesc hidden_elem" cid="121299"> ... </div>  <!-- 开课部门/学时等 -->
    <div class="taskList hidden_elem" cid="121299"></div>         <!-- 教学班容器，初始空，点击 trigger 后 AJAX 加载 -->
  </div>
</div>
```

**锁定课程**（不可选，无教学班入口，仅 programTask 实测到）：

```html
<div class="courseShow clearfix" cid="120555" prop="1">
  <div class="UIChooser">
    <div class="title">
      <span class="stat locked"></span>                   <!-- 锁定标记，代替 trigger -->
      <span class="name">编译原理</span>
      ...
    </div>
    ...
  </div>
</div>
```

**已选课程**：trigger 带额外 `checked` 类，如 `<a cid="120576" class="trigger close checked"></a>`

### 解析选择器（对照 `course_service._parse_course_list`）

| 字段 | 选择器 | 实测结果 |
| --- | --- | --- |
| 课程列表容器 | `.courseShow` | ✓ 每门课一个 div（含可选+锁定） |
| 课程 ID（可选课） | `.trigger::attr(cid)` 或 `div.courseShow::attr(cid)` | ✓ 两者一致 |
| 课程名 | `.name::text` | ✓ |
| 学分 | `.numeric::text`（第一个） | ✓ |
| 课程性质 | `.type::text` / `prop` 属性（1=必修,2=限选） | 可选 |
| 锁定状态 | `.stat.locked` 存在即锁定 | 现代码未识别，但 `if not cid: continue` 会跳过锁定课（因无 trigger） |

> 现有 `_parse_course_list` 用 `.trigger::attr(cid)` 取 cid，**锁定课程因无 trigger 自动被跳过**——符合"只列可选课程"语义，行为正确。如需展示锁定课程（标灰），需改用 `div.courseShow::attr(cid)` 取 cid 并检查 `.stat.locked`。

### 代码修正（已实施）

`backend/app/services/course_service.py` 的 `CATEGORY_TASK` 已按实测修正，改为 `task_type`/`table_api`/`choose_api` 三字段映射：

| 枚举 | task_type | table_api（教学班） | choose_api（选课） |
| --- | --- | --- | --- |
| `PE` | `sportTask` | `apiSportTaskTable` | `apiChooseSportTask` |
| `GENERAL` | `commonTask` | `apiCommonTaskTable` | `apiChooseCommonTask` |
| `MAJOR_LIMITED` | `programTask` | `apiPlanTaskTable` | `apiChoosePlanTask` |
| `SUPPLEMENT` | `fixupTask` | `apiFixupPlanTaskTable` | `apiFixupPlanTask` |
| `RETAKE` | `retakeTask` | `apiRetakePlanTaskTable` | `apiRetakePlanTask` |

> 注意：`sportTask`/`commonTask`/`programTask` 选课 API 带 `Choose` 前缀，`fixupTask`/`retakeTask` **不带**。已用完整 `choose_api` 字段规避前缀差异。

## 教学班详情 / 选课提交 / 取消选课 API（已实测）

> 以下从五个分类列表页的 JS（`chooseCourse` / `removeTask` 函数体）提取，2026-08-28 实测。全部为 `POST`，`Content-Type: application/x-www-form-urlencoded`，返回 JSON（选课/取消）或 HTML 片段（教学班）。

### 1. 教学班详情

- **请求**：`POST index.cfm?event=chooseCourse:{table_api}`
- **body**：`TID={学期ID}&CID={课程ID}&seed={毫秒时间戳}`
- **返回**：HTML 片段，填入 `div.taskList[cid]`，内含教学班表格与 `chooseCourse(...)` 选课调用
- **TID 来源**：列表页 JS 内硬编码 `'TID' : '261'`（学期 ID，每学期变），后端用 `_extract_tid` 正则 `'TID'\s*:\s*'(\d+)'` 提取

### 2. 选课提交

- **请求**：`POST index.cfm?event=chooseCourse:{choose_api}`
- **body**：

| 字段 | 说明 | 来源 |
| --- | --- | --- |
| `CT` | 选课轮次 | 配置（当前 2） |
| `TID` | 学期 ID | 列表页提取 |
| `CID` | 课程 ID | 教学班 chooseCourse 调用第 1 参 |
| `CIDX` | 教学班索引 | chooseCourse 第 2 参 |
| `TSK` | 任务 ID | chooseCourse 第 5 参 |
| `TT` | 任务类型 | chooseCourse 第 4 参（sportTask 固定 `'T'`） |
| `ST` | 哈希校验 | chooseCourse 第 6 参 |
| `CP` | 课程性质 | `div.courseShow` 的 `prop` 属性（仅 fixupTask/retakeTask 需要） |
| `seed` | 时间戳 | `Date.now()` |

- **返回**：JSON `{success: bool, reason?: string}`
- **成功后**：前端再 POST `apiChoosenCourseTable`（刷新课表）和 `apiChoosenTaskTable`（刷新已选清单），body 均 `TID/seed`

### 3. 取消选课（退课）

- **请求**：`POST index.cfm?event=chooseCourse:apiCancelTask`（五个分类统一）
- **body**：`CT/TID/CID/CIDX/TSK/TT/ST` 同选课，额外 `SCC={chooserId}`（选课记录 ID）
- **chooserId 来源**：已选课程表里 `removeTask(chooserId, courseId, courseIdx, termId, taskType, taskId, hash)` 的第 1 参，形如 `5120246728,121387,261T`（学号+cid+termId+taskType 拼接）
- **返回**：JSON `{success: bool, reason?: string}`

### JS 函数签名（实测）

```javascript
// 选课（教学班详情展开后，点击某教学班触发）
chooseCourse(courseId, courseIdx, termId, taskType, taskId, hash)
// 取消（已选课程表里点撤销触发）
removeTask(chooserId, courseId, courseIdx, termId, taskType, taskId, hash)
```

### 后端已实现

- `course_service.select()`：用 `choose_api`，body 按上表构造，fixup/retake 附 `CP`
- `course_service.cancel()`：新增，用 `apiCancelTask`，body 附 `SCC`
- `course_service._fetch_class_details()`：用 `table_api`，body 附 `TID/seed`
- `course_service._extract_tid()`：新增，从列表页 HTML 提取学期 ID
- API 端点：`POST /api/course/cancel`（`CancelCourseRequest{course_id, category, chooser_id}`）
- 前端：`cancelCourse(req)` 已加

### 已记录的原始数据（`captures/five2/`）

| 文件 | 内容 |
| --- | --- |
| `00_cookies.json` | 登录态全部 63 条 cookie（含 matrix/cas 域） |
| `NN_<task>.html` | 各分类列表页渲染后 DOM（含完整 JS：chooseCourse/removeTask 函数体） |
| `NN_<task>_requests.json` | 各分类全部网络请求（URL/方法/请求头/请求体/响应状态/响应头/响应体） |

