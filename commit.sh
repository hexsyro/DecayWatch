#!/usr/bin/env bash
# ============================================================================
# commit.sh — Bug checks + safe commit workflow
# ============================================================================
# Usage:
#   ./commit.sh "message"   — check, commit & push
#   ./commit.sh             — prompt for message
#
# Env overrides:
#   SKIP_CONFLICT_CHECK=true   bypass conflict marker check
#   RUN_LINT=false       skip ruff
#   RUN_TYPECHECK=false  skip pyright
#   RUN_TESTS=false      skip pytest
#   RUN_PUSH=false       skip push
#   STRICT=false         allow lint/test warnings
#   SKIP=a,b             comma list: lint,typecheck,test
# ============================================================================

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

RUN_LINT="${RUN_LINT:-true}"
RUN_TYPECHECK="${RUN_TYPECHECK:-true}"
RUN_TESTS="${RUN_TESTS:-true}"
RUN_PUSH="${RUN_PUSH:-true}"
STRICT="${STRICT:-true}"
SKIP_CONFLICT_CHECK="${SKIP_CONFLICT_CHECK:-false}"
SKIP="${SKIP:-}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
pass()  { echo -e " ${GREEN}✓${NC} $1"; }
fail()  { echo -e " ${RED}✖${NC} $1"; }
warn()  { echo -e " ${YELLOW}⚠${NC} $1"; }
info()  { echo -e " ${CYAN}→${NC} $1"; }
die()   { fail "$1"; exit 1; }
skip()  { [[ ",$SKIP," == *",$1,"* ]]; }

MSG="${MSG:-${*:-}}"
ensure_repo_root() {
    local repo_root
    repo_root=$(git rev-parse --show-toplevel 2>/dev/null) \
        || die "Not inside a Git repository"
    [ "$(cd "$repo_root" && pwd)" = "$ROOT" ] \
        || die "Run this script from the Git repository root: $repo_root"
}

BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")

# ── Install pre-commit hook (if the repo ships one) ─────────────────────────
install_hook() {
    local src=".githooks/pre-commit" dst=".git/hooks/pre-commit"
    [ -f "$src" ] || return 0
    if [ ! -f "$dst" ] || ! diff -q "$src" "$dst" &>/dev/null; then
        cp "$src" "$dst" 2>/dev/null || return 0
        chmod +x "$dst"
        pass "Pre-commit hook installed"
    fi
}

# ── Conflict markers ────────────────────────────────────────────────────────
check_conflicts() {
    local found=0 f
    local files
    files=$(git diff --name-only --diff-filter=ACM 2>/dev/null || true)
    for f in $files; do
        if [ -f "$f" ] && grep -qP '^<<<<<<< |^=======$|^>>>>>>> ' "$f" 2>/dev/null; then
            fail "Conflict markers in: $f"; found=1
        fi
    done
    while IFS= read -r f; do
        if [ -f "$f" ] && grep -qP '^<<<<<<< |^=======$|^>>>>>>> ' "$f" 2>/dev/null; then
            fail "Conflict markers in untracked: $f"; found=1
        fi
    done < <(git ls-files --others --exclude-standard 2>/dev/null || true)
    [ "$found" -eq 1 ] && die "Resolve conflict markers first"
    pass "No conflict markers"
}

# ── Python discovery (repo .venv) ───────────────────────────────────────────
PY=""
find_python() {
    local probe
    for probe in "$ROOT/.venv/bin/python" "$ROOT/.venv/Scripts/python" python3 python; do
        if [ -x "$probe" ] || command -v "$probe" &>/dev/null; then
            if $probe -c "import pytest" &>/dev/null 2>&1; then
                PY="$probe"; return 0
            fi
        fi
    done
    if command -v py &>/dev/null && py -3 -c "import pytest" &>/dev/null 2>&1; then
        PY="py -3"; return 0
    fi
    return 1
}

# ── Bug checks: Lint (ruff) ─────────────────────────────────────────────────
run_lint() {
    skip lint && { pass "ruff — skipped (SKIP=lint)"; return 0; }
    local failed=0
    if command -v ruff &>/dev/null; then
        if ruff check src tests --quiet; then pass "ruff — lint OK"
        else warn "ruff — lint issues"; [ "$STRICT" = "true" ] && failed=1; fi
    elif find_python && $PY -m ruff check src tests --quiet 2>/dev/null; then
        pass "ruff — lint OK"
    else
        warn "ruff — not installed, skipped"
    fi
    [ "$failed" -eq 1 ] && die "Lint failed (STRICT)"
    return 0
}

# ── Bug checks: Typecheck (pyright) ─────────────────────────────────────────
run_typecheck() {
    skip typecheck && { pass "pyright — skipped (SKIP=typecheck)"; return 0; }
    local failed=0
    if command -v pyright &>/dev/null; then
        if pyright src; then pass "pyright — types OK"
        else warn "pyright — type errors"; [ "$STRICT" = "true" ] && failed=1; fi
    elif find_python && $PY -m pyright src 2>/dev/null; then
        pass "pyright — types OK"
    else
        warn "pyright — not installed, skipped"
    fi
    [ "$failed" -eq 1 ] && die "Typecheck failed (STRICT)"
    return 0
}

# ── Bug checks: Tests ───────────────────────────────────────────────────────
run_tests() {
    skip test && { pass "pytest — skipped (SKIP=test)"; return 0; }
    local failed=0
    if find_python; then
        if $PY -m pytest -q; then
            pass "pytest — tests OK"
        else
            warn "pytest — tests failed"; [ "$STRICT" = "true" ] && failed=1
        fi
    else
        warn "pytest — skipped (no Python with pytest)"
    fi
    [ "$failed" -eq 1 ] && die "Tests failed (STRICT)"
    return 0
}

# ── Commit & Push ───────────────────────────────────────────────────────────
do_commit() {
    if [ -n "$MSG" ]; then
        git commit -m "$MSG" || die "Commit failed"
    else
        local default="update: $(date +%Y-%m-%d)"
        read -r -p "Commit message [$default]: " input
        local msg="${input:-$default}"
        git commit -m "$msg" || die "Commit failed"
        MSG="$msg"
    fi
    pass "Committed: ${MSG}"
}

do_push() {
    local remote=""
    if git remote 2>/dev/null | grep -qx origin; then remote="origin"
    else remote=$(git remote 2>/dev/null | head -1); fi
    [ -z "$remote" ] && { warn "No remote — skipping push"; return; }

    git pull --rebase --autostash "$remote" "$BRANCH" 2>/dev/null || warn "pull --rebase failed"
    if git push -u "$remote" "$BRANCH" 2>/dev/null; then
        pass "Pushed to ${remote}/${BRANCH}"
    else
        warn "Push failed — check remote and try: git push --force-with-lease $remote $BRANCH"
    fi
}

# ============================================================================
#  MAIN
# ============================================================================
echo ""
echo -e "${CYAN}━━━ DecayWatch — Safe Commit ━━━${NC}"
echo ""

ensure_repo_root
install_hook

[ "$SKIP_CONFLICT_CHECK" != "true" ] && { info "Checking conflicts..."; check_conflicts; }

info "Staging changes..."
git add -A
pass "Changes staged"

[ "$RUN_LINT" = "true" ]      && { info "Checking for bugs (lint)...";  run_lint; }
[ "$RUN_TYPECHECK" = "true" ] && { info "Checking for bugs (types)..."; run_typecheck; }
[ "$RUN_TESTS" = "true" ]     && { info "Checking for bugs (tests)..."; run_tests; }

echo ""
pass "All checks passed"

info "Committing..."
do_commit
[ "$RUN_PUSH" = "true" ] && do_push

echo ""
echo -e "${GREEN}━━━ Done ━━━${NC}"
echo ""
