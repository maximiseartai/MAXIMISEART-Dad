"""Otwieracz żądań HTTP Centrum z jednym kontekstem TLS na proces.

``urllib.request.build_opener`` bez podanego ``HTTPSHandler`` tworzy nowy kontekst TLS przy każdym otwieraczu, także do
``http://``, a na Windows wczytuje on wtedy cały magazyn certyfikatów systemu: w sondzie #1673 na runnerze Windows 3.13
trwało to 42–75 ms (pierwsze w procesie 242 ms), poza limitem czasu żądania. Zjadało to limit sprawdzenia Wydań (#1580)
i limit czekania launchera na ``health`` (``version.running_centrum``). Dlatego otwieracz w ``src/`` daje tylko
``opener`` (zakaz ``build_opener`` i ``urlopen`` w ``src/ruff.toml``). Moduł używa tylko biblioteki standardowej:
launcher woła ``health`` przed wczytaniem FastAPI, a opiekun ponownego startu działa z jego kopii.
"""

from __future__ import annotations

from functools import cache
import ssl
import urllib.request


def opener(*handlers: urllib.request.BaseHandler) -> urllib.request.OpenerDirector:
    """Otwieracz z ``handlers`` i ze wspólnym kontekstem TLS procesu."""

    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=_tls()), *handlers)


@cache
def _tls() -> ssl.SSLContext:
    """Kontekst TLS procesu z certyfikatami systemu wczytanymi raz.

    Certyfikat dodany do systemu w czasie pracy Centrum liczy się więc dopiero po jego ponownym starcie. ALPN mówi tylko
    ``http/1.1``, jak kontekst, który ``urllib`` tworzy sam.
    """

    context = ssl.create_default_context()
    context.set_alpn_protocols(["http/1.1"])
    return context
