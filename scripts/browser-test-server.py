"""Isolated browser-test API; real providers and user storage are disabled."""
import os
from pathlib import Path
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'backend'))
with tempfile.TemporaryDirectory(prefix='bodybrain-browser-') as data:
    os.environ.update(PYTHON_DOTENV_DISABLED='1', BODYBRAIN_DATA_DIR=data, COGNEE_MODE='disabled', COGNEE_URL='', COGNEE_API_KEY='', COGNEE_BEARER_TOKEN='', CLAWMAX_URL='', CLAWMAX_TOKEN='', CLAWMAX_TRANSPORT='dashboard', BODYBRAIN_API_TOKEN='', BODYBRAIN_AGENT_TOKEN='', BODYBRAIN_ALLOWED_HOSTS='localhost,127.0.0.1,testserver', BODYBRAIN_ALLOWED_ORIGINS='http://127.0.0.1:3017')
    import uvicorn
    uvicorn.run('bodybrain.main:app', host='127.0.0.1', port=8082, log_level='warning')
