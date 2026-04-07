#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/s3rdl/ocean-reef.git}"
REPO_DIR="${REPO_DIR:-$HOME/ocean-reef}"
BRANCH="${BRANCH:-main}"
INSTALL_SYSTEM_DEPS="${INSTALL_SYSTEM_DEPS:-1}"

echo "==> Repo URL: $REPO_URL"
echo "==> Repo dir: $REPO_DIR"
echo "==> Branch: $BRANCH"

PARENT_DIR="$(dirname "$REPO_DIR")"
mkdir -p "$PARENT_DIR"

if [ ! -d "$REPO_DIR/.git" ]; then
  echo "==> Cloning repository..."
  git clone --branch "$BRANCH" "$REPO_URL" "$REPO_DIR"
fi

cd "$REPO_DIR"
git rev-parse --is-inside-work-tree >/dev/null

STASHED=0
if [ -n "$(git status --porcelain)" ]; then
  echo "==> Local changes found, stashing first..."
  git stash push -u -m "auto-stash before update $(date +%F_%T)" >/dev/null
  STASHED=1
fi

echo "==> Updating source..."
git fetch origin
git checkout "$BRANCH"
git pull --rebase origin "$BRANCH"

echo "==> Setting up Python environment..."
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

if [ "$INSTALL_SYSTEM_DEPS" = "1" ] && command -v apt-get >/dev/null 2>&1; then
  echo "==> Installing Linux rendering dependencies..."
  sudo apt-get update
  sudo apt-get install -y openscad xvfb blender
fi

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

echo "==> Update complete."
git log -1 --oneline
