# Laskutettavuus- ja kerroin-tagit raportissa

**Päivä:** 2026-08-11
**Tila:** hyväksytty, odottaa toteutusta

## Tavoite

Toggl-kirjausten tageja käytetään kahteen asiaan, joita raportti ei tällä hetkellä tunne:

1. `ei-laskutettava` — kirjaus ei kuulu laskutettavaan työhön. Nämä rivit halutaan PDF:ään omana listanaan, ja `--only-billable`-lipulla kokonaan pois.
2. `x2` — työsessioon tai palaveriin osallistui kaksi henkilöä, joten tunnit kaksinkertaistetaan. Rivillä pitää näkyä, mistä kerroin tulee.

## Mittausdata (2026-08-11)

Päätökset perustuvat todelliseen dataan aikaväliltä 2026-05-11–2026-08-11 (36 kirjausta):

| Signaali | Osumia |
| --- | --- |
| `ei-laskutettava`-tag | 7 |
| `x2`-tag | 4 |
| `billable: true` | **0** |

Kaikilla työtilan projekteilla on `billable: false`, eikä yhdelläkään kirjauksella ole `billable: true`. Toggl-käyttöliittymän laskutettavuusvalinta ei siis ole tässä työtilassa käytössä.

## Päätökset

### 1. Laskutettavuus tulkitaan pelkästä tagista

Rivi on ei-laskutettava, jos sillä on tag `ei-laskutettava` (kirjainkoko ei merkitse, ympäröivät välilyönnit siivotaan).

Toggl API:n `billable`-kenttä **tallennetaan välimuistiin mutta ei vaikuta luokitteluun**. Jos `billable` otetaan myöhemmin käyttöön, sääntöä voi muuttaa ilman uutta hakua.

Perustelu: mittausdatan mukaan `billable` on aina `false`. Jos sitä käytettäisiin luokitteluun, jokainen rivi päätyisi ei-laskutettavien listaan ja laskutettavien taulukko jäisi tyhjäksi.

Työtilassa on myös tag `laskutettava` (id 1675510). Sitä ei käytetä: poissaolo ei ole luotettava signaali, koska valtaosaa kirjauksista ei ole tagitettu lainkaan.

### 2. Kerroin luetaan `x{N}`-muotoisesta tagista

Tag `x2` tarkoittaa kerrointa 2. Tagi tulkitaan säännöllisellä lausekkeella `^x(\d+)$`, joten `x3` toimii ilman lisätyötä. Numero tarvitaan joka tapauksessa selitetekstiin (`2 hlöä`), joten yleistys ei kasvata koodia.

Jos rivillä ei ole kerrointagia, kerroin on 1.

### 3. Pyöristys ensin, kerroin sen jälkeen

```
per_person = round_up_half_hour(seconds)    # tai seconds_to_hours(), jos --exact-hours
row_total  = per_person * multiplier
```

Perustelu: henkilökohtainen osuus on aina siisti 0,5 tunnin lohko, joten selitetekstin laskutoimitus täsmää sivulla. Toisin päin laskettuna teksti näyttäisi muodolta `2 hlöä × 0,33 h, yhteensä 1 h`.

`row_total` menee `Aika (h)` -sarakkeeseen ja summiin.

### 4. Tagit ovat toisistaan riippumattomia

Rivi, jolla on sekä `ei-laskutettava` että `x2`, päätyy ei-laskutettavien taulukkoon **ja** sen tunnit kaksinkertaistetaan siellä.

## Tietomalli

`time_entries`-tauluun kaksi saraketta:

| Sarake | Tyyppi | Oletus |
| --- | --- | --- |
| `billable` | `INTEGER NOT NULL` | `1` |
| `tags` | `TEXT NOT NULL` | `'[]'` (JSON-taulukko) |

Migraatio ajetaan `_init_db`-metodissa: `PRAGMA table_info(time_entries)` kertoo puuttuvat sarakkeet, jotka lisätään `ALTER TABLE`-lauseilla. Olemassa oleva `toggl_cache.sqlite` päivittyy paikallaan, eikä sitä tarvitse poistaa.

`normalize_entry` lukee `entry["billable"]` ja `entry["tags"]`. Toggl v9 `/me/time_entries` palauttaa tagit valmiiksi niminä (`"tags": ["ei-laskutettava"]`), joten id-nimi-kartoitusta ei tarvita.

### Uudelleenhaku

Välimuistissa jo olevilla riveillä ei ole tagitietoa. Ne tulkitaan laskutettaviksi ja kertoimeksi 1, kunnes ne haetaan uudelleen:

```bash
python generate_invoice_pdf.py fetch --from 2026-05-11 --to 2026-08-11
```

Tätä vanhempaa dataa ei voi hakea uudelleen tällä komennolla, ks. *Rajaukset*.

## Luokittelufunktiot

Puhtaita funktioita rivisanakirjojen yli, ei I/O:ta:

```python
NON_BILLABLE_TAG = "ei-laskutettava"
MULTIPLIER_RE = re.compile(r"^x(\d+)$", re.IGNORECASE)

def is_non_billable(row) -> bool     # tag löytyy, kirjainkoko ei merkitse
def multiplier(row) -> int           # "x2" → 2, ei tagia → 1
def split_billable(rows) -> Tuple[List[dict], List[dict]]   # (laskutettavat, ei-laskutettavat)
```

`split_billable` säilyttää alkuperäisen järjestyksen molemmissa listoissa.

## PDF

Kaksi taulukkoa, kummallakin omat summansa. Yhteissummaa ei tulosteta: laskun liitteen kokonaistunnit ovat laskutettavien summa.

```
Työraportti — Aikaväli: 01.06.2026–31.07.2026

┌ Pvm | Asiakas | Projekti | Kuvaus | Aika (h) ┐
│ ...laskutettavat rivit...                    │
│                    Yhteensä          │ 42.50 │
│                    Yhteensä (HTP)    │  5.67 │
└──────────────────────────────────────────────┘

Ei-laskutettavat

┌ Pvm | Asiakas | Projekti | Kuvaus | Aika (h) ┐
│ ...tagitetut rivit...                        │
│                    Yhteensä          │  8.00 │
│                    Yhteensä (HTP)    │  1.07 │
└──────────────────────────────────────────────┘
```

Toinen taulukko ja sen otsikko tulostetaan vain, jos ei-laskutettavia rivejä on. Kun niitä ei ole, PDF näyttää täsmälleen nykyiseltä.

### Refaktorointi

`generate_pdf` rakentaa taulukon tällä hetkellä paikallaan noin 70 rivillä. Taulukon rakennus eriytetään:

```python
def build_entries_table(rows, theme, col_widths, desc_style, exact_hours) -> Table
```

Sarakeleveydet lasketaan **kerran kaikista riveistä** ja annetaan molemmille taulukoille, jotta ne asettuvat sivulla kohdakkain.

### Kerroinrivin esitys

Kun kerroin on suurempi kuin 1, `Kuvaus`-soluun tulee toinen kappale:

```
Suunnittelupalaveri asiakkaan kanssa          2.00
2 hlöä × 1 h, yhteensä 2 h
```

Muoto: `{N} hlöä × {per_person} h, yhteensä {total} h`

Kielitoimiston ohjeiden mukaisesti:

- `hlö` on sisälyhenne, joten ei pistettä eikä kaksoispistettä taivutuksessa: `hlöä`
- desimaalierotin on pilkku: `0,5 h`
- luvun ja yksikön väliin välilyönti: `1 h`
- kertomerkki on `×`, ei kirjain `x`

Lukujen muotoilu selitetekstissä: enintään kaksi desimaalia, perässä olevat nollat karsitaan, ja desimaalipiste korvataan pilkulla. Siis `1 h`, `0,5 h`, `1,75 h` — ei `1,00 h`. Sama sääntö koskee sekä henkilökohtaista osuutta että yhteissummaa, myös `--exact-hours`-tilassa.

Tyyli: sama fontti pistekokoa pienempänä, harmaa (`#666666`).

**Tietoinen epäjohdonmukaisuus:** `Aika (h)` -sarake käyttää edelleen pistettä (`2.00`), koska sarakkeen muotoilu on olemassa olevaa toimintaa eikä sen muuttamista pyydetty. Selitetekstissä käytetään suomen kielen mukaista pilkkua. Koko raportin voi siirtää pilkkuun myöhemmin erikseen.

## `list`-komento

Laskutettavat ensin, sitten tyhjä rivi, otsikko ja ei-laskutettavat:

```
11.06.2026 | Asiakas | Projekti | Kuvaus | 2.00h (2 hlöä × 1 h, yhteensä 2 h)
...

Ei-laskutettavat:
14.06.2026 | Asiakas | Sisäiset työt | Palaveri | 1.00h
```

Kerroinselite tulee samalle riville sulkeisiin. `list` näyttää edelleen tarkat tunnit ilman 0,5 tunnin pyöristystä, kuten nytkin — kerroin lasketaan tarkoista tunneista.

Ei-laskutettavien osuus ja otsikko tulostetaan vain, jos rivejä on.

## Komentoriviliput

`--only-billable` lisätään sekä `pdf`- että `list`-alikomentoon. Merkitys on sama: jätä `ei-laskutettava`-tagitetut rivit kokonaan pois.

Jos lipun kanssa laskutettavia rivejä ei jää yhtään, komento tulostaa nykyisen virheilmoituksen (`No matching cached entries found.`) ja palauttaa paluuarvon 4.

## Virheilmoitukset

`TogglClient.get` ei tällä hetkellä näytä Togglin vastausrunkoa, vaikka README lupaa muodon `Toggl response body: "..."`. Korjataan:

1. `get` liittää vastausrungon `HTTPError`-poikkeuksen viestiin.
2. `fetch` nappaa `HTTPError`-poikkeuksen ja tulostaa ohjeen raa'an jäljitysvedoksen sijaan:

```
Toggl API rejected the request: start_date must not be earlier than 2026-05-11
Toggl only serves ~3 months of history via this endpoint.
Try: --from 2026-05-11
```

Paluuarvo 5.

Päivämäärä poimitaan vastausrungosta säännöllisellä lausekkeella. Jos poiminta ei osu, ohjeteksti jätetään pois ja vastausrunko tulostetaan sellaisenaan.

## Siivous työn alla olevassa koodissa

`generate_pdf`-kutsu on sisennetty `pdf`-haaran ulkopuolelle (rivit 474–477). Se toimii vain siksi, että `fetch` ja `list` palaavat aiemmin. Kutsu siirretään haaran sisään ja sen alapuoliset saavuttamattomat rivit poistetaan.

## Testit

Uusi `tests/test_billable.py`:

- `is_non_billable`: tagi löytyy, kirjainkoko vaihtelee, ympärillä välilyöntejä, muita tageja mukana, ei tageja lainkaan
- `multiplier`: `x2` → 2, `X2` → 2, `x3` → 3, ei tagia → 1, muut tagit eivät osu (`x`, `2x`, `xa`)
- `split_billable`: jako oikein, järjestys säilyy, tyhjä syöte
- kerroinlaskenta: pyöristys ennen kerrointa molemmilla `exact_hours`-arvoilla
- selitetekstin muotoilu: `2 hlöä × 1 h, yhteensä 2 h` ja `2 hlöä × 0,5 h, yhteensä 1 h`

Olemassa olevat `tests/test_rounding.py` -testit pysyvät ennallaan.

## Rajaukset

**Python 3.9.** Ympäristö on Python 3.9, joten `X | Y` -tyyppisyntaksia ei käytetä ajonaikaisesti eikä `match`-lauseita. Tiedostossa on `from __future__ import annotations`, joten `Tuple[...]`-annotaatiot toimivat.

**Historiallinen haku ei kuulu tähän muutokseen.** `/me/time_entries` palauttaa vain noin kolmen kuukauden historian (tänään 2026-05-11 alkaen). Reports API v3 palauttaa vanhempaakin dataa, ja se todennettiin toimivaksi tälle työtilalle, mutta vastauksen muoto poikkeaa (`tag_ids` nimien sijaan, sisäkkäinen `time_entries`-taulukko, sivutus). Tämä toteutetaan omana muutoksenaan omalla määrittelyllään.

Käytännön seuraus: huhti–toukokuun kirjaukset jäävät välimuistiin ilman tageja, jolloin ne näkyvät laskutettavina ja kertoimella 1.

**Toggl-laskutettavuusvalinta.** `billable`-kenttä tallennetaan mutta jätetään käyttämättä.

**Yhteissumma.** Laskutettavien ja ei-laskutettavien yhteenlaskettua summaa ei tulosteta.
