// Package config 负责加载 Go 控制面的运行配置。
//
// 设计原则：所有配置只从环境变量读取，不在 Go 侧引入第二份配置文件。
// 生产环境由 systemd 的 EnvironmentFile 注入 backend/.env（与 Python 共用同一份），
// 这样「切流量前后两个进程看到的是同一套配置」，不会出现 Go 连了另一个库的情况。
package config

import (
	"bufio"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

// Config 是控制面的全部运行参数。
type Config struct {
	// HTTPAddr 监听地址，默认 127.0.0.1:8001（避开 Python 的 8000）。
	HTTPAddr string
	// DatabaseURL 沿用 Python 的 DATABASE_URL 格式（mysql+aiomysql://...），
	// 由 ParseMySQLDSN 转成 driver 能用的 DSN。
	DatabaseURL string
	// JWTSecret 用于校验前端带来的 token，必须与 Python 一致。
	JWTSecret string
	// EnvName 仅用于日志区分（dev / prod）。
	EnvName string
	// ShutdownTimeout 优雅关闭的等待上限。
	ShutdownTimeout time.Duration
	// DBMaxOpenConns / DBMaxIdleConns 控制连接池。
	// 默认值刻意压低：这台机器只有 2 vCPU / 4 GiB，
	// Go 侧抢走太多连接会让 Python worker 排队。
	DBMaxOpenConns int
	DBMaxIdleConns int
}

// Load 从环境变量构造配置。
//
// 找不到 backend/.env 时不报错：容器与 systemd 都已经把变量注入环境，
// .env 只用于本地 `go run` 的便利。
func Load() (*Config, error) {
	loadDotEnvIfPresent()

	cfg := &Config{
		HTTPAddr:        getenv("GO_API_ADDR", "127.0.0.1:8001"),
		DatabaseURL:     os.Getenv("DATABASE_URL"),
		JWTSecret:       os.Getenv("JWT_SECRET"),
		EnvName:         getenv("APP_ENV", "dev"),
		ShutdownTimeout: durationFromEnv("GO_API_SHUTDOWN_TIMEOUT", 10*time.Second),
		DBMaxOpenConns:  intFromEnv("GO_API_DB_MAX_OPEN", 10),
		DBMaxIdleConns:  intFromEnv("GO_API_DB_MAX_IDLE", 5),
	}

	if cfg.DatabaseURL == "" {
		return nil, fmt.Errorf("缺少 DATABASE_URL：Go 控制面与 Python 共用同一个数据库")
	}
	if cfg.JWTSecret == "" {
		// 不在这里阻止启动：/health 等无鉴权端点仍应可用，
		// 但受保护路由必须失败。具体判定放在 auth 中间件里。
		fmt.Fprintln(os.Stderr, "[warn] JWT_SECRET 为空：受保护接口将一律返回 401")
	}

	return cfg, nil
}

// getenv 返回环境变量，为空时使用默认值。
func getenv(key, fallback string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return fallback
}

// intFromEnv 读取整型环境变量，非法值回退默认。
func intFromEnv(key string, fallback int) int {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return fallback
	}
	v, err := strconv.Atoi(raw)
	if err != nil {
		return fallback
	}
	return v
}

// durationFromEnv 读取形如 "10s" 的时长，非法值回退默认。
func durationFromEnv(key string, fallback time.Duration) time.Duration {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return fallback
	}
	v, err := time.ParseDuration(raw)
	if err != nil {
		return fallback
	}
	return v
}

// loadDotEnvIfPresent 在本地开发时补读 backend/.env。
//
// 行为约定：
// - 文件不存在 → 静默返回（生产由 systemd/容器注入，不依赖该文件）；
// - 已存在的环境变量优先，不覆盖（保证外部注入的配置总是权威）。
func loadDotEnvIfPresent() {
	path := os.Getenv("GO_API_ENV_FILE")
	if path == "" {
		path = ".env"
	}
	file, err := os.Open(path)
	if err != nil {
		return
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		key = strings.TrimSpace(key)
		value = strings.Trim(strings.TrimSpace(value), `"'`)
		if key == "" || os.Getenv(key) != "" {
			continue
		}
		_ = os.Setenv(key, value)
	}
}

// ParseMySQLDSN 把 Python 风格的 DATABASE_URL 转成 go-sql-driver 的 DSN。
//
// 输入示例：mysql+aiomysql://user:pass@127.0.0.1:3306/dyeingtime
// 输出示例：user:pass@tcp(127.0.0.1:3306)/dyeingtime?parseTime=true&loc=UTC
//
// 为什么要自己转：Go 侧只替换驱动名是不够的（Python 的 scheme 与 DSN 语法都不同），
// 而让运维为 Go 单独配一份 DSN 会引入「两边连到不同库」的风险。
func ParseMySQLDSN(raw string) (string, error) {
	const marker = "://"
	idx := strings.Index(raw, marker)
	if idx < 0 {
		return "", fmt.Errorf("DATABASE_URL 格式不合法，缺少 ://")
	}
	rest := raw[idx+len(marker):]

	// 拆分 userinfo 与 host/path，注意密码里可能含 @，因此从最后一个 @ 切分。
	at := strings.LastIndex(rest, "@")
	slash := strings.Index(rest, "/")
	if at < 0 || slash < 0 || at > slash {
		return "", fmt.Errorf("DATABASE_URL 格式不合法，应为 user:pass@host:port/db")
	}
	userinfo := rest[:at]
	hostport := rest[at+1 : slash]
	dbname := rest[slash+1:]
	if hostport == "" || dbname == "" {
		return "", fmt.Errorf("DATABASE_URL 缺少主机或库名")
	}
	if !strings.Contains(hostport, ":") {
		hostport += ":3306"
	}

	// parseTime=true：让 DATETIME 直接映射到 time.Time，避免手工解析字符串；
	// loc=UTC：与 Python 侧 timezone=True 的行为对齐。
	return fmt.Sprintf("%s@tcp(%s)/%s?parseTime=true&loc=UTC&charset=utf8mb4", userinfo, hostport, dbname), nil
}
