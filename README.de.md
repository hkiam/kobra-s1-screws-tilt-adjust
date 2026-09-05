# kobra-s1-screws-tilt-adjust

*[English version: README.md](README.md)*

**Mechanische Druckbett-Justage für den Anycubic Kobra S1 mit
[Rinkhals](https://github.com/rinkhals-community/Rinkhals/).**

Ein Ersatz für Klippers `SCREWS_TILT_ADJUST`, das es auf dieser Plattform nicht
gibt. Das Tool läuft auf dem PC, spricht den Drucker über Moonraker an, tastet
die Punkte über den vier Bettschrauben an und sagt für jede Schraube, wie weit
sie zu drehen ist — in Klipper-Notation.

---

## Inhalt

- [Das Ergebnis](#das-ergebnis)
- [Warum es das gibt](#warum-es-das-gibt)
- [Was es nicht ist](#was-es-nicht-ist)
- [Voraussetzungen](#voraussetzungen)
- [Installation](#installation)
- [Schritt für Schritt](#schritt-für-schritt)
- [Die Ausgabe lesen](#die-ausgabe-lesen)
- [Grenzen: vier Punkte sind eine Ebene](#grenzen-vier-punkte-sind-eine-ebene)
- [Optional: feineres Bed Mesh](#optional-feineres-bed-mesh)
- [Weiterführende Dokumentation](#weiterführende-dokumentation)
- [Sicherheit](#sicherheit)
- [Entwicklung](#entwicklung)
- [Dank](#dank)
- [Lizenz](#lizenz)

---

## Das Ergebnis

Das Testgerät hatte ab Werk diese Abweichungen an den vier Aufnahmepunkten:

```
                    VORHER                                    NACHHER

                    hinten                                    hinten
        1.10 mm             0.40 mm               0.08 mm             0.00 mm
             ┌───────────────────┐                     ┌───────────────────┐
      links  │                   │  rechts      links  │                   │  rechts
             └───────────────────┘                     └───────────────────┘
        0.10 mm             0.00 mm               0.02 mm             0.04 mm
                    vorne                                     vorne

        Spannweite:  1.10 mm                      Spannweite:  0.08 mm
        entspricht:  01:34                        entspricht:  00:07
```

**Von 1,10 mm auf 0,08 mm** — Faktor 13. Die hintere linke Ecke stand über eine
volle Schraubenumdrehung daneben.

Erreicht wurde das in zwei Stufen:

1. **Gedruckte Abstandshalter**, die den Werksversatz vorwegnehmen — der Kobra
   S1 hat ab Werk keine (siehe [docs/SPACER.md](docs/SPACER.md)).
2. **Feinjustage über die Schrauben** mit diesem Tool.

Was das Bed Mesh danach noch ausgleichen muss, ist eine andere Größenordnung.
Statt 1,1 mm Schieflage kompensiert es nur noch die Restwelligkeit der Platte.

---

## Warum es das gibt

Klipper bringt mit
[`SCREWS_TILT_ADJUST`](https://www.klipper3d.org/Manual_Level.html) ein
ausgezeichnetes Werkzeug für die mechanische Bettjustage mit: Es fährt die
Punkte über den Nivellierschrauben an, tastet sie an und sagt, welche Schraube
um wie viel zu drehen ist.

**Auf dem Kobra S1 gibt es dieses Kommando nicht.** Der Drucker fährt kein
echtes Klipper, sondern `gklib` — eine Go-Portierung von Anycubic mit
eingeschränktem Funktionsumfang. `PROBE`, `BED_MESH_CALIBRATE` und vieles
andere sind vorhanden, `SCREWS_TILT_ADJUST` fehlt. Die Firmware zu erweitern
ist keine Option: sie ist proprietär und geschlossen.

**Die Lösung ist, die Logik auszulagern.** Alles, was `SCREWS_TILT_ADJUST`
braucht, ist im Drucker vorhanden:

- ein Kommando zum Antasten (`PROBE`)
- ein Weg, das Ergebnis auszulesen (`probe.last_z_result`)
- Bewegungssteuerung (`G0`/`G1`, `G28`)

Rinkhals stellt über Moonraker eine HTTP- und Websocket-Schnittstelle bereit.
Damit lässt sich die Messschleife komplett vom PC aus fahren — der Drucker
führt nur einzelne Kommandos aus, die Auswertung passiert außerhalb. Das hat
sogar Vorteile: Die Auswertung ist in Python geschrieben, testbar, und lässt
sich erweitern, ohne die Firmware anzufassen.

Ein Umstand kommt entgegen: **Der Kobra S1 tastet mit der Düse selbst an**
(Kraftsensor, `[cs1237]` in der Konfiguration), Probe-Offset ist 0/0. Die
Messpunkte sind damit exakt die Schraubenkoordinaten, ohne Offset-Rechnerei.

---

## Was es nicht ist

> **Dieses Tool ersetzt kein Bed Leveling.** Es schafft die mechanische Basis,
> damit das Bed Mesh anschließend eine leichte Aufgabe hat.

Die Arbeitsteilung:

| | Aufgabe | Womit |
|---|---|---|
| **1. Mechanik** | Bett physisch eben ausrichten | dieses Tool + Schrauben |
| **2. Software** | Restwelligkeit kompensieren | `BED_MESH_CALIBRATE` |

Ein Bed Mesh kann eine Schieflage von über einem Millimeter rechnerisch
ausgleichen — aber es zwingt die Z-Achse dann, bei jeder Bewegung über das Bett
ständig nachzuführen. Das kostet Genauigkeit, belastet die Mechanik und
verschleiert echte Probleme. Je ebener das Bett mechanisch liegt, desto weniger
muss das Mesh tun.

**Nach der Justage muss das Bed Mesh neu erstellt werden** — die Bettlage hat
sich ja geändert.

---

## Voraussetzungen

### Drucker

| | |
|---|---|
| Modell | Anycubic Kobra S1 |
| Firmware | [Rinkhals](https://github.com/rinkhals-community/Rinkhals/), getestet mit `20260901_01` |
| Klipper-Kern | `gklib` auf `rinkhals_gklib.cfg` |
| Netzwerk | Moonraker erreichbar, Standardport 7125 |

**Rinkhals wird zwingend gebraucht.** Die Anycubic-Werksfirmware bietet keinen
offenen Zugang — sie stellt nur eine proprietäre API auf Port 18086 bereit.
Rinkhals setzt ein echtes Moonraker davor, und erst darüber ist der Drucker
steuerbar.

### Worauf das Tool zugreift

Ausschließlich lesend und über Moonraker — es wird nichts an der Firmware
verändert, keine Datei auf dem Drucker angefasst und keine Konfiguration
überschrieben.

| Endpunkt / Objekt | Wofür |
|---|---|
| `GET /printer/info` | Zustand prüfen |
| `GET /printer/objects/query?toolhead` | Position, Achsgrenzen, Homing-Status |
| `GET /printer/objects/query?probe` | Messergebnis (`last_z_result`) |
| `GET /printer/objects/query?extruder&heater_bed` | Temperaturen |
| `GET /printer/objects/query?bed_mesh&gcode_move` | Mesh-Status, Z-Offset |
| `GET /printer/gcode/help` | verfügbare Kommandos ermitteln |
| `POST /printer/gcode/script` | `G28`, `G0`/`G1`, `PROBE`, `M104`/`M140`, `M105` |

Ein **SSH-Zugang ist nicht nötig**. Er war nur bei der Entwicklung nützlich, um
Firmware-Eigenheiten nachzuvollziehen — dokumentiert in
[docs/RINKHALS.md](docs/RINKHALS.md).

### PC

| | |
|---|---|
| Python | ≥ 3.11 |
| Paketmanager | [uv](https://docs.astral.sh/uv/) |
| Betriebssystem | Linux, macOS (getestet), Windows ungetestet¹ |

¹ `bedlevel teach` nutzt `termios` für die Pfeiltasten und läuft auf Windows
nicht. Alle anderen Kommandos sollten funktionieren.

### Mechanik

Die Bettschrauben müssen **mit Spiel gelagert** sein, sodass sich die
Vorspannung über die Schraube einstellen lässt. Beim Kobra S1 ab Werk ist das
nicht gegeben — dort ist ein Umbau nötig, und gedruckte Spacer sind ohnehin
empfehlenswert.

---

## Installation

```bash
git clone https://github.com/hkiam/kobra-s1-screws-tilt-adjust.git
cd kobra-s1-screws-tilt-adjust
uv sync
cp bedlevel.example.toml bedlevel.toml
```

Dann `bedlevel.toml` anpassen — mindestens diese Werte:

| Wert | Bedeutung | Hilfe |
|---|---|---|
| `printer.host` | IP des Druckers | — |
| `screws.points` | Koordinaten über den Schrauben | `bedlevel teach` |
| `screws.cw_lowers_bed` | ob Anziehen das Bett senkt | `bedlevel calibrate-direction` |
| `screws.tolerance_minutes` | wie genau es werden soll | siehe unten |

Prüfen, ob alles passt:

```bash
uv run bedlevel check
```

```
╭────────────────────────────────── Drucker ───────────────────────────────────╮
│ Verbindung: http://192.168.1.50:7125                                      │
│ Zustand: ready                                                               │
╰──────────────────────────────────────────────────────────────────────────────╯
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ Voraussetzung                                      ┃ vorhanden ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ PROBE-Kommando                                     │ ja        │
│ probe.last_z_result                                │ ja        │
│ toolhead-Objekt                                    │ ja        │
│ SCREWS_TILT_ADJUST (dann waere dies hier unnoetig) │ nein      │
└────────────────────────────────────────────────────┴───────────┘
Fahrbereich: X [-6 .. 265]  Y [0 .. 277]  Z [-4 .. 253]
Alles Noetige vorhanden.
```

---

## Schritt für Schritt

### 1. Düse und Platte vorbereiten

Angetastet wird mit der Düse. Ein anhaftender Filamentrest wird bei jedem
Antasten flacher gedrückt und lässt die Messwerte wandern — die häufigste
Ursache unbrauchbarer Messungen. Das Tool kann vor jeder Messung automatisch
wischen (`[wipe]`), sonst von Hand reinigen.

Ebenso wichtig: **Druckplatte plan auflegen.** Ein Krümel zwischen
Federstahlplatte und Magnetunterlage lässt die Platte kippeln — die Messwerte
springen dann zwischen zwei Lagen, und der Median landet in der Lücke
dazwischen.

### 2. Schraubenpositionen einlernen

```bash
uv run bedlevel teach
```

Die Düse fährt zur ersten Schraube, du positionierst mit den Pfeiltasten:

```
[vorne links]  fahre Startposition an ...
  Pfeiltasten: X/Y     Bild-auf/ab oder +/-: Z     1-5: Schrittweite
  Enter: Position uebernehmen     s: ueberspringen     q: abbrechen
  X   41.000   Y   43.000   Z   5.000   Schritt 1 mm
```

| Taste | Wirkung |
|---|---|
| Pfeile | X / Y |
| Bild-auf/ab, `+` / `-` | Z |
| `1`–`5` | Schrittweite 0,1 / 0,5 / 1 / 5 / 10 mm |
| Enter | übernehmen, weiter |
| `s` | Punkt unverändert lassen |
| `q` | abbrechen |

Die Positionen landen in `bedlevel.toml`, die alte Fassung in
`bedlevel.toml.bak`.

### 3. Drehrichtung bestimmen

Ob Anziehen dein Bett hebt oder senkt, hängt an deiner Mechanik. Bei falscher
Annahme macht jede Korrektur es doppelt schlimm:

```bash
uv run bedlevel calibrate-direction "vorne links"
```

Das Kommando misst, lässt dich eine Viertelumdrehung anziehen, misst nach und
nennt den Wert für `cw_lowers_bed`.

### 4. Justieren

```bash
uv run bedlevel level
```

```
Bed Mesh 'default' geladen (Korrektur bis 1.023 mm) - ohne Einfluss auf die
Messwerte, wird beim ersten Messpunkt geprueft.
Heize Bett auf 60 C und Duese auf 140 C ...
  Bett  47.2 C / 60 C   Duese 118.4 C / 140 C
Temperaturen erreicht.
Duese reinigen bei 170 C ...
Zurueck auf Antast-Temperatur 140 C ...
Durchgang 1/2 (4x je Punkt): vorne links -> hinten rechts -> vorne rechts -> hinten links
  vorne links: Vormessung z=-0.4517 (verworfen)
  vorne links: z=-0.4633
  ...
Durchgang 2/2 (4x je Punkt): hinten links -> vorne rechts -> hinten rechts -> vorne links
  ...
Fahre den Druckkopf aus dem Weg ...
```

Dann die Auswertung:

```
        Messung  (Referenz: hinten links, nur-anziehen)
┏━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━┓
┃ Schraube      ┃      XY ┃      z ┃   +/- ┃   Abw. ┃ adjust     ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━┩
│ vorne links   │   41/43 │ -0.627 │ 0.012 │ +0.011 │ (CW 00:01) │
│ vorne rechts  │  211/43 │ -0.522 │ 0.014 │ +0.116 │ (CW 00:10) │
│ hinten rechts │ 211/213 │ -0.515 │ 0.018 │ +0.123 │ CW 00:11   │
│ hinten links  │  41/213 │ -0.638 │ 0.024 │ +0.000 │ (base)     │
└───────────────┴─────────┴────────┴───────┴────────┴────────────┘
╭───────────────────────────────── Kennzahlen ─────────────────────────────────╮
│ Groesste Korrektur: 11 Minuten - noch nachstellen  (Ziel: <= 00:10)          │
│ Spannweite hoch/tief: 0.123 mm = 11 Minuten                                  │
│ Verkippung: X +0.67 mm/m, Y -0.01 mm/m                                       │
│ Bettverzug (nicht wegdrehbar): 0.009 mm = 1 Minute                           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Abweichung zur Referenz (mm) ─╮
│         hinten                 │
│     +0.000     +0.123          │
│         ┌───────────┐          │
│   links │           │ rechts   │
│         └───────────┘          │
│     +0.011     +0.116          │
│         vorne                  │
╰────────────────────────────────╯

Schrauben wie angegeben drehen, dann Enter fuer die naechste Messung (q = beenden):
```

Der Kopf ist zu diesem Zeitpunkt bereits weggefahren und das Bett abgesenkt —
du kommst an alle Schrauben. Drehen, Enter, nächste Runde.

### 5. Bed Mesh neu erstellen

Nach der Justage ist das alte Mesh ungültig. Am Drucker:

```
BED_MESH_CALIBRATE
SAVE_CONFIG
```

Wer konsequent nur angezogen hat, hat das Bett insgesamt abgesenkt — dann
vorher den **Z-Offset** neu setzen.

---

## Die Ausgabe lesen

### Die Drehanweisung

Die Notation folgt Klipper: `CW 01:20` bedeutet **1 volle Umdrehung und
20 Minuten** im Uhrzeigersinn.

| Anzeige | Drehung | bei M4 (0,7 mm) |
|---|---|---:|
| `01:00` | volle Umdrehung, 360° | 0,700 mm |
| `00:30` | halbe Umdrehung, 180° | 0,350 mm |
| `00:15` | Viertelumdrehung, 90° | 0,175 mm |
| `00:05` | kleiner Stups, 30° | 0,058 mm |

`CW` = clockwise = anziehen (bei Rechtsgewinde), `CCW` = counter-clockwise =
lösen. Die Legende unter der Tabelle nennt zusätzlich, in welche Richtung sich
das Bett dabei bewegt — das ist am Gerät eindeutiger als eine Drehrichtung mit
Blickrichtung im Kleingedruckten.

**Klammern bedeuten: nicht nötig, aber wirksam.** `(CW 00:10)` liegt innerhalb
der Toleranz. Das ist wichtig, wenn mehrere Schrauben knapp darunter liegen —
dreht man nur die eine, die überschreitet, wird eine andere zur neuen höchsten
Ecke und die Spannweite bleibt, wo sie war.

`(base)` ist die Referenzschraube: die bleibt stehen.

### Die Toleranz

| Ziel | Bedeutung |
|---|---|
| unter `00:10` | **gut** — für den Alltag ausreichend, den Rest macht das Bed Mesh |
| unter `00:05` | **exzellent** — wenn das Bett möglichst spannungsfrei liegen soll |
| unter `00:02` | **Grenze des mechanischen Spiels** von Schrauben und Lagerung |

### Die Kennzahlen

- **Größte Korrektur** — die stärkste nötige Drehung, mit Einstufung.
- **Spannweite** — Differenz zwischen höchster und tiefster Ecke.
- **Verkippung** — Neigung der Ausgleichsebene in mm/m, getrennt nach X und Y.
  Zeigt, in welche Richtung das Bett kippt.
- **Bettverzug** — was nach dem Ebenenabgleich übrig bleibt. **Die wichtigste
  Zahl, um zu wissen, wann man aufhören sollte** (siehe nächster Abschnitt).

---

## Grenzen: vier Punkte sind eine Ebene

Das Tool justiert **vier Punkte**. Vier Punkte spannen eine Ebene auf — mehr
Information steckt nicht in der Messung. Was sich damit korrigieren lässt:

✅ **Verkippung** — das Bett steht schief, eine Ecke höher als die andere.
✅ **Versatz einzelner Aufnahmepunkte** — eine Ecke hängt durch.

Was sich damit **nicht** korrigieren lässt:

❌ **Welligkeit der Platte** — Berge oder Täler zwischen den Schrauben.
❌ **Verzug** — eine Platte, die sich schüsselt oder wellt.

### Der Bettverzug als Abbruchkriterium

Genau dafür weist die Ausgabe den **Bettverzug** aus: die Restwelligkeit nach
dem Ebenenabgleich. Das Tool legt eine Ausgleichsebene durch die vier
Messpunkte und misst, wie weit die Punkte davon abweichen.

```
Bettverzug (nicht wegdrehbar): 0.009 mm = 1 Minute
```

**Liegt dieser Wert nahe der eingestellten Toleranz, ist die Justage
ausgereizt.** Weiterdrehen verschiebt dann nur noch, welche Ecke danebenliegt.
Der Rest gehört ins Bed Mesh — genau dafür ist es da.

### Wenn das Mesh Berge in der Mitte zeigt

Nach der Justage `BED_MESH_CALIBRATE` laufen lassen und die Karte ansehen. Ein
typisches Bild bei einer verzogenen Platte:

```
     -0.02  -0.01   0.00  -0.01  -0.02
     -0.01   0.12   0.18   0.11  -0.01
      0.00   0.18   0.24   0.17   0.00      ← Berg in der Mitte
     -0.01   0.11   0.17   0.10  -0.01
     -0.02  -0.01   0.00  -0.01  -0.02
```

Die Ecken liegen sauber (das hat die Justage erledigt), aber die Mitte steht
hoch. **Das bekommt keine Schraube weg** — die Platte selbst ist verzogen.

Bei nennenswerter Welligkeit (grob ab 0,15–0,2 mm) ist ein **dickeres oder
steiferes Druckbett** die eigentliche Lösung:

| Option | Anmerkung |
|---|---|
| **Funssor 8 mm Aluminium** | naheliegender Tausch, deutlich steifer als das Original |
| **Feingefrästes Aluminiumbett** | planer als gewalztes Material, entsprechend teurer |
| **Sandwich: 5 mm Original + feingefräste Platte** | ungetestet — mehr Masse bedeutet längere Aufheizzeit und veränderte Wärmeverteilung |

Das Originalbett des Kobra S1 ist 5 mm stark. Mehr Dicke bedeutet mehr
Biegesteifigkeit: Die Platte folgt der Verspannung durch die Schrauben weniger
und bleibt eher plan. Der Preis ist Trägheit — dickere Betten brauchen länger
zum Aufheizen und reagieren langsamer auf Temperaturwechsel.

> **Erst justieren, dann entscheiden.** Ohne saubere mechanische Basis lässt
> sich nicht beurteilen, ob eine Welligkeit von der Platte kommt oder von der
> Verspannung. Der ausgewiesene Bettverzug ist die Zahl, an der man es
> festmacht.

---

## Optional: feineres Bed Mesh

*Nicht Teil dieses Tools, aber die naheliegende Ergänzung dazu.*

Der Kobra S1 tastet für sein Bed Mesh ab Werk **5 × 5 Punkte** ab und
interpoliert dazwischen mit `lagrange`. Für eine mechanisch gut ausgerichtete
Platte reicht das oft — bei erkennbarer Welligkeit ist ein feineres Raster
aber deutlich besser: Ein Berg zwischen zwei Messpunkten wird bei 5 × 5
schlicht übersehen.

Rinkhals bringt dafür `printer.custom.cfg` mit. Der Inhalt dieser Datei wird
mit der Hauptkonfiguration **zusammengeführt**: neue Abschnitte werden ergänzt,
vorhandene Werte überschrieben. Die Werksfirmware bleibt unangetastet.

Auf dem Testgerät sind folgende Anpassungen im Einsatz:

```ini
[probe]
speed: 10.0
final_speed: 10.0
lift_speed: 20.0
samples: 1

[bed_mesh]
speed: 500
horizontal_move_z:2
probe_count:7,7  # original 5,5
algorithm:bicubic

[leviQ3]
bed_temp: 80
```

Was die Änderungen bewirken:

| Wert | ab Werk | geändert | Wirkung |
|---|---|---|---|
| `probe_count` | `5,5` | `7,7` | 49 statt 25 Messpunkte — feineres Raster, erkennt Welligkeit zwischen den Ecken |
| `algorithm` | `lagrange` | `bicubic` | glattere Interpolation, weniger Überschwingen zwischen Stützstellen |
| `probe.speed` | `4.0` | `10.0` | schnelleres Antasten — nötig, sonst dauert 7 × 7 spürbar länger |
| `probe.samples` | `2` | `1` | eine Antastung je Punkt statt zwei |
| `horizontal_move_z` | `3` | `2` | geringere Fahrhöhe zwischen den Punkten |
| `leviQ3.bed_temp` | `55` | `80` | Kalibriertemperatur der Werksroutine |

### So änderst du es

1. In **Mainsail** unter *Machine* die Datei `printer.custom.cfg` öffnen
2. Abschnitte einfügen, speichern
3. **Drucker neu starten** — ein `FIRMWARE_RESTART` genügt hier nicht, weil
   `gklib` die zusammengeführte Konfiguration beim Start einliest
4. Danach `BED_MESH_CALIBRATE` und `SAVE_CONFIG`

Prüfen, ob es angekommen ist:

```bash
curl -s "http://<ip>:7125/printer/objects/query?configfile" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['status']['configfile']['settings']['bed_mesh'])"
```

### Ein Wort zur Reihenfolge

Ein feineres Mesh **ersetzt die mechanische Justage nicht**, es ergänzt sie.
Zuerst die vier Ecken mit diesem Tool ausrichten, dann das Mesh neu erstellen.
Umgekehrt kompensiert das Mesh eine Schieflage, die dort nicht hingehört — und
verschleiert, was mechanisch im Argen liegt.

Umgekehrt gilt: Ein 7 × 7-Mesh macht die Restwelligkeit überhaupt erst
sichtbar. Wenn du nach der Justage wissen willst, ob deine Platte einen Berg in
der Mitte hat, ist das feinere Raster die Voraussetzung dafür.

> **Ohne Gewähr.** Diese Werte stammen von einem einzelnen Gerät. `probe.speed`
> und `samples` beeinflussen, wie fest die Düse aufsetzt — bei zu schnellem
> Antasten kann die Wiederholgenauigkeit leiden. Nach einer Änderung mit
> `bedlevel stability "<name>"` gegenprüfen.

---

## Weiterführende Dokumentation

| | |
|---|---|
| [docs/ABLAUF.md](docs/ABLAUF.md) | Vollständiger Ablauf, Schritt für Schritt |
| [docs/SPACER.md](docs/SPACER.md) | Abstandshalter drucken, die den Werksversatz ausgleichen |
| [docs/MESSQUALITAET.md](docs/MESSQUALITAET.md) | Notation, Toleranz, Referenzwahl, Fehlerbilder |
| [docs/RINKHALS.md](docs/RINKHALS.md) | Firmware-Eigenheiten und ihre Nachweise |

### Kommandoübersicht

| Kommando | Zweck |
|---|---|
| `check` | Verbindung und Firmware-Fähigkeiten prüfen |
| `teach` | Schraubenpositionen mit den Pfeiltasten einlernen |
| `calibrate-direction <name>` | Drehrichtung durch eine Testdrehung bestimmen |
| `measure` | Einmal messen und auswerten |
| `level` | Messen, nachstellen, wiederholen bis im Ziel |
| `stability <name>` | Wiederholgenauigkeit eines Punktes prüfen |
| `spacers` | Werksversatz messen und Abstandshalter als STL erzeugen |
| `cooldown` | Heizungen ausschalten |

---

## Sicherheit

Das Tool bewegt einen heißen Druckkopf über ein beheiztes Bett.

- Es verfährt nur innerhalb der **vom Drucker gelesenen** Achsgrenzen.
- Vor jeder Fahrt wird angehoben; vor dem Wegfahren wird erst das Bett
  abgesenkt, dann der Kopf zur Seite bewegt.
- Bei `Strg-C` bleiben die Heizungen an — `uv run bedlevel cooldown` schaltet
  sie aus.

**Beim ersten Lauf danebenstehen.** Besonders `teach` erlaubt es, die Düse bis
auf Bettkontakt herunterzufahren.

---

## Entwicklung

```bash
uv run pytest tests -q
```

Die Tests laufen **ohne Drucker**. Sie decken die Auswertung, die
Tastatureingabe, die Messreihenfolge und die STL-Geometrie ab — und halten
mehrere Fehler fest, die bei der Entwicklung am Gerät aufgetreten sind:

- Escape-Sequenzen, die in Pythons Puffer verschwinden, während `select` den
  Dateideskriptor abfragt
- Sollwerte, die im Leerlauf von außen genullt werden
- Messwerte, die zwischen zwei Lagen springen und deren Median dadurch
  bedeutungslos wird
- ein STL-Netz mit vertauschten Deck- und Bodenflächen

### Aufbau

| Modul | Aufgabe |
|---|---|
| `moonraker.py` | HTTP-Client, Temperaturwarten mit Sollwert-Nachsetzen |
| `keepalive.py` | hält den Drucker wach, damit der Leerlauf nicht dazwischenfunkt |
| `procedure.py` | Messablauf: heizen, wischen, homen, antasten, parken |
| `screws.py` | Auswertung: Referenzwahl, Drehempfehlung, Ebenen-Fit |
| `spacers.py` | Spacerberechnung und STL-Erzeugung |
| `keys.py` | Tastenleser für die interaktive Positionierung |
| `cli.py` | Kommandozeile und Ausgabe |

---

## Dank

Dieses Projekt steht auf der Arbeit anderer. Ohne die folgenden Quellen wäre es
nicht entstanden:

### [Rinkhals](https://github.com/rinkhals-community/Rinkhals/)

Die alternative Firmware, die den Kobra S1 überhaupt zugänglich macht. Sie
stellt ein echtes Moonraker vor den geschlossenen `gklib`-Kern — ohne diesen
Zugang gäbe es keine Möglichkeit, den Drucker von außen zu vermessen und zu
steuern. Der gesamte Ansatz dieses Tools beruht darauf. **Vielen Dank an das
Rinkhals-Projekt und alle Beitragenden.**

### [Kobra S1 bed tramming spacers](https://www.makeronline.com/en/model/Kobra%20S1%20bed%20tramming%20spacers/166490.html)

Von dort stammt die Idee, den Werksversatz mit gedruckten Abstandshaltern
auszugleichen, statt ihn allein den Schrauben aufzubürden. Dieses Projekt
greift den Gedanken auf und erzeugt die Spacer aus einer echten Messung, statt
sie zu schätzen. **Danke für die Vorlage.**

### [Anycubic Kobra S1 – checking and adjusting the flatness of the hot bed](https://forum.makeronline.com/en/forum/topic/anycubic%20kobra%20s1%20-%20checking%20and%20adjusting%20the%20flatness%20of%20the%20hot%20bed-3704.html)

Der Forumsthread mit den Grundlagen zum Thema: wie man die Ebenheit des
Heizbetts beim Kobra S1 überhaupt beurteilt, worauf zu achten ist und welche
Größenordnungen realistisch sind. **Danke an alle Beteiligten.**

### Klipper

Die Grundidee stammt von Klippers
[`SCREWS_TILT_ADJUST`](https://www.klipper3d.org/Manual_Level.html). Dieses
Projekt bildet dessen Verhalten für eine Plattform nach, auf der das Kommando
nicht verfügbar ist — inklusive der bewährten Notation `CW 01:20`. **Danke an
das Klipper-Projekt.**

---

## Lizenz

[MIT](LICENSE) — © 2026 Maik Hofmann
