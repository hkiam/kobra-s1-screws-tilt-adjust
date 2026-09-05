# Messqualität, Notation und Toleranz

## Die Drehanweisung lesen

Die Schreibweise folgt Klippers `SCREWS_TILT_ADJUST`:

```
adjust  CW 01:20     1 volle Umdrehung und 20 Minuten, im Uhrzeigersinn
```

Das Zifferblatt als Maß für den Drehwinkel:

| Anzeige | Drehung | bei M4 (0,7 mm Steigung) |
|---|---|---:|
| `01:00` | volle Umdrehung, 360° | 0,700 mm |
| `00:30` | halbe Umdrehung, 180° | 0,350 mm |
| `00:15` | Viertelumdrehung, 90° | 0,175 mm |
| `00:05` | kleiner Stups, 30° | 0,058 mm |

`CW` = clockwise, `CCW` = counter-clockwise. Bei Rechtsgewinde ist `CW` immer
Anziehen — die Legende unter der Tabelle nennt zusätzlich, in welche Richtung
sich das Bett dabei bewegt. Die Referenzschraube steht als `(base)` da.

**Klammern bedeuten: nicht nötig, aber wirksam.** Eine Korrektur in Klammern
liegt innerhalb der Toleranz. Das ist wichtig, wenn mehrere Schrauben knapp
darunter liegen: Dreht man nur die eine, die die Toleranz überschreitet, wird
eine andere zur neuen höchsten Ecke und die Spannweite bleibt, wo sie war.

## Toleranz

Angegeben wird sie in derselben Einheit wie die Anweisung
(`tolerance_minutes`), damit sich das Abbruchkriterium mit der Zahl deckt, die
in der Spalte `adjust` steht.

| Ziel | Bedeutung |
|---|---|
| unter `00:10` | **gut** — für den Alltag völlig ausreichend, den Rest macht das Bed Mesh |
| unter `00:05` | **exzellent** — wenn das Bett möglichst spannungsfrei liegen soll |
| unter `00:02` | **Grenze des mechanischen Spiels** von Schrauben und Lagerung |

**Alle Warnungen zur Messqualität beziehen sich auf diesen Wert.** Was stört,
hängt am Ziel: eine Drift von einer Minute ist bei `00:10` ein Achtel der
Toleranz und belanglos, bei `00:02` dagegen die halbe Toleranz.

## Referenzschraube

Eine Schraube bleibt stehen, die übrigen werden auf sie ausgerichtet.
`reference` steuert, welche:

| Wert | Bedeutung |
|---|---|
| `nur-anziehen` | wählt die Ecke so, dass **keine** Schraube gelöst werden muss |
| `auto` | geringster Gesamtdrehaufwand — kann Lösen verlangen |
| `<name>` | genau diese Schraube |

`nur-anziehen` ist die Vorgabe: Anziehen hält die Vorspannung der Lagerung
besser als Ausdrehen. Welche Ecke das ist, leitet das Tool aus
`cw_lowers_bed` ab — senkt Anziehen das Bett, ist es die tiefste, sonst die
höchste.

Die Wahl wird **bei jedem Durchgang neu** getroffen. Das ist der Unterschied zu
einer fest eingetragenen Schraube: Schießt man beim Anziehen über das Ziel
hinaus und die Ecke liegt plötzlich tiefer als die Referenz, wandert die
Referenz mit — und man zieht weiter nur an, statt wieder lösen zu müssen.

## Messreihenfolge

Nicht jeder Punkt wird am Stück gemessen, sondern über zwei Durchgänge
verschränkt — über Kreuz, im zweiten Durchgang rückwärts:

```
Durchgang 1:  vorne links → hinten rechts → vorne rechts → hinten links
Durchgang 2:  hinten links → vorne rechts → hinten rechts → vorne links
```

Der Grund: Das Bett senkt sich während einer Messreihe um messbare
0,01–0,02 mm. Bei sequenzieller Messung erschiene der zuletzt gemessene Punkt
dadurch systematisch tiefer — aus einem reinen *Zeit*-Effekt würde eine
*Scheinverkippung*. Durch die umgekehrte Reihenfolge liegt der zeitliche
Schwerpunkt jeder Ecke in der Mitte der Gesamtreihe, und ein gleichmäßiger
Zeittrend hebt sich rechnerisch auf.

Simuliert an einem perfekt ebenen Bett, das 0,002 mm je Antastung nachgibt:

| Durchgänge | vorgetäuschte Verkippung |
|---|---:|
| 1 (sequenziell) | 0,054 mm = `00:05` |
| 2 (verschränkt) | 0,000 mm |

Das Kreuzmuster innerhalb eines Durchgangs hat einen eigenen Zweck: benachbarte
Ecken werden nicht direkt nacheinander belastet, jede Stelle bekommt
Erholungszeit.

## Wenn die Messung nicht trägt

Je Punkt werden acht Messungen genommen und der Median gebildet. Das Tool
unterscheidet drei Fehlerbilder, weil sie unterschiedliche Konsequenzen haben:

| Muster | Beispiel | Bedeutung |
|---|---|---|
| **Streuung** | `-0.425 -0.432 -0.421` | Rauschen — der Median mittelt es weg |
| **Drift** | `-0.437 → -0.462 → -0.480` | gerichtet, mittelt sich **nicht** weg |
| **Zwei Lagen** | `-0.520 -0.696 -0.518 -0.698` | die Lagerung rastet zwischen zwei Positionen ein |

### Drift

Die Werte laufen monoton in eine Richtung. Die Lagerung gibt unter dem
Antastdruck nach oder das Bett setzt sich. Mehr Messungen helfen nicht — sie
drücken die Ecke nur weiter herunter.

### Zwei Lagen

Der gefährlichste Fall, weil er wie normale Streuung aussieht. Die Werte
springen zwischen zwei Gruppen; **der Median landet in der Lücke dazwischen**
und beschreibt eine Lage, die das Bett nie einnimmt. Ein realer Fall:

```
-0.5358  -0.6667  -0.5200  -0.6958  -0.5175  -0.6983  -0.5258  -0.7075
    A        B        A        B        A        B        A        B
```

Median: −0,601 — ein Wert, der in keiner der beiden Lagen vorkommt. Häufigste
Ursache: die Druckplatte liegt nicht plan auf.

### Was das Tool damit macht

Bei Drift oder zwei Lagen gibt es für den betroffenen Punkt **keine**
Drehempfehlung und wählt ihn auch nicht als Referenz — eine Korrektur darauf
wäre auf einen Phantomwert gerechnet. Stattdessen erscheint der Grund in der
Tabelle und ein Hinweis, dass die Justage so nicht möglich ist.

### Einzelnen Punkt prüfen

```bash
uv run bedlevel stability "vorne links"
```

Tastet den Punkt zehnmal an und weist Streuung und Drift getrennt aus, jeweils
im Verhältnis zur eingestellten Toleranz.

**Der Sensor ist selten das Problem.** An intakten Ecken liefert er 6–17 µm
Wiederholgenauigkeit. Streut ein einzelner Punkt deutlich stärker als die
übrigen in derselben Messreihe, ist die Ursache dort mechanisch — gleiche
Düse, gleicher Sensor, gleiche Reihe.

## Kennzahlen der Ausgabe

- **Größte Korrektur** — die stärkste nötige Drehung, mit Einstufung.
- **Spannweite** — Differenz zwischen höchster und tiefster Ecke.
- **Verkippung** — Neigung der Ausgleichsebene in mm/m, getrennt nach X und Y.
- **Bettverzug** — was nach dem Ebenenabgleich übrig bleibt. Der erreichbare
  Boden; liegt er nahe der Toleranz, lohnt weiteres Drehen nicht.
