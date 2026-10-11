from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.models import Question, Round
from app.timeutil import local_to_utc


def recompute_closes(db: Session) -> None:
    """Een ronde sluit zodra de volgende opent; de laatste blijft LAST_ROUND_DAYS open."""
    rounds = db.scalars(select(Round).order_by(Round.opens_at)).all()
    for i, r in enumerate(rounds):
        r.number = i + 1
        if i + 1 < len(rounds):
            r.closes_at = rounds[i + 1].opens_at
        else:
            r.closes_at = r.opens_at + timedelta(days=config.LAST_ROUND_DAYS)


def generate_schedule(db: Session, start_local: datetime, intervals: list[int], per_round: int) -> int:
    """Verdeelt alle nog niet ingeplande vragen over nieuwe rondes. Geeft het aantal rondes terug."""
    unscheduled = db.scalars(
        select(Question).where(Question.round_id.is_(None), Question.active.is_(True)).order_by(Question.position)
    ).all()
    intervals = [d for d in intervals if d > 0] or [2, 3]
    per_round = max(1, per_round)
    opens_local = start_local
    created = 0
    for i in range(0, len(unscheduled), per_round):
        r = Round(opens_at=local_to_utc(opens_local), closes_at=local_to_utc(opens_local))
        db.add(r)
        db.flush()
        for q in unscheduled[i : i + per_round]:
            q.round_id = r.id
        opens_local += timedelta(days=intervals[created % len(intervals)])
        created += 1
    recompute_closes(db)
    db.commit()
    return created


def open_rounds(db: Session, now: datetime) -> list[Round]:
    return db.scalars(select(Round).where(Round.opens_at <= now, Round.closes_at > now).order_by(Round.opens_at)).all()


def next_round(db: Session, now: datetime) -> Round | None:
    return db.scalars(select(Round).where(Round.opens_at > now).order_by(Round.opens_at)).first()


def closed_rounds(db: Session, now: datetime) -> list[Round]:
    return db.scalars(select(Round).where(Round.closes_at <= now).order_by(Round.opens_at.desc())).all()
