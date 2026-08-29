#!/usr/bin/env python3
"""解析逻辑单测：优先用 captures/five2/ 实测抓包数据，缺失时退化为内联最小 fixture。

运行：python3 backend/tests/test_parsing.py
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.models.course import CourseCategory  # noqa: E402
from app.services.course_service import CourseService  # noqa: E402

CAPTURES = BACKEND_DIR.parent / "captures" / "five2"

# 内联最小已选清单 fixture（结构按 2026-08-28 实测 sportTask 列表页 div#Choosen）
CHOOSEN_FIXTURE = """
<div id="Choosen" class="tabContent">
  <div id="choosenTable">
    <table class="UIEditable">
      <thead><tr><td>教学班</td><td>任课教师</td><td>学分</td><td>修读方式</td><td>课程性质</td><td>重修</td><td>选课轮次</td><td>选课时间</td><td></td></tr></thead>
      <tbody>
        <tr class="editRows">
          <td><span class="index">1</span></td>
          <td>编译原理.-.<span class="numeric">(003)</span></td>
          <td>蒋勇</td>
          <td><span class="numeric">3.00</span></td>
          <td>正常</td><td>必修</td><td></td><td>其他</td>
          <td><span class="numeric">2026-06-24 08:20</span></td>
          <td><span title="该选课记录禁止修改" class="stat locked"></span></td>
        </tr>
        <tr class="editRows">
          <td><span class="index">2</span></td>
          <td>大学体育5——篮球俱乐部.-.<span class="numeric">(T17)</span></td>
          <td>王豫蓉</td>
          <td><span class="numeric">0.50</span></td>
          <td>正常</td><td>必修</td><td></td><td>初选</td>
          <td><span class="numeric">2026-06-25 09:02</span></td>
          <td><a title="撤销课程" class="stat delete" href="javascript:removeTask('5120246728,121387,261T','121387','T17','261','T','261,121387,T17','FDF6E2A654006A7FB386E4B974B0FB3CA88BF22AC57A0ED7');"></a></td>
        </tr>
      </tbody>
    </table>
  </div>
</div>
"""

# 内联最小课程列表 fixture（可选 + 锁定 + 已选三种形态）
COURSE_LIST_FIXTURE = """
<div class="courseShow clearfix" cid="121299" prop="1">
  <div class="UIChooser"><div class="title">
    <a cid="121299" class="trigger close"></a>
    <span class="name">大学体育3-保健体育</span>
    <span class="numeric">1.00</span><span>学分</span>
  </div></div>
</div>
<div class="courseShow clearfix" cid="120555" prop="1">
  <div class="UIChooser"><div class="title">
    <span class="stat locked"></span>
    <span class="name">编译原理</span>
    <span class="numeric">3.00</span><span>学分</span>
  </div></div>
</div>
<div class="courseShow clearfix" cid="120576" prop="2">
  <div class="UIChooser"><div class="title">
    <a cid="120576" class="trigger close checked"></a>
    <span class="name">Web应用系统开发与实践</span>
    <span class="numeric">2.00</span><span>学分</span>
  </div></div>
</div>
"""

# 内联最小教学班表格 fixture（用别名表头：任课教师/地点/教室，验证归一化）
CLASS_TABLE_FIXTURE = """
<table>
  <thead><tr>
    <td>课序号</td><td>任课教师</td><td>人数</td><td>席位</td><td>校区</td><td>周次</td><td>上课时间</td><td>地点</td>
  </tr></thead>
  <tbody>
    <tr class="editRows">
      <td><span class="stat peoples" title="人数已满"></span></td>
      <td><span>002</span></td><td><span>张三</span></td><td>60</td><td>0</td><td>新区</td>
      <td>02-16</td><td>周一第1-2节{1-16周}</td><td>东1201</td>
    </tr>
    <tr class="editRows">
      <td><span class="stat"></span><a href="javascript:chooseCourse('121299','003','261','T','261,121299,003','AABBCC');">选课</a></td>
      <td>003</td><td>李四</td><td>50</td><td>12</td><td>新区</td>
      <td>02-16</td><td>周四第四讲</td><td>东1302</td>
    </tr>
  </tbody>
</table>
"""

_p = print
_failed: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    if cond:
        _p(f"  PASS {name}")
    else:
        _failed.append(name)
        _p(f"  FAIL {name} {extra}")


def read_capture(fname: str) -> str:
    return (CAPTURES / fname).read_text(encoding="utf-8")


def test_choosen_table_fixture() -> None:
    _p("_parse_choosen_table（内联 fixture）")
    items = CourseService._parse_choosen_table(CHOOSEN_FIXTURE)
    check("共 2 行", len(items) == 2, f"got {len(items)}")
    locked = items[0]
    check("锁定行 locked=True", locked["locked"] is True)
    check("锁定行无 chooser_id", locked["chooser_id"] == "")
    check("锁定行课程名", locked["name"] == "编译原理", locked["name"])
    check("锁定行教学班号", locked["class_name"] == "003", locked["class_name"])
    ok = items[1]
    check("可退行 locked=False", ok["locked"] is False)
    check("chooser_id", ok["chooser_id"] == "5120246728,121387,261T", ok["chooser_id"])
    check("cid", ok["cid"] == "121387", ok["cid"])
    check(
        "course_id 编码",
        ok["course_id"] == "121387|T17|261|T|261,121387,T17|FDF6E2A654006A7FB386E4B974B0FB3CA88BF22AC57A0ED7",
        ok["course_id"],
    )
    check("教师", ok["teacher"] == "王豫蓉", ok["teacher"])
    check("课程名", ok["name"] == "大学体育5——篮球俱乐部", ok["name"])


def test_course_list_fixture() -> None:
    _p("_parse_course_list（内联 fixture）")
    items = CourseService._parse_course_list(COURSE_LIST_FIXTURE, CourseCategory.PE, 2)
    check("共 3 门（含锁定）", len(items) == 3, f"got {len(items)}")
    check("第1门可选", items[0].raw.get("locked") is None)
    check("第2门锁定", items[1].raw.get("locked") is True)
    check("锁定课 cid 取自 courseShow 属性", items[1].course_id == "120555", items[1].course_id)
    check("第3门已选", items[2].raw.get("checked") is True)


def test_class_table_fixture() -> None:
    _p("_parse_class_table（内联 fixture）")
    items = CourseService._parse_class_table(CLASS_TABLE_FIXTURE, CourseCategory.PE, "121299", "大学体育3", 1.0)
    check("共 2 个教学班", len(items) == 2, f"got {len(items)}")
    full, avail = items[0], items[1]
    check("已满行状态", full.raw.get("状态") == "已满", str(full.raw.get("状态")))
    check("已满行余量 0", full.capacity == 60 and full.selected_count == 60, f"{full.capacity}/{full.selected_count}")
    check("可选行状态", avail.raw.get("状态") == "可选", str(avail.raw.get("状态")))
    check("可选行余量 38", avail.selected_count == 38, str(avail.selected_count))
    check("course_id 编码", avail.course_id == "121299|003|261|T|261,121299,003|AABBCC", avail.course_id)
    check("raw 含 cid", avail.raw.get("cid") == "121299")
    check("中文讲次时间解析(周四第四讲)", avail.time_slots and avail.time_slots[0].day_of_week == 4 and avail.time_slots[0].start_node == 4 and avail.time_slots[0].end_node == 4,
          str(avail.time_slots))
    check("地点列别名归一化(地点→上课地点)", avail.raw.get("上课地点") == "东1302", str(avail.raw.get("上课地点")))
    check("教师列别名归一化(任课教师→教师)", avail.raw.get("教师") == "李四", str(avail.raw.get("教师")))
    check("周次解析(02-16)", avail.weeks_available == list(range(2, 17)))


def test_captures() -> None:
    if not CAPTURES.exists():
        _p("captures/five2/ 不存在，跳过实测数据用例")
        return
    _p("实测数据（captures/five2）")
    sport = read_capture("01_sportTask.html")
    chosen = CourseService._parse_choosen_table(sport)
    check("已选条数 > 0", len(chosen) > 0, f"got {len(chosen)}")
    check("可退条数 = removeTask 链接数", all(s["course_id"].count("|") == 5 for s in chosen if s["chooser_id"]))
    check("TID=261", CourseService._extract_tid(sport) == "261", CourseService._extract_tid(sport))
    courses = CourseService._parse_course_list(sport, CourseCategory.PE, 2)
    check("sportTask 课程数=25", len(courses) == 25, f"got {len(courses)}")
    prog = read_capture("04_programTask.html")
    pcourses = CourseService._parse_course_list(prog, CourseCategory.MAJOR_LIMITED, 2)
    locked_n = sum(1 for c in pcourses if c.raw.get("locked"))
    check("programTask 8 门且 5 门锁定", len(pcourses) == 8 and locked_n == 5, f"got {len(pcourses)}/{locked_n}")
    common = read_capture("05_commonTask.html")
    gcourses = CourseService._parse_course_list(common, CourseCategory.GENERAL, 2)
    check("commonTask 课程数=179", len(gcourses) == 179, f"got {len(gcourses)}")


def test_time_parser() -> None:
    _p("_parse_time_str 格式兼容")
    parse = CourseService._parse_time_str
    a = parse("周一第1-2节{1-16周}")
    check("数字节次+周次", len(a) == 1 and a[0].day_of_week == 1 and a[0].weeks == list(range(1, 17)))
    b = parse("周四第四讲")
    check("中文讲次", len(b) == 1 and b[0].day_of_week == 4 and b[0].start_node == 4 and b[0].end_node == 4)
    c = parse("周二第十一讲")
    check("中文十一讲", len(c) == 1 and c[0].start_node == 11)
    d = parse("周五第三讲-第四讲")
    check("中文讲次区间", len(d) == 1 and d[0].start_node == 3 and d[0].end_node == 4)
    e = parse("周一第1-2节{1-8周},周三第三讲")
    check("多段混合", len(e) == 2 and e[0].day_of_week == 1 and e[1].day_of_week == 3)


if __name__ == "__main__":
    test_time_parser()
    test_choosen_table_fixture()
    test_course_list_fixture()
    test_class_table_fixture()
    test_captures()
    print()
    if _failed:
        print(f"结果：{len(_failed)} 项失败 -> {_failed}")
        sys.exit(1)
    print("结果：全部通过")
