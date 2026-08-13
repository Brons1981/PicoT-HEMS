#!/usr/bin/with-contenv bashio
set -e

python - <<'PY'
import importlib.util

if importlib.util.find_spec("picot.addon") is not None:
    raise SystemExit("Refusing to start PicoT v2: legacy picot.addon is importable")
PY

exec python -m picot.v2.live_runtime
