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
python generate_invoice_pdf.py fetch --from 2026-06-01 --to 2026-08-11
```

### Toggl API -rajoite (fetch)

Toggl API sallii `start_date`-päivän vain noin 3 kuukauden ajalta taaksepäin hakuhetkestä (liukuva raja, ei kalenterikuukausi). Jos haet liian vanhasta päivästä, API palauttaa HTTP 400 -virheen.

Esimerkki:

```text
Toggl API rejected the request: start_date must not be earlier than 2026-05-11
Toggl only serves ~3 months of history via this endpoint.
Try: --from 2026-05-11
```

Ratkaisu: valitse `--from`-päivä, joka on vähintään API:n ilmoittama aikaisin sallittu päivämäärä.

Huom. Tätä vanhempia kirjauksia ei voi hakea uudelleen. Jos ne ovat jo välimuistissa, ne säilyvät, mutta niiltä puuttuvat tagit (ks. alla).

Listaa cached‑kirjaukset:

```bash
python generate_invoice_pdf.py list --from 2026-06-01 --to 2026-07-31 --project "Projekti X"
```

PDF cached‑kirjauksista:

```bash
python generate_invoice_pdf.py pdf --from 2026-06-01 --to 2026-07-31 --out lasku-liite.pdf
```

PDF-raportti pyöristää oletuksena jokaisen rivin ylöspäin 0,5 tunnin lohkoihin. Lisää `--exact-hours`, jos haluat näyttää kirjatut tunnit ilman pyöristystä.

## Tagit

Raportti tunnistaa kaksi Toggl-tagia. Kirjainkoolla ei ole väliä.

### `ei-laskutettava`

Kirjaus ei kuulu laskutettavaan työhön. Nämä rivit tulostetaan omana listanaan `Ei-laskutettavat`-otsikon alle, omine summineen. Laskutettavien taulukon summa sisältää siis vain laskutettavan työn.

Lipulla `--only-billable` rivit jätetään kokonaan pois. Lippu toimii sekä `pdf`- että `list`-komennossa:

```bash
python generate_invoice_pdf.py list --from 2026-06-01 --to 2026-07-31 --only-billable
python generate_invoice_pdf.py pdf --from 2026-06-01 --to 2026-07-31 --only-billable --out lasku-liite.pdf
```

Toggl-käyttöliittymän oma laskutettavuusvalinta (`billable`) tallennetaan välimuistiin, mutta sitä **ei** käytetä luokitteluun — pelkkä tagi ratkaisee.

### `x2`

Työsessioon osallistui kaksi henkilöä, joten rivin tunnit kerrotaan kahdella. Rivin alle tulostetaan selite:

```text
2 hlöä × 1 h, yhteensä 2 h
```

Tunnit pyöristetään ensin 0,5 tunnin lohkoon ja kerrotaan vasta sen jälkeen, jotta selitteen laskutoimitus täsmää. Myös muut kertoimet toimivat, esimerkiksi `x3`.

Tagit ovat toisistaan riippumattomia: rivi, jolla on sekä `ei-laskutettava` että `x2`, päätyy ei-laskutettavien listaan ja sen tunnit kaksinkertaistetaan siellä.

### Tagien päivitys välimuistiin

Ennen tagituen lisäämistä haetuilla riveillä ei ole tagitietoa, joten ne näkyvät laskutettavina ilman kerrointa. Aja `fetch` uudelleen:

```bash
python generate_invoice_pdf.py fetch --from 2026-05-11 --to 2026-08-11
```

Välimuistin rakenne päivittyy automaattisesti; vanhoja kirjauksia ei tarvitse poistaa.

Teema:

```bash
python generate_invoice_pdf.py pdf --from 2026-06-01 --to 2026-07-31 --theme monospace --out beely.pdf --project "Beely"
```

## Välimuisti (SQLite)

API-kutsut tehdään vain `fetch`-komennolla. Muut komennot lukevat paikallisesta `toggl_cache.sqlite`-tiedostosta.
