#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_NAME="wayfinder-implement-orchestrator"
CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
AGENTS_HOME_DIR="${AGENTS_HOME:-$HOME/.agents}"
CLAUDE_HOME_DIR="${CLAUDE_HOME:-$HOME/.claude}"
SKIP_DEPS=0
TARGET="codex"

usage() {
  cat <<EOF
Usage: ./scripts/install.sh [--target codex|claude|all] [--skip-deps-check]

Default target: codex

Installs $SKILL_NAME to one or both (all targets symlink to this checkout):
  \${CODEX_HOME:-~/.codex}/skills/$SKILL_NAME
  \${CLAUDE_HOME:-~/.claude}/skills/$SKILL_NAME

Codex dependency discovery checks both:
  \${CODEX_HOME:-~/.codex}/skills
  \${AGENTS_HOME:-~/.agents}/skills
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --skip-deps-check)
      SKIP_DEPS=1
      ;;
    --target)
      [ "$#" -ge 2 ] || { echo "--target requires codex, claude, or all" >&2; exit 1; }
      TARGET="$2"
      shift
      ;;
    --codex)
      TARGET="codex"
      ;;
    --claude)
      TARGET="claude"
      ;;
    --all)
      TARGET="all"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
  shift
done

case "$TARGET" in
  codex|claude|all) ;;
  *)
    echo "Invalid --target: $TARGET" >&2
    usage
    exit 1
    ;;
esac

if command -v python3 >/dev/null 2>&1; then
  python3 "$ROOT/scripts/validate.py"
fi

install_codex() {
  local source="$ROOT/skills/$SKILL_NAME"
  local dest="$CODEX_HOME_DIR/skills/$SKILL_NAME"

  [ -f "$source/SKILL.md" ] || {
    echo "Cannot find bundled Codex skill at $source" >&2
    exit 1
  }

  rm -rf "$dest"
  mkdir -p "$(dirname "$dest")"
  ln -s "$source" "$dest"

  echo "Symlinked Codex $SKILL_NAME to $dest -> $source"
}

install_claude() {
  local skill_source="$ROOT/claude/skills/$SKILL_NAME"
  local skill_dest="$CLAUDE_HOME_DIR/skills/$SKILL_NAME"

  [ -f "$skill_source/SKILL.md" ] || {
    echo "Cannot find bundled Claude skill at $skill_source" >&2
    exit 1
  }

  rm -rf "$skill_dest"
  mkdir -p "$(dirname "$skill_dest")"
  ln -s "$skill_source" "$skill_dest"

  echo "Symlinked Claude $SKILL_NAME to $skill_dest -> $skill_source"
}

has_codex_dependency() {
  local dep="$1"
  local root
  for root in "$CODEX_HOME_DIR/skills" "$AGENTS_HOME_DIR/skills"; do
    [ -f "$root/$dep/SKILL.md" ] && return 0
  done
  return 1
}

if [ "$SKIP_DEPS" -eq 0 ] && { [ "$TARGET" = "codex" ] || [ "$TARGET" = "all" ]; }; then
  missing=()
  for dep in implement; do
    has_codex_dependency "$dep" || missing+=("$dep")
  done

  if [ "${#missing[@]}" -gt 0 ]; then
    echo "Missing Matt Pocock skill dependencies:" >&2
    printf '  - %s\n' "${missing[@]}" >&2
    echo "Checked:" >&2
    echo "  - $CODEX_HOME_DIR/skills" >&2
    echo "  - $AGENTS_HOME_DIR/skills" >&2
    echo "Install them with: npx skills@latest add mattpocock/skills" >&2
    echo "Or rerun with --skip-deps-check only if another harness supplies them." >&2
    exit 1
  fi
fi

case "$TARGET" in
  codex)
    install_codex
    ;;
  claude)
    install_claude
    ;;
  all)
    install_codex
    install_claude
    ;;
esac
