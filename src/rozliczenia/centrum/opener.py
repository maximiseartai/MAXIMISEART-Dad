from __future__ import annotations

from functools import cache
import ssl
import urllib.request


def opener(*handlers: urllib.request.BaseHandler) -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=_tls()), *handlers)


@cache
def _tls() -> ssl.SSLContext:
    context = ssl.create_default_context()
    # ZEWNĘTRZNE: http.client ustawia ALPN http/1.1 tylko w kontekście TLS, który tworzy sam, a nie w podanym (CPython Lib/http/client.py, HTTPSConnection i _create_https_context)
    context.set_alpn_protocols(["http/1.1"])
    return context
