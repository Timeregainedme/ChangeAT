"""Celery 应用实例。

最小落地原则：
- 仅把 Celery 当作执行层与 broker 客户端；
- 任务状态/结果真相仍然回写 GenerationTask；
- 第一阶段不依赖 Celery result backend。
"""

from celery import Celery
from celery.signals import worker_process_init

from app.config import settings
from app.core.db import reset_db_runtime


celery_app = Celery(
    "dyeingtime",
    broker=settings.celery_broker_url,
    include=["app.tasks.execute_task"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    timezone="Asia/Shanghai",
    enable_utc=False,
)


@worker_process_init.connect
def _init_worker_process(**_: object) -> None:
    """Celery prefork 子进程启动后，重建 DB 运行时并注册内置能力。

    为什么必须在这里做 provider bootstrap：
    - 供应商注册表（provider key/alias → 能力）与任务适配器注册表都是进程内状态；
    - web 进程在 `app.main` 启动时已调用 `bootstrap_all_registries()`，
      但 Celery worker 是独立进程，从未执行过这段逻辑；
    - 结果是 worker 里解析供应商名一律失败（`Unsupported provider name: ...`）。

    两个注册入口都是幂等的，prefork 每个子进程各执行一次是安全的。
    """

    reset_db_runtime()

    from app.bootstrap import bootstrap_all_registries

    bootstrap_all_registries()
