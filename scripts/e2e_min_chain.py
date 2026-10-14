#!/usr/bin/env python3
"""全链路最小冒烟测试：10 秒剧本 -> 切分分镜 -> 跑关键帧图 -> 跑视频 -> 合并导出。

用法：
    python3 scripts/e2e_min_chain.py            # 完整链路
    python3 scripts/e2e_min_chain.py --dry-run  # 只建项目/章节/切分，不跑图不跑视频

前置：后端已启动在 http://127.0.0.1:8000，且 model_settings 的默认 text/image/video 模型可用。
脚本会真实调用供应商接口（会消耗额度），产生的项目/分镜/文件都会留在数据库里，便于在界面上查看。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = "http://127.0.0.1:8000"

# 10 秒剧本：两个镜头，各约 5 秒。
SCRIPT = """【场景：清晨的城市天台】
镜头1：少女推开锈迹斑斑的铁门，晨光洒在她脸上，她深吸一口气，望向远处的高楼群。
镜头2：她抬手遮住刺眼的阳光，嘴角微微上扬，转身朝楼梯口走去。
"""

PROJECT_RATIO = "16:9"
PROFILE = "standard"

IMAGE_POLL_TIMEOUT = 420
VIDEO_POLL_TIMEOUT = 1800
POLL_INTERVAL = 5


def call(method: str, path: str, body: dict | None = None, *, expect: tuple[int, ...] = (200, 201)):
    url = BASE + path
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        status = exc.code
    if status not in expect:
        raise RuntimeError(f"{method} {path} -> HTTP {status}\n{raw[:2000]}")
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(payload, dict) and "data" in payload and "code" in payload:
        return payload["data"]
    return payload


def step(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def poll(task_id: str, *, timeout: int, label: str) -> str:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        data = call("GET", f"/api/v1/film/tasks/{task_id}/status")
        status = (data or {}).get("status")
        progress = (data or {}).get("progress")
        if status != last:
            print(f"  [{label}] {task_id} status={status} progress={progress}", flush=True)
            last = status
        if status in ("succeeded", "failed", "cancelled"):
            return status
        time.sleep(POLL_INTERVAL)
    raise RuntimeError(f"[{label}] 任务 {task_id} 超时（{timeout}s 未结束，最后状态 {last}）")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="不跑图不跑视频")
    parser.add_argument("--skip-images", action="store_true", help="复用已生成的首帧，不重跑图片")
    parser.add_argument("--reuse-videos", action="store_true", help="已有成功视频版本时直接采用，不重新生成")
    parser.add_argument("--project-id", default=None, help="复用已有项目 ID（跳过建项目/章节/切分）")
    args = parser.parse_args()

    tag = uuid.uuid4().hex[:8]
    project_id = args.project_id

    if project_id is None:
        step("1/7 新建项目")
        project_id = f"proj-e2e-{tag}"
        project = call(
            "POST",
            "/api/v1/studio/projects",
            {
                "id": project_id,
                "name": f"全链路最小测试 {tag}",
                "description": "10 秒剧本：天台",
                "style": "动漫3D",
                "visual_style": "动漫",
                "seed": 42,
                "unify_style": True,
                "progress": 0,
                "default_video_ratio": PROJECT_RATIO,
                "default_image_ratio": PROJECT_RATIO,
                "default_image_resolution_profile": PROFILE,
            },
        )
        print(f"  project_id={project.get('id')} ratio={project.get('default_video_ratio')}")

        step("2/7 开工预检（只读）")
        readiness = call("GET", f"/api/v1/studio/projects/{project_id}/production-readiness")
        for item in readiness.get("checks", []):
            flag = "OK " if item.get("ok") else "NG "
            print(f"  {flag} {item.get('key'):32s} {item.get('message')}")
        print(f"  ready={readiness.get('ready')}")

        step("3/7 新建章节（10 秒剧本）")
        chapter_id = f"chap-e2e-{tag}"
        call(
            "POST",
            "/api/v1/studio/chapters",
            {
                "id": chapter_id,
                "project_id": project_id,
                "index": 1,
                "title": "天台清晨",
                "summary": "少女在天台迎接清晨",
                "raw_text": SCRIPT,
                "status": "draft",
            },
        )
        print(f"  chapter_id={chapter_id}")

        step("4/7 切分分镜（写入数据库）")
        division = call(
            "POST",
            "/api/v1/script-processing/divide",
            {"script_text": SCRIPT, "write_to_db": True, "chapter_id": chapter_id},
        )
        shots = (division or {}).get("shots") or []
        print(f"  切分得到 {len(shots)} 个分镜")

        step("5/7 读取分镜列表")
        listing = call("GET", f"/api/v1/studio/shots?chapter_id={chapter_id}&page=1&page_size=50")
        items = (listing or {}).get("items") or []
        for it in items:
            print(f"  #{it.get('index')} {it.get('title')} [{it.get('status')}] {it.get('id')}")
    else:
        chapter_id = None
        timeline = call("GET", f"/api/v1/studio/timeline/projects/{project_id}")
        items = [
            {"id": c["shot_id"], "index": c.get("index"), "title": c.get("title")}
            for c in (timeline.get("clips") or [])
        ]
        for it in items:
            print(f"  #{it.get('index')} {it.get('title')} {it.get('id')}")

    if not items:
        print("\n没有分镜，链路终止。")
        return 1

    if args.dry_run:
        print("\n--dry-run 结束。")
        return 0

    step("6/7 跑图：为每个分镜生成首帧")
    for shot in items:
        sid = shot["id"]
        if args.skip_images:
            print(f"  #{shot.get('index')} 跳过跑图（--skip-images）")
            continue
        base_prompt = f"{shot.get('title')}，动漫3D风格，清晨城市天台，晨光"
        try:
            rendered = call(
                "POST",
                f"/api/v1/studio/image-tasks/shot/{sid}/frame-render-prompt",
                {"frame_type": "first", "prompt": base_prompt},
            )
            prompt = rendered.get("rendered_prompt") or base_prompt
        except Exception as exc:  # noqa: BLE001
            print(f"  [warn] 提示词渲染失败，退回原始提示词：{exc}")
            prompt = base_prompt
        created = call(
            "POST",
            f"/api/v1/studio/image-tasks/shot/{sid}/frame-image-tasks",
            {
                "frame_type": "first",
                "prompt": prompt,
                "target_ratio": PROJECT_RATIO,
                "resolution_profile": PROFILE,
                "images": [],
            },
        )
        task_id = created["task_id"]
        print(f"  #{shot.get('index')} image task={task_id}")
        status = poll(task_id, timeout=IMAGE_POLL_TIMEOUT, label="image")
        if status != "succeeded":
            raise RuntimeError(f"分镜 {sid} 的图片任务失败：{status}")

    step("6.5/7 视频准备度自检（必要时标记「无需提取」）")
    for shot in items:
        sid = shot["id"]
        readiness = call("GET", f"/api/v1/studio/shots/{sid}/video-readiness?reference_mode=first")
        blocking = [c for c in readiness.get("checks", []) if not c.get("ok")]
        if any(c.get("key") == "extraction_ready" for c in blocking):
            print(f"  #{shot.get('index')} extraction_ready NG -> 走官方「标记无需提取」")
            call("PATCH", f"/api/v1/studio/shots/{sid}/skip-extraction", {"skip": True})
            readiness = call("GET", f"/api/v1/studio/shots/{sid}/video-readiness?reference_mode=first")
            blocking = [c for c in readiness.get("checks", []) if not c.get("ok")]
        print(f"  #{shot.get('index')} ready={readiness.get('ready')}")
        for item in blocking:
            print(f"    NG {item.get('key')}: {item.get('message')}")
        if blocking:
            raise RuntimeError(
                f"分镜 {sid} 视频准备度未通过："
                + "; ".join(f"{c['key']}: {c['message']}" for c in blocking)
            )

    step("7/7 跑视频 + 采用 + 合并导出")
    for shot in items:
        sid = shot["id"]
        if args.reuse_videos:
            try:
                existing = call("GET", f"/api/v1/studio/shots/{sid}/video-versions")
            except Exception as exc:  # noqa: BLE001
                print(f"  [warn] 版本列表不可用：{exc}")
                existing = []
            done = next(
                (v for v in existing if v.get("status") == "succeeded" and v.get("file_id")),
                None,
            )
            if done:
                print(
                    f"  #{shot.get('index')} 复用已有视频 file={done.get('file_id')} "
                    f"current={done.get('is_current')}"
                )
                if not done.get("is_current"):
                    adopted = call(
                        "POST",
                        f"/api/v1/studio/shots/{sid}/video-versions/adopt",
                        {"file_id": done["file_id"]},
                    )
                    print(f"     已采用 -> generated_video_file_id={adopted.get('generated_video_file_id')}")
                continue
        created = call(
            "POST",
            "/api/v1/film/tasks/video",
            {"shot_id": sid, "reference_mode": "first", "ratio": PROJECT_RATIO},
        )
        task_id = created["task_id"]
        print(f"  #{shot.get('index')} video task={task_id}")
        status = poll(task_id, timeout=VIDEO_POLL_TIMEOUT, label="video")
        if status != "succeeded":
            versions = call("GET", f"/api/v1/studio/shots/{sid}/video-versions")
            print("  video-versions:", json.dumps(versions, ensure_ascii=False)[:1200])
            raise RuntimeError(f"分镜 {sid} 的视频任务失败：{status}")
        versions = call("GET", f"/api/v1/studio/shots/{sid}/video-versions")
        current = next((v for v in versions if v.get("is_current")), None) or next(
            (v for v in versions if v.get("file_id")), None
        )
        print(
            f"     version task={current.get('task_id')} file={current.get('file_id')} "
            f"current={current.get('is_current')}"
        )
        if not current.get("is_current"):
            adopted = call(
                "POST",
                f"/api/v1/studio/shots/{sid}/video-versions/adopt",
                {"file_id": current["file_id"]},
            )
            print(f"     已采用 -> generated_video_file_id={adopted.get('generated_video_file_id')}")

    step("时间线聚合")
    timeline = call("GET", f"/api/v1/studio/timeline/projects/{project_id}")
    print(f"  stats={json.dumps(timeline.get('stats'), ensure_ascii=False)}")
    for clip in timeline.get("clips") or []:
        print(
            f"  #{clip.get('index')} {clip.get('title')} "
            f"{clip.get('start')}-{clip.get('end')}s video={clip.get('video_file_id')} "
            f"frames={len(clip.get('frames') or [])} dialogs={len(clip.get('dialogs') or [])}"
        )

    step("导出成片")
    exported = call("POST", f"/api/v1/studio/timeline/projects/{project_id}/export", {})
    print(f"  file_id={exported.get('file_id')}")
    print(f"  download_path={exported.get('download_path')}")
    print(f"  clip_count={exported.get('clip_count')} duration={exported.get('duration')}")

    print(f"\nALL_OK project_id={project_id}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nFAILED: {exc}", file=sys.stderr)
        sys.exit(1)
