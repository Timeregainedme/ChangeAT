package auth

import (
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

const testSecret = "unit-test-secret"

// sign 生成一个 HS256 令牌，用于构造各种形态的输入。
func sign(t *testing.T, secret string, claims jwt.MapClaims) string {
	t.Helper()
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	signed, err := token.SignedString([]byte(secret))
	if err != nil {
		t.Fatalf("签发测试令牌失败: %v", err)
	}
	return signed
}

// TestParseTokenValid 验证正常令牌能取出用户 ID。
func TestParseTokenValid(t *testing.T) {
	token := sign(t, testSecret, jwt.MapClaims{
		"sub": "42",
		"exp": time.Now().Add(time.Hour).Unix(),
	})

	claims, err := ParseToken(testSecret, token)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if claims.UserID != 42 {
		t.Fatalf("UserID = %d, want 42", claims.UserID)
	}
}

// TestParseTokenRejects 覆盖所有应拒绝的形态。
//
// 这些分支就是「登录态校验」的全部安全边界，任何一条放松都会让伪造令牌通过。
func TestParseTokenRejects(t *testing.T) {
	t.Run("过期令牌", func(t *testing.T) {
		token := sign(t, testSecret, jwt.MapClaims{
			"sub": "1",
			"exp": time.Now().Add(-time.Hour).Unix(),
		})
		if _, err := ParseToken(testSecret, token); err == nil {
			t.Fatal("过期令牌必须被拒绝")
		}
	})

	t.Run("签名不符", func(t *testing.T) {
		token := sign(t, "another-secret", jwt.MapClaims{
			"sub": "1",
			"exp": time.Now().Add(time.Hour).Unix(),
		})
		if _, err := ParseToken(testSecret, token); err == nil {
			t.Fatal("错误密钥签发的令牌必须被拒绝")
		}
	})

	t.Run("缺少 exp", func(t *testing.T) {
		token := sign(t, testSecret, jwt.MapClaims{"sub": "1"})
		if _, err := ParseToken(testSecret, token); err == nil {
			t.Fatal("缺少 exp 的令牌必须被拒绝")
		}
	})

	t.Run("sub 非数字", func(t *testing.T) {
		token := sign(t, testSecret, jwt.MapClaims{
			"sub": "alice",
			"exp": time.Now().Add(time.Hour).Unix(),
		})
		if _, err := ParseToken(testSecret, token); err == nil {
			t.Fatal("sub 非数字必须被拒绝")
		}
	})

	t.Run("空密钥", func(t *testing.T) {
		token := sign(t, testSecret, jwt.MapClaims{
			"sub": "1",
			"exp": time.Now().Add(time.Hour).Unix(),
		})
		if _, err := ParseToken("", token); err == nil {
			t.Fatal("未配置 JWT_SECRET 时必须拒绝一切令牌")
		}
	})

	t.Run("alg=none", func(t *testing.T) {
		// 算法混淆攻击的最小复现：不签名，把 alg 直接写成 none。
		token := jwt.NewWithClaims(jwt.SigningMethodNone, jwt.MapClaims{
			"sub": "1",
			"exp": time.Now().Add(time.Hour).Unix(),
		})
		signed, err := token.SignedString(jwt.UnsafeAllowNoneSignatureType)
		if err != nil {
			t.Fatalf("构造 none 令牌失败: %v", err)
		}
		if _, err := ParseToken(testSecret, signed); err == nil {
			t.Fatal("alg=none 必须被拒绝")
		}
	})
}
