#!/usr/bin/env bash
set -uo pipefail
cd /srv/dyeingtime

echo "════════ 1. 服务器本地 git 历史里所有 .env 相关文件 ════════"
git log --all --pretty=format:'%h %ci %s' --name-only -- 'backend/.env*' | head -40

echo
echo "════════ 2. 当前 .git 里是否还能读到明文（dangling 提交）════════"
for c in $(git fsck --no-reflogs --unreachable 2>/dev/null | awk '$2=="commit"{print $3}' | head -5); do
  echo "  dangling commit: $c $(git log -1 --format='%s' $c 2>/dev/null)"
done

echo
echo "════════ 3. 磁盘上散落的 .env 副本（含备份目录）════════"
ls -la /srv/dyeingtime/backend/.env* 2>/dev/null | sed 's/^/  /'
echo "  --- /srv/backup-* ---"
find /srv/backup-* -type f \( -name '*env*' -o -name '*.pw' \) 2>/dev/null | sed 's/^/  /' | head -20
echo "  --- /tmp ---"
ls -la /tmp/env.bak.* /tmp/backend.env 2>/dev/null | sed 's/^/  /' | head -10

echo
echo "════════ 4. 密钥文件的权限 ════════"
stat -c '%A %U:%G %n' /srv/dyeingtime/backend/.env /home/ubuntu/.mysql_app_pw 2>/dev/null | sed 's/^/  /'

echo
echo "════════ 5. .gitignore 是否忽略 .env ════════"
grep -nE '\.env' .gitignore | sed 's/^/  /'

echo
echo "════════ 6. 系统日志里是否出现明文密钥（抽查）════════"
journalctl -u dyeingtime-api --since "7 days ago" --no-pager 2>/dev/null | grep -cE 'sk-[A-Za-z0-9]{20,}|GOCSPX-|AKIA[0-9A-Z]{16}' | sed 's/^/  api 日志命中数: /'
