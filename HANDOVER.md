# AntiSWUST 交接文档

> 西南科技大学教务辅助系统 · 需求与实现交接

## 一、项目背景

西南科技大学教务系统（`matrix.dean.swust.edu.cn`）界面混乱，学生无法直观查看可选课程，也难以按课程名/教师/星期/节次/周次/校区快速筛选。本项目在不替换原教务系统的前提下，做一个辅助选课前端：用户微信扫码登录后，后端抓取并缓存 cookie（30 分钟过期），代理请求教务系统拉取可选课程，前端提供多维筛选后返回符合条件的课程并提交选课。

本阶段只做**选课**，后期扩展课表、绩点等。

## 二、架构

| 层 | 技术栈 | 说明 |
| --- | --- | --- |
| 前端 | Vue3 + Vite + Ant Design Vue + Pinia + Vue Router | 登录页(二维码+串行轮询)、选课页(分类Tab+筛选+选课)、诊断页 |
| 后端 | Python + FastAPI + httpx + parsel | 微信扫码登录代理、cookie 本地持久化、教务系统爬取与筛选 |
| 一键启动 | run.py | 自动检查/安装前后端依赖，同时启动 uvicorn + vite |

```
AntiSWUST/
├─ run.py                      一键启动
├─ scripts/
│  └─ capture.py               mitmproxy 抓包脚本（接口分析用）
├─ backend/
│  ├─ app/
│  │  ├─ main.py               FastAPI 入口
│  │  ├─ config.py             真实 URL 配置（.env）
│  │  ├─ api/
│  │  │  ├─ login.py           登录接口 + 诊断端点
│  │  │  └─ course.py          选课接口
│  │  ├─ core/
│  │  │  ├─ cookie_store.py    本地 cookie 持久化 + 30min TTL
│  │  │  ├─ auth_adapter.py    微信扫码登录（真实流程）
│  │  │  └─ swust_client.py    教务系统 HTTP 客户端
│  │  ├─ services/
│  │  │  ├─ course_service.py  五类课程抓取 + 选课提交
│  │  │  └─ filter_service.py  多维筛选逻辑
│  │  └─ models/course.py      课程/筛选数据模型
│  ├─ requirements.txt
│  └─ .env.example
└─ frontend/
   └─ src/
      ├─ api/ stores/ router/ components/ views/
      ├─ App.vue / main.ts
      └─ package.json /0 / vite.config.ts
```

## 三、真实接口（已对接，来源：开源项目抓包验证）

统一认证与教务系统域名均经实际探测确认：`jwxt.swust.edu.cn` / `passport.swust.edu.cn` DNS 不存在，真实地址如下（来自 `Kelab/auth_swust`、`YDHusky/SWUST-Tools` 抓包代码）：

| 用途 | 真实地址 |
| --- | --- |
| 统一认证 CAS | `https://cas.swust.edu.cn/authserver/login` |
| 验证码 | `https://cas.swust.edu.cn/authserver/captcha` |
| RSA 公钥 | `https://cas.swust.edu.cn/authserver/getKey` |
| 微信回调 | `http://cas.swust.edu.cn/authserver/callback` |
| 教务系统 | `https://matrix.dean.swust.edu.cn/acadmicManager/index.cfm` |
| 学生信息 | `http://myo.swust.edu.cn/mht_shall/a/service/studentInfo` |

> 网络要求：`cas.swust.edu.cn`、`matrix.dean.swust.edu.cn` 仅校内网或 atrust VPN 可达，外网不可访问。

### 3.1 微信扫码登录流程（已实现）

1. 请求 `open.weixin.qq.com/connect/qrconnect?appid=wx3e5a3c590b52de4d&redirect_uri={callback}&response_type=code&scope=snsapi_login`
2. 解析返回 HTML 中 `.js_qrcode_img` 的 src，拼接图片 URL，末段即 `uuid`
3. 长轮询 `open.weixin.qq.com/connect/l/qrconnect?uuid={uuid}`，解析 `wx_errcode`：408 未扫码 / 404 已扫码待确认 / 405 已确认(带 `wx_code`)
4. `wx_code` 非空即扫码确认，请求回调 `{callback}?code={wx_code}&store=` 获取 CAS cookie
5. 带 cookie 访问教务门户 `?event=studentPortal:DEFAULT_EVENT` 换取教务 cookie

### 3.2 选课接口（已实现）

教务系统 `matrix.dean.swust.edu.cn` 的 `chooseCourse` 事件：

| 课程类型 | task_type | task_name(API) | 对应枚举 |
| --- | --- | --- | --- |
| 体育课 | `sportTask` | `SportTask` | `pe` |
| 全校通选课 | `commonTask` | `CommonTask` | `general` |
| 专业限选课 | `programTask` | `PlanTask` | `major_limited` |
| 补选低年级 | `programTask` | `PlanTask` | `supplement`（CT 轮次待确认） |
| 重修 | `programTask` | `PlanTask` | `retake`（CT 轮次待确认） |

- **课程列表**：`GET ?event=chooseCourse:{task_type}&CT={轮次}` → 解析 HTML `.courseShow`（`.name` 课程名 + `.trigger[cid]` 课程ID）
- **教学班详情**：`POST ?event=chooseCourse:api{Task}Table`，body `CID=xxx` → 解析 HTML `.editRows`，从 `chooseCourse('CID','CIDX','TID','TT','TSK','ST')` JS 调用提取选课参数
- **提交选课**：`POST ?event=chooseCourse:apiChoose{Task}`，body `{CT,TID,CID,CIDX,TSK,TT,ST,seed[,CP=2]}`，返回 JSON `{success: bool}`

## 四、启动

### 一键启动

```bash
git clone https://github.com/gnitimg/AntiSWUST.git
cd AntiSWUST
python run.py
```

自动检查 Python≥3.10、Node/npm，缺依赖则自动安装（已有则跳过），启动后端 http://127.0.0.1:8000 + 前端 http://localhost:5173。按 Ctrl+C 停止全部。

### 诊断页

访问 `http://localhost:5173/debug`：直接请求微信二维码页并返回原始解析结果，验证选择器/轮询格式是否过时。

## 五、抓包工具（接口分析）

`scripts/capture.py` 基于 mitmproxy，在虚拟机内连 atrust 后使用：

```bash
pip install mitmproxy
mitmdump -s scripts/capture.py
# 浏览器/系统设置代理 → 127.0.0.1:8080
# 访问 http://mitm.it 安装 CA 证书
# 打开教务系统正常操作选课
```

自动记录所有 `matrix.dean.swust.edu.cn` / `cas.swust.edu.cn` 请求到 `captures/` 目录，按类型标记（选课列表/教学班详情/选课提交/课表/成绩/登录认证），每个请求一个 JSON（含完整 req/resp），`summary.log` 一行一条摘要。操作完成后把 `captures/` 打包交回，据此完善 `course_service.py` 字段映射与补选/重修接口。

## 六、待校内联调确认

> 教务系统仅校内网/VPN 可达，以下需在虚拟机内实测微调：

1. **选课轮次 CT**：`config.py` 的 `choose_course_ct` 及补选/重修的 `CATEGORY_CT_OVERRIDE`，按学期选课通知调整
2. **教学班表格字段**：`course_service.py` 的 `_parse_class_table` 表头映射（课程名称/教师/校区/容量/已选/时间）需对照实际 HTML 列名
3. **时间字符串格式**：`_parse_time_str` 当前按 `周一第1-2节{1-16周}` 解析，若实际格式不同需调整正则
4. **补选低年级 / 重修**：真实 event 是否复用 `programTask` 还是单独事件，需抓包确认
5. **学生信息字段**：`auth_adapter._fetch_user_profile` 中 `xm`/`xh` 字段名需对照实际返回
6. **微信选择器**：若 `.js_qrcode_img` 或 `wx_errcode`/`wx_code` 格式变更，用诊断页 `/debug` 实地验证

## 七、后期扩展计划

抓包确认接口后逐步扩展：

| 功能 | 教务接口 | 状态 |
| --- | --- | --- |
| 选课（五类） | `chooseCourse:*` | 已实现，待联调字段 |
| 课表查看 | `?event=studentPortal:courseTable` | 接口已知，待实现 |
| 绩点/成绩 | `?event=studentProfile:courseMark` | 接口已知，待实现 |
| 实验课课表 | `http://202.115.175.177/StuExpbook/...` | 接口已知，待实现 |
| 一卡通 | `myo.swust.edu.cn/.../cardData` | 待实现 |

## 八、已知问题与注意事项

- **HTTP 代理**：若机器设了 HTTP 代理，会干扰微信长轮询。后端 httpx 已设 `trust_env=False` 直连，不走代理。
- **HTTPS 证书**：`cas.swust.edu.cn` 是 HTTP，`matrix.dean.swust.edu.cn` 证书可能不受信任，后端已设 `verify=False` 跳过校验。
- **cookie 安全**：登录态 cookie 存于 `backend/data/cookies/`（已 gitignore），30 分钟自动过期，含敏感信息勿提交。
- **微信 appid**：`wx3e5a3c590b52de4d` 是西南科大在微信开放平台的公开 appid（前端二维码 URL 本就可见），非密钥。
