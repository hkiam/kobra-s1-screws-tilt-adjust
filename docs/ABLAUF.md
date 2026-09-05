# Ablauf

Von der ersten Messung bis zum fertig ausgerichteten Bett. Wer schon Spacer
verbaut hat, kann Schritt 1 überspringen.

## Schritt 0 — Vorbereitung

**Düse sauber.** Angetastet wird mit der Düse selbst. Ein anhaftender
Filamentrest wird bei jedem Antasten flacher gedrückt und lässt die Messwerte
wandern — das ist die häufigste Ursache für unbrauchbare Messungen. Das Tool
kann vor jeder Messung automatisch wischen, siehe `[wipe]` in der
Konfiguration.

**Druckplatte plan.** Ein Krümel zwischen Federstahlplatte und Magnetunterlage
lässt die Platte kippeln, und sie fällt bei jedem Antasten in eine andere Lage.
Das erzeugt Messwerte, die zwischen zwei Werten springen — unbrauchbar für die
Justage. Beide Flächen abwischen.

**Warm messen, nicht kalt.** Die Geometrie ändert sich mit der Temperatur; kalt
justiert ist im Betrieb wieder schief. Die Vorgabe sind 60 °C Bett und 140 °C
Düse. Sinnvoll ist die Betttemperatur, bei der später gedruckt wird.

## Schritt 1 — Abstandshalter (einmalig)

Der Kobra S1 hat ab Werk keine Abstandshalter. Der Werksversatz der vier
Aufnahmepunkte muss dadurch komplett von den Schrauben ausgeglichen werden —
eine Ecke arbeitet dauerhaft nahe am Anschlag, eine andere hat kaum
Vorspannung. Gedruckte Spacer nehmen den Versatz vorweg.

```bash
uv run bedlevel spacers
```

Details, Geometrie und Druckparameter: [SPACER.md](SPACER.md).

## Schritt 2 — Positionen einlernen

Das Tool muss wissen, wo deine Schrauben sitzen. Weil mit der Düse angetastet
wird (Probe-Offset 0/0), ist die eingelernte Düsenposition unmittelbar die
Messkoordinate.

```bash
uv run bedlevel teach
```

| Taste | Wirkung |
|---|---|
| Pfeile | X / Y |
| Bild-auf/ab, `+` / `-` | Z |
| `1`–`5` | Schrittweite 0,1 / 0,5 / 1 / 5 / 10 mm |
| Enter | Position übernehmen, weiter zur nächsten |
| `s` | Punkt unverändert lassen |
| `q` | abbrechen |

Die Positionen landen in `bedlevel.toml`, die alte Fassung in
`bedlevel.toml.bak`. Mit `--dry-run` wird nur angezeigt.

`teach` startet mit `G28` und fährt auf Z 5 mm. Mit Schrittweite `5` und
Bild-ab kommst du auf Bettkontakt — beim Feinpositionieren auf `1` oder kleiner
bleiben, oder höher starten mit `--z 10`.

## Schritt 3 — Drehrichtung bestimmen

Ob Anziehen dein Bett hebt oder senkt, hängt an deiner Mechanik. Das ist nichts
zum Raten: bei falscher Annahme macht jede Korrektur es doppelt schlimm.

```bash
uv run bedlevel calibrate-direction "vorne links"
```

Das Kommando misst, lässt dich eine Viertelumdrehung anziehen, misst nach und
nennt den Wert für `cw_lowers_bed`. Wer die Richtung sicher kennt, kann ihn
direkt eintragen:

```toml
cw_lowers_bed = true    # Anziehen senkt das Bett (Abstand zur Düse wird größer)
```

## Schritt 4 — Justieren

```bash
uv run bedlevel level
```

Der Ablauf je Runde:

1. Aufheizen (beim ersten Mal), Düse reinigen, referenzieren
2. Messen — 8 Antastungen je Punkt, über zwei Durchgänge verschränkt
3. Der Kopf fährt nach hinten weg und senkt das Bett ab
4. Tabelle mit Drehanweisung je Schraube
5. Du schraubst, Enter startet die nächste Runde

Fertig ist es, wenn keine Korrektur mehr über der Toleranz liegt. `q` beendet
vorzeitig.

**Erwartbarer Verlauf:** Die erste Runde bringt den größten Sprung. Ab der
dritten Runde bewegt sich meist wenig — dann ist entweder das Ziel erreicht
oder der Bettverzug die Grenze.

## Schritt 5 — Bed Mesh neu erstellen

Nach der Justage ist das alte Mesh ungültig, die Bettlage hat sich geändert.
Am Drucker:

```
BED_MESH_CALIBRATE
SAVE_CONFIG
```

Wer konsequent nur angezogen hat, hat das Bett insgesamt abgesenkt — dann
vorher den **Z-Offset** neu setzen.

Ab Werk tastet der S1 dafür 5 × 5 Punkte ab. Ein feineres Raster macht die
Restwelligkeit überhaupt erst sichtbar — wie man auf 7 × 7 umstellt, steht im
README unter *Optional: feineres Bed Mesh*.

## Wann es genug ist

Die Ausgabe weist den **Bettverzug** aus: was nach dem Ebenenabgleich übrig
bleibt. Das ist der Anteil, der keine Verkippung ist — Wellen und Verzug der
Platte selbst. Mit vier Schrauben bekommt man ihn grundsätzlich nicht weg.

Liegt der Verzug nahe der eingestellten Toleranz, ist die Justage ausgereizt.
Weiter zu drehen verschiebt dann nur noch, welche Ecke danebenliegt. Der Rest
gehört ins Bed Mesh — genau dafür ist es da.

Ein realer Verlauf zur Einordnung:

| | Spannweite | Bettverzug |
|---|---:|---:|
| erste warme Messung | `00:23` | — |
| nach Runde 1 | `00:14` | `00:09` |
| nach Runde 2 | `00:11` | `00:01` |
| nach Runde 3 | `00:07` | `00:04` |

Der Verzugswert fiel mit — der hohe Anfangswert war nicht die Platte, sondern
eine Ecke, die unter dem Antastdruck nachgab.
