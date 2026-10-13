#!/usr/bin/env bash
# Jellyfish Docker 部署管理脚本
#
# 用法：
#   ./scripts/jellyfish-docker.sh up        # 构建并启动全部服务
#   ./scripts/jellyfish-docker.sh init      # 初始化数据库表/素材 bucket（幂等）
#   ./scripts/jellyfish-docker.sh down      # 停止并移除容器（保留数据卷）
#   ./scripts/jellyfish-docker.sh destroy   # 停止并删除数据卷（会清空 MySQL/素材！）
#   ./scripts/jellyfish-docker.sh ps        # 查看容器状态
#   ./scripts/jellyfish-docker.sh logs [svc]# 跟踪日志（默认 backend）
#   ./scripts/jellyfish-docker.sh check     # 端到端健康检查
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$PROJECT_DIR/deploy/compose/docker-compose.yml"
ENV_FILE="$PROJECT_DIR/deploy/compose/.env"

# 项目内 DOCKER_CONFIG：使用匿名凭据助手，避免受限 shell 下 macOS keychain 报错
export DOCKER_CONFIG="$PROJECT_DIR/.docker"
export PATH="$PROJECT_DIR/bin:$PATH"

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

# 等待后端健康接口可用，最长约 5 分钟
wait_backend() {
  echo "[jellyfish] 等待后端就绪 ..."
  for _ in $(seq 1 60); do
    if [ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://localhost:8000/api/v1/health)" = "200" ]; then
      echo "[jellyfish] 后端就绪"
      return 0
    fi
    sleep 5
  done
  echo "[jellyfish] 后端超时未就绪，请检查 ./scripts/jellyfish-docker.sh logs backend" >&2
  return 1
}

case "${1:-}" in
  up)
    compose up -d --build
    wait_backend
    "$0" init
    "$0" check
    ;;
  init)
    # 建表 + 建 bucket + 公共读策略，均为幂等操作
    compose exec -T -w /app backend uv run python init_db.py
    compose exec -T -w /app backend uv run python init_storage_public.py
    ;;
  down)
    compose down --remove-orphans
    ;;
  destroy)
    echo "[jellyfish] 即将删除全部数据卷（MySQL 数据与素材文件都会丢失）"
    read -r -p "确认请输入 yes: " ans
    [ "$ans" = "yes" ] || { echo "已取消"; exit 1; }
    compose down --remove-orphans -v
    ;;
  ps)
    compose ps -a
    ;;
  logs)
    compose logs -f --tail=200 "${2:-backend}"
    ;;
  check)
    echo "--- 容器状态 ---"
    compose ps --format 'table {{.Name}}\t{{.Status}}\t{{.Ports}}'
    echo "--- 接口探活 ---"
    printf 'backend  /api/v1/health : %s\n' "$(curl -s -m 10 -o /dev/null -w '%{http_code}' http://localhost:8000/api/v1/health)"
    printf 'backend  /docs           : %s\n' "$(curl -s -m 10 -o /dev/null -w '%{http_code}' http://localhost:8000/docs)"
    printf 'front    :7788/          : %s\n' "$(curl -s -m 10 -o /dev/null -w '%{http_code}' http://localhost:7788/)"
    printf 'rustfs   :9000/          : %s (403 属正常，服务在监听)\n' "$(curl -s -m 10 -o /dev/null -w '%{http_code}' http://localhost:9000/)"
    echo "--- 访问地址 ---"
    echo "前端   : http://localhost:7788"
    echo "后端   : http://localhost:8000  (Swagger: http://localhost:8000/docs)"
    echo "RustFS : http://localhost:9001  (控制台)"
    ;;
  *)
    sed -n '2,12p' "${BASH_SOURCE[0]}"
    exit 1
    ;;
esac
