"""Pobiera dane z Garmin Connect i zapisuje je jako JSON w katalogu data/.

Układ:
  data/daily/RRRR-MM-DD.json        - sen, kalorie, kroki, HR, HRV, stres,
                                      Body Battery, SpO2, oddech, gotowość,
                                      status treningowy, VO2max, waga
  data/activities/RRRR-MM-DD_<id>_<typ>.json - każdy trening z detalami
  data/activities/fit/<id>.fit      - surowy plik FIT (opcjonalnie, --fit)
  data/latest/*.json                - aktualne wskaźniki (status treningowy,
                                      VO2max, predykcje, rekordy, strefy HR)
  data/state.json                   - znacznik ostatniej synchronizacji

Użycie:
  uv run scripts/garmin_sync.py                # ostatnie 3 dni + nowe treningi
  uv run scripts/garmin_sync.py --days 30      # dociągnij 30 dni wstecz
  uv run scripts/garmin_sync.py --since 2025-10-01
  uv run scripts/garmin_sync.py --force        # nadpisz istniejące dni
  uv run scripts/garmin_sync.py --fit          # dodatkowo ściągnij pliki FIT
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectTooManyRequestsError,
)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TOKENSTORE = os.environ.get("GARMINTOKENS", "~/.garminconnect")
PAUSE = float(os.environ.get("GARMIN_PAUSE", "0.4"))  # sekundy między zapytaniami
# Ostatnie N dni są odświeżane zawsze, bo Garmin uzupełnia je z opóźnieniem
# (np. sen z nocy, status treningowy przeliczany rano).
REFRESH_TAIL_DAYS = 2

log = logging.getLogger("garmin_sync")


# --------------------------------------------------------------------------- utils
def dump(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True))
    tmp.replace(path)


def call(fn: Callable[[], Any], errors: dict[str, str], key: str) -> Any:
    """Wywołuje endpoint; błąd zapisuje do `errors` zamiast przerywać dzień."""
    try:
        out = fn()
    except GarminConnectTooManyRequestsError:
        log.warning("%s: 429, czekam 60 s", key)
        time.sleep(60)
        try:
            out = fn()
        except Exception as e:  # noqa: BLE001
            errors[key] = f"{type(e).__name__}: {e}"
            return None
    except Exception as e:  # noqa: BLE001
        errors[key] = f"{type(e).__name__}: {e}"
        return None
    finally:
        time.sleep(PAUSE)
    return out


def daterange(start: dt.date, end: dt.date):
    d = start
    while d <= end:
        yield d
        d += dt.timedelta(days=1)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "activity"


class Progress:
    """Pasek postępu z szacowanym czasem do końca.

    W terminalu rysuje jedną odświeżaną linię. W logu (launchd, przekierowanie
    do pliku) wypisuje zwykłe linie z licznikiem i procentem.
    """

    WIDTH = 30

    def __init__(self, label: str, total: int) -> None:
        self.label, self.total, self.done = label, total, 0
        self.t0 = time.monotonic()
        self.tty = sys.stderr.isatty()

    def _eta(self) -> str:
        if not self.done:
            return "--:--"
        left = (time.monotonic() - self.t0) / self.done * (self.total - self.done)
        m, s = divmod(int(left), 60)
        return f"{m:02d}:{s:02d}"

    def step(self, what: str) -> None:
        """Wywołaj PRZED pobraniem elementu `what`."""
        pct = self.done / self.total * 100 if self.total else 100
        head = f"{self.label} {self.done + 1}/{self.total} {pct:3.0f}% ETA {self._eta()}"
        if self.tty:
            fill = int(self.WIDTH * self.done / max(self.total, 1))
            bar = "█" * fill + "░" * (self.WIDTH - fill)
            sys.stderr.write(f"\r\033[K{bar} {head}  {what}"[:160])
            sys.stderr.flush()
        else:
            log.info("[%s] %s", head, what)

    def advance(self) -> None:
        self.done += 1

    def close(self) -> None:
        if self.tty and self.total:
            took = int(time.monotonic() - self.t0)
            sys.stderr.write(
                f"\r\033[K{'█' * self.WIDTH} {self.label} {self.total}/{self.total} "
                f"100% w {took // 60}:{took % 60:02d}\n"
            )
            sys.stderr.flush()


# --------------------------------------------------------------------------- daily
def fetch_day(g: Garmin, day: dt.date) -> dict[str, Any]:
    c = day.isoformat()
    err: dict[str, str] = {}
    out: dict[str, Any] = {
        "date": c,
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        # dzień: kalorie, kroki, HR spoczynkowe, stres, Body Battery, minuty intensywne
        "summary": call(lambda: g.get_user_summary(c), err, "summary"),
        "sleep": call(lambda: g.get_sleep_data(c), err, "sleep"),
        "hrv": call(lambda: g.get_hrv_data(c), err, "hrv"),
        "stress": call(lambda: g.get_stress_data(c), err, "stress"),
        "body_battery": call(lambda: g.get_body_battery(c), err, "body_battery"),
        "heart_rate": call(lambda: g.get_heart_rates(c), err, "heart_rate"),
        "respiration": call(lambda: g.get_respiration_data(c), err, "respiration"),
        "spo2": call(lambda: g.get_spo2_data(c), err, "spo2"),
        "steps": call(lambda: g.get_steps_data(c), err, "steps"),
        "intensity_minutes": call(
            lambda: g.get_intensity_minutes_data(c), err, "intensity_minutes"
        ),
        "hydration": call(lambda: g.get_hydration_data(c), err, "hydration"),
        "training_readiness": call(
            lambda: g.get_training_readiness(c), err, "training_readiness"
        ),
        "training_status": call(lambda: g.get_training_status(c), err, "training_status"),
        "max_metrics": call(lambda: g.get_max_metrics(c), err, "max_metrics"),  # VO2max
        "fitness_age": call(lambda: g.get_fitnessage_data(c), err, "fitness_age"),
        "weigh_ins": call(lambda: g.get_daily_weigh_ins(c), err, "weigh_ins"),
    }
    if err:
        out["_errors"] = err
    return out


def sync_daily(g: Garmin, start: dt.date, end: dt.date, force: bool) -> int:
    tail_from = end - dt.timedelta(days=REFRESH_TAIL_DAYS)
    todo = [
        day
        for day in daterange(start, end)
        if force
        or day >= tail_from
        or not (DATA / "daily" / f"{day.isoformat()}.json").exists()
    ]
    skipped = (end - start).days + 1 - len(todo)
    if skipped:
        log.info("dni: %d do pobrania, %d już są", len(todo), skipped)
    bar = Progress("dni", len(todo))
    for day in todo:
        bar.step(day.isoformat())
        dump(DATA / "daily" / f"{day.isoformat()}.json", fetch_day(g, day))
        bar.advance()
    bar.close()
    return len(todo)


# --------------------------------------------------------------------------- activities
def fetch_activity(g: Garmin, a: dict[str, Any]) -> dict[str, Any]:
    aid = str(a["activityId"])
    err: dict[str, str] = {}
    out: dict[str, Any] = {
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "summary": a,
        "details": call(lambda: g.get_activity(aid), err, "details"),
        "splits": call(lambda: g.get_activity_splits(aid), err, "splits"),
        "laps": call(lambda: g.get_activity_laps(aid), err, "laps"),
        "hr_zones": call(lambda: g.get_activity_hr_in_timezones(aid), err, "hr_zones"),
        "weather": call(lambda: g.get_activity_weather(aid), err, "weather"),
    }
    if "strength" in (a.get("activityType") or {}).get("typeKey", ""):
        out["exercise_sets"] = call(
            lambda: g.get_activity_exercise_sets(aid), err, "exercise_sets"
        )
    if err:
        out["_errors"] = err
    return out


def sync_activities(
    g: Garmin, start: dt.date, end: dt.date, force: bool, fit: bool
) -> int:
    acts = g.get_activities_by_date(start.isoformat(), end.isoformat()) or []

    def target(a: dict[str, Any]) -> Path:
        day = (a.get("startTimeLocal") or "")[:10] or "unknown"
        typ = slug((a.get("activityType") or {}).get("typeKey", ""))
        return DATA / "activities" / f"{day}_{a['activityId']}_{typ}.json"

    todo = [a for a in acts if force or not target(a).exists()]
    if len(acts) > len(todo):
        log.info("treningi: %d do pobrania, %d już są", len(todo), len(acts) - len(todo))
    bar = Progress("treningi", len(todo))
    for a in todo:
        aid = str(a["activityId"])
        path = target(a)
        bar.step(f"{path.name[:10]} {a.get('activityName')}")
        dump(path, fetch_activity(g, a))
        bar.advance()
        if fit:
            fit_path = DATA / "activities" / "fit" / f"{aid}.zip"
            if not fit_path.exists():
                try:
                    fit_path.parent.mkdir(parents=True, exist_ok=True)
                    fit_path.write_bytes(
                        g.download_activity(
                            aid, dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL
                        )
                    )
                except Exception as e:  # noqa: BLE001
                    log.warning("FIT %s: %s", aid, e)
                time.sleep(PAUSE)
    bar.close()
    return len(todo)


# --------------------------------------------------------------------------- latest
def sync_latest(g: Garmin, today: dt.date) -> None:
    c = today.isoformat()
    year_ago = (today - dt.timedelta(days=365)).isoformat()
    err: dict[str, str] = {}
    items: dict[str, Callable[[], Any]] = {
        "training_status": lambda: g.get_training_status(c),
        "training_readiness": lambda: g.get_training_readiness(c),
        "max_metrics": lambda: g.get_max_metrics_latest(c),
        "race_predictions": lambda: g.get_race_predictions(),
        "endurance_score": lambda: g.get_endurance_score(year_ago, c),
        "hill_score": lambda: g.get_hill_score(year_ago, c),
        "lactate_threshold": lambda: g.get_lactate_threshold(),
        "fitness_age": lambda: g.get_fitness_age_details(c),
        "personal_records": lambda: g.get_personal_record(),
        "heart_rate_zones": lambda: g.get_heart_rate_zones_v2(),
        "training_load_4w": lambda: g.get_training_four_week_load_balance(c),
        "devices": lambda: g.get_devices(),
        "body_composition_1y": lambda: g.get_body_composition(year_ago, c),
    }
    for key, fn in items.items():
        val = call(fn, err, key)
        if val is not None:
            dump(DATA / "latest" / f"{key}.json", val)
    for key, msg in err.items():
        log.warning("latest/%s: %s", key, msg)


# --------------------------------------------------------------------------- main
def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--days", type=int, default=3, help="ile dni wstecz (domyślnie 3)")
    p.add_argument("--since", type=dt.date.fromisoformat, help="od daty RRRR-MM-DD")
    p.add_argument("--until", type=dt.date.fromisoformat, help="do daty (domyślnie dziś)")
    p.add_argument("--force", action="store_true", help="nadpisz istniejące pliki")
    p.add_argument("--fit", action="store_true", help="ściągaj też oryginalne pliki FIT")
    p.add_argument("--no-latest", action="store_true", help="pomiń data/latest")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("garminconnect").setLevel(logging.WARNING)

    end = args.until or dt.date.today()
    start = args.since or (end - dt.timedelta(days=args.days - 1))

    g = Garmin()
    try:
        g.login(TOKENSTORE)
    except GarminConnectAuthenticationError as e:
        log.error("Brak ważnych tokenów (%s). Uruchom: uv run scripts/garmin_login.py", e)
        return 2

    log.info("zakres %s .. %s", start, end)
    nd = sync_daily(g, start, end, args.force)
    na = sync_activities(g, start, end, args.force, args.fit)
    if not args.no_latest:
        sync_latest(g, end)

    dump(
        DATA / "state.json",
        {
            "last_sync": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "range": [start.isoformat(), end.isoformat()],
            "days_written": nd,
            "activities_written": na,
        },
    )
    log.info("gotowe: %d dni, %d treningów", nd, na)
    return 0


if __name__ == "__main__":
    sys.exit(main())
