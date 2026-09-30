# -*- coding: utf-8 -*-
"""用 codex-rs 自带的 scenario fixtures 验证 apply_patch 复刻是否对齐。

重要：codex-rs 的判据是「最终文件系统状态与 expected/ 完全一致」，
*不*检查命令是否报错（见 tests/suite/scenarios.rs 的注释：
"We intentionally do not assert on the exit status here"）。

所以 rejects_* 场景的正确含义是：补丁被拒绝 → 文件保持原样 → 与 expected/ 一致。
"""
import os, sys, shutil, tempfile, traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from mini_codex.patch import parse_patch, PatchParseError
from mini_codex.patch_apply import apply_patch, PatchApplyError

FIX = os.path.join(
    r"C:\Users\r26304\Documents\codex-shop\codex-src\codex-rs\apply-patch",
    "tests", "fixtures", "scenarios",
)

def read_tree(root):
    out = {}
    for dp, dn, fn in os.walk(root):
        for f in fn:
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, root).replace("\\", "/")
            with open(p, encoding="utf-8", errors="replace") as fh:
                out[rel] = fh.read()
    return out

passed, failed = [], []

for name in sorted(os.listdir(FIX)):
    sdir = os.path.join(FIX, name)
    if not os.path.isdir(sdir):
        continue
    pp = os.path.join(sdir, "patch.txt")
    if not os.path.exists(pp):
        continue

    patch_text = open(pp, encoding="utf-8").read()
    indir, expdir = os.path.join(sdir, "input"), os.path.join(sdir, "expected")
    expected = read_tree(expdir) if os.path.isdir(expdir) else {}

    work = tempfile.mkdtemp(prefix="ap_")
    rejected = False
    err = ""
    try:
        if os.path.isdir(indir):
            shutil.copytree(indir, work, dirs_exist_ok=True)
        try:
            args = parse_patch(patch_text)
            apply_patch(args.hunks, cwd=work)
        except (PatchParseError, PatchApplyError) as e:
            rejected = True
            err = str(e)[:90]

        actual = read_tree(work)
        if actual == expected:
            tag = "被拒绝，文件保持不变" if rejected else "应用成功，内容一致"
            passed.append((name, tag))
        else:
            missing = [k for k in expected if k not in actual]
            wrong = [k for k in expected if k in actual and expected[k] != actual[k]]
            extra = [k for k in actual if k not in expected]
            detail = []
            if missing: detail.append("缺少 %s" % missing[:2])
            if extra: detail.append("多出 %s" % extra[:2])
            for k in wrong[:1]:
                detail.append("%s 期望 %r 实际 %r" % (k, expected[k][:80], actual[k][:80]))
            failed.append((name, ("拒绝原因: " + err + " | ") if rejected else "" + "；".join(detail)))
    except Exception as e:
        failed.append((name, "内部异常：%s" % e))
        traceback.print_exc()
    finally:
        shutil.rmtree(work, ignore_errors=True)

print("=" * 70)
print("apply_patch 对齐 codex-rs：通过 %d / 失败 %d" % (len(passed), len(failed)))
print("=" * 70)
for n, why in passed:
    print("  PASS  %-48s %s" % (n, why))
for n, why in failed:
    print("  FAIL  %-48s %s" % (n, why))
sys.exit(1 if failed else 0)
