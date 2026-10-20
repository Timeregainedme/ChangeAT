// Package db 负责 MySQL 连接池。
//
// 与控制面的定位相配：Go 只做「薄资源」的增删改查与状态查询，
// 因此连接池刻意开得小，避免和 Python worker 抢连接。
package db

import (
	"context"
	"database/sql"
	"fmt"
	"time"

	_ "github.com/go-sql-driver/mysql"
)

// Open 建立 MySQL 连接池并做一次探活。
//
// 为什么必须 Ping：`sql.Open` 是懒加载，不建立任何连接；
// 如果不在启动时探活，第一次真实请求才会暴露「密码错了 / 库不存在」，
// 而此时进程已经被健康检查标记为 ready。
func Open(ctx context.Context, dsn string, maxOpen, maxIdle int) (*sql.DB, error) {
	pool, err := sql.Open("mysql", dsn)
	if err != nil {
		return nil, fmt.Errorf("打开数据库连接池失败: %w", err)
	}

	pool.SetMaxOpenConns(maxOpen)
	pool.SetMaxIdleConns(maxIdle)
	// 略小于 MySQL 默认 wait_timeout（8h），避免拿到已被服务端关闭的连接。
	pool.SetConnMaxLifetime(30 * time.Minute)
	pool.SetConnMaxIdleTime(5 * time.Minute)

	pingCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	if err := pool.PingContext(pingCtx); err != nil {
		_ = pool.Close()
		return nil, fmt.Errorf("数据库探活失败: %w", err)
	}

	return pool, nil
}
