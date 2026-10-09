# Yolbulan — çalışma kuralları

## Her kod değişikliğinden sonra build al

Kodda (`*.py`, `kurallar.json`, `requirements.txt`, `derle.py`) her değişiklikten sonra Windows EXE'yi yeniden derle ve sonucu doğrula:

```bash
.venv/Scripts/python.exe derle.py
```

- Başarılı build sonunda `dist/Yolbulan/Yolbulan.exe` bulunmalı ve komut `Derlendi:` yazmalı. Hata olursa düzeltmeden işi bitmiş sayma; hatayı kullanıcıya bildir.
- Derlemeden önce çalışan `Yolbulan.exe` kapatılmalı; açıksa `dist/Yolbulan` değiştirilemez.
- `DERLE.cmd` sonda `pause` beklediği için otomatik çalıştırmada doğrudan `derle.py` kullan.
- Yalnız belge (`*.md`) değişikliklerinde build gerekmez.
