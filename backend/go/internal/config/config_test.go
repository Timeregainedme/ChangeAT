package config

import "testing"

// TestParseMySQLDSN 覆盖 Python 风格 URL 到 driver DSN 的转换。
//
// 这条转换是「两个进程连同一个库」的唯一保证点，出错会让 Go 侧静默连错库，
// 因此对常见形态（含特殊字符密码、缺省端口）都要固定住。
func TestParseMySQLDSN(t *testing.T) {
	cases := []struct {
		name string
		in   string
		want string
	}{
		{
			name: "标准形态",
			in:   "mysql+aiomysql://dyeingtime:secret@127.0.0.1:3306/dyeingtime",
			want: "dyeingtime:secret@tcp(127.0.0.1:3306)/dyeingtime?parseTime=true&loc=UTC&charset=utf8mb4",
		},
		{
			name: "缺省端口补 3306",
			in:   "mysql+aiomysql://u:p@db/dyeingtime",
			want: "u:p@tcp(db:3306)/dyeingtime?parseTime=true&loc=UTC&charset=utf8mb4",
		},
		{
			name: "密码含 @ 时按最后一个 @ 切分",
			in:   "mysql+aiomysql://u:pa@ss@127.0.0.1:3306/dyeingtime",
			want: "u:pa@ss@tcp(127.0.0.1:3306)/dyeingtime?parseTime=true&loc=UTC&charset=utf8mb4",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, err := ParseMySQLDSN(tc.in)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if got != tc.want {
				t.Fatalf("got %q, want %q", got, tc.want)
			}
		})
	}
}

// TestParseMySQLDSNRejectsInvalid 保证非法输入返回错误而不是空 DSN。
func TestParseMySQLDSNRejectsInvalid(t *testing.T) {
	for _, raw := range []string{"", "127.0.0.1:3306/dyeingtime", "mysql://u:p@host"} {
		if _, err := ParseMySQLDSN(raw); err == nil {
			t.Fatalf("expected error for %q", raw)
		}
	}
}
