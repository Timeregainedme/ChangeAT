# Codex 审查简报：媒体参考「只存 file_id、派发期物化」

- **仓库**：`/Users/mac/Desktop/03-公司业务/jellyfish`（https://github.com/Forget-C/Jellyfish 的二次开发）
- **分支**：`main`，**HEAD = `c7af42e`**（本次唯一提交，工作区干净）
- **一句话**：把 `generation_tasks.payload` 里内联的 base64 参考图，改成只存 `file_id`，在 worker 调用供应商**前一刻**才物化回 data URL。设计对齐 toonflow「引用存储、派发期读取」。

---

## 1. 复现环境（重要，否则看不到改动）

1. **后端代码是烘进镜像的，compose backend 没有源码 bind mount**。改完代码不重建镜像，容器里跑的还是旧代码：
   ```bash
   cd /Users/mac/Desktop/03-公司业务/jellyfish
   docker compose -f deploy/compose/docker-compose.yml build backend celery-worker
   docker compose -f deploy/compose/docker-compose.yml up -d backend celery-worker
   ```
2. **跑测试**（容器内）：
   ```bash
   # 宿主机改的文件必须先 cp 进容器
   docker cp backend/tests/x.py compose-backend-1:/app/tests/x.py
   docker exec compose-backend-1 uv run pytest tests -q
   ```
   （也可宿主机 `cd backend && .venv/bin/python -m pytest tests -q`，`addopts` 默认排除 `integration` marker）
3. **看数据库**：
   ```bash
   source scripts/dockerenv.sh
   DB_PASS=$(grep -E "^MYSQL_ROOT_PASSWORD=" deploy/compose/.env | cut -d= -f2-)
   docker exec -i compose-mysql-1 mysql -uroot -p"$DB_PASS" jellyfish --default-character-set=utf8mb4 -e "..."
   ```

---

## 2. 要解决的原始问题

`generation_tasks.payload`（`JSON` 列）里 `run_args.input.images[*].image_url` 存的是**内联 base64 图片**。实测：

| task_kind | 行数 | 最大 payload |
|---|---|---|
| `image_generation` | 7 | **11,150,928 字节（≈11 MB）** |
| `video_generation` | 2 | **780,203 字节** |
| `audio_generation` | 1 | 467 字节 |

`payload` 原文形如 `{"run_args": {"input": {"model": "gpt-image-2.5-flare", "images": [{"image_url": "data:image/png;base64,iVBOR..."}`。

服务端 MySQL 参数 `@@sort_buffer_size = 262144`（256 KB）、`@@max_sort_length = 1024`。后果是**任何对该宽表带 `ORDER BY` 的查询直接失败**：

```
sqlalchemy.exc.OperationalError: (pymysql.err.OperationalError)
(1038, 'Out of sort memory, consider increasing server sort buffer size')
```

**可用 mysql CLI 一行复现**（我实测过，确实报 1038）：
```sql
SELECT id, task_kind, LENGTH(payload) FROM generation_tasks ORDER BY created_at DESC LIMIT 8;
```

> 注：此前已单独修过 `backend/app/services/studio/shot_video_versions.py` 里唯一一处宽行排序（改为「先窄列排序取 id、再回表」两段式），本次不再重复。

---

## 3. 改动清单

### 3.1 新增 `backend/app/services/media_reference_files.py`（唯一共享入口，157 行）

放在 `app/services/` 顶层而非 `services/studio/` 或 `services/film/` 下 —— 避免这两个包互相 import 触发 `__init__` 循环。

| 函数 | 作用 |
|---|---|
| `_image_content_type(file_obj) -> str \| None` | 取对象存储 MIME，拿不到按扩展名 `mimetypes.guess_type` 猜 |
| `assert_reference_image_file_id(db, *, file_id) -> None` | **只读元信息、不下载**；行不存在/无 storage_key/MIME 非 `image/*` → `HTTPException(400)` |
| `image_data_url_from_file_id(db, *, file_id) -> str` | 下载字节 + base64 → `data:image/<fmt>;base64,...`（**仅派发期调用**） |
| `compact_image_reference_refs(db, *, file_ids) -> list[dict]` | 校验后返回 `[{"file_id": ...}]`，顺序与入参一致，跳过空白项 |
| `materialize_image_reference_refs(db, *, images) -> list[dict]` | `{"file_id": x}` → `{"image_url": "data:..."}`；**已带 `image_url` 的条目原样直通**（历史 payload 兼容） |
| `materialize_file_ids(db, *, file_ids) -> list[str]` | file_id 列表 → data URL 列表 |

统一错误文案 `_INVALID_FILE_ID_DETAIL = "Invalid image file_id: {file_id}"`（与改前 `generated_video.file_id_to_data_url` 的文案完全一致，避免行为漂移）。

### 3.2 图片链路

- `backend/app/services/studio/image_task_references.py`
  - 删除 `resolve_reference_image_refs_by_file_ids`（旧实现会**就地**把 file_id 编成 `{"image_url": "data:..."}`，即 11MB 的直接来源）。
  - 新增 `compact_reference_image_refs_by_file_ids(db, *, file_ids)` → 一行委托 `compact_image_reference_refs`。
  - 清理失效 import（`base64`/`mimetypes`/`HTTPException`/`status`/`storage`/`FileItem`）。
- `backend/app/api/v1/routes/studio/image_tasks.py`：import 别名改为 `_compact_reference_image_refs_by_file_ids_service`，4 个调用点（:197/:262/:327/:405，分别对应 actor / asset / character / shot-frame 四类出图）改为传紧凑引用。
- `backend/app/services/studio/image_task_runner.py`：`run_image_generation_task` 内 `input_dict = dict(run_args.get("input") or {})`（:336）之后、`ImageGenerationInput.model_validate(input_dict)`（:353）**之前**插入物化（:340-342）：
  ```python
  raw_refs = input_dict.get("images")
  if raw_refs:
      input_dict["images"] = await materialize_image_reference_refs(session, images=raw_refs)
  ```

### 3.3 视频链路 `backend/app/services/film/generated_video.py`

- `file_id_to_data_url(db, *, file_id) -> str` **保留模块级名字**（7 处既有测试 monkeypatch 依赖它），函数体改为一行委托 `image_data_url_from_file_id`。
- 新增 `materialize_input_references(db, *, input_dict) -> dict`：`pop("reference_file_ids")` → `reference_images`；`pop("frame_file_ids")`（`first`/`last`/`key`）→ `first_frame_base64`/`last_frame_base64`/`key_frame_base64`。
- `build_run_args` 不再调 `file_id_to_data_url`，只写 id：
  - 参考图模式：`"reference_file_ids": list(submission.images)`
  - 首尾帧模式：`"frame_file_ids": {"first": ..., "last": ..., "key": ...}`
- `run_video_generation_task` 内（:370 之后）插入 `input_dict = await materialize_input_references(session, input_dict=input_dict)`。
  **注意**：必须先把 `*_file_ids` 键 pop 掉，因为 `VideoGenerationInput` 是 `extra="forbid"`。
- 清理 import：删 `base64` / `mimetypes` / `from app.core import storage`。

### 3.4 删除死代码

`backend/app/services/studio/image_tasks.py` 删掉 `resolve_front_image_ref` 与 `resolve_ordered_image_refs`（原 132-261 行）。二者**零调用者**，且唯一行为就是把 file_id 就地 base64 —— 正是本次要消灭的形态。同步从 `backend/app/services/studio/__init__.py` 的懒导入块与 `__all__` 移除。该文件 284 → 154 行。全仓 `grep` 确认无残留引用（含 tests）。

**净 diff：9 个文件修改 + 2 个新增，+107 / −252 行。**

### 3.5 测试

- **新增** `backend/tests/test_media_reference_files.py`（10 个用例）：`_FakeSession`（只实现 `db.get`）+ `monkeypatch.setattr(mrf, "storage", _FakeStorage())`。覆盖：紧凑引用只含 file_id 且 `repr` 不含 base64、跳过空白项、物化为 data URL、历史 `image_url` 直通、混合顺序保持、坏 file_id / 非图片 / 缺行 → 400。
- **改** `backend/tests/test_generated_video_service.py`：`test_build_run_args_maps_reference_images` 断言改为检查 `frame_file_ids == {"first": "img-first", "last": "img-last", "key": None}` 且 `"first_frame_base64" not in run_args["input"]`，并新增派发期物化断言。
- **改** `backend/tests/test_image_task_services.py`：用例重命名为 `test_compact_reference_image_refs_keeps_file_ids_only`，把 `download_file` 换成 `_fail_download_file`，**断言提交阶段不得下载字节**。
- **改** `backend/tests/test_image_tasks_api_responses.py`：断言 `kwargs["images"] == [{"file_id": "file-1"}]`。

---

## 4. 验证证据

### 4.1 单元测试
`400 passed, 2 deselected in 14.47s`（改前 390；新增 10）。

### 4.2 payload 体积实测（真实任务，非 mock）

| 路径 | 改前 | 改后 | payload 内是否含 `base64` |
|---|---|---|---|
| 带参考图的图片任务 | 11,150,928 B | **8,626 B** | 有 → **无** |
| 视频任务 | 780,203 B | **4,678 B** | 有 → **无** |

改后图片任务 payload 里 `images` 的原文：
```json
"images": [{"file_id": "e29cdb6e-671c-4d9c-9aaa-a73ed87f3aa6"}]
```

三个新任务（1 图 + 2 视频）全部 `status=succeeded, progress=100` —— 说明**派发期物化在真实 PIX 供应商上是通的**（若物化错，PIX 会立刻回 `400 invalid_reference_provenance: reference image ... is not a stable http(s) URL`）。

### 4.3 全链路
`scripts/e2e_min_chain.py --project-id proj-e2e-deef6dc3`（10 秒剧本、2 个分镜）→ `ALL_OK`，timeline `clips_with_video=2 / exportable=true`，导出成片 `file_id=f8b429f6-aa30-44e0-81cf-c48951d855fa`。

### 4.4 lint
用 `git worktree add /tmp/jf-head HEAD` 在基线上跑同一套 `uvx ruff check`：HEAD = 19 findings，改后 = 18（只减不增）。剩余项（`I001` 导入排序、`F841`、`RUF022`、`S110`、`B008`）均为**既有**问题，本仓库不以 ruff 作门禁。

---

## 5. 请重点审查的点（我自己认为的风险 / 未验证项）

**R1〔我认为最值得看〕worker 上下文里抛 `HTTPException`。**
`image_data_url_from_file_id` 在下载失败/校验失败时抛 `fastapi.HTTPException(400)`。它现在被 **worker**（`run_image_generation_task` / `run_video_generation_task`）调用，不在 HTTP 请求上下文里。请确认 task_manager 对任意异常都能把任务落到 `failed` + `error`，而不是卡在 `running`。
**我未实测「坏 file_id 在派发期」这条分支**（只在提交期有单测覆盖）。

**R2 首尾帧模式缺少 E2E。**
本次真实链路走的是**参考图模式**（`REFERENCE_MODE`）。首尾帧模式（`REQUIRED_FRAMES_BY_MODE`）只有单测覆盖。

**R3 一个可能的行为差异：`key_frame_base64` 键从「存在且为 None」变成「不存在」。**
改前：`"key_frame_base64": frame_map.get(ShotFrameType.key)` → 键**存在**、值为 `None`。
改后：`frame_file_ids` 里 key 为 `None` → `materialize_input_references` **跳过** → 物化后结果里**没有** `key_frame_base64` 键。
实测 minimax-h3 参考图模式跑通，但若某个供应商适配器或 `VideoGenerationInput` 依赖「键存在但为 None」，这里是静默变化。**建议确认。**

**R4 提交期多了一次串行对象存储元信息调用。**
`compact_image_reference_refs` 对每个 file_id 调 `storage.get_file_info`（N 次串行 IO）。toonflow 是刻意串行的（但那是读**字节**、防探测风暴），这里只是元信息。参考图多时是否值得批量化？

**R5 历史大 payload 未迁移。**
`materialize_image_reference_refs` 对已含 `image_url` 的条目原样直通 → 老 payload 仍可执行。所以「payload 不再变大」**只对新任务成立**；库里仍有 4 行历史大 payload（2 图 11MB + 2 视频）。数据迁移是不可逆操作，**我未擅自执行，等用户拍板**。

**R6 `submission.images[i]` 索引无长度校验。**
`frame_map = {ft: submission.images[i] for i, ft in enumerate(required_frames)}`，图片数少于所需帧数会 `IndexError`。与改前同构（改前 `frame_data_urls[i]` 同样），**未新增风险**，但可顺手加固。

**R7 删除的公共符号。**
`resolve_front_image_ref` / `resolve_ordered_image_refs` 已从 `app/services/studio/__init__.py` 的 `__all__` 移除。若外部插件/脚本曾导入会 `ImportError`。全仓 grep 无引用，但仓外消费方我看不到。

**R8 错误信息可读性。**
`_INVALID_FILE_ID_DETAIL` 把「行不存在 / 存储读取失败 / 不是图片」三种原因统一成一句 `Invalid image file_id: {file_id}`，排障时区分不开（是刻意保持与改前一致）。

**R9 测试打桩面。**
`test_generated_video_service.py` 仍 monkeypatch `app.services.film.generated_video.file_id_to_data_url`。`materialize_input_references` 内部调用的是**该模块内**的名字，所以打桩生效。若后续有人把它改成直接调 `image_data_url_from_file_id`，会绕过打桩、测试静默失真。

**R10 未跑真实 HTTP 端点验证「坏 file_id → 400」。**
单测覆盖了 `compact_image_reference_refs` 的 400 分支，但我没发真实请求打端点确认。

---

## 6. 回滚

单提交，`git revert c7af42e` 即可（无 DB schema 变更、无迁移）。旧 payload 形状在新代码下仍可执行，所以**回滚不会让历史任务失效**，这点是刻意设计的。

---

## 附：我参考 toonflow 得到的设计依据

源码：`https://github.com/HBAI-Ltd/Toonflow-app`（浅克隆在 `/tmp/toonflow-src`）。

- toonflow **没有数据库**，媒体全部落工作区文件系统（`packages/file` 的 `writeAtomic`/`resolveWorkspacePath`）。
- `apps/server/src/utils/ai/files.ts`：输入图上传供应商 Files API 后只缓存 `{fileId, expiresAt}`，以 **sha256 内容哈希**为键；请求体写 `{type:"input_image", file_id}`；`stale()` 在 400/404/422 时重传。
- `apps/server/src/utils/ai/requestFiles.ts`：`getRequestFiles(payload)` 找出内联图片，给出 `replace(file)` / `offload(text)` / `useReference(ref)` 三个动作 —— 内联只是「临时的派发态」。
- `apps/server/src/utils/media/generation.ts`：`readReference()` **只在请求体组装那一刻**读字节并 base64，限 100MB、按魔术字节嗅探 MIME、参考素材串行读取。

**核心思想：磁盘/库存引用，base64 只在派发瞬间存在于内存。** jellyfish 之前是把「派发态」直接写进了 DB payload。

**未照搬**的部分（有意）：供应商 Files API 上传（PIX 只接受 http(s) URL，jellyfish 的 PIX 适配器本来就在派发时把 data URL 换成公网链）、100MB 上限、MIME 魔术字节嗅探 —— 都不在本次范围。
