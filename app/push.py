import asyncio
import json
import logging

from pywebpush import WebPushException, webpush
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.db import SessionLocal
from app.models import PushSubscription, Round, utcnow
from app.timeutil import to_local

log = logging.getLogger(__name__)


def push_enabled() -> bool:
    return bool(config.VAPID_PUBLIC_KEY and config.VAPID_PRIVATE_KEY)


def _send(db: Session, subs: list[PushSubscription], title: str, body: str, url: str = "/") -> int:
    if not push_enabled():
        log.info("Push overgeslagen (geen VAPID-sleutels): %s", title)
        return 0
    payload = json.dumps({"title": title, "body": body, "url": url})
    sent = 0
    for sub in subs:
        try:
            webpush(
                subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                data=payload,
                vapid_private_key=config.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": config.VAPID_SUBJECT},
                ttl=60 * 60 * 24,
            )
            sent += 1
        except WebPushException as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in (404, 410):
                db.delete(sub)  # abonnement verlopen of ingetrokken
            else:
                log.warning("Push naar %s mislukt: %s", sub.id, exc)
    db.commit()
    return sent


def send_to_all(db: Session, title: str, body: str, url: str = "/") -> int:
    return _send(db, db.scalars(select(PushSubscription)).all(), title, body, url)


def send_to_user(db: Session, user_id: int, title: str, body: str, url: str = "/") -> int:
    subs = db.scalars(select(PushSubscription).where(PushSubscription.user_id == user_id)).all()
    return _send(db, subs, title, body, url)


def within_notify_hours() -> bool:
    hour = to_local(utcnow()).hour
    return config.NOTIFY_FROM_HOUR <= hour < config.NOTIFY_UNTIL_HOUR


def notify_due_rounds() -> int:
    """Stuurt een melding voor rondes die geopend zijn en nog niet gemeld. Buiten de meldingsuren wacht hij."""
    now = utcnow()
    with SessionLocal() as db:
        due = db.scalars(select(Round).where(Round.opens_at <= now, Round.notified_at.is_(None))).all()
        notified = 0
        for r in due:
            if r.closes_at <= now:
                r.notified_at = now  # gemist, niet meer melden
                continue
            if not within_notify_hours():
                continue
            n = len(r.questions)
            send_to_all(db, "Nieuwe vragen staan klaar", f"{n} {'vraag' if n == 1 else 'vragen'} om over na te denken.", "/")
            r.notified_at = now
            notified += 1
        db.commit()
        return notified


async def notifier_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(notify_due_rounds)
        except Exception:
            log.exception("Fout in de notificatie-loop")
        await asyncio.sleep(60)
