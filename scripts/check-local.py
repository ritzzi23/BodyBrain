"""Print local availability and relay status without document contents or credentials."""
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from bodybrain.config import Settings

settings = Settings()
headers = {'Authorization': f'Bearer {settings.api_token}'} if settings.api_token else {}
try:
    with urlopen(Request('http://127.0.0.1:8080/api/health', headers=headers), timeout=10) as response:
        health = json.load(response)
    with urlopen(Request('http://127.0.0.1:8080/api/integrations', headers=headers), timeout=60) as response:
        integrations = json.load(response)
    with urlopen('http://127.0.0.1:3016/', timeout=10) as response:
        ui = response.status
    cognee = integrations['cognee']
    ingestion = integrations['clawmax']['ingestion']
    evidence = integrations['clawmax']['evidence']
    print(json.dumps({'ui_http_status': ui, 'api': health['status'],
                      'cognee': {key: cognee.get(key) for key in ('mode', 'configured', 'reachable', 'last_error', 'note')},
                      'transport': health['integrations']['clawmax'].get('transport'),
                      'ingestion': ingestion, 'evidence': evidence}, indent=2))
    raise SystemExit(0 if ui == 200 and health['status'] == 'ok'
                     and cognee.get('configured') and cognee.get('reachable')
                     and ingestion.get('status') == 'ready' and evidence.get('status') == 'ready' else 1)
except Exception as exc:
    print(json.dumps({'status': 'unavailable', 'error_type': type(exc).__name__}))
    raise SystemExit(1)
