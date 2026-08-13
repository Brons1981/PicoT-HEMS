#!/usr/bin/with-contenv bashio
set -e

python -m picot.addon.history_export_server &
exec python -m picot.addon.runtime_financial_entrypoint
