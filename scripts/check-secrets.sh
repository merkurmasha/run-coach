#!/usr/bin/env bash
# Run before every commit: fails if a real .env, API key, or token is about
# to be committed. Wire it up with: git config core.hooksPath scripts/hooks
# or call it from a pre-commit hook.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

fail=0

staged() {
  git diff --cached --name-only --diff-filter=ACM
}

if staged | grep -qx '\.env$'; then
  echo "check-secrets: .env is staged for commit. It must stay local." >&2
  fail=1
fi

if staged | grep -qE '^data/'; then
  echo "check-secrets: files under data/ are staged. That directory is user data, not code." >&2
  fail=1
fi

# Common secret shapes: long hex/base64-ish tokens assigned to KEY= style vars.
pattern='(API_KEY|TOKEN|SECRET|PASSWORD)\s*=\s*[A-Za-z0-9_\-\.]{16,}'
while IFS= read -r file; do
  [ -f "$file" ] || continue
  if git diff --cached -- "$file" | grep -E '^\+' | grep -Ev '^\+\+\+' | grep -qiE "$pattern"; then
    echo "check-secrets: possible secret literal added in $file" >&2
    fail=1
  fi
done < <(staged)

if [ "$fail" -ne 0 ]; then
  echo "check-secrets: blocked commit. Remove the secret or unstage the file." >&2
  exit 1
fi

echo "check-secrets: ok"
