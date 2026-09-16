#!/bin/sh
# Start the RD-Agent log server, which also serves the Research Studio at http://127.0.0.1:19899/app/.
#
#   UI_LOAD_LEGACY_PICKLE_TRACES=true sh scripts/start-studio.sh
#
# Uses $STUDIO_PYTHON, else the active virtualenv's python, else `python` on PATH. If
# git_ignore_folder/deepseek.env (or $STUDIO_ENV_FILE) exists it is loaded with python-dotenv so the
# LLM keys and research settings reach the server and the experiments it launches.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
PY=${STUDIO_PYTHON:-${VIRTUAL_ENV:+$VIRTUAL_ENV/bin/python}}
PY=${PY:-python}
ENV_FILE=${STUDIO_ENV_FILE:-git_ignore_folder/deepseek.env}
if [ -f "$ENV_FILE" ]; then
  exec "$PY" -m dotenv -f "$ENV_FILE" run -- "$PY" -m rdagent.log.server.app --host 127.0.0.1 --port "${STUDIO_PORT:-19899}"
fi
exec "$PY" -m rdagent.log.server.app --host 127.0.0.1 --port "${STUDIO_PORT:-19899}"
