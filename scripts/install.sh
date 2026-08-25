#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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

Installs one canonical delivery-pipeline and delivery-pipeline-setup into each selected CLI home.
Codex also receives delivery-pipeline-codex-app; Claude keeps pane-dispatch compatibility support.
All skills symlink to this checkout. The pre-commit validator is installed unless --no-hooks is used.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --no-hooks) WITH_HOOKS=0 ;;
    --target)
      [ "$#" -ge 2 ] || { echo "--target requires codex, claude, pi, or all" >&2; exit 1; }
      TARGET="$2"; shift ;;
    --codex) TARGET="codex" ;;
    --claude) TARGET="claude" ;;
    --pi) TARGET="pi" ;;
    --all) TARGET="all" ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
  shift
done

case "$TARGET" in codex|claude|pi|all) ;; *) echo "Invalid --target: $TARGET" >&2; exit 1 ;; esac

command -v python3 >/dev/null 2>&1 && python3 "$ROOT/scripts/validate.py"

link_skill() {
  local source="$1" dest="$2" label="$3"
  [ -f "$source/SKILL.md" ] || { echo "Cannot find $label at $source" >&2; exit 1; }
  rm -rf "$dest"
  mkdir -p "$(dirname "$dest")"
  ln -s "$source" "$dest"
  echo "Symlinked $label to $dest -> $source"
}

install_codex() {
  link_skill "$ROOT/skills/delivery-pipeline" \
    "$CODEX_HOME_DIR/skills/delivery-pipeline" "Codex delivery-pipeline"
  link_skill "$ROOT/skills/delivery-pipeline-setup" \
    "$CODEX_HOME_DIR/skills/delivery-pipeline-setup" "Codex delivery-pipeline-setup"
  link_skill "$ROOT/skills/delivery-pipeline-codex-app" \
    "$CODEX_HOME_DIR/skills/delivery-pipeline-codex-app" "Codex App shell"
  link_skill "$ROOT/skills/ticket-sizing" \
    "$CODEX_HOME_DIR/skills/ticket-sizing" "Codex ticket-sizing"
}

install_claude() {
  link_skill "$ROOT/skills/delivery-pipeline" \
    "$CLAUDE_HOME_DIR/skills/delivery-pipeline" "Claude canonical delivery-pipeline"
  link_skill "$ROOT/skills/delivery-pipeline-setup" \
    "$CLAUDE_HOME_DIR/skills/delivery-pipeline-setup" "Claude delivery-pipeline-setup"
  link_skill "$ROOT/claude/skills/pane-dispatch" \
    "$CLAUDE_HOME_DIR/skills/pane-dispatch" "Claude pane-dispatch compatibility"
  link_skill "$ROOT/claude/skills/ticket-sizing" \
    "$CLAUDE_HOME_DIR/skills/ticket-sizing" "Claude ticket-sizing"
}

install_pi() {
  # ADR-0004 retires the pi-specific wrapper; remove a prior installed symlink/copy.
  rm -rf "$PI_HOME_DIR/agent/skills/delivery-pipeline-pi"
  link_skill "$ROOT/skills/delivery-pipeline" \
    "$PI_HOME_DIR/agent/skills/delivery-pipeline" "pi canonical delivery-pipeline"
  link_skill "$ROOT/skills/delivery-pipeline-setup" \
    "$PI_HOME_DIR/agent/skills/delivery-pipeline-setup" "pi delivery-pipeline-setup"
}

install_hooks() {
  local source="$ROOT/scripts/hooks/pre-commit" hooks_dir
  hooks_dir="$(git -C "$ROOT" rev-parse --git-path hooks 2>/dev/null)" || {
    echo "Not a Git checkout, skipping pre-commit hook install" >&2; return 0;
  }
  [ -f "$source" ] || { echo "Cannot find hook source at $source" >&2; exit 1; }
  mkdir -p "$hooks_dir"
  ln -sf "$source" "$hooks_dir/pre-commit"
  chmod +x "$source"
  echo "Installed pre-commit gate to $hooks_dir/pre-commit -> $source"
}

report_owner_availability() {
  echo "Dependency availability (diagnostic only, never blocks):"
  command -v python3 >/dev/null 2>&1 || { echo "  skipped: python3 unavailable"; return 0; }
  local name found
  while IFS= read -r name; do
    found=()
    compgen -G "$CLAUDE_HOME_DIR/plugins/cache/*/mattpocock-skills/*/skills/*/$name/SKILL.md" >/dev/null && found+=("plugin-cache")
    [ -f "$CLAUDE_HOME_DIR/skills/$name/SKILL.md" ] && found+=("claude-home")
    [ -f "$CODEX_HOME_DIR/skills/$name/SKILL.md" ] && found+=("codex-home")
    [ -f "$PI_HOME_DIR/agent/skills/$name/SKILL.md" ] && found+=("pi-home")
    [ -f "$AGENTS_HOME_DIR/skills/$name/SKILL.md" ] && found+=("agents-home")
    if [ "${#found[@]}" -gt 0 ]; then
      printf '  %s\t%s\n' "$name" "$(IFS=,; echo "${found[*]}")"
    else
      printf '  %s\tMISSING\n' "$name"
    fi
  done < <(python3 -c 'import json; print("\n".join(x["name"] for x in json.load(open("'"$ROOT"'/skill-bundle.json"))["requires"]))')
  for binary in herdr pi codex claude; do
    command -v "$binary" >/dev/null 2>&1 \
      && printf '  %s CLI\t%s\n' "$binary" "$(command -v "$binary")" \
      || printf '  %s CLI\tMISSING\n' "$binary"
  done
}

case "$TARGET" in
  codex) install_codex ;;
  claude) install_claude ;;
  pi) install_pi ;;
  all) install_codex; install_claude; install_pi ;;
esac

[ "$WITH_HOOKS" -eq 0 ] || install_hooks
report_owner_availability
