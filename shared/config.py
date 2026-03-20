"""Oula Trading - Shared Config"""
import os, json
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
CONFIG_DIR = PROJECT_ROOT / "config"
AUDIT_DB_PATH = DATA_DIR / "audit.db"
def load_env():
    f = PROJECT_ROOT / ".env"
    if not f.exists(): raise FileNotFoundError(f".env not found: {f}")
    with open(f) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"): continue
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip() not in os.environ: os.environ[k.strip()] = v.strip().strip('"').strip("'")
def get_alpaca_credentials():
    return {"api_key": os.environ.get("ALPACA_API_KEY",""), "secret_key": os.environ.get("ALPACA_SECRET_KEY",""), "paper": os.environ.get("ALPACA_PAPER_TRADE","true").lower()=="true"}
def load_risk_profiles():
    f = CONFIG_DIR / "risk_profiles.json"
    return json.loads(f.read_text()) if f.exists() else {}
load_env()
