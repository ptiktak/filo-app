from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.models import Answer, FriendPrediction, GroupPrediction, Question, Round, User


@dataclass
class Distribution:
    counts: dict[int, int]  # option_id → aantal
    total: int

    @property
    def visible(self) -> bool:
        return self.total >= config.MIN_STATS_ANSWERS

    def pct(self, option_id: int) -> int:
        return round(100 * self.counts.get(option_id, 0) / self.total) if self.total else 0

    @property
    def majority(self) -> set[int]:
        if not self.counts:
            return set()
        top = max(self.counts.values())
        return {oid for oid, c in self.counts.items() if c == top}


def distribution(db: Session, question_id: int) -> Distribution:
    option_ids = db.scalars(select(Answer.option_id).where(Answer.question_id == question_id)).all()
    counts = Counter(option_ids)
    return Distribution(dict(counts), len(option_ids))


def pick_friend(db: Session, user_id: int, question_id: int) -> User | None:
    """Kiest deterministisch een andere deelnemer om te voorspellen; wisselt per vraag."""
    others = db.scalars(select(User).where(User.id != user_id).order_by(User.id)).all()
    if not others:
        return None
    return others[(user_id * 31 + question_id * 17) % len(others)]


@dataclass
class Outcome:
    option_text: str
    status: str  # pending | correct | wrong | void
    target_name: str = ""


def group_outcome(db: Session, question: Question, user_id: int, now: datetime) -> Outcome | None:
    pred = db.scalar(
        select(GroupPrediction).where(GroupPrediction.user_id == user_id, GroupPrediction.question_id == question.id)
    )
    if not pred:
        return None
    text = next((o.text for o in question.options if o.id == pred.option_id), "")
    if not question.round or not question.round.is_closed(now):
        return Outcome(text, "pending")
    dist = distribution(db, question.id)
    if not dist.visible:
        return Outcome(text, "void")
    return Outcome(text, "correct" if pred.option_id in dist.majority else "wrong")


def friend_outcome(db: Session, question: Question, user_id: int, now: datetime) -> Outcome | None:
    pred = db.scalar(
        select(FriendPrediction).where(FriendPrediction.user_id == user_id, FriendPrediction.question_id == question.id)
    )
    if not pred:
        return None
    target = db.get(User, pred.target_user_id)
    text = next((o.text for o in question.options if o.id == pred.option_id), "")
    name = target.name if target else "?"
    if not question.round or not question.round.is_closed(now):
        return Outcome(text, "pending", name)
    actual = db.scalar(
        select(Answer.option_id).where(Answer.user_id == pred.target_user_id, Answer.question_id == question.id)
    )
    if actual is None:
        return Outcome(text, "void", name)
    return Outcome(text, "correct" if actual == pred.option_id else "wrong", name)


def leaderboard(db: Session, now: datetime) -> list[tuple[User, int]]:
    """Voorspelpunten over gesloten rondes: 1 punt per goede groeps- of vriendvoorspelling."""
    closed_q = db.scalars(select(Question.id).join(Round).where(Round.closes_at <= now)).all()
    points: dict[int, int] = defaultdict(int)
    if closed_q:
        answers = {
            (a.user_id, a.question_id): a.option_id
            for a in db.scalars(select(Answer).where(Answer.question_id.in_(closed_q)))
        }
        dists: dict[int, Distribution] = {}
        for qid in closed_q:
            counts = Counter(oid for (uid, q), oid in answers.items() if q == qid)
            dists[qid] = Distribution(dict(counts), sum(counts.values()))
        for p in db.scalars(select(GroupPrediction).where(GroupPrediction.question_id.in_(closed_q))):
            d = dists[p.question_id]
            if d.visible and p.option_id in d.majority:
                points[p.user_id] += 1
        for p in db.scalars(select(FriendPrediction).where(FriendPrediction.question_id.in_(closed_q))):
            if answers.get((p.target_user_id, p.question_id)) == p.option_id:
                points[p.user_id] += 1
    users = db.scalars(select(User).order_by(User.name)).all()
    return sorted(((u, points[u.id]) for u in users), key=lambda t: (-t[1], t[0].name.lower()))
