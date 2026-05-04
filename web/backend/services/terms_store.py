import json
from pathlib import Path


TERMS_FILE = Path(__file__).parent.parent.parent.parent / "config" / "replace_terms.json"


def load_terms() -> dict:
    if not TERMS_FILE.exists():
        return {}
    return json.loads(TERMS_FILE.read_text(encoding="utf-8"))


def save_terms(terms: dict) -> None:
    TERMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TERMS_FILE.write_text(
        json.dumps(terms, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def add_term(terms: dict, source: str, target: str) -> dict:
    terms[source] = target
    return terms
