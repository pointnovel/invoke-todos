#!/bin/sh
# install.sh: link the todos command and the Claude Code skill from this tree into place. Safe to re-run.
# Needs python3 3.9 or later on PATH; nothing is built or downloaded (README.md, Setup).
#
# Usage: ./install.sh [--bin DIR] [--name NAME] [--skills DIR] [--no-skill] [--config] [--force] [--dry-run] [--uninstall]
#   --bin DIR     folder for the command link (default: $HOME/.local/bin)
#   --name NAME   the command's name (default: todos; for machines where that name is taken)
#   --skills DIR  Claude Code skills folder for the skill link (default: $HOME/.claude/skills)
#   --no-skill    leave the skill link out (CLI only)
#   --config      run `todos config init` when no config exists yet, and print its path
#   --force       replace a file, or a link that points elsewhere (never a real folder)
#   --dry-run     run the checks and print each step; change nothing
#   --uninstall   remove the links that point into this tree; the tree and the config stay
set -eu

HERE=$(cd "$(dirname "$0")" && pwd -P)
BIN=$HOME/.local/bin
NAME=todos
SKILLS=$HOME/.claude/skills
SKILL=1
CONFIG=0
FORCE=0
DRY=0
UNINSTALL=0
REFUSED=0

say() { printf '%s\n' "$*"; }
warn() { printf 'install.sh: warning: %s\n' "$*" >&2; }
die() { printf 'install.sh: %s\n' "$*" >&2; exit 1; }
usage() { sed -n '5,13p' "$0" | sed 's/^# \{0,1\}//'; }
bad_usage() { printf 'install.sh: %s\n' "$*" >&2; usage >&2; exit 2; }
# Run a command, or under --dry-run only show it.
run() { if [ "$DRY" = 1 ]; then say "  would run: $*"; else "$@"; fi; }

# An absolute path, without trailing slashes, for a folder named on the command line. A leading
# "~" the caller's shell left unexpanded (as in --bin=~/bin) is matched literally on purpose.
absdir() {
  # shellcheck disable=SC2088
  case $1 in
    "~") d=$HOME ;;
    "~/"*) d=$HOME/${1#"~/"} ;;
    /*) d=$1 ;;
    *) d=$(pwd -P)/$1 ;;
  esac
  while [ "$d" != / ] && [ "${d%/}" != "$d" ]; do d=${d%/}; done
  printf '%s\n' "$d"
}

while [ $# -gt 0 ]; do
  case $1 in
    --bin) [ $# -ge 2 ] || bad_usage "--bin needs a folder"; BIN=$(absdir "$2"); shift ;;
    --bin=*) BIN=$(absdir "${1#--bin=}") ;;
    --name) [ $# -ge 2 ] || bad_usage "--name needs a name"; NAME=$2; shift ;;
    --name=*) NAME=${1#--name=} ;;
    --skills) [ $# -ge 2 ] || bad_usage "--skills needs a folder"; SKILLS=$(absdir "$2"); shift ;;
    --skills=*) SKILLS=$(absdir "${1#--skills=}") ;;
    --no-skill) SKILL=0 ;;
    --config) CONFIG=1 ;;
    --force) FORCE=1 ;;
    --dry-run) DRY=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h | --help) usage; exit 0 ;;
    *) bad_usage "unknown option: $1" ;;
  esac
  shift
done

case $NAME in '' | */* | .*) bad_usage "--name needs a plain file name, got '$NAME'" ;; esac

CMD_SRC=$HERE/todos
CMD_DST=$BIN/$NAME
SKILL_SRC=$HERE/skills/invoke-todos
SKILL_DST=$SKILLS/invoke-todos

# Each failed check prints the fix and exits 1.
preflight() {
  [ -f "$CMD_SRC" ] || die "no launcher at $CMD_SRC; run this script from the invoke-todos tree."
  [ -f "$SKILL_SRC/SKILL.md" ] || die "no skill at $SKILL_SRC/SKILL.md; the tree is incomplete."
  command -v python3 >/dev/null 2>&1 || die "python3 is not on PATH. Install Python 3.9 or later, open a new terminal and re-run."
  pyv=$(python3 -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null) || die "python3 on PATH does not run."
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null || die "todos needs Python 3.9 or later; python3 on PATH is $pyv."
  say "ok: python3 $pyv ($(command -v python3)); tree $HERE"
}

# link SRC DST: make DST a symlink to SRC. Already right: leave it. A dangling link (its target
# gone): replace it. A file, or a link to something else: refuse unless --force. A folder: refuse.
link() {
  src=$1 dst=$2
  if [ -L "$dst" ]; then
    cur=$(readlink "$dst")
    if [ "$cur" = "$src" ]; then
      say "ok, already linked: $dst -> $src"
      return 0
    elif [ ! -e "$dst" ]; then
      say "replacing a dangling link: $dst -> $cur (its target is gone)"
    elif [ "$FORCE" = 1 ]; then
      say "replacing (--force) the link $dst -> $cur"
    else
      warn "$dst is a link to $cur, not to $src; left alone. Remove it, or re-run with --force."
      REFUSED=1
      return 0
    fi
    run rm -f "$dst"
  elif [ -d "$dst" ]; then
    warn "$dst is a folder; install.sh never replaces a folder. Move it away, then re-run."
    REFUSED=1
    return 0
  elif [ -e "$dst" ]; then
    if [ "$FORCE" != 1 ]; then
      warn "$dst exists and is not a link; left alone. Remove it, or re-run with --force."
      REFUSED=1
      return 0
    fi
    say "replacing (--force) the file $dst"
    run rm -f "$dst"
  fi
  run mkdir -p "$(dirname "$dst")"
  run ln -s "$src" "$dst"
  if [ "$DRY" != 1 ]; then say "linked: $dst -> $src"; fi
}

# unlink_ours DST: remove DST if it is a link into this tree; leave anything else alone.
unlink_ours() {
  dst=$1
  if [ -L "$dst" ]; then
    cur=$(readlink "$dst")
    case $cur in
      "$HERE"/*)
        run rm -f "$dst"
        if [ "$DRY" != 1 ]; then say "removed: $dst -> $cur"; fi
        ;;
      *) say "left alone: $dst -> $cur (not a link into $HERE)" ;;
    esac
  elif [ -e "$dst" ]; then
    say "left alone: $dst (not a link)"
  else
    say "nothing to remove at $dst"
  fi
}

if [ "$DRY" = 1 ]; then say "dry run: the checks run, nothing is changed"; fi

if [ "$UNINSTALL" = 1 ]; then
  unlink_ours "$CMD_DST"
  if [ "$SKILL" = 1 ]; then unlink_ours "$SKILL_DST"; fi
  say "The tree stays at $HERE and the config where todos config path says; delete them by hand to finish."
  exit 0
fi

preflight

link "$CMD_SRC" "$CMD_DST"
if [ "$SKILL" = 1 ]; then link "$SKILL_SRC" "$SKILL_DST"; else say "skipped the skill link (--no-skill)"; fi

case ":$PATH:" in
  *":$BIN:"*) ;;
  *) warn "$BIN is not on PATH. Add it, for example with this line in your shell profile: export PATH=\"$BIN:\$PATH\"" ;;
esac

if [ "$CONFIG" = 1 ]; then
  cfgpath=$(python3 "$CMD_SRC" config path | sed 's/  (no file.*$//')
  if [ -e "$cfgpath" ]; then
    say "ok, config exists: $cfgpath"
  else
    run python3 "$CMD_SRC" config init
  fi
fi

if [ "$DRY" = 1 ]; then
  say "  would run: python3 $CMD_SRC help"
else
  python3 "$CMD_SRC" help >/dev/null || die "$CMD_SRC help failed (output above)."
  say "done: $NAME is linked. Next: store the API token (python3 $CMD_SRC doctor says how), write the config"
  say "      ($NAME config init, or config init --from-account), then $NAME setup plan and $NAME brief."
  say "to undo: $HERE/install.sh --uninstall --bin $BIN --name $NAME --skills $SKILLS"
fi

if [ "$REFUSED" = 1 ]; then die "some links were left alone; the warnings above say why."; fi
exit 0
