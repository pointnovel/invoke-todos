#!/bin/sh
# pack.sh: build the release archive of invoke-todos from git, honouring .gitattributes export-ignore.
#
#   scripts/pack.sh [REF]      REF defaults to HEAD; a tag vX.Y.Z must match invoke_todos.__version__ at that ref
#
# Writes dist/invoke-todos-<version>.tar.gz (top folder invoke-todos-<version>/) and dist/SHA256SUMS, then
# lists the top folder and checks the sums. dist/ is gitignored (docs/spec-onboarding.md, sec. 1).
set -eu

HERE=$(cd "$(dirname "$0")/.." && pwd -P)
REF=${1:-HEAD}
DIST=$HERE/dist

die() { printf 'pack.sh: %s\n' "$*" >&2; exit 1; }
# sha256sum where it exists (Linux, GNU coreutils), else shasum -a 256 (macOS); the same arguments.
sums() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }

git -C "$HERE" rev-parse --verify --quiet "$REF^{commit}" >/dev/null || die "no such ref: $REF"
version=$(git -C "$HERE" show "$REF:invoke_todos/__init__.py" | sed -n 's/^__version__ = "\(.*\)"$/\1/p')
[ -n "$version" ] || die "no __version__ in invoke_todos/__init__.py at $REF"
case $REF in
  v[0-9]*) [ "$REF" = "v$version" ] || die "the tag $REF does not match __version__ $version at that ref" ;;
esac
if [ "$REF" = HEAD ] && [ -n "$(git -C "$HERE" status --porcelain --untracked-files=no)" ]; then
  printf 'pack.sh: warning: the working tree has uncommitted changes; the archive is of the commit, not the tree\n' >&2
fi

name=invoke-todos-$version
mkdir -p "$DIST"
git -C "$HERE" archive --format=tar.gz --prefix="$name/" -o "$DIST/$name.tar.gz" "$REF"
(cd "$DIST" && sums "$name.tar.gz" > SHA256SUMS)

top=$(tar tzf "$DIST/$name.tar.gz" | cut -d/ -f1 | sort -u)
[ "$top" = "$name" ] || die "the archive holds more than one top folder: $top"
(cd "$DIST" && sums -c SHA256SUMS)
printf 'built %s (%s files, ref %s)\n' "$DIST/$name.tar.gz" "$(tar tzf "$DIST/$name.tar.gz" | grep -vc '/$')" "$(git -C "$HERE" rev-parse --short "$REF^{commit}")"
