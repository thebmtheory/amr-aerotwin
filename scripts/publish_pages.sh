#!/usr/bin/env bash
# Publish the built site/ folder to the gh-pages branch, which GitHub Pages serves.
# Each publish is one commit on top of the last, so earlier versions stay in the branch history.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f site/.aerotwin-site ] || { echo "no built site in site/; run make report first" >&2; exit 1; }
git_dir=$(git rev-parse --absolute-git-dir)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
export GIT_INDEX_FILE="$tmp/index"

# The tree is the built site as it is, minus the build marker and the bare page fragment
git -C site --git-dir="$git_dir" --work-tree=. add -A .
git update-index --force-remove .aerotwin-site page.html
git update-index --add --cacheinfo "100644,$(git hash-object -w --stdin </dev/null),.nojekyll"  # serve files unprocessed
tree=$(git write-tree)

parent=""
if git fetch -q origin gh-pages 2>/dev/null; then parent=$(git rev-parse FETCH_HEAD); fi
if [ -n "$parent" ] && [ "$(git rev-parse "$parent^{tree}")" = "$tree" ]; then
  echo "gh-pages already has this site"
  exit 0
fi
commit=$(git commit-tree "$tree" ${parent:+-p "$parent"} -m "Report built from $(git describe --always --dirty)")
git update-ref refs/heads/gh-pages "$commit"
git push -q origin gh-pages
echo "published $(git rev-parse --short "$commit") to gh-pages"
