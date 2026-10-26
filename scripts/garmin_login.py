"""Jednorazowe logowanie do Garmin Connect.

Pyta o e-mail, hasło (bez echa) i ewentualny kod MFA, po czym zapisuje
tokeny OAuth w ~/.garminconnect/garmin_tokens.json (tylko dla właściciela).
Hasło nie jest nigdzie zapisywane. Kolejne uruchomienia garmin_sync.py
korzystają już tylko z tokenów.
"""

import getpass
import os
import sys

from garminconnect import Garmin, GarminConnectAuthenticationError

TOKENSTORE = os.environ.get("GARMINTOKENS", "~/.garminconnect")


def prompt_mfa() -> str:
    return input("Kod MFA z aplikacji/e-maila Garmina: ").strip()


def main() -> int:
    print("Logowanie do Garmin Connect (dane idą tylko do sso.garmin.com).")
    email = input("E-mail konta Garmin: ").strip()
    password = getpass.getpass("Hasło (nie będzie widoczne): ")
    try:
        client = Garmin(email=email, password=password, prompt_mfa=prompt_mfa)
        client.login(TOKENSTORE)
    except GarminConnectAuthenticationError as e:
        print(f"Logowanie nieudane: {e}", file=sys.stderr)
        return 1
    name = client.get_full_name() or "?"
    print(f"OK, zalogowano jako: {name}")
    print(f"Tokeny zapisane w {os.path.expanduser(TOKENSTORE)}/garmin_tokens.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
