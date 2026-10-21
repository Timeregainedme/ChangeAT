"""参考图接线稽核（只读）。

用途：排查「某个项目的镜头为什么没带上参考图」。逐个镜头打印：
  - 已生成的分镜帧（首/关键/尾）
  - 已关联的角色/场景/道具/服装
  - IR 实际解析出的参考图顺序（图1、图2…）
  - 被跳过的原因（资产没图 / 角色名未在剧本里出现）

用法：
    .venv/bin/python scripts/audit_reference_wiring.py <project_id>
"""
import asyncio
import sys

import pymysql

from sqlalchemy import select

from app.config import settings
from app.core.db import async_session_maker
from app.models.studio import (
    Character,
    Chapter,
    Costume,
    FileItem,
    Project,
    Scene,
    Shot,
    ShotDetail,
)
from app.services.studio.generation.video.build_context import VideoGenerationContext
from app.services.studio.generation.video.derive_preview import _build_ir, _reference_file_ids
from app.services.studio.shot_video_prompt_pack import build_shot_video_prompt_pack


def _conn():
    from urllib.parse import urlparse

    url = urlparse(
        settings.database_url.replace("+aiomysql", "+pymysql").replace("mysql+pymysql", "mysql")
    )
    return pymysql.connect(
        host=url.hostname,
        port=url.port or 3306,
        user=url.username,
        password=url.password,
        database=url.path.lstrip("/"),
    )


async def main() -> None:
    if len(sys.argv) < 2:
        print("用法: audit_reference_wiring.py <project_id>")
        return
    project_id = sys.argv[1]
    raw = _conn()
    cur = raw.cursor()

    cur.execute(
        "SELECT id, name FROM projects WHERE id=%s",
        (project_id,),
    )
    print("project:", cur.fetchone())

    # 帧图：shot_frame_images 通过 shot_detail_id 关联
    cur.execute(
        """
        SELECT s.id, s.`index`, f.frame_type, (f.file_id IS NOT NULL AND f.file_id<>'') AS has_file
        FROM shots s
        JOIN shot_details d ON d.id = s.id
        LEFT JOIN shot_frame_images f ON f.shot_detail_id = d.id
        WHERE s.chapter_id IN (SELECT id FROM chapters WHERE project_id=%s)
        ORDER BY s.`index`
        """,
        (project_id,),
    )
    frames: dict[int, list[str]] = {}
    for _sid, idx, ftype, has_file in cur.fetchall():
        if ftype and has_file:
            frames.setdefault(idx, []).append(ftype)
    print("\n== 帧图（首/关键/尾）==")
    for idx in sorted(frames):
        print(f"  #{idx}: {frames[idx]}")

    raw.close()

    async with async_session_maker() as db:
        project = await db.get(Project, project_id)
        print("\n== 项目风格 ==", project.visual_style, project.style)

        chapters = (
            (await db.execute(select(Chapter).where(Chapter.project_id == project_id))).scalars().all()
        )
        for chapter in chapters:
            shots = (
                (
                    await db.execute(
                        select(Shot).where(Shot.chapter_id == chapter.id).order_by(Shot.index)
                    )
                )
                .scalars()
                .all()
            )
            print(f"\n== 章节 {chapter.index} {chapter.title}，镜头 {len(shots)} 个 ==")
            for shot in shots:
                pack = await build_shot_video_prompt_pack(db, shot_id=shot.id)
                ctx = VideoGenerationContext(
                    shot_id=shot.id, reference_mode="reference", images=[], ratio="16:9"
                )
                ir = _build_ir(pack, ctx)
                refs = [(r.token, r.kind, r.name) for r in ir.references]
                print(f"\n#{shot.index} {shot.title}")
                print("  参考:", refs if refs else "（无）", "| file_ids:", len(_reference_file_ids(ir)))
                print(
                    "  关联资产:",
                    "角色=", [c.name for c in pack.characters],
                    "场景=", pack.scene.name if pack.scene else None,
                    "道具=", [p.name for p in pack.props],
                    "服装=", [c.name for c in pack.costumes],
                )
                for warning in ir.warnings:
                    print("  !", warning)


asyncio.run(main())
