# AntiSWUST 交接文档

> 西南科技大学教务辅助选课系统 · 实现交接（最后更新：2026-08-29）

## 一、项目背景

西南科技大学教务系统（`matrix.dean.swust.edu.cn`）界面混乱，学生无法直观查看可选课程，也难以按课程名/教师/星期/节次/周次/校区快速筛选。本项目在不替换原教务系统的前提下，做一个辅助选课前端：用户微信扫码登录后，后端抓取并缓存 cookie（登录态时长当前不限，原 30 分钟已注释关闭），代理请求教务系统拉取可选课程，前端提供多维筛选后提交选课/退课/抢课。

## 二、架构

| 层 | 技术栈 | 说明 |
| --- | --- | --- |
| 前端 | Vue3 + Vite7 + **Element Plus** + Pinia + Vue Router（hash 模式）| 基于 [v3-admin-vite](https://github.com/un-pany/v3-admin-vite) v5.2.0 模板裁剪；左侧菜单：所有选课（体育项目/全校通选课/计划课程/补选低年级/重新学习）/ 我的选课 / 实验功能（抢课/预置选课/课程组）|
| 后端 | Python + FastAPI + httpx + parsel | 微信扫码登录代理、cookie 本地持久化、教务系统爬取与筛选、抢课任务管理、课程组存储 |
| 一键启动 | run.py | 自动检查/安装前后端依赖，同时启动 uvicorn + vite |

```
AntiSWUST/
├─ run.py                      一键启动（进程组隔离，Linux 安全退出）
├─ scripts/                    CDP/mitmproxy 抓包脚本
├─ captures/five2/             实测抓包数据（DOM/请求/cookie）
├─ backend/
│  ├─ app/
│  │  ├─ main.py               FastAPI 入口（login/course/snipe/groups 路由）
│  │  ├─ config.py             真实 URL 配置（.env）
│  │  ├─ api/
│  │  │  ├─ login.py           登录接口 + 诊断端点
│  │  │  ├─ course.py          选课/退课/列表/已选清单接口
│  │  │  ├─ snipe.py           抢课任务启动/停止/查询
│  │  ├─ preset.py          预置选课条目/导入/运行
│  │  │  └─ groups.py          课程组 CRUD
│  │  ├─ core/
│  │  │  ├─ cookie_store.py    本地 cookie 持久化（TTL 当前 0=不限）
│  │  │  ├─ auth_adapter.py    微信扫码登录（容错加固 + cookie jar 持久化）
│  │  │  └─ swust_client.py    教务系统 HTTP 客户端（同步 Client + to_thread）
│  │  ├─ services/
│  │  │  ├─ course_service.py  五类课程抓取 + 选课/退课 + 60s缓存 + 已选清单解析
│  │  │  ├─ filter_service.py  多维筛选逻辑
│  │  │  │  ├─ snipe_service.py   抢课任务管理器（频率下限0.5s/成功熔断/参数自动刷新）
│  │  │  ├─ preset_service.py  预置选课（CSV导入/匹配/自动提交运行器）
│  │  │  ├─ group_service.py   课程组（backend/data/course_groups.json 持久化）
│  │  │  └─ preset_service.py  预置选课（条目持久化+CSV导入+匹配+运行器）
│  │  └─ models/course.py      课程/筛选数据模型
│  ├─ tests/test_parsing.py    解析单测（fixture + captures 实测数据）
│  └─ requirements.txt
└─ frontend/                   v3-admin-vite 裁剪版
   └─ src/
      ├─ layouts/               模板布局（侧边栏/导航栏/标签栏/主题）
      ├─ pages/
      │  ├─ login/              微信扫码登录页（二维码模糊防误扫）
      │  ├─ course/             选课页（5 分类共用，两阶段加载+组筛选+抢课入口）
      │  ├─ my/                 我的选课（已选清单+退课）
      │  ├─ snipe/              抢课任务管理（设置+任务表+选课弹窗）
      │  └─ groups/             课程组管理（增删改+加课弹窗）
      ├─ pinia/stores/          user（会话）/ course（已选+课程组共享）/ settings 等
      ├─ http/axios.ts          裸 JSON 适配（session_id 注入 / 401 登出）
      └─ common/apis/           login / course / snipe / groups
```

## 三、所有教务系统请求接口（实测，CT=2）

> 全部接口仅校内网或 atrust VPN 可达，外网不可访问。

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

**轮询返回 `wx_errcode`**：408 未扫码 / 404 已扫码待确认 / 405 已确认（带 `wx_code`）

### 3.3 教务系统门户

| 用途 | URL | 方法 |
| --- | --- | --- |
| 教务首页 | `https://matrix.dean.swust.edu.cn/acadmicManager/index.cfm?event=studentPortal:DEFAULT_EVENT` | GET |
| 学生信息 | `http://myo.swust.edu.cn/mht_shall/a/service/studentInfo` | GET（返回 JSON，字段 `xm`/`xh`；实测当前抓不到，已容错为空） |

### 3.4 选课 — 五个分类列表页

统一 URL 模板：`GET https://matrix.dean.swust.edu.cn/acadmicManager/index.cfm?event=chooseCourse:{task_type}&CT={轮次}`

| 分类 | task_type | 实测课程数 | 可选 | 锁定 |
| --- | --- | --- | --- | --- |
| 体育项目（体育课） | `sportTask` | 25 | 25 | 0 |
| 补选低年级 | `fixupTask` | 1 | 1 | 0 |
| 重新学习（重修） | `retakeTask` | 11 | 11 | 0 |
| 计划课程（专业限选） | `programTask` | 8 | 3 | 5 |
| 全校通选课 | `commonTask` | 179 | 179 | 0 |

返回 `text/html`，含全部课程的 `<div class="courseShow">` 列表（单次 GET 即全量）。
**每个列表页都内嵌「已选课程清单」**（`div#Choosen` → `#choosenTable` → `tr.editRows`），是退课参数的唯一来源：

- 可退行：`<a class="stat delete" href="javascript:removeTask('SCC','CID','CIDX','TID','TT','TSK','ST');"></a>`
- 锁定行：`<span class="stat locked" title="该选课记录禁止修改">`（往期轮次记录，不可退）
- chooserId 形如 `5120246728,121387,261T`（学号+cid+termId+taskType）

### 3.5 选课 — 教学班详情

- **请求**：`POST index.cfm?event=chooseCourse:{table_api}`，body `TID={学期ID}&CID={课程ID}&seed={毫秒}`
- **返回**：HTML 片段（表格 `.editRows` + `chooseCourse(...)` 调用）
- **TID 来源**：列表页 JS 内硬编码 `'TID' : '261'`（每学期变）
- **表头列名五个分类存在差异**（如"任课教师"vs"教师"、"地点"vs"上课地点"），后端用 `HEADER_ALIASES` 别名归一化处理
- **上课时间两种格式**：`周一第1-2节{1-16周}`（体育）、`周四第四讲`（中文讲次，限选/补选），解析器均兼容

| 分类 | table_api |
| --- | --- |
| 体育项目课 | `apiSportTaskTable` |
| 全校通选课 | `apiCommonTaskTable` |
| 计划课程 | `apiPlanTaskTable` |
| 补选低年级 | `apiFixupPlanTaskTable` |
| 重新学习 | `apiRetakePlanTaskTable` |

### 3.6 提交选课 / 取消选课

- **选课**：`POST ?event=chooseCourse:{choose_api}`，body `CT/TID/CID/CIDX/TSK/TT/ST/seed`（fixup/retake 加 `CP`），返回 `{success, reason?}`；注意 ST 哈希随页面渲染变化，抢课任务每 5 分钟自动重抓详情换新参数
- **退课**：`POST ?event=chooseCourse:apiCancelTask`（五类统一），body 同上 + `SCC={chooserId}`

| 分类 | choose_api |
| --- | --- |
| 体育项目课 | `apiChooseSportTask` |
| 全校通选课 | `apiChooseCommonTask` |
| 计划课程 | `apiChoosePlanTask` |
| 补选低年级 | `apiFixupPlanTask`（**无 Choose 前缀**） |
| 重新学习 | `apiRetakePlanTask`（**无 Choose 前缀**） |

## 四、已实现功能

### 4.1 登录

- [x] 微信扫码登录（后端代理二维码流程）+ 串行轮询（408/404/405）
- [x] wx_code 去重、CAS 回调换 cookie、教务门户换 SSO cookie
- [x] **登录容错加固**：教务门户页渲染慢（实测 >15s 会 ReadTimeout），回调/门户抓取全部 best-effort，成功判据=cookie jar 含教务域（`.dean.swust.edu.cn`）cookie；真实失败原因透传到前端显示
- [x] auth_adapter cookie jar 持久化到 `backend/data/auth_jar.json`（`--reload`/重启不再丢登录态）
- [x] 本地登录态 30 分钟限时**已注释关闭**（`config.cookie_ttl_seconds`，恢复改回 `30 * 60`）
- [x] 二维码在加载中/已扫描/已过期/出错时**模糊+遮罩处理**，防止误扫

### 4.2 课程抓取

- [x] 五分类列表抓取 + TID 提取 + 已选检测 + 锁定课程解析（置灰展示）
- [x] **两阶段加载**：`basic` 模式只解析列表页（秒级返回先渲染），详情异步补齐
- [x] 并行教学班详情（`FETCH_CONCURRENCY` 默认 6；实测 CFM 对同一会话近似串行加锁，并发过高反而排队超时）
- [x] 表头别名归一化（HEADER_ALIASES）+ 中文讲次时间解析（`周四第四讲`/`第三讲-第四讲`/`第三-第四讲`）
- [x] 席位解析（`-/-`=已满）+ 60s 缓存（basic/full 分开缓存，选/退课后自动失效）
- [x] 唯一 course_id（`CID|CIDX|TID|TT|TSK|ST` 编码）
- [x] 会话失效检测（302 到 CAS → 401 → 前端自动回登录页）
- [x] 列表页 GET 超时自动重试一次

### 4.3 选课/退课/抢课

- [x] 选课提交（按分类 choose_api，fixup/retake 附 CP）
- [x] **退课修复**：已选清单从列表页内嵌 `#Choosen` 解析（含真实 chooser_id/ST），`GET /api/course/selected` 提供全量退课参数；主表格"已选"行按 cid 关联退课；锁定记录按钮禁用并提示
- [x] **抢课**（实验功能）：多课程并发任务、请求间隔下限 0.5s、持续时间不限上限（0=不限时）、抢到自动熔断该课程任务、"已选/重复"关键词视为成功熔断、致命错误立即停止、每 5 分钟自动刷新选课参数（ST 哈希会过期）、同课程新任务自动顶替旧任务；任务仅存内存，后端重启清空
- [x] **课程组**（实验功能）：自定义名称、增删课程、重命名/删除；选课页筛选栏可直接按组过滤
- [x] **预置选课**（实验功能）：CSV 导入（表头别名识别/无表头兜底/GBK 兼容）或手动录入意向课程；匹配预览；开始选课后自动匹配（课程名双向包含+教师/课序号/校区/星期/节次全约束）并按优先级提交；支持定时开始、失败自动重试、同类只选一门；条目持久化 preset_courses.json，运行任务存内存

### 4.4 前端（v3-admin-vite 模板）

- [x] 左侧菜单：所有选课（体育项目/通选/计划/补选/重修）/ 我的选课 / 实验功能（抢课+课程组）
- [x] 选课页：两阶段加载（列表秒出→详情异步）、实时筛选（名称/教师/校区/星期/节次/课程组/仅看有余量）、状态标签（可选/已选/已满/锁定/详情未加载）、选课/退课/抢课/加入组操作
- [x] 登录页：二维码 + 串行轮询 + 模糊防误扫 + 失败原因展示
- [x] 手动刷新（跳过缓存）、选/退课成功后局部更新行状态并刷新已选清单
- [x] hash 路由（`/#/course/pe`）；模板主题/暗色/标签栏保留

### 4.5 基础设施

- [x] `run.py` 一键启动（自动装依赖、`RUN_NO_RELOAD=1` 可关热重载）
- [x] 解析单测 `backend/tests/test_parsing.py`（内联 fixture + captures/five2 实测数据，`python3 backend/tests/test_parsing.py` 运行）

## 五、遗留问题（原 5.1-5.6 处置结果）

| 原问题 | 状态 |
| --- | --- |
| 5.1 退课不可用（无 chooser_id） | ✅ 已修复：列表页内嵌已选清单含完整 removeTask 参数 |
| 5.2 加载慢 | ✅ 大幅缓解：basic 秒出 + 并发调优 + 缓存；CFM 会话锁是硬约束（同一会话请求近似串行） |
| 5.3 部分教学班表格请求失败 | ✅ 已修复：空解析自动重试，仍失败则标记"详情未加载"并禁用选课按钮 |
| 5.4 --reload 丢 CAS session | ✅ 已修复：cookie jar 持久化到 auth_jar.json |
| 5.5 调试日志残留 | ✅ 已移除（/tmp/auth_debug.log 等不再写入） |
| 5.6 锁定课程未展示 | ✅ 已修复：锁定课展示并置灰禁用 |

## 六、可能的扩展功能

| 功能 | 优先级 | 说明 |
| --- | --- | --- |
| 课表查看 | 高 | `?event=studentPortal:courseTable`，接口已知（00_current_chooseCourse.html 有快照） |
| 绩点/成绩查询 | 高 | `?event=studentProfile:courseMark`，接口已知 |
| 抢课任务持久化 | 中 | 当前任务存内存，重启丢失（已提交的选课结果不受影响） |
| 选课结果实时刷新 | 中 | POST `apiChoosenCourseTable` + `apiChoosenTaskTable` |
| 课程冲突检测 | 中 | 前端对比已选课时间槽 |
| 抢课成功消息推送 | 低 | 目前仅页面内提示 |

## 七、启动

```bash
python3 run.py        # 后端 http://127.0.0.1:8000 + 前端 http://localhost:5173
```

访问 http://localhost:5173 （hash 路由，登录页 `/#/login`），微信扫码后进入选课页。

## 八、已知问题与注意事项

- **HTTP 代理**：httpx 已设 `trust_env=False` 直连，避免系统代理干扰微信长轮询。
- **HTTPS 证书**：后端已设 `verify=False`（matrix 证书链不完全受信任）。
- **网络要求**：cas/matrix 仅校内网或 atrust VPN 可达；matrix 门户页渲染极慢（>15s），登录流程已做容错。
- **httpx AsyncClient 不可用**：atrust 下 async TLS 握手失败，必须同步 Client + `asyncio.to_thread`。
- **CFM 会话锁**：教务系统对同一会话的请求近似串行，多页面/多实例并发会互相排队（超时重试可恢复，但会拖慢）。
- **ST 哈希时效**：选课参数里的 ST 随页面渲染变化，抢课任务每 5 分钟自动重抓；手动选课用列表页最新数据。
- **parsel 注意**：`td::text` 不含嵌套 span 文本，用 `td.xpath("string()")`；`SelectorList.attrib` 不可靠，用 `::attr(name)`。
- **cookie 安全**：`backend/data/`（会话 cookie、auth_jar.json、course_groups.json）已 gitignore。
- **微信 appid**：`wx3e5a3c590b52de4d` 为学校在微信开放平台的公开 appid，非密钥。
