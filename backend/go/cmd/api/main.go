// Command api 是 Go 控制面的入口。
//
// 当前阶段（P2-1）只提供健康检查，目的是先把「进程能起来、配置能读到、
// 数据库能连上、日志能落地」这条链路验证通，再谈接管业务接口。
// 切流前它跑在 8001 端口，Nginx 仍把全部流量给 Python（8000）。
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/timeregainedme/dyeingtime/backend/go/internal/config"
	"github.com/timeregainedme/dyeingtime/backend/go/internal/db"
	"github.com/timeregainedme/dyeingtime/backend/go/internal/server"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	}))
	slog.SetDefault(logger)

	if err := run(logger); err != nil {
		logger.Error("api exited with error", "error", err)
		os.Exit(1)
	}
}

// run 完成「加载配置 → 连库 → 起服务 → 优雅关闭」的完整生命周期。
//
// 返回值而非在内部 os.Exit：便于测试直接调用并断言错误，也让 main 保持极薄。
func run(logger *slog.Logger) error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}

	dsn, err := config.ParseMySQLDSN(cfg.DatabaseURL)
	if err != nil {
		return err
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	pool, err := db.Open(ctx, dsn, cfg.DBMaxOpenConns, cfg.DBMaxIdleConns)
	if err != nil {
		return err
	}
	defer func() { _ = pool.Close() }()

	router := server.NewRouter(server.Deps{Logger: logger, DB: pool, JWTSecret: cfg.JWTSecret})

	srv := &http.Server{
		Addr:              cfg.HTTPAddr,
		Handler:           router,
		ReadHeaderTimeout: 10 * time.Second,
		// 不设 WriteTimeout：业务接口将来会包含 SSE 与文件流式下载，
		// 全局写超时会把这些长连接掐断。改用 ReadHeaderTimeout 防慢速攻击。
		IdleTimeout: 120 * time.Second,
	}

	serveErr := make(chan error, 1)
	go func() {
		logger.Info("go control-plane listening",
			"addr", cfg.HTTPAddr,
			"env", cfg.EnvName,
		)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			serveErr <- err
			return
		}
		serveErr <- nil
	}()

	select {
	case err := <-serveErr:
		return err
	case <-ctx.Done():
		logger.Info("shutdown signal received")
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), cfg.ShutdownTimeout)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		return err
	}
	logger.Info("go control-plane stopped")
	return nil
}
