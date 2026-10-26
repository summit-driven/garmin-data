# garmin-sync

Codzienne archiwum danych z Garmin Connect (sen, kalorie, treningi, wytrenowanie)
zapisywane jako JSON w `data/`. Korzysta z nieoficjalnej biblioteki
[garminconnect](https://github.com/cyberjunky/python-garminconnect).

## Pierwsze uruchomienie

```bash
uv run scripts/garmin_login.py
```

Pyta o e-mail, hasło i kod MFA. Hasło nie jest zapisywane; tokeny OAuth lądują
w `~/.garminconnect/garmin_tokens.json` (poza repo, uprawnienia 600).

```bash
./sync.sh --days 30
```

## Codziennie / na żądanie

```bash
./sync.sh                 # ostatnie 3 dni + nowe treningi + data/latest
./sync.sh --days 7        # dociągnij tydzień
./sync.sh --since 2025-01-01   # pełna historia
./sync.sh --fit           # dodatkowo oryginalne pliki FIT
```

`sync.sh` po pobraniu commituje `data/` i pushuje, jeśli repo ma `origin`.

## Układ danych

| ścieżka | zawartość |
|---|---|
| `data/daily/RRRR-MM-DD.json` | summary (kalorie, kroki, RHR, stres, Body Battery), sleep, hrv, stress, body_battery, heart_rate, respiration, spo2, steps, intensity_minutes, hydration, training_readiness, training_status, max_metrics (VO2max), fitness_age, weigh_ins |
| `data/activities/RRRR-MM-DD_<id>_<typ>.json` | summary, details, splits, laps, hr_zones, weather, exercise_sets (siłownia) |
| `data/activities/fit/<id>.zip` | oryginalny FIT (tylko z `--fit`) |
| `data/latest/*.json` | training_status, training_readiness, max_metrics, race_predictions, endurance_score, hill_score, lactate_threshold, fitness_age, personal_records, heart_rate_zones, training_load_4w, devices, body_composition_1y |
| `data/state.json` | czas i zakres ostatniej synchronizacji |

Ostatnie 2 dni są zawsze odświeżane (Garmin uzupełnia je z opóźnieniem).
Błędy pojedynczych endpointów trafiają do klucza `_errors` w pliku dnia.

## Jeśli logowanie przestanie działać

Garmin co jakiś czas zmienia coś po swojej stronie. Najpierw `uv lock --upgrade-package garminconnect`,
potem ponownie `uv run scripts/garmin_login.py`. Gdyby token wyciekł: Garmin Connect →
Ustawienia konta → Bezpieczeństwo → cofnij dostęp, dopiero potem skasuj plik tokenów.
