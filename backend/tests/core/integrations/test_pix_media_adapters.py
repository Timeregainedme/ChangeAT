"""回归：PIX 图片/视频 adapter 必须能导入并调用 HTTP 日志辅助函数。

缺陷背景（真实复现）：`app/core/integrations/pix/images.py` 与
`app/core/integrations/pix/video.py` 都调用了 `log_media_http_request` /
`log_media_http_response`，但没有从 `app.core.integrations.http_logging`
导入这两个名字。运行期抛 `NameError`，而
`AbstractImageGenerationTask.run()` / `AbstractVideoGenerationTask.run()`
用 `except Exception` 把它吞成 `self._error`，任务最终只能上报
「Image generation task returned no result」，供应商**根本没有被调用**
（worker 日志里没有任何 `media_generation_http_request provider=pix`）。

因此这里既做「名字可解析」的静态护栏，也做一次真实的适配器调用，
断言 HTTP 请求确实发到了 PIX 端点。
"""

from __future__ import annotations

import base64
import json
from types import ModuleType

import httpx
import pytest

from app.core.contracts.image_generation import ImageGenerationInput, InputImageRef
from app.core.contracts.provider import ProviderConfig
from app.core.contracts.video_generation import VideoGenerationInput
from app.core.integrations.pix import images as pix_images
from app.core.integrations.pix import video as pix_video
from app.core.integrations.pix.images import PixImageApiAdapter
from app.core.integrations.pix.video import PixVideoApiAdapter


def _patch_httpx_client(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    """让 adapter 内 `import httpx` 后使用的 AsyncClient 走 MockTransport。"""

    real_client = httpx.AsyncClient

    def factory(**kwargs: object) -> httpx.AsyncClient:
        timeout = kwargs.get("timeout", 60.0)
        return real_client(transport=transport, timeout=timeout)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", factory)


@pytest.mark.parametrize("module", [pix_images, pix_video], ids=["images", "video"])
def test_pix_adapter_module_exposes_http_logging_helpers(module: ModuleType) -> None:
    """护栏：两个模块都必须在自身命名空间里绑定这两个辅助函数。"""

    namespace = vars(module)
    assert "log_media_http_request" in namespace
    assert "log_media_http_response" in namespace


@pytest.mark.asyncio
async def test_pix_image_adapter_sends_create_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """回归：图片 adapter 的 create 路径必须真的发出 HTTP 请求。"""

    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"task_id": "pix-task-1"})

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))
    cfg = ProviderConfig(provider="pix", api_key="sk-pix-test", base_url="https://pix.example.com")
    inp = ImageGenerationInput(prompt="hello", model="gpt-image-2.5-flare")

    task_id = await PixImageApiAdapter().create_image_task(cfg=cfg, inp=inp, timeout_s=30.0)

    assert task_id == "pix-task-1"
    assert seen["path"].endswith("/api/v1/model-runtime/invoke")
    body = json.loads(seen["body"])
    assert body["model_id"] == "gpt-image-2.5-flare"
    assert body["modality"] == "image"
    assert body["params"]["prompt"] == "hello"


@pytest.mark.asyncio
async def test_pix_image_adapter_defaults_to_1k_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """回归：未显式指定尺寸时，PIX 出图统一落到 `1K` 档位。

    角色卡/场景/道具这类 `purpose="generic"` 的调用不透传 size
    （`resolve_image_size` 对非 video_reference 直接返回 requested_size=None），
    原默认值 `2K` 会让角色卡出到 2048x2048；项目既定规格是 1K。
    """

    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"task_id": "pix-task-1k"})

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))
    cfg = ProviderConfig(provider="pix", api_key="sk-pix-test", base_url="https://pix.example.com")
    inp = ImageGenerationInput(prompt="hello", model="gpt-image-2.5-flare")

    task_id = await PixImageApiAdapter().create_image_task(cfg=cfg, inp=inp, timeout_s=30.0)

    assert task_id == "pix-task-1k"
    assert pix_images.DEFAULT_PIX_IMAGE_RESOLUTION == "1K"
    body = json.loads(seen["body"])
    assert body["params"]["resolution"] == "1K"
    assert body["params"]["aspect_ratio"] == "1:1"


@pytest.mark.asyncio
async def test_pix_video_adapter_sends_create_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """回归：视频 adapter 的 create 路径必须真的发出 HTTP 请求。"""

    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"task_id": "pix-video-1"})

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))
    cfg = ProviderConfig(provider="pix", api_key="sk-pix-test", base_url="https://pix.example.com")
    inp = VideoGenerationInput(prompt="hello", model="minimax-h3", ratio="16:9")

    task_id = await PixVideoApiAdapter().create_media_task(cfg=cfg, input_=inp, timeout_s=30.0)

    assert task_id == "pix-video-1"
    assert seen["path"].endswith("/v1/media/generate")
    body = json.loads(seen["body"])
    assert body["model"] == "minimax-h3"


@pytest.mark.asyncio
async def test_pix_image_adapter_uploads_data_url_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    """回归：`data:` 参考图必须先经 `/v1/files` 换链，再以公网 URL 传给 invoke。

    缺陷背景：平台侧 `resolve_reference_image_refs_by_file_ids` 产出的参考图是
    `data:image/png;base64,...`，而 PIX `model-runtime/invoke` 只接受稳定
    http(s) URL；直接透传会被 400 `invalid_reference_provenance` 拒绝，导致
    「分镜必须挂参考图」的核心链路必失败（实测 task 8718fe65 即为此失败）。
    """

    calls: list[str] = []
    invoke_body: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/v1/files"):
            assert "multipart/form-data" in request.headers.get("content-type", "")
            return httpx.Response(200, json={"data": {"url": "https://cdn.example.com/ref0.png"}})
        invoke_body.update(json.loads(request.content.decode()))
        return httpx.Response(200, json={"task_id": "pix-task-ref"})

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))
    cfg = ProviderConfig(provider="pix", api_key="sk-pix-test", base_url="https://pix.example.com")
    data_url = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
    inp = ImageGenerationInput(
        prompt="scene",
        model="gpt-image-2.5-flare",
        images=[InputImageRef(image_url=data_url)],
    )

    task_id = await PixImageApiAdapter().create_image_task(cfg=cfg, inp=inp, timeout_s=30.0)

    assert task_id == "pix-task-ref"
    assert calls[0].endswith("/v1/files")
    assert calls[1].endswith("/api/v1/model-runtime/invoke")
    params = invoke_body["params"]
    assert isinstance(params, dict)
    assert params["images"] == ["https://cdn.example.com/ref0.png"]
    assert params["mode"] == "image-edit"


@pytest.mark.asyncio
async def test_pix_image_adapter_passes_through_http_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """http(s) 参考图原地透传，不应额外触发上传。"""

    calls: list[str] = []
    invoke_body: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        invoke_body.update(json.loads(request.content.decode()))
        return httpx.Response(200, json={"task_id": "pix-task-direct"})

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))
    cfg = ProviderConfig(provider="pix", api_key="sk-pix-test", base_url="https://pix.example.com")
    inp = ImageGenerationInput(
        prompt="scene",
        model="gpt-image-2.5-flare",
        images=[InputImageRef(image_url="https://cdn.example.com/direct.png")],
    )

    task_id = await PixImageApiAdapter().create_image_task(cfg=cfg, inp=inp, timeout_s=30.0)

    assert task_id == "pix-task-direct"
    assert len(calls) == 1
    params = invoke_body["params"]
    assert isinstance(params, dict)
    assert params["images"] == ["https://cdn.example.com/direct.png"]
    assert params["mode"] == "image-edit"
