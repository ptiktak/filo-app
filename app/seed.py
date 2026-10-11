import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Option, Question

SEED_FILE = Path(__file__).parent / "data" / "questions.json"


def import_questions(db: Session, path: Path = SEED_FILE) -> int:
    """Voegt de vragen uit het JSON-bestand toe achter de bestaande vragen."""
    items = json.loads(path.read_text(encoding="utf-8"))
    start = db.scalar(select(func.coalesce(func.max(Question.position), 0))) or 0
    for i, item in enumerate(items, start=1):
        q = Question(position=start + i, title=item["title"], scenario=item.get("scenario", ""))
        q.options = [
            Option(position=j, text=o["text"], reflection=o.get("reflection", ""))
            for j, o in enumerate(item["options"])
        ]
        db.add(q)
    db.commit()
    return len(items)


def seed_if_empty(db: Session) -> None:
    if db.scalar(select(func.count(Question.id))) == 0:
        import_questions(db)
