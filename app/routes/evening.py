from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import flash, render, require_user
from app.models import CONTRIBUTION_KINDS, Attendance, Contribution, Evening, Question, Round, TopicVote, User, utcnow

router = APIRouter()

# Een avond blijft 'de volgende avond' tot een paar uur na de start
EVENING_GRACE = timedelta(hours=6)
MAX_TOPICS = 3


def next_evening(db: Session, now: datetime) -> Evening | None:
    return db.scalars(select(Evening).where(Evening.starts_at > now - EVENING_GRACE).order_by(Evening.starts_at)).first()


def attendance_of(db: Session, evening_id: int, user_id: int) -> bool | None:
    row = db.scalar(select(Attendance).where(Attendance.evening_id == evening_id, Attendance.user_id == user_id))
    return row.attending if row else None


def discussable_questions(db: Session, now: datetime) -> list[Question]:
    """Alle vragen die al gesteld zijn (ronde geopend)."""
    return db.scalars(select(Question).join(Round).where(Round.opens_at <= now).order_by(Round.opens_at, Question.position)).all()


@router.get("/avond")
def evening_page(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    now = utcnow()
    ev = next_evening(db, now)
    ctx: dict = {"ev": ev}
    if ev:
        attendance = db.scalars(select(Attendance).where(Attendance.evening_id == ev.id)).all()
        ctx["attending"] = attendance_of(db, ev.id, user.id)
        ctx["coming"] = sorted((a.user.name for a in attendance if a.attending), key=str.lower)
        ctx["questions"] = discussable_questions(db, now)
        ctx["my_topics"] = set(
            db.scalars(select(TopicVote.question_id).where(TopicVote.evening_id == ev.id, TopicVote.user_id == user.id)).all()
        )
        ctx["max_topics"] = MAX_TOPICS
        ctx["kinds"] = CONTRIBUTION_KINDS
        ctx["mine"] = db.scalars(
            select(Contribution).where(Contribution.evening_id == ev.id, Contribution.user_id == user.id).order_by(Contribution.created_at)
        ).all()
    return render(request, "evening.html", user, nav="avond", **ctx)


def _current(db: Session) -> Evening:
    ev = next_evening(db, utcnow())
    if not ev:
        raise HTTPException(404, "Er is geen avond gepland")
    return ev


@router.post("/avond/aanwezig")
def set_attendance(request: Request, attending: bool = Form(...), user: User = Depends(require_user), db: Session = Depends(get_db)):
    ev = _current(db)
    row = db.scalar(select(Attendance).where(Attendance.evening_id == ev.id, Attendance.user_id == user.id))
    if row:
        row.attending = attending
    else:
        db.add(Attendance(evening_id=ev.id, user_id=user.id, attending=attending))
    db.commit()
    flash(request, "Top, tot dan!" if attending else "Jammer! Je kunt het altijd nog aanpassen.")
    return RedirectResponse("/avond", status_code=303)


@router.post("/avond/onderwerpen")
async def set_topics(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    ev = _current(db)
    form = await request.form()
    allowed = {q.id for q in discussable_questions(db, utcnow())}
    chosen = [int(v) for v in form.getlist("question_id") if str(v).isdigit() and int(v) in allowed][:MAX_TOPICS]
    for vote in db.scalars(select(TopicVote).where(TopicVote.evening_id == ev.id, TopicVote.user_id == user.id)):
        db.delete(vote)
    db.flush()
    for qid in chosen:
        db.add(TopicVote(evening_id=ev.id, user_id=user.id, question_id=qid))
    db.commit()
    flash(request, "Je keuze is opgeslagen.")
    return RedirectResponse("/avond#onderwerpen", status_code=303)


@router.post("/avond/inbreng")
def add_contribution(
    request: Request,
    kind: str = Form(...),
    text: str = Form(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    ev = _current(db)
    text = text.strip()
    if kind not in CONTRIBUTION_KINDS or not text:
        raise HTTPException(400, "Onvolledige inbreng")
    db.add(Contribution(evening_id=ev.id, user_id=user.id, kind=kind, text=text[:1000]))
    db.commit()
    flash(request, "Dank je! Je inbreng is opgeslagen.")
    return RedirectResponse("/avond#inbreng", status_code=303)


@router.post("/avond/inbreng/{cid}/verwijder")
def delete_contribution(cid: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    row = db.get(Contribution, cid)
    if row and row.user_id == user.id:
        db.delete(row)
        db.commit()
    return RedirectResponse("/avond#inbreng", status_code=303)
