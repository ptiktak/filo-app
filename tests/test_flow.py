"""End-to-end test van de hele flow met zeven deelnemers."""

import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Question, Round, utcnow
from app.timeutil import to_local

NAMES = ["Jeroen", "Anna", "Bram", "Chris", "Dewi", "Eva", "Femke"]


@pytest.fixture(scope="module")
def clients():
    with TestClient(app):
        result = {}
        for name in NAMES:
            c = TestClient(app)
            c.__enter__()
            path = "/beheer/beheer-token" if name == "Jeroen" else "/uitnodiging/vrienden-token"
            r = c.post(path, data={"name": name}, follow_redirects=False)
            assert r.status_code == 303
            result[name] = c
        yield result
        for c in result.values():
            c.__exit__(None, None, None)


def ids_in(html: str, pattern: str) -> list[int]:
    return [int(x) for x in re.findall(pattern, html)]


def answer_all(clients, qid: int, choose) -> None:
    """Laat iedereen antwoorden + beide voorspellingen doen. choose(i) → optie-index."""
    for i, name in enumerate(NAMES):
        c = clients[name]
        page = c.get(f"/vraag/{qid}").text
        options = ids_in(page, r'name="option_id" value="(\d+)"')
        assert len(options) == 4, name
        c.post(f"/vraag/{qid}/antwoord", data={"option_id": options[choose(i)], "explanation": f"Omdat {name}"})
        page = c.get(f"/vraag/{qid}").text
        assert "Wat kiest de meerderheid?" in page
        c.post(f"/vraag/{qid}/voorspel-groep", data={"option_id": options[0]})
        page = c.get(f"/vraag/{qid}").text
        assert "Wat denk je dat" in page
        target = ids_in(page, r'name="target_id" value="(\d+)"')[0]
        c.post(f"/vraag/{qid}/voorspel-vriend", data={"option_id": options[0], "target_id": target})


def test_links():
    with TestClient(app) as c:
        assert c.get("/uitnodiging/fout").status_code == 404
        assert c.get("/beheer/fout").status_code == 404
        assert c.post("/beheer/fout", data={"name": "Mallory"}).status_code == 404
        assert "uitnodigingslink nodig" in c.get("/login").text
        assert "Hoe heet je?" in c.get("/uitnodiging/vrienden-token").text
        # Geplakte link op het inlogscherm (iOS-beginscherm-app)
        r = c.post("/login", data={"link": "https://x.up.railway.app/uitnodiging/vrienden-token"}, follow_redirects=False)
        assert r.headers["location"] == "/uitnodiging/vrienden-token"
        r = c.post("/login", data={"link": "https://x/beheer/beheer-token "}, follow_redirects=False)
        assert r.headers["location"] == "/beheer/beheer-token"
        assert "werkt niet" in c.post("/login", data={"link": "https://x/uitnodiging/fout"}).text


def test_friend_link_cannot_take_admin_name(clients):
    with TestClient(app) as c:
        r = c.post("/uitnodiging/vrienden-token", data={"name": "jeroen"})
        assert "al in gebruik" in r.text
        assert c.get("/admin", follow_redirects=False).status_code == 303
        # Bestaande vriend kan op een nieuw apparaat opnieuw inloggen
        r = c.post("/uitnodiging/vrienden-token", data={"name": "anna"}, follow_redirects=False)
        assert r.status_code == 303
        assert c.get("/admin", follow_redirects=False).status_code == 303


def test_non_admin_cannot_open_admin(clients):
    r = clients["Anna"].get("/admin", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    page = clients["Jeroen"].get("/admin").text
    assert "/uitnodiging/vrienden-token" in page and "/beheer/beheer-token" in page


def test_full_month(clients):
    admin = clients["Jeroen"]
    start = (to_local(utcnow()) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    r = admin.post("/admin/planning/genereer", data={"start": start, "intervals": "2,3", "per_round": 3})
    assert "7 rondes ingepland" in r.text

    with SessionLocal() as db:
        rounds = db.query(Round).order_by(Round.opens_at).all()
        assert len(rounds) == 7
        assert rounds[0].closes_at == rounds[1].opens_at
        assert (rounds[1].opens_at - rounds[0].opens_at).days == 2
        assert (rounds[2].opens_at - rounds[1].opens_at).days == 3
        q1, q2, _ = [q.id for q in rounds[0].questions]
        round_ids = [r.id for r in rounds]

    home = clients["Anna"].get("/").text
    assert "3 vragen wachten" in home

    # Vijf antwoorden: groepsuitslag nog verborgen
    for name in NAMES[:5]:
        c = clients[name]
        options = ids_in(c.get(f"/vraag/{q1}").text, r'name="option_id" value="(\d+)"')
        c.post(f"/vraag/{q1}/antwoord", data={"option_id": options[0]})
    anna = clients["Anna"]
    options = ids_in(anna.get(f"/vraag/{q1}").text, r'name="option_id" value="(\d+)"')
    anna.post(f"/vraag/{q1}/voorspel-groep", data={"option_id": options[0]})
    page = anna.get(f"/vraag/{q1}").text
    target = ids_in(page, r'name="target_id" value="(\d+)"')[0]
    anna.post(f"/vraag/{q1}/voorspel-vriend", data={"option_id": options[0], "target_id": target})
    result = anna.get(f"/vraag/{q1}/resultaat").text
    assert "Nog 1 te gaan" in result and "van de groep koos" not in result
    options = ids_in(clients["Anna"].get(f"/vraag/{q2}").text, r'name="option_id" value="(\d+)"')

    # Iedereen beantwoordt vraag 2 volledig (5x optie A, 2x optie B)
    answer_all(clients, q2, lambda i: 0 if i < 5 else 1)
    result = clients["Anna"].get(f"/vraag/{q2}/resultaat").text
    assert "71% van de groep koos hetzelfde" in result
    assert "Uitslag na sluiting" in result
    # Andermans toelichting is nergens zichtbaar
    assert "Omdat Bram" not in result

    # Ronde 2 nu openen → ronde 1 sluit
    admin.post(f"/admin/ronde/{round_ids[1]}/nu")
    result = clients["Anna"].get(f"/vraag/{q2}/resultaat").text
    assert "Goed! +1" in result  # meerderheid = optie A
    home = clients["Anna"].get("/").text
    assert "Mensenkenners" in home

    # Gemiste vraag na sluiting kan niet meer beantwoord worden
    r = clients["Femke"].post(f"/vraag/{q1}/antwoord", data={"option_id": options[0]})
    assert r.status_code in (400, 409)


def test_evening(clients):
    admin, anna, bram = clients["Jeroen"], clients["Anna"], clients["Bram"]
    assert "Nog geen avond geprikt" in anna.get("/avond").text

    when = (to_local(utcnow()) + timedelta(days=10)).replace(hour=20, minute=0).strftime("%Y-%m-%dT%H:%M")
    r = admin.post("/admin/avond/nieuw", data={"starts_at": when, "notify": "true"})
    assert "Avond geprikt" in r.text
    assert "Ben je erbij? →" in anna.get("/").text

    # Aanwezigheid
    anna.post("/avond/aanwezig", data={"attending": "true"})
    bram.post("/avond/aanwezig", data={"attending": "false"})
    page = anna.get("/avond").text
    assert "1 komt: Anna" in page
    assert "Je bent erbij" in anna.get("/").text

    # Interessante vragen: maximaal 3, alleen al gestelde vragen
    qids = ids_in(page, r'name="question_id" value="(\d+)"')
    assert len(qids) == 6  # ronde 1 en 2 zijn geopend, latere rondes niet
    with SessionLocal() as db:
        future_q = db.query(Question).join(Round).filter(Round.opens_at > utcnow()).first().id
    anna.post("/avond/onderwerpen", data={"question_id": [qids[0], qids[1], future_q]})
    bram.post("/avond/onderwerpen", data={"question_id": [qids[1]]})
    page = anna.get("/avond").text
    assert page.count("checked") >= 2

    # Eigen inbreng
    anna.post("/avond/inbreng", data={"kind": "vraag", "text": "Bestaat er een goed leven zonder twijfel?"})
    bram.post("/avond/inbreng", data={"kind": "inzicht", "text": "Ik twijfel meer dan ik dacht"})
    assert "Bestaat er een goed leven" in anna.get("/avond").text
    assert "Ik twijfel meer" not in anna.get("/avond").text  # andermans inbreng niet zichtbaar

    admin_page = admin.get("/admin/avond").text
    assert "Ja · 1" in admin_page and "Nee · 1" in admin_page
    assert "2×" in admin_page  # vraag 2 door Anna en Bram gekozen
    assert "Ik twijfel meer dan ik dacht" in admin_page and "Bram" in admin_page

    # Inbreng verwijderen
    page = bram.get("/avond").text
    cid = ids_in(page, r'/avond/inbreng/(\d+)/verwijder')[0]
    bram.post(f"/avond/inbreng/{cid}/verwijder")
    assert "Ik twijfel meer" not in admin.get("/admin/avond").text


def test_push_subscribe(clients):
    r = clients["Eva"].post(
        "/push/subscribe", json={"endpoint": "https://push.example/abc", "keys": {"p256dh": "x", "auth": "y"}}
    )
    assert r.json() == {"ok": True}
    assert "1" in clients["Jeroen"].get("/admin").text


def test_question_edit_keeps_answered_options(clients):
    admin = clients["Jeroen"]
    with SessionLocal() as db:
        q = db.query(Question).filter(Question.round_id.is_not(None)).order_by(Question.position).first()
        qid = q.id
    page = admin.get(f"/admin/vraag/{qid}").text
    assert "Reflectie na het kiezen" in page
    admin.post(
        f"/admin/vraag/{qid}",
        data={"title": "Nieuwe titel", "scenario": "x", "active": "on", "text_0": "", "text_1": "B", "text_2": "C", "text_3": "D"},
    )
    with SessionLocal() as db:
        q = db.get(Question, qid)
        assert q.title == "Nieuwe titel"
        assert len(q.options) == 4  # optie 1 had antwoorden en blijft staan
