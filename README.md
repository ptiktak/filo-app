# jeroen & pep filosofie app

Een PWA voor een vriendengroep van 10 tot 20 mensen, met twee onderdelen:

- **Vragen**: om de 2 à 3 dagen krijg je een melding met een paar filosofische dilemma's. Je antwoordt (optioneel met een korte toelichting), voorspelt wat de meerderheid en een vriend kiezen, en ziet daarna een korte reflectie en de groepsverdeling.
- **Avond**: in Beheer prik je een vaste avond (alleen datum en tijd). Iedereen geeft aan of hij of zij erbij is, kiest maximaal 3 vragen die het interessantst zijn om te bespreken, en kan zelf een vraag of inzicht inbrengen.

**Stack:** FastAPI met server-rendered Jinja-templates, SQLAlchemy (lokaal SQLite, op Railway Postgres) en Web Push (VAPID).

## Lokaal draaien

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv -r requirements-dev.txt
cp .env.example .env            # vul in; VAPID-sleutels via het script hieronder
.venv/Scripts/python scripts/generate_vapid.py   # (macOS/Linux: .venv/bin/python)
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8060
```

Open daarna http://localhost:8060/uitnodiging/dev-uitnodiging (deelnemer) of http://localhost:8060/beheer/dev-beheer (beheerder). Dit zijn de standaardtokens voor lokaal gebruik.

Tests draaien met `.venv/Scripts/python -m pytest -q`.

## Deployen op Railway

1. Push deze repo naar GitHub (privé).
2. Maak in Railway een nieuw project: **Deploy from GitHub repo** en kies deze repo.
3. Voeg in hetzelfde project een **Postgres**-database toe.
4. Ga bij de app-service naar **Variables** en kies **Raw Editor**. Plak daar de inhoud van `.env.production`. Dat bestand staat alleen lokaal en niet in git; maak het opnieuw met `generate_vapid.py` en `secrets.token_urlsafe` als het kwijt is. `DATABASE_URL=${{Postgres.DATABASE_URL}}` verwijst naar de database.
5. Ga naar **Settings**, dan **Networking**, en kies **Generate Domain**. Dat geeft de app een https-adres.
6. Open `https://<domein>/beheer/<ADMIN_TOKEN>`, vul je naam in, en kopieer in Beheer de vriendenlink.

Railway bouwt met Nixpacks (Python uit `.python-version`, pakketten uit `requirements.txt`) en start `scripts/start.py`. Tabellen en de twintig standaardvragen worden bij de eerste start aangemaakt. Draai **één** instance, want de notificatie-loop zit in het webproces.

Moet een link opnieuw? Verander `INVITE_TOKEN` of `ADMIN_TOKEN` in Railway. Wie al ingelogd is, blijft ingelogd.

## Beheer

| Waar | Wat |
|---|---|
| Planning | Verdeel de vragen over rondes (standaard 3 per ronde, om en om 2 en 3 dagen). Je kunt een ronde verplaatsen of meteen openen. Een ronde blijft open tot de volgende opent, en meldingen gaan alleen tussen 9:00 en 21:00. |
| Vragen | Vragen, antwoordopties en reflectieteksten bewerken. |
| Avond | Een avond prikken (datum en tijd, met een optionele melding naar iedereen). Je ziet wie komt, welke vragen het populairst zijn en wie wat inbrengt. |
| Overzicht | Deelnemers beheren en een melding naar iedereen sturen. |

## Privacy in het spel

- Deelnemers zien nooit elkaars antwoorden, toelichtingen of inbreng. Ze zien alleen percentages, en die pas vanaf `MIN_STATS_ANSWERS` (standaard 6) antwoorden.
- Bij "voorspel een vriend" zie je na sluiting alleen of je goed zat.
- Wie er komt naar de avond is wel voor iedereen zichtbaar.
- Jeroen en Pep (beheer) kunnen alles zien.

Inloggen gaat via de link plus een naam. Wie de vriendenlink heeft, kan dus ook als een andere vriend inloggen, maar niet als beheerder. Voor een vriendengroep is dat acceptabel.
