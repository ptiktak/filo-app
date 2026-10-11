from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import config
from app.db import get_db
from app.deps import flash, render, require_admin
from app.models import (
    Answer,
    Attendance,
    Contribution,
    Evening,
    FriendPrediction,
    GroupPrediction,
    Option,
    PushSubscription,
    Question,
    Round,
    TopicVote,
    User,
    utcnow,
)
from app.push import push_enabled, send_to_all
from app.routes.evening import next_evening
from app.scheduling import generate_schedule, recompute_closes
from app.seed import import_questions
from app.timeutil import fmt, parse_local_input, to_local

router = APIRouter(prefix="/admin")


def back(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


# ---------- Dashboard ----------


@router.get("")
def dashboard(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    base = str(request.base_url).rstrip("/")
    users = db.scalars(select(User).order_by(User.name)).all()
    rows = []
    for u in users:
        rows.append(
            {
                "user": u,
                "answers": db.scalar(select(func.count(Answer.id)).where(Answer.user_id == u.id)),
                "devices": db.scalar(select(func.count(PushSubscription.id)).where(PushSubscription.user_id == u.id)),
            }
        )
    return render(
        request,
        "admin/dashboard.html",
        admin,
        nav="admin",
        rows=rows,
        push_ok=push_enabled(),
        invite_url=f"{base}/uitnodiging/{config.INVITE_TOKEN}",
        admin_url=f"{base}/beheer/{config.ADMIN_TOKEN}",
        question_total=db.scalar(select(func.count(Question.id)).where(Question.active.is_(True))),
    )


@router.post("/gebruiker/{uid}/verwijder")
def delete_user(uid: int, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, uid)
    if user and user.id != admin.id:
        for model in (Answer, GroupPrediction, FriendPrediction, PushSubscription, Attendance, TopicVote, Contribution):
            for row in db.scalars(select(model).where(model.user_id == uid)):
                db.delete(row)
        for row in db.scalars(select(FriendPrediction).where(FriendPrediction.target_user_id == uid)):
            db.delete(row)
        db.delete(user)
        db.commit()
        flash(request, f"{user.name} is verwijderd.")
    return back("/admin")


@router.post("/melding")
def broadcast(request: Request, title: str = Form(...), body: str = Form(""), admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    n = send_to_all(db, title.strip()[:80], body.strip()[:200], "/")
    flash(request, f"Melding verstuurd naar {n} apparaten." if push_enabled() else "Push staat niet aan (VAPID-sleutels ontbreken).")
    return back("/admin")


# ---------- Vragen ----------


@router.get("/vragen")
def questions(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    qs = db.scalars(select(Question).options(selectinload(Question.round), selectinload(Question.options)).order_by(Question.position)).all()
    return render(request, "admin/questions.html", admin, nav="admin", questions=qs)


@router.post("/vragen/nieuw")
def new_question(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    pos = (db.scalar(select(func.max(Question.position))) or 0) + 1
    q = Question(position=pos, title="Nieuwe vraag", scenario="", active=False)
    db.add(q)
    db.commit()
    return back(f"/admin/vraag/{q.id}")


@router.post("/vragen/import")
def reimport(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    n = import_questions(db)
    flash(request, f"{n} vragen uit de standaardset toegevoegd.")
    return back("/admin/vragen")


OPTION_SLOTS = 5


@router.get("/vraag/{qid}")
def edit_question(qid: int, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    q = db.get(Question, qid)
    if not q:
        raise HTTPException(404)
    slots = [
        {"text": o.text, "reflection": o.reflection, "answers": db.scalar(select(func.count(Answer.id)).where(Answer.option_id == o.id))}
        for o in q.options
    ]
    slots += [{"text": "", "reflection": "", "answers": 0}] * (OPTION_SLOTS - len(slots))
    return render(request, "admin/question_edit.html", admin, nav="admin", q=q, slots=slots)


@router.post("/vraag/{qid}")
async def save_question(qid: int, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    q = db.get(Question, qid)
    if not q:
        raise HTTPException(404)
    form = await request.form()
    q.title = str(form.get("title", "")).strip()[:120] or q.title
    q.scenario = str(form.get("scenario", "")).strip()
    q.active = form.get("active") == "on"
    existing = list(q.options)
    position = 0
    for i in range(OPTION_SLOTS):
        text = str(form.get(f"text_{i}", "")).strip()
        option = existing[i] if i < len(existing) else None
        if not text:
            # Lege tekst = optie verwijderen, maar alleen als er nog niet op is gestemd
            if option and not db.scalar(select(func.count(Answer.id)).where(Answer.option_id == option.id)):
                q.options.remove(option)
            elif option:
                option.position = position
                position += 1
            continue
        if option is None:
            option = Option()
            q.options.append(option)
        option.text = text[:255]
        option.reflection = str(form.get(f"reflection_{i}", "")).strip()[:255]
        option.position = position
        position += 1
    db.commit()
    flash(request, "Vraag opgeslagen.")
    return back(f"/admin/vraag/{qid}")


# ---------- Planning ----------


@router.get("/planning")
def planning(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    rounds = db.scalars(select(Round).options(selectinload(Round.questions)).order_by(Round.opens_at)).all()
    counts = dict(db.execute(select(Answer.question_id, func.count(Answer.id)).group_by(Answer.question_id)).all())
    unscheduled = db.scalar(select(func.count(Question.id)).where(Question.round_id.is_(None), Question.active.is_(True)))
    user_total = db.scalar(select(func.count(User.id)))
    default_start = to_local(utcnow()).replace(hour=10, minute=0, second=0, microsecond=0)
    return render(
        request,
        "admin/planning.html",
        admin,
        nav="admin",
        rounds=rounds,
        counts=counts,
        unscheduled=unscheduled,
        user_total=user_total,
        default_start=default_start.strftime("%Y-%m-%dT%H:%M"),
    )


@router.post("/planning/genereer")
def generate(
    request: Request,
    start: str = Form(...),
    intervals: str = Form("2,3"),
    per_round: int = Form(3),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        days = [int(x) for x in intervals.replace(" ", "").split(",") if x]
    except ValueError:
        days = [2, 3]
    n = generate_schedule(db, datetime.fromisoformat(start), days, per_round)
    flash(request, f"{n} rondes ingepland." if n else "Er zijn geen ongeplande (actieve) vragen meer.")
    return back("/admin/planning")


@router.post("/ronde/{rid}")
def update_round(rid: int, request: Request, opens_at: str = Form(...), admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    r = db.get(Round, rid)
    parsed = parse_local_input(opens_at)
    if r and parsed:
        r.opens_at = parsed
        if parsed > utcnow():
            r.notified_at = None
        db.flush()
        recompute_closes(db)
        db.commit()
        flash(request, "Ronde verplaatst.")
    return back("/admin/planning")


@router.post("/ronde/{rid}/nu")
def open_now(rid: int, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    r = db.get(Round, rid)
    if r:
        r.opens_at = utcnow()
        r.notified_at = None
        db.flush()
        recompute_closes(db)
        db.commit()
        flash(request, f"Ronde {r.number} staat nu open. De melding gaat binnen een minuut uit (binnen de meldingsuren).")
    return back("/admin/planning")


@router.post("/ronde/{rid}/verwijder")
def delete_round(rid: int, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    r = db.get(Round, rid)
    if r:
        for q in list(r.questions):
            q.round_id = None
        db.delete(r)
        db.flush()
        recompute_closes(db)
        db.commit()
        flash(request, "Ronde verwijderd; de vragen zijn weer ongepland.")
    return back("/admin/planning")


# ---------- Avond ----------


@router.get("/avond")
def evenings(request: Request, id: int | None = None, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    now = utcnow()
    all_evenings = db.scalars(select(Evening).order_by(Evening.starts_at.desc())).all()
    ev = db.get(Evening, id) if id else next_evening(db, now)
    ctx: dict = {"evenings": all_evenings, "ev": ev}
    if ev:
        users = db.scalars(select(User).order_by(User.name)).all()
        att = {a.user_id: a.attending for a in db.scalars(select(Attendance).where(Attendance.evening_id == ev.id))}
        ctx["yes"] = [u.name for u in users if att.get(u.id) is True]
        ctx["no"] = [u.name for u in users if att.get(u.id) is False]
        ctx["unknown"] = [u.name for u in users if u.id not in att]
        votes = db.execute(
            select(Question.title, User.name)
            .join(TopicVote, TopicVote.question_id == Question.id)
            .join(User, User.id == TopicVote.user_id)
            .where(TopicVote.evening_id == ev.id)
        ).all()
        ranking: dict[str, list[str]] = {}
        for title, name in votes:
            ranking.setdefault(title, []).append(name)
        ctx["topics"] = sorted(ranking.items(), key=lambda t: (-len(t[1]), t[0]))
        ctx["contributions"] = db.scalars(
            select(Contribution).where(Contribution.evening_id == ev.id).order_by(Contribution.created_at)
        ).all()
    default_start = to_local(now).replace(hour=20, minute=0, second=0, microsecond=0)
    return render(request, "admin/evening.html", admin, nav="admin", default_start=default_start.strftime("%Y-%m-%dT%H:%M"), **ctx)


@router.post("/avond/nieuw")
def new_evening(
    request: Request,
    starts_at: str = Form(...),
    notify: bool = Form(False),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    when = parse_local_input(starts_at)
    if not when:
        raise HTTPException(400, "Datum ontbreekt")
    ev = Evening(starts_at=when)
    db.add(ev)
    db.commit()
    message = f"Avond geprikt op {fmt(when)}."
    if notify:
        n = send_to_all(db, "Nieuwe avond geprikt", f"{fmt(when)}. Ben je erbij?", "/avond")
        message += f" Melding naar {n} apparaten." if push_enabled() else " (Push staat niet aan.)"
    flash(request, message)
    return back(f"/admin/avond?id={ev.id}")


@router.post("/avond/{eid}")
def save_evening(
    eid: int,
    request: Request,
    starts_at: str = Form(...),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    ev = db.get(Evening, eid)
    when = parse_local_input(starts_at)
    if not ev or not when:
        raise HTTPException(404)
    ev.starts_at = when
    db.commit()
    flash(request, "Datum opgeslagen.")
    return back(f"/admin/avond?id={eid}")


@router.post("/avond/{eid}/verwijder")
def delete_evening(eid: int, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    ev = db.get(Evening, eid)
    if ev:
        for model in (Attendance, TopicVote, Contribution):
            for row in db.scalars(select(model).where(model.evening_id == eid)):
                db.delete(row)
        db.delete(ev)
        db.commit()
        flash(request, "Avond verwijderd.")
    return back("/admin/avond")
