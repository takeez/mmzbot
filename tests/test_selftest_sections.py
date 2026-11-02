# -*- coding: utf-8 -*-
"""自检的每一段 = 一条 pytest 用例（自检整份只跑一次）。"""
import pytest

from conftest import all_section_names, result_of, sid


def pytest_generate_tests(metafunc):
    if "sect" in metafunc.fixturenames:
        names = all_section_names(result_of(metafunc.config))
        metafunc.parametrize("sect", names, ids=[sid(n) for n in names])


def test_section(sect, selftest_result):
    """这一段里的全部断言都要通过；如果它崩了，这里单独报。"""
    crashed = selftest_result.get("_crashed") or []
    by_name = {s["name"]: s for s in selftest_result["sections"]}
    if sect not in by_name:
        if sect in crashed:
            pytest.fail("%s\n这一段抛了异常，自检在这里停住了：\n%s"
                        % (sect, selftest_result["_stdout_tail"]))
        pytest.fail("%s\n这一段没跑到（前面某段崩了）：\n%s"
                    % (sect, selftest_result["_stdout_tail"]))
    data = by_name[sect]
    fails = data["failed"]
    if fails:
        lines = ["%s（%d 条断言失败）" % (sect, len(fails))]
        for f in fails[:20]:
            lines.append("  ✗ %s %s" % (f["what"], ("｜ " + f["detail"]) if f["detail"] else ""))
        pytest.fail("\n".join(lines))


def test_all_sections_green(selftest_result):
    """整份自检退出码要是 0。"""
    assert selftest_result["rc"] == 0, selftest_result["_stdout_tail"]


def test_no_section_crashed(selftest_result):
    """没有哪一段是"抛异常中断"的。"""
    crashed = selftest_result.get("_crashed") or []
    assert not crashed, "这几段抛了异常：%s" % "、".join(crashed)


def test_assertion_count(selftest_result):
    """断言条数不该无理由缩水。"""
    total = sum(s["total"] for s in selftest_result["sections"])
    assert total >= 1100, "只跑了 %d 条断言" % total
