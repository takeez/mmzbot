# -*- coding: utf-8 -*-
"""扩展包工具的**隔离运行器**：一个包一个子进程。

为什么：包和主程序同权限、同进程时，
  · 工具超时只是"主线程不再等它"，那个线程还在跑、还能继续写数据目录；
  · 包里 `os._exit()` / 段错误能直接带走整个机器人。

用法（由 `capabilities` 内部调用，人不直接用）：

    python -m fgbot.caprunner --dir <包目录> --tool <工具名>      # 跑一次工具，stdin 给 JSON
    python -m fgbot.caprunner --dir <包目录> --describe            # 只报工具定义（不跑）

协议：stdin 一行 JSON，stdout 一行 JSON。失败也在 stdout 回 `{"ok": false, ...}`，
退出码非 0 只表示"这个进程自己出事了"。
"""
import argparse
import importlib.util
import json
import os
import sys
import traceback


def _jsonable(v, depth=0):
    """把工具返回值压成能 JSON 的形状（超出的用字符串兜底，绝不抛）。"""
    if depth > 8:
        return str(v)[:2000]
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, dict):
        return {str(k): _jsonable(x, depth + 1) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x, depth + 1) for x in v]
    try:
        json.dumps(v)
        return v
    except Exception:
        return str(v)[:2000]


def _load(pkg_dir):
    tool_py = os.path.join(pkg_dir, "tool.py")
    name = "cap_runner_%d" % os.getpid()
    spec = importlib.util.spec_from_file_location(name, tool_py)
    if spec is None or spec.loader is None:
        raise ImportError("tool.py 不是一个可加载的 Python 文件")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _param_desc(mod):
    for attr in ("PARAMS", "params"):
        v = getattr(mod, attr, None)
        if isinstance(v, dict):
            return v
    return None


def _one(mod):
    for attr in ("NAME", "name"):
        v = getattr(mod, attr, None)
        if isinstance(v, str) and v.strip():
            name = v.strip()
            break
    else:
        raise ValueError("tool.py 里没有 NAME")
    desc = ""
    for attr in ("DESC", "desc"):
        v = getattr(mod, attr, None)
        if isinstance(v, str):
            desc = v.strip()
            break
    return {"name": name, "description": desc, "params": _param_desc(mod),
            "timeout": getattr(mod, "TIMEOUT", None)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--tool", default="")
    ap.add_argument("--describe", action="store_true")
    args = ap.parse_args(argv)

    pkg_dir = os.path.abspath(args.dir)
    try:
        mod = _load(pkg_dir)
    except BaseException:
        print(json.dumps({"ok": False, "stage": "load",
                          "error": traceback.format_exc(limit=4)[-1500:]},
                         ensure_ascii=False))
        return 2

    if args.describe:
        try:
            print(json.dumps({"ok": True, "tool": _one(mod)}, ensure_ascii=False))
            return 0
        except BaseException as e:
            print(json.dumps({"ok": False, "stage": "describe", "error": repr(e)},
                             ensure_ascii=False))
            return 3

    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception as e:
        print(json.dumps({"ok": False, "stage": "input", "error": repr(e)},
                         ensure_ascii=False))
        return 4

    run = getattr(mod, "run", None) or getattr(mod, "RUN", None)
    if not callable(run):
        print(json.dumps({"ok": False, "stage": "run", "error": "tool.py 里没有 run()"},
                         ensure_ascii=False))
        return 5

    try:
        res = run(payload.get("args") or {}, payload.get("ctx") or {})
    except BaseException:
        print(json.dumps({"ok": False, "stage": "call",
                          "error": traceback.format_exc(limit=6)[-2000:]},
                         ensure_ascii=False))
        return 6

    print(json.dumps({"ok": True, "result": _jsonable(res)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
