"""Ustawienia Centrum (ADR 0032): pliki Ustawień w ``config``, ich Historia i pamięć mają jednego właściciela,
``owner.CentrumSettings``; plik Folderów i motywu opisuje ``folders``.

Pakiet niczego nie wczytuje przy imporcie, więc moduł, który bierze z niego tylko nazwę pliku albo typ, nie zależy od
zapisu plików (``atomic_file``)."""
