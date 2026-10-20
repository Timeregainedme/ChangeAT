# Go 控制面的常用命令。
#
# 所有命令都假设当前目录是 backend/go。
#
# 为什么用 Makefile 而不是把命令散在文档里：
# `oapi-codegen` 的输出路径是相对**当前工作目录**解析的，
# 从 `backend/` 或仓库根目录运行会把文件生成到错误的层级（且 exit code 仍为 0）。
# 把命令固化下来，避免下次有人在错误目录运行后以为生成成功。

GO ?= go
OAPI_CODEGEN ?= $(shell $(GO) env GOPATH)/bin/oapi-codegen
# 契约的权威来源是前端冻结的基线文件，与 Python 侧的契约门禁共用同一份。
OPENAPI_SPEC ?= ../../front/openapi.json

.PHONY: help build test vet fmt generate run clean

help:
	@echo "make build     # 编译全部包"
	@echo "make test      # 运行单元测试"
	@echo "make vet       # 静态检查"
	@echo "make generate  # 由 OpenAPI 重新生成类型"
	@echo "make run       # 本地启动（默认 127.0.0.1:8001）"

build:
	$(GO) build ./...

test:
	$(GO) test ./...

vet:
	$(GO) vet ./...

fmt:
	$(GO) fmt ./...

# 重新生成 OpenAPI 模型。
#
# 前置：契约基线必须先与后端一致（cd front && pnpm run openapi:check）。
# 顺序不能反：先改后端 → 更新 front/openapi.json → 生成 Go 类型，
# 否则 Go 侧会拿到一份旧的契约。
generate:
	@test -x "$(OAPI_CODEGEN)" || { echo "缺少 oapi-codegen，请先安装："; echo "  go install github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen@v2.8.0"; exit 1; }
	$(OAPI_CODEGEN) -config oapi-codegen.yaml $(OPENAPI_SPEC)
	$(GO) fmt ./internal/oapi/...

run:
	$(GO) run ./cmd/api

clean:
	$(GO) clean ./...
