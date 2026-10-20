#!/usr/bin/env python3
"""扫描 MainLayout 下所有页面，判定是否缺少滚动容器。

判定依据（来自 MainLayout.tsx 的三层约束）：
    Layout(100vh, overflow:hidden)
      └─ Layout(flex:1, minHeight:0)
         └─ Content(flex:1, minHeight:0, overflow:hidden, flex column)
            └─ div(w-full h-full min-h-0 overflow-hidden flex flex-col)
               └─ <Outlet />        ← 页面从这里开始

页面必须在自身根节点提供纵向滚动（overflow-y-auto / overflow-auto /
overflowY:'auto'），否则超出视口的内容被裁切且无法滚动。

同时标记「显式 fixed-height 型」页面（内部用 h-full + 子容器各自滚动），
这类是另一种正确解法，不能误判为 bug。
"""
import re
import sys
from pathlib import Path

ROOT = Path("/Users/mac/Desktop/03-公司业务/jellyfish/front/src")

# App.tsx 里挂在 MainLayout 下的 route -> 组件
ROUTES = [
    ("projects", "ProjectLobby"),
    ("projects/:id", "ProjectWorkbench"),
    ("roles/:id/edit", "RoleDetailPage"),
    ("chapters/:id/studio", "ChapterStudio"),
    ("shots/:id/edit", "ChapterShotEditPage"),
    ("chapters/:id/shots", "ChapterShotsPage"),
    ("editor", "VideoEditor"),
    ("assets", "AssetManager"),
    ("assets/actors/:id/edit", "ActorAssetEditPage"),
    ("assets/scenes/:id/edit", "SceneAssetEditPage"),
    ("assets/props/:id/edit", "PropAssetEditPage"),
    ("assets/costumes/:id/edit", "CostumeAssetEditPage"),
    ("prompts", "PromptTemplateManager"),
    ("models", "ModelManagement"),
    ("voices", "VoiceManager"),
    ("settings", "Settings"),
    ("*", "NotFound"),
]

# 找组件文件
def find_component(name: str):
    hits = [p for p in ROOT.rglob(f"{name}.tsx")]
    return hits[0] if hits else None


SCROLL_PATTERNS = [
    r"overflow-y-auto", r"overflowY:\s*'auto'", r"overflowY:\s*\"auto\"",
    r"overflow-auto", r"overflow:\s*'auto'", r"overflow:\s*\"auto\"",
]
FIXED_H_PATTERNS = [
    r"calc\(100vh", r"\bh-full\b", r"height:\s*'100%'",
    r"flex-1", r"min-h-0", r"scroll:\s*\{",
]


def first_return_block(src: str) -> str:
    """取最后一个顶层 return（组件的渲染出口）之后的内容。"""
    # 找到所有 "return (" 的位置，取最后一个非嵌套的
    idx = src.rfind("\n  return (")
    if idx == -1:
        idx = src.rfind("\n  return <")
    return src[idx:] if idx != -1 else src


def analyse(path: Path):
    src = path.read_text(encoding="utf-8")
    block = first_return_block(src)
    head = block[:1500]  # 只看根节点附近

    has_scroll = any(re.search(p, head) for p in SCROLL_PATTERNS)
    has_fixed_h = any(re.search(p, head) for p in FIXED_H_PATTERNS)

    # 是否整页都用 max-h-[NNvh] 内滚（列表卡片型）
    n_maxh = len(re.findall(r"max-h-\[", src))
    n_scroll = sum(len(re.findall(p, src)) for p in SCROLL_PATTERNS)

    return {
        "scroll_in_root": has_scroll,
        "fixed_height": has_fixed_h,
        "maxh_count": n_maxh,
        "scroll_count": n_scroll,
    }


print("=" * 96)
print("页面滚动容器体检（MainLayout 三层 overflow:hidden 约束下）")
print("=" * 96)
print(f"{'路由':<28} {'组件':<24} {'根容器可滚':<10} {'固定高':<8} {'结论'}")
print("-" * 96)

issues = []
for route, comp in ROUTES:
    f = find_component(comp)
    if not f:
        print(f"{route:<28} {comp:<24} {'?':<10} {'?':<8} 未找到文件")
        continue
    r = analyse(f)
    if r["scroll_in_root"]:
        verdict = "OK"
    elif r["fixed_height"] and r["scroll_count"] > 0:
        verdict = "OK(内滚)"
    elif r["fixed_height"]:
        verdict = "⚠️ 疑似：无滚动且非固定高"
        issues.append((route, comp, f, r))
    else:
        verdict = "🔴 缺滚动容器"
        issues.append((route, comp, f, r))

    mark = "✅" if verdict.startswith("OK") else ("⚠️" if verdict.startswith("⚠️") else "🔴")
    print(f"{route:<28} {comp:<24} {str(r['scroll_in_root']):<10} "
          f"{str(r['fixed_height']):<8} {mark} {verdict}")

print()
print("=" * 96)
print(f"需处理：{len(issues)} 个")
print("=" * 96)
for route, comp, f, r in issues:
    print(f"\n### {comp}  ({route})")
    print(f"    文件: {f.relative_to(ROOT.parent)}")
    print(f"    根容器有滚动: {r['scroll_in_root']}   固定高: {r['fixed_height']}   "
          f"max-h-[ 用量: {r['maxh_count']}   滚动声明总数: {r['scroll_count']}")
    src = f.read_text(encoding="utf-8")
    block = first_return_block(src)
    # 打印根节点前 6 行
    for line in block.splitlines()[:8]:
        if line.strip():
            print(f"      {line.rstrip()[:110]}")