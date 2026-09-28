from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=False)


@dataclass(frozen=True)
class Settings:
    workspace_label: str = os.environ.get('BODYBRAIN_WORKSPACE_LABEL', '')
    data_dir: Path = (ROOT / os.environ.get("BODYBRAIN_DATA_DIR", ".bodybrain")).resolve()
    atlas_path: Path = ROOT / "public/models/atlas.json"
    cognee_mode: str = os.environ.get("COGNEE_MODE", "disabled")
    cognee_url: str = os.environ.get("COGNEE_URL", "")
    cognee_api_key: str = os.environ.get("COGNEE_API_KEY", "")
    cognee_token: str = os.environ.get("COGNEE_BEARER_TOKEN", "")
    cognee_dataset: str = os.environ.get("COGNEE_DATASET", "bodybrain")
    clawmax_url: str = os.environ.get("CLAWMAX_URL", "")
    clawmax_token: str = os.environ.get("CLAWMAX_TOKEN", "")
    clawmax_ingest_workflow: str = os.environ.get("CLAWMAX_INGEST_WORKFLOW_ID", "")
    clawmax_evidence_workflow: str = os.environ.get("CLAWMAX_EVIDENCE_WORKFLOW_ID", "")
    clawmax_transport: str = os.environ.get("CLAWMAX_TRANSPORT", "dashboard")
    clawmax_relay_inbox: str = os.environ.get("CLAWMAX_RELAY_INBOX", "bodybrain_clawmax_jobs")
    clawmax_relay_outbox: str = os.environ.get("CLAWMAX_RELAY_OUTBOX", "bodybrain_clawmax_results")
    api_token: str = os.environ.get("BODYBRAIN_API_TOKEN", "")
    agent_token: str = os.environ.get("BODYBRAIN_AGENT_TOKEN", "")
    allowed_hosts: tuple[str, ...] = tuple(h.strip() for h in os.environ.get("BODYBRAIN_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",") if h.strip())
    allowed_origins: tuple[str, ...] = tuple(o.strip() for o in os.environ.get("BODYBRAIN_ALLOWED_ORIGINS", "http://127.0.0.1:3016,http://localhost:3016,http://127.0.0.1:8080,http://localhost:8080").split(",") if o.strip())
    max_upload_bytes: int = 10 * 1024 * 1024
    max_text_chars: int = 150_000

    def __post_init__(self):
        if self.clawmax_transport not in {"dashboard", "cognee_relay"}:
            raise ValueError("CLAWMAX_TRANSPORT must be dashboard or cognee_relay")
        if self.clawmax_transport == "cognee_relay":
            datasets = (self.cognee_dataset, self.clawmax_relay_inbox, self.clawmax_relay_outbox)
            if any(not isinstance(name, str) or not name.strip() for name in datasets):
                raise ValueError("ClawMax inbox, outbox, and approved Cognee memory require non-empty dataset names")
            if len({name.strip() for name in datasets}) != 3:
                raise ValueError("ClawMax inbox, outbox, and approved Cognee memory must use separate datasets")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "bodybrain.sqlite3"
