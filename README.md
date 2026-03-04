# Time Report PDF

Generoi Toggl Trackin tuntikirjauksista selkeän A4-PDF:n laskun liitteeksi. Sovellus hakee kirjaukset Toggl API:sta, tallentaa ne SQLite-välimuistiin ja luo PDF:n valitsemalla kirjaukset päivämäärän, asiakkaan ja projektin perusteella.

Huom! Tämä tuökalu on tuotettu Open AI Codexilla. Käytä omalla vastuullasi ja tarkista koodi ennen käyttöä.

## Asennus (venv)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Konfigurointi

Luo `.env` tiedosto (esimerkki `.env.example`):

```
TOGGL_TOKEN=your_token_here
```

## Käyttö

```bash
python generate_invoice_pdf.py fetch --from 2026-01-01 --to 2026-01-31
```

Listaa cached‑kirjaukset:

```bash
python generate_invoice_pdf.py list --from 2026-01-01 --to 2026-01-31 --client "Asiakas Oy" --project "Projekti X"
```

PDF cached‑kirjauksista:

```bash
python generate_invoice_pdf.py pdf --from 2026-01-01 --to 2026-01-31 --out lasku-liite.pdf
```

PDF-raportti pyöristää oletuksena jokaisen rivin ylöspäin 0,5 tunnin lohkoihin. Lisää `--exact-hours`, jos haluat näyttää kirjatut tunnit ilman pyöristystä.

Teema:

```bash
python generate_invoice_pdf.py pdf --from 2026-01-01 --to 2026-01-31 --theme monospace --out lasku-liite.pdf
```

## Välimuisti (SQLite)

API-kutsut tehdään vain `fetch`-komennolla. Muut komennot lukevat paikallisesta `toggl_cache.sqlite`-tiedostosta.
