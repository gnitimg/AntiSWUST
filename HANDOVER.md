# AntiSWUST 交接文档

> 西南科技大学教务辅助选课系统 · 实现交接（最后更新：2026-08-28）

## 一、项目背景

西南科技大学教务系统（`matrix.dean.swust.edu.cn`）界面混乱，学生无法直观查看可选课程，也难以按课程名/教师/星期/节次/周次/校区快速筛选。本项目在不替换原教务系统的前提下，做一个辅助选课前端：用户微信扫码登录后，后端抓取并缓存 cookie（30 分钟过期），代理请求教务系统拉取可选课程，前端提供多维筛选后提交选课/退课。

## 二、架构

| 层 | 技术栈 | 说明 |
| --- | --- | --- |
| 前端 | Vue3 + Vite + Ant Design Vue + Pinia + Vue Router | 登录页(二维码+串行轮询)、选课页(分类Tab+筛选+选课/退课)、诊断页 |
| 后端 | Python + FastAPI + httpx + parsel | 微信扫码登录代理、cookie 本地持久化、教务系统爬取与筛选 |
| 一键启动 | run.py | 自动检查/安装前后端依赖，同时启动 uvicorn + vite |

```
AntiSWUST/
├─ run.py                      一键启动（进程组隔离，Linux 安全退出）
├─ scripts/
│  ├─ capture.py               mitmproxy 抓包脚本
│  ├─ cdp_capture.py           Chrome DevTools Protocol 单页抓取
│  └─ cdp_fetch_five.py        CDP 批量抓取五个分类列表页
├─ captures/five2/             实测抓包数据（DOM/请求/cookie）
├─ backend/
│  ├─ app/
│  │  ├─ main.py               FastAPI 入口
│  │  ├─ config.py             真实 URL 配置（.env）
│  │  ├─ api/
│  │  │  ├─ login.py           登录接口 + 诊断端点
│  │  │  └─ course.py          选课/退课接口
│  │  ├─ core/
│  │  │  ├─ cookie_store.py    本地 cookie 持久化 + 30min TTL
│  │  │  ├─ auth_adapter.py    微信扫码登录（真实流程）
│  │  │  └─ swust_client.py    教务系统 HTTP 客户端（同步 Client + to_thread）
│  │  ├─ services/
│  │  │  ├─ course_service.py  五类课程抓取 + 选课/退课提交 + 60s缓存
│  │  │  └─ filter_service.py  多维筛选逻辑
│  │  └─ models/course.py      课程/筛选数据模型
│  ├─ requirements.txt
│  └─ .env.example
└─ frontend/
   └─ src/
      ├─ api/ stores/ router/ components/ views/
      ├─ App.vue / main.ts
      └─ package.json / vite.config.ts
```

## 三、所有教务系统请求接口（2026-08-28 实测，CT=2）

> 全部接口仅校内网或 atrust VPN 可达，外网不可访问。实测环境：Chrome DevTools Protocol + 校园 VPN。

### 3.1 统一身份认证 CAS

| 用途 | URL | 方法 |
| --- | --- | --- |
| CAS 登录页 | `https://cas.swust.edu.cn/authserver/login?service={教务门户URL}` | GET |
| 验证码 | `https://cas.swust.edu.cn/authserver/captcha` | GET |
| RSA 公钥 | `https://cas.swust.edu.cn/authserver/getKey` | GET |
| 微信回调 | `https://cas.swust.edu.cn/authserver/callback?code={wx_code}&store=` | GET |

### 3.2 微信扫码

| 用途 | URL | 方法 |
| --- | --- | --- |
| 二维码页 | `https://open.weixin.qq.com/connect/qrconnect?appid=wx3e5a3c590b52de4d&redirect_uri={callback}&response_type=code&scope=snsapi_login` | GET |
| 二维码图片 | `https://open.weixin.qq.com/connect/qrcode/{uuid}` | GET |
| 长轮询状态 | `https://open.weixin.qq.com/connect/l/qrconnect?uuid={uuid}` | GET（hold ~25-35s） |
| 长轮询备用 | `https://lp.open.weixin.qq.com/connect/l/qrconnect?uuid={uuid}&last=404` | GET |

**轮询返回 `wx_errcode`**：408 未扫码 / 404 已扫码待确认 / 405 已确认（带 `wx_code`）

### 3.3 教务系统门户

| 用途 | URL | 方法 |
| --- | --- | --- |
| 教务首页 | `https://matrix.dean.swust.edu.cn/acadmicManager/index.cfm?event=studentPortal:DEFAULT_EVENT` | GET |
| 学生信息 | `http://myo.swust.edu.cn/mht_shall/a/service/studentInfo` | GET（返回 JSON，字段 `xm`/`xh`） |

### 3.4 选课 — 五个分类列表页

统一 URL 模板：`GET https://matrix.dean.swust.edu.cn/acadmicManager/index.cfm?event=chooseCourse:{task_type}&CT={轮次}`

| 分类 | task_type | 列表请求 URL | 实测课程数 | 可选 | 锁定 |
| --- | --- | --- | --- | --- | --- |
| 体育项目课 | `sportTask` | `?event=chooseCourse:sportTask&CT=2` | 25 | 25 | 0 |
| 补选低年级 | `fixupTask` | `?event=chooseCourse:fixupTask&CT=2` | 1 | 1 | 0 |
| 重新学习（重修） | `retakeTask` | `?event=chooseCourse:retakeTask&CT=2` | 11 | 11 | 0 |
| 计划课程（专业限选） | `programTask` | `?event=chooseCourse:programTask&CT=2` | 8 | 3 | 5 |
| 全校通选课 | `commonTask` | `?event=chooseCourse:commonTask&CT=2` | 179 | 179 | 0 |

返回 `text/html`，含全部课程的 `<div class="courseShow">` 列表（非 AJAX，单次 GET 即全量）。

### 3.5 选课 — 教学班详情

- **请求**：`POST index.cfm?event=chooseCourse:{table_api}`
- **body**：`TID={学期ID}&CID={课程ID}&seed={毫秒时间戳}`
- **返回**：HTML 片段，含教学班表格 `.editRows` 与 `chooseCourse(...)` 选课 JS 调用
- **TID 来源**：列表页 JS 内硬编码 `'TID' : '261'`（学期 ID，每学期变）

| 分类 | table_api |
| --- | --- |
| 体育项目课 | `apiSportTaskTable` |
| 全校通选课 | `apiCommonTaskTable` |
| 计划课程 | `apiPlanTaskTable` |
| 补选低年级 | `apiFixupPlanTaskTable` |
| 重新学习 | `apiRetakePlanTaskTable` |

### 3.6 选课 — 提交选课

- **请求**：`POST index.cfm?event=chooseCourse:{choose_api}`
- **Content-Type**：`application/x-www-form-urlencoded`
- **body**：

| 字段 | 说明 | 来源 |
| --- | --- | --- |
| `CT` | 选课轮次 | 配置（当前 2） |
| `TID` | 学期 ID | 列表页提取 |
| `CID` | 课程 ID | chooseCourse 第 1 参 |
| `CIDX` | 教学班索引 | chooseCourse 第 2 参 |
| `TSK` | 任务 ID | chooseCourse 第 5 参 |
| `TT` | 任务类型 | chooseCourse 第 4 参 |
| `ST` | 哈希校验 | chooseCourse 第 6 参 |
| `CP` | 课程性质 | `div.courseShow` 的 `prop` 属性（仅 fixup/retake 需要） |
| `seed` | 时间戳 | `Date.now()` |

- **返回**：JSON `{success: bool, reason?: string}`

| 分类 | choose_api |
| --- | --- |
| 体育项目课 | `apiChooseSportTask` |
| 全校通选课 | `apiChooseCommonTask` |
| 计划课程 | `apiChoosePlanTask` |
| 补选低年级 | `apiFixupPlanTask`（**无 Choose 前缀**） |
| 重新学习 | `apiRetakePlanTask`（**无 Choose 前缀**） |

### 3.7 选课 — 取消选课（退课）

- **请求**：`POST index.cfm?event=chooseCourse:apiCancelTask`（五个分类统一）
- **body**：同选课的 `CT/TID/CID/CIDX/TSK/TT/ST`，额外 `SCC={chooserId}`
- **chooserId 来源**：已选课程表中 `removeTask(chooserId, courseId, courseIdx, termId, taskType, taskId, hash)` 的第 1 参
- **返回**：JSON `{success: bool, reason?: string}`

### 3.8 JS 函数签名（实测）

```javascript
// 选课（教学班详情展开后，点击某教学班触发）
chooseCourse(courseId, courseIdx, termId, taskType, taskId, hash)
// 取消（已选课程表里点撤销触发）
removeTask(chooserId, courseId, courseIdx, termId, taskType, taskId, hash)
```

### 3.9 其他已知但未实现的接口

| 功能 | 教务接口 | 状态 |
| --- | --- | --- |
| 课表查看 | `?event=studentPortal:courseTable` | 接口已知，待实现 |
| 绩点/成绩 | `?event=studentProfile:courseMark` | 接口已知，待实现 |
| 实验课课表 | `http://202.115.175.177/StuExpbook/...` | 接口已知，待实现 |
| 一卡通 | `myo.swust.edu.cn/.../cardData` | 待实现 |
| 选课后刷新课表 | `POST ?event=chooseCourse:apiChoosenCourseTable`，body `TID/seed` | 待实现 |
| 选课后刷新已选清单 | `POST ?event=chooseCourse:apiChoosenTaskTable`，body `TID/seed` | 待实现 |

## 四、已实现功能

### 4.1 登录

- [x] 微信扫码登录（后端代理二维码流程）
- [x] CAS 登录页预访问获取 session cookie（route + SESSION）
- [x] 长轮询微信扫码状态（408/404/405 三态）
- [x] wx_code 去重（避免同一 code 重复处理）
- [x] CAS 回调换取认证 cookie
- [x] 教务门户换取教务 cookie
- [x] 从 client cookie jar 提取全部 cookie（含重定向链中 302 设置的）
- [x] 学生信息抓取（姓名 `xm` / 学号 `xh`）
- [x] cookie 本地持久化（30 分钟 TTL，存于 `backend/data/cookies/`）
- [x] httpx 同步 Client + `asyncio.to_thread`（规避 atrust VPN 下 AsyncClient TLS 握手失败）

### 4.2 课程抓取

- [x] 五个分类列表页抓取（sportTask / fixupTask / retakeTask / programTask / commonTask）
- [x] 列表页 TID 提取（正则 `'TID'\s*:\s*'(\d+)'`）
- [x] 列表页已选课程检测（trigger 带 `checked` 类）
- [x] 并行抓取教学班详情（Semaphore 限并发 5）
- [x] 3 次重试 + 1 秒间隔 + 30 秒超时
- [x] 60 秒短期缓存（同一 session+分类）
- [x] 教学班表格解析（`xpath("string()")` 提取嵌套 span 文本）
- [x] 表头对齐与字段映射（课序号/教师/人数/席位/校区/周次/上课时间/上课地点）
- [x] 状态区分：可选（chooseCourse 链接）/ 已选（stat on / removeTask 链接）/ 已满（stat peoples）
- [x] 席位解析：`-/-` → 已满，数字 → 余量
- [x] 上课时间解析（`周一第1-2节{1-16周}` 格式）
- [x] 周次解析（`02-15` 格式）
- [x] 唯一 course_id（`{cid}_{课序号}` 或编码的 `CID|CIDX|TID|TT|TSK|ST`）

### 4.3 选课/退课

- [x] 选课提交（`select()`，按分类用不同 choose_api，fixup/retake 附 CP）
- [x] 退课提交（`cancel()`，统一 apiCancelTask + SCC）
- [x] 前端选课按钮（已满课禁用）
- [x] 前端退课按钮（已选课显示红色退课按钮）

### 4.4 前端

- [x] 登录页（二维码 + 串行轮询 + 倒计时）
- [x] 选课页（分类 Tab + 筛选 + 表格）
- [x] 实时筛选（课程名/教师/校区，无需点击按钮）
- [x] "仅看有余量"开关（默认关闭）
- [x] 状态列、地点列、行课周次列
- [x] 余量/容量显示
- [x] 诊断页 `/debug`

### 4.5 基础设施

- [x] `run.py` 一键启动（进程组隔离，Linux 下 `start_new_session=True` 避免 killpg 误杀父进程）
- [x] 自动检查/安装前后端依赖
- [x] 后端 `--reload` 热重载（可 `RUN_NO_RELOAD=1` 禁用）
- [x] CORS 配置（前端 5173 → 后端 8000）

## 五、存在问题

### 5.1 退课功能不可用（高优先级）

**问题**：教学班表格中**没有** `removeTask` 链接，无法获取 `chooser_id`（SCC 参数）。

**影响**：前端退课按钮存在，但点击后后端 `cancel()` 因 `chooser_id` 为空，API 会返回失败。

**解决方向**：
1. 在 Chrome 中打开教务系统"已选课程"页面，用 CDP 抓取 HTML
2. 分析已选课程表中 `removeTask(...)` 调用，提取 `chooserId`
3. 后端新增"已选课程"抓取端点，或在教学班详情解析时从其他途径获取 chooser_id
4. 注意：`removeTask(chooserId, courseId, courseIdx, termId, taskType, taskId, hash)` 中 chooserId 形如 `5120246728,121387,261T`（学号+cid+termId+taskType 拼接），可能可以自行构造

### 5.2 加载速度慢（中优先级）

**问题**：全校通选课 179 门，并发 5 + 重试 3 次 + 超时 30 秒，加载可能需要 30-60 秒。

**解决方向**：
- 调高并发数（但教务系统可能限流/封 IP）
- 列表页已含课程基本信息，可先展示列表再懒加载教学班详情
- 前端骨架屏 + 分页加载

### 5.3 部分教学班表格请求失败（中优先级）

**问题**：部分课程教学班表格 POST 请求失败，返回只含基本信息的 CourseOption（无教师/时间/地点）。

**解决方向**：排查失败请求的 HTTP 状态码与响应体，可能是教务系统对特定课程的特殊处理。

### 5.4 后端 --reload 导致 CAS session 丢失（低优先级）

**问题**：后端 `--reload` 热重载时，`auth_adapter` 的 `httpx.Client` cookie jar 被重置，已登录用户需重新扫码。

**解决方向**：生产环境用 `RUN_NO_RELOAD=1`；或将 cookie jar 持久化到文件。

### 5.5 调试日志残留（低优先级）

**文件**：
- `/tmp/auth_debug.log` — 登录调试日志
- `/tmp/class_table_debug.log` — 教学班表格调试日志

**解决**：确认联调完成后移除 `auth_adapter.py` 中的 `_dbg` 调试代码。

### 5.6 锁定课程未展示（低优先级）

**问题**：计划课程中 5 门锁定课（`.stat.locked`）因无 trigger 被 `_parse_course_list` 跳过。

**解决**：如需展示锁定课程（标灰），改用 `div.courseShow::attr(cid)` 取 cid 并检查 `.stat.locked`。

## 六、可能的扩展功能

| 功能 | 优先级 | 说明 |
| --- | --- | --- |
| 课表查看 | 高 | `?event=studentPortal:courseTable`，接口已知 |
| 绩点/成绩查询 | 高 | `?event=studentProfile:courseMark`，接口已知 |
| 退课功能完善 | 高 | 需抓取"已选课程"页面获取 chooser_id |
| 选课结果实时刷新 | 中 | 选课成功后 POST `apiChoosenCourseTable` + `apiChoosenTaskTable` 刷新 |
| 实验课课表 | 中 | `http://202.115.175.177/StuExpbook/...` |
| 一卡通余额/流水 | 中 | `myo.swust.edu.cn/.../cardData` |
| 课程冲突检测 | 中 | 前端对比已选课时间槽，选课前提示冲突 |
| 选课收藏/心愿单 | 低 | 前端 localStorage，跨会话保存意向课程 |
| 批量选课 | 低 | 勾选多门课一次性提交 |
| 历史选课记录 | 低 | 需额外接口 |
| 消息通知 | 低 | 选课成功/失败/余量变化推送 |

## 七、启动

### 一键启动

```bash
git clone https://github.com/gnitimg/AntiSWUST.git
cd AntiSWUST
python3 run.py
```

自动检查 Python≥3.10、Node/npm，缺依赖则自动安装，启动后端 http://127.0.0.1:8000 + 前端 http://localhost:5173。按 Ctrl+C 停止全部。

### 诊断页

访问 `http://localhost:5173/debug`：直接请求微信二维码页并返回原始解析结果，验证选择器/轮询格式是否过时。

## 八、抓包工具

### mitmproxy（虚拟机内用）

```bash
pip install mitmproxy
mitmdump -s scripts/capture.py
# 浏览器/系统设置代理 → 127.0.0.1:8080
# 访问 http://mitm.it 安装 CA 证书
```

### Chrome DevTools Protocol（已用）

```bash
# 启动 Chrome 远程调试
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome_cdp_profile
# 运行抓取脚本
python3 scripts/cdp_fetch_five.py
```

实测数据存于 `captures/five2/`：各分类 DOM HTML、网络请求清单、cookie。

## 九、已知问题与注意事项

- **HTTP 代理**：若机器设了 HTTP 代理，会干扰微信长轮询。后端 httpx 已设 `trust_env=False` 直连。
- **HTTPS 证书**：`cas.swust.edu.cn` 是 HTTPS，`matrix.dean.swust.edu.cn` 证书可能不受信任，后端已设 `verify=False` 跳过校验。
- **cookie 安全**：登录态 cookie 存于 `backend/data/cookies/`（已 gitignore），30 分钟自动过期，含敏感信息勿提交。
- **微信 appid**：`wx3e5a3c590b52de4d` 是西南科大在微信开放平台的公开 appid（前端二维码 URL 本就可见），非密钥。
- **网络要求**：`cas.swust.edu.cn`、`matrix.dean.swust.edu.cn` 仅校内网或 atrust VPN 可达。
- **httpx AsyncClient 不可用**：atrust VPN 环境下 async TLS 握手失败，必须用同步 `httpx.Client` + `asyncio.to_thread`。
- **parsel 注意**：`td::text` 只提取直接文本不提取嵌套 span，必须用 `td.xpath("string()")`；`SelectorList.attrib` 不可靠，用 `::attr(name)` 选择器。
