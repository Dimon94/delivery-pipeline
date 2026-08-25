#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_NAME="delivery-pipeline"
CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
AGENTS_HOME_DIR="${AGENTS_HOME:-$HOME/.agents}"
CLAUDE_HOME_DIR="${CLAUDE_HOME:-$HOME/.claude}"
PI_HOME_DIR="${PI_HOME:-$HOME/.pi}"
TARGET="codex"
WITH_HOOKS=1

usage() {
  cat <<EOF
Usage: ./scripts/install.sh [--target codex|claude|pi|all] [--no-hooks]

Default target: codex

Also installs the repo's pre-commit gate (scripts/hooks/pre-commit -> .git/hooks)
so a red validator refuses the commit. Pass --no-hooks to skip.

Installs $SKILL_NAME and ticket-sizing to one or both, plus delivery-pipeline-pi to pi (all targets symlink to this checkout):
  \${CODEX_HOME:-~/.codex}/skills/$SKILL_NAME
  \${CODEX_HOME:-~/.codex}/skills/ticket-sizing
  \${CLAUDE_HOME:-~/.claude}/skills/$SKILL_NAME
  \${CLAUDE_HOME:-~/.claude}/skills/ticket-sizing
  ~/.pi/agent/skills/delivery-pipeline-pi

Ends with a non-blocking dependency-availability diagnostic. Owners resolve at
runtime via references/owner-skill-resolution.md; no local copies required.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --no-hooks)
      WITH_HOOKS=0
      ;;
    --target)
      [ "$#" -ge 2 ] || { echo "--target requires codex, claude, pi, or all" >&2; exit 1; }
      TARGET="$2"
      shift
      ;;
    --pi)
      TARGET="pi"
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
  codex|claude|pi|all) ;;
  *)
    echo "Invalid --target: $TARGET" >&2
    usage
    exit 1
    ;;
esac

if command -v python3 >/dev/null 2>&1; then
  python3 "$ROOT/scripts/validate.py"
fi

install_hooks() {
  local source="$ROOT/scripts/hooks/pre-commit"
  local hooks_dir

  hooks_dir="$(git -C "$ROOT" rev-parse --git-path hooks 2>/dev/null)" || {
    echo "Not a Git checkout, skipping pre-commit hook install" >&2
    return 0
  }
  [ -f "$source" ] || {
    echo "Cannot find hook source at $source" >&2
    exit 1
  }

  mkdir -p "$hooks_dir"
  # Symlink so the hook tracks the checkout instead of going stale after edits.
  ln -sf "$source" "$hooks_dir/pre-commit"
  chmod +x "$source"

  echo "Installed pre-commit gate to $hooks_dir/pre-commit -> $source"
}

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

install_pi() {
  local source="$ROOT/skills/delivery-pipeline-pi"
  local dest="$PI_HOME_DIR/agent/skills/delivery-pipeline-pi"

  [ -f "$source/SKILL.md" ] || {
    echo "Cannot find bundled pi skill at $source" >&2
    exit 1
  }

  rm -rf "$dest"
  mkdir -p "$(dirname "$dest")"
  ln -s "$source" "$dest"

  echo "Symlinked pi delivery-pipeline-pi to $dest -> $source"
}

install_claude_pane_dispatch() {
  local source="$ROOT/claude/skills/pane-dispatch"
  local dest="$CLAUDE_HOME_DIR/skills/pane-dispatch"

  [ -f "$source/SKILL.md" ] || {
    echo "Cannot find bundled Claude pane-dispatch skill at $source" >&2
    exit 1
  }

  rm -rf "$dest"
  mkdir -p "$(dirname "$dest")"
  ln -s "$source" "$dest"

  echo "Symlinked Claude pane-dispatch to $dest -> $source"
}

install_codex_ticket_sizing() {
  local source="$ROOT/skills/ticket-sizing"
  local dest="$CODEX_HOME_DIR/skills/ticket-sizing"

  [ -f "$source/SKILL.md" ] || {
    echo "Cannot find bundled Codex ticket-sizing skill at $source" >&2
    exit 1
  }

  rm -rf "$dest"
  mkdir -p "$(dirname "$dest")"
  ln -s "$source" "$dest"

  echo "Symlinked Codex ticket-sizing to $dest -> $source"
}

install_claude_ticket_sizing() {
  local source="$ROOT/claude/skills/ticket-sizing"
  local dest="$CLAUDE_HOME_DIR/skills/ticket-sizing"

  [ -f "$source/SKILL.md" ] || {
    echo "Cannot find bundled Claude ticket-sizing skill at $source" >&2
    exit 1
  }

  rm -rf "$dest"
  mkdir -p "$(dirname "$dest")"
  ln -s "$source" "$dest"

  echo "Symlinked Claude ticket-sizing to $dest -> $source"
}

# Diagnostic only, never blocks: owners reach workers as absolute SKILL.md
# paths resolved by the dispatcher (references/owner-skill-resolution.md), so
# no local copy is a prerequisite. Mirrors the filesystem probes of that
# resolution chain (plugin cache, CODEX_HOME, AGENTS_HOME); the session
# catalog step is only visible to the runtime, not to a shell script.
report_owner_availability() {
  echo "Dependency availability (diagnostic only, never blocks):"
  if ! command -v python3 >/dev/null 2>&1; then
    echo "  skipped: python3 not available to read skill-bundle.json requires"
    return 0
  fi
  local names
  names="$(python3 -c '
import json
with open("'"$ROOT"'/skill-bundle.json") as fh:
    for item in json.load(fh)["requires"]:
        print(item["name"])
')" || {
    echo "  skipped: cannot read requires from skill-bundle.json"
    return 0
  }
  local name found
  for name in $names; do
    found=()
    compgen -G "$CLAUDE_HOME_DIR/plugins/cache/*/mattpocock-skills/*/skills/*/$name/SKILL.md" >/dev/null && found+=("plugin-cache")
    [ -f "$CLAUDE_HOME_DIR/skills/$name/SKILL.md" ] && found+=("claude-home")
    [ -f "$CODEX_HOME_DIR/skills/$name/SKILL.md" ] && found+=("codex-home")
    [ -f "$AGENTS_HOME_DIR/skills/$name/SKILL.md" ] && found+=("agents-home")
    if [ "${#found[@]}" -gt 0 ]; then
      printf '  %s\t%s\n' "$name" "$(IFS=,; echo "${found[*]}")"
    else
      printf '  %s\tMISSING\n' "$name"
    fi
  done
  command -v herdr >/dev/null 2>&1 \
    && printf '  %s\t%s\n' "herdr CLI" "$(command -v herdr)" \
    || printf '  %s\tMISSING\n' "herdr CLI"
}

case "$TARGET" in
  codex)
    install_codex
    install_codex_ticket_sizing
    ;;
  claude)
    install_claude
    install_claude_pane_dispatch
    install_claude_ticket_sizing
    ;;
  pi)
    install_pi
    ;;
  all)
    install_codex
    install_codex_ticket_sizing
    install_claude
    install_claude_pane_dispatch
    install_claude_ticket_sizing
    install_pi
    ;;
esac

if [ "$WITH_HOOKS" -eq 1 ]; then
  install_hooks
fi

report_owner_availability
