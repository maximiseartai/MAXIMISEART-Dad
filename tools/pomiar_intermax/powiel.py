# mypy: ignore-errors
# ruff: noqa: E401
"""Powiela uporządkowane wiersze syntetycznego INTERMAX nad nimi, do skali taty, chirurgią XML (bez openpyxl).

Kopie stają w wierszach od 2, a oryginalne wiersze, wklejenie i Hiperłącza przesuwają się w dół. Kopie nie mają
Hiperłączy. Użycie: powiel.py WEJŚCIE WYJŚCIE KOPIE
"""
import re, sys, zipfile

src, out, copies = sys.argv[1], sys.argv[2], int(sys.argv[3])
SHEET = "xl/worksheets/sheet2.xml"
z = zipfile.ZipFile(src)
parts = {i.filename: z.read(i) for i in z.infolist()}
xml = parts[SHEET]
start = xml.index(b"<sheetData>") + len(b"<sheetData>")
end = xml.index(b"</sheetData>")
rows = re.findall(rb'<row r="\d+".*?(?:</row>|/>)(?=<row|$)', xml[start:end] + b"", re.S)
rows = [m.group(0) for m in re.finditer(rb'<row r="(\d+)"[^>]*?(?:/>|>.*?</row>)', xml[start:end], re.S)]
numbers = [int(re.match(rb'<row r="(\d+)"', r).group(1)) for r in rows]
header = rows[0]
# uporządkowane wiersze: od 2 do ostatniego wiersza z datą przed żółtym wierszem (fixture: ciągły blok od 2)
block_end = next(i for i, r in enumerate(rows) if b'customFormat="1"' in r and b"<c" not in r)  # żółty wiersz
block = rows[1:block_end]
span = numbers[block_end - 1] - 1
shift = span * copies

def renumber(row: bytes, delta: int) -> bytes:
    return re.sub(rb'(<row r="|<c r="[A-Z]{1,3})(\d+)', lambda m: m.group(1) + str(int(m.group(2)) + delta).encode(), row)

new_rows = [header]
for k in range(copies):
    new_rows += [renumber(r, k * span) for r in block]
new_rows += [renumber(r, shift) for r in rows[1:]]
tail = xml[end:]
tail = re.sub(rb'(<hyperlink\b[^>]*?\sref="[A-Z]{1,3})(\d+)', lambda m: m.group(1) + str(int(m.group(2)) + shift).encode(), tail)
head = re.sub(rb'(<dimension ref="A1:[A-Z]+)(\d+)', lambda m: m.group(1) + str(int(m.group(2)) + shift).encode(), xml[:start])
parts[SHEET] = head + b"".join(new_rows) + tail
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
    for info in z.infolist():
        copied = zipfile.ZipInfo(info.filename, info.date_time)
        copied.compress_type = info.compress_type
        copied._compresslevel = 2
        target.writestr(copied, parts[info.filename])
print("wierszy", len(new_rows), "XML", len(parts[SHEET]))
