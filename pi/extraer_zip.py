"""Descomprime en la Raspberry el zip que manda instalar.ps1 (nombres con tildes incluidos)."""
import os
import sys
import zipfile

src, dest = sys.argv[1], sys.argv[2]
os.makedirs(dest, exist_ok=True)
real = os.path.realpath(dest)
n = 0
with zipfile.ZipFile(src) as z:
    for m in z.infolist():
        target = os.path.realpath(os.path.join(dest, m.filename))
        if not target.startswith(real + os.sep) or m.filename.endswith("/"):
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with z.open(m) as a, open(target, "wb") as b:
            while True:
                chunk = a.read(1 << 20)
                if not chunk:
                    break
                b.write(chunk)
        n += 1
print(f"{n} archivos copiados en {dest}")
