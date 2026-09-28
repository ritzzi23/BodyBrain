"""Explicit provider-disabled environment for isolated dataset workspaces."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABS = ROOT / '.runtime/datasets/workspaces'


def local_environment(dataset: str, api_port: int, ui_port: int) -> dict[str, str]:
    if dataset not in {'synthea', 'fitbit'}:
        raise ValueError('Unknown dataset')
    env = {k: v for k, v in os.environ.items() if not k.startswith(('BODYBRAIN_', 'COGNEE_', 'CLAWMAX_'))}
    env.update({
        'PYTHON_DOTENV_DISABLED': '1', 'PYTHONUNBUFFERED': '1',
        'BODYBRAIN_DATA_DIR': str(LABS / dataset),
        'BODYBRAIN_WORKSPACE_LABEL': f'{dataset.title()} dataset sample · separate participant · local providers disabled',
        'BODYBRAIN_API_URL': f'http://127.0.0.1:{api_port}',
        'BODYBRAIN_API_TOKEN': '', 'BODYBRAIN_AGENT_TOKEN': '',
        'BODYBRAIN_ALLOWED_HOSTS': 'localhost,127.0.0.1,testserver',
        'BODYBRAIN_ALLOWED_ORIGINS': f'http://127.0.0.1:{ui_port},http://localhost:{ui_port}',
        'COGNEE_MODE': 'disabled', 'COGNEE_URL': '', 'COGNEE_API_KEY': '', 'COGNEE_BEARER_TOKEN': '',
        'CLAWMAX_TRANSPORT': 'dashboard', 'CLAWMAX_URL': '', 'CLAWMAX_TOKEN': '',
        'CLAWMAX_INGEST_WORKFLOW_ID': '', 'CLAWMAX_EVIDENCE_WORKFLOW_ID': '',
    })
    return env
