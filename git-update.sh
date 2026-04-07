#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="${REPO_DIR:-$HOME/ocean-reef}"
BRANCH="main"
echo "==> Repo: $REPO_DIR"
cd "$REPO_DIR"
git rev-parse --is-inside-work-tree >/dev/null
STASHED=0
if [ -n "$(git status --porcelain)" ]; then
  echo "==> Local changes found, stashing first..."
  git stash push -u -m "auto-stash before update $(date +%F_%T)" >/dev/null
  STASHED=1
fi
echo "==> Updating git branch..."
git fetch origin
git checkout "$BRANCH"
git pull --rebase origin "$BRANCH"
echo "==> Ensuring Python venv + deps..."
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
echo "==> Ensuring Linux render dependencies..."
sudo apt-get update
sudo apt-get install -y openscad xvfb blender
if [ "$STASHED" -eq 1 ]; then
  echo "==> Restoring stashed local changes..."
  set +e
  git stash pop
  POP_RC=$?
  set -e
  if [ "$POP_RC" -ne 0 ]; then
    echo "!! Stash pop had conflicts. Resolve them manually."
  fi
fi
echo "==> Done."
git log -1 --oneline
