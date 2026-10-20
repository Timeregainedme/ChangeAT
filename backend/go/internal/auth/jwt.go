// Package auth 负责 JWT 校验。
//
// 与 Python 侧必须逐项一致，否则切流后同一批用户会在两套服务之间出现
// 「一会儿能登录、一会儿 401」的错乱：
//   - 算法：HS256
//   - 密钥：JWT_SECRET（同一份环境变量）
//   - 载荷：`sub` 为字符串形式的用户 ID
//   - 过期：`exp` 由 Python 签发，Go 只校验不签发
package auth

import (
	"errors"
	"fmt"
	"strconv"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

// ErrInvalidToken 表示令牌缺失、签名不符或已过期。
//
// 刻意不区分具体原因：向客户端区分「过期」与「伪造」会帮助攻击者判断
// 密钥是否猜对，而业务上两者的处理完全一样（要求重新登录）。
var ErrInvalidToken = errors.New("invalid token")

// Claims 是校验通过后的最小载荷。
type Claims struct {
	UserID int
}

// ParseToken 校验令牌并取出用户 ID。
//
// 只接受 HS256：`jwt.WithValidMethods` 会拒绝 `alg: none` 与 RS256，
// 后者是经典的算法混淆攻击面（攻击者用公钥当 HMAC 密钥签名）。
func ParseToken(secret, token string) (Claims, error) {
	if secret == "" {
		return Claims{}, ErrInvalidToken
	}

	parsed, err := jwt.Parse(
		token,
		func(t *jwt.Token) (any, error) {
			if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
				return nil, fmt.Errorf("unexpected signing method: %v", t.Header["alg"])
			}
			return []byte(secret), nil
		},
		jwt.WithValidMethods([]string{jwt.SigningMethodHS256.Alg()}),
		jwt.WithExpirationRequired(),
		jwt.WithLeeway(30*time.Second),
	)
	if err != nil || !parsed.Valid {
		return Claims{}, ErrInvalidToken
	}

	claims, ok := parsed.Claims.(jwt.MapClaims)
	if !ok {
		return Claims{}, ErrInvalidToken
	}
	sub, _ := claims["sub"].(string)
	if sub == "" {
		return Claims{}, ErrInvalidToken
	}
	userID, err := strconv.Atoi(sub)
	if err != nil || userID <= 0 {
		return Claims{}, ErrInvalidToken
	}

	return Claims{UserID: userID}, nil
}
