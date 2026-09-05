#!/usr/bin/env bash
# Application checks only: Azure CLI handles resource waiting and terminal access.
set -euo pipefail
revision=${1:?Expected revision name}
az resource wait --ids "$APP_ID" --api-version 2025-07-01 --interval 5 --timeout 420 \
  --custom "properties.runningStatus == 'Running' && properties.latestReadyRevisionName == '$revision'"
umask 077
log="$RUNNER_TEMP/reibot-deploy/smoke.log"
# util-linux script supplies the terminal required by az containerapp exec.
timeout 300 script -q -e -c "az containerapp exec -g ReiBot -n reibot --revision $revision --container reibot --command 'python /app/deploy/smoke.py https://www.youtube.com/watch?v=mYEA5A0Bjyo'" "$log" >/dev/null 2>&1 || true
# Print only already-redacted application diagnostics, never raw terminal output.
sed -n 's/.*\(REIBOT_.*\)/\1/p' "$log"
grep -q 'REIBOT_SMOKE_OK' "$log"
az containerapp replica list -g ReiBot -n reibot --revision "$revision" -o json > "$RUNNER_TEMP/reibot-deploy/replicas.json"
python3 - <<'PYTHON'
import json, os
from pathlib import Path
replicas = json.loads((Path(os.environ['RUNNER_TEMP']) / 'reibot-deploy/replicas.json').read_text())
assert len(replicas) == 1, 'Expected one replica'
assert all(c['ready'] and not c.get('restartCount', 0) for r in replicas for c in r['properties']['containers']), 'Unhealthy replica'
print('DEPLOYMENT_VERIFIED: one healthy bot; Discord, storage and audio passed.')
PYTHON
