from fastapi import APIRouter, Body, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import config
from app.db import get_db
from app.deps import flash, render, require_user
from app.models import Answer, FriendPrediction, GroupPrediction, PushSubscription, Question, User, utcnow
from app.push import push_enabled, send_to_user
from app.routes.evening import attendance_of, next_evening
from app.scheduling import closed_rounds, next_round, open_rounds
from app.stats import distribution, friend_outcome, group_outcome, leaderboard, pick_friend

router = APIRouter()


def _load_question(db: Session, qid: int) -> Question:
    q = db.scalar(
        select(Question).where(Question.id == qid).options(selectinload(Question.options), selectinload(Question.round))
    )
    if not q or not q.round or q.round.opens_at > utcnow():
        raise HTTPException(404, "Deze vraag is (nog) niet beschikbaar")
    return q


def _answer(db: Session, user_id: int, qid: int) -> Answer | None:
    return db.scalar(select(Answer).where(Answer.user_id == user_id, Answer.question_id == qid))


def _has(db: Session, model, user_id: int, qid: int) -> bool:
    return db.scalar(select(model.id).where(model.user_id == user_id, model.question_id == qid)) is not None


def next_step(db: Session, user: User, q: Question) -> str:
    """answer → group → friend → result. Na sluiting van de ronde alleen nog het resultaat."""
    if not q.round.is_open(utcnow()):
        return "result"
    if not _answer(db, user.id, q.id):
        return "answer"
    if not _has(db, GroupPrediction, user.id, q.id):
        return "group"
    if not _has(db, FriendPrediction, user.id, q.id) and pick_friend(db, user.id, q.id):
        return "friend"
    return "result"


def _next_open_question(db: Session, user: User) -> Question | None:
    for r in open_rounds(db, utcnow()):
        for q in r.questions:
            if next_step(db, user, q) != "result":
                return q
    return None


@router.get("/")
def home(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    now = utcnow()
    current = []
    for r in open_rounds(db, now):
        for q in r.questions:
            current.append({"q": q, "round": r, "step": next_step(db, user, q)})
    past = []
    for r in closed_rounds(db, now):
        for q in r.questions:
            past.append({"q": q, "answered": _answer(db, user.id, q.id) is not None})
    evening = next_evening(db, now)
    board = leaderboard(db, now)
    return render(
        request,
        "home.html",
        user,
        nav="vragen",
        current=current,
        past=past,
        upcoming=next_round(db, now),
        evening=evening,
        attending=attendance_of(db, evening.id, user.id) if evening else None,
        board=board,
        board_has_points=any(p for _, p in board),
    )


@router.get("/vraag/{qid}")
def question(qid: int, request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    q = _load_question(db, qid)
    step = next_step(db, user, q)
    if step == "result":
        return RedirectResponse(f"/vraag/{qid}/resultaat", status_code=303)
    ctx = {"q": q, "step": step}
    if step == "friend":
        ctx["friend"] = pick_friend(db, user.id, q.id)
    template = "question_answer.html" if step == "answer" else "question_predict.html"
    return render(request, template, user, nav="vragen", **ctx)


def _valid_option(q: Question, option_id: int) -> int:
    if option_id not in {o.id for o in q.options}:
        raise HTTPException(400, "Onbekende optie")
    return option_id


def _require_open(q: Question) -> None:
    if not q.round.is_open(utcnow()):
        raise HTTPException(409, "Deze ronde is gesloten")


@router.post("/vraag/{qid}/antwoord")
def submit_answer(
    qid: int,
    option_id: int = Form(...),
    explanation: str = Form(""),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    q = _load_question(db, qid)
    _require_open(q)
    if not _answer(db, user.id, qid):
        db.add(
            Answer(
                user_id=user.id,
                question_id=qid,
                option_id=_valid_option(q, option_id),
                explanation=explanation.strip()[:140] or None,
            )
        )
        db.commit()
    return RedirectResponse(f"/vraag/{qid}", status_code=303)


@router.post("/vraag/{qid}/voorspel-groep")
def predict_group(qid: int, option_id: int = Form(...), user: User = Depends(require_user), db: Session = Depends(get_db)):
    q = _load_question(db, qid)
    _require_open(q)
    if _answer(db, user.id, qid) and not _has(db, GroupPrediction, user.id, qid):
        db.add(GroupPrediction(user_id=user.id, question_id=qid, option_id=_valid_option(q, option_id)))
        db.commit()
    return RedirectResponse(f"/vraag/{qid}", status_code=303)


@router.post("/vraag/{qid}/voorspel-vriend")
def predict_friend(
    qid: int,
    option_id: int = Form(...),
    target_id: int = Form(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    q = _load_question(db, qid)
    _require_open(q)
    if target_id == user.id or not db.get(User, target_id):
        raise HTTPException(400, "Ongeldige vriend")
    if _answer(db, user.id, qid) and not _has(db, FriendPrediction, user.id, qid):
        db.add(FriendPrediction(user_id=user.id, question_id=qid, target_user_id=target_id, option_id=_valid_option(q, option_id)))
        db.commit()
    return RedirectResponse(f"/vraag/{qid}", status_code=303)


@router.get("/vraag/{qid}/resultaat")
def result(qid: int, request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    q = _load_question(db, qid)
    now = utcnow()
    if q.round.is_open(now) and next_step(db, user, q) != "result":
        return RedirectResponse(f"/vraag/{qid}", status_code=303)
    answer = _answer(db, user.id, qid)
    dist = distribution(db, qid)
    same_pct = dist.pct(answer.option_id) if answer else 0
    return render(
        request,
        "question_result.html",
        user,
        nav="vragen",
        q=q,
        answer=answer,
        dist=dist,
        same_pct=same_pct,
        missing=max(0, config.MIN_STATS_ANSWERS - dist.total),
        group=group_outcome(db, q, user.id, now),
        friend=friend_outcome(db, q, user.id, now),
        closed=q.round.is_closed(now),
        next_q=_next_open_question(db, user),
    )


# ---------- Push ----------


@router.post("/push/subscribe")
def push_subscribe(payload: dict = Body(...), user: User = Depends(require_user), db: Session = Depends(get_db)):
    endpoint = payload.get("endpoint")
    keys = payload.get("keys") or {}
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        raise HTTPException(400, "Ongeldig abonnement")
    existing = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if existing:
        existing.user_id, existing.p256dh, existing.auth = user.id, keys["p256dh"], keys["auth"]
    else:
        db.add(PushSubscription(user_id=user.id, endpoint=endpoint, p256dh=keys["p256dh"], auth=keys["auth"]))
    db.commit()
    return {"ok": True}


@router.post("/push/unsubscribe")
def push_unsubscribe(payload: dict = Body(...), user: User = Depends(require_user), db: Session = Depends(get_db)):
    sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == payload.get("endpoint", "")))
    if sub and sub.user_id == user.id:
        db.delete(sub)
        db.commit()
    return {"ok": True}


@router.post("/push/test")
def push_test(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if not push_enabled():
        flash(request, "Push staat nog niet aan op de server (VAPID-sleutels ontbreken).")
    else:
        n = send_to_user(db, user.id, "Testmelding", "Als je dit leest, werken de notificaties.", "/")
        flash(request, f"Testmelding verstuurd naar {n} apparaat/apparaten." if n else "Geen apparaat gevonden. Zet eerst notificaties aan.")
    return RedirectResponse("/installeer", status_code=303)
