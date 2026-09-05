# Firmware-Eigenheiten (Rinkhals / gklib)

*[English version: RINKHALS.md](RINKHALS.md)*

Der Kobra S1 fährt kein echtes Klipper, sondern **gklib** — eine Go-Portierung
von Anycubic. Rinkhals setzt ein echtes Moonraker davor. Vieles verhält sich
wie gewohnt, einiges nicht. Die folgenden Punkte sind am Gerät nachgewiesen,
nicht aus der Dokumentation übernommen — sie kosten sonst Stunden.

Getestet mit Rinkhals `20260901_01`, gklib auf `rinkhals_gklib.cfg`.

## `probe` fehlt in `objects/list`, ist aber abfragbar

`/printer/objects/list` führt **kein** `probe`-Objekt. Wer der Liste glaubt,
baut den Auslesepfad unnötig um. Die Abfrage funktioniert trotzdem:

```bash
curl "http://<ip>:7125/printer/objects/query?probe"
# {"probe": {"last_query": false, "last_z_result": 0}}
```

Konsequenz fürs Tool: `check` testet die Abfrage direkt, statt der Liste zu
vertrauen.

## `PROBE` liefert die rohe Kinematikposition

Ein geladenes Bed Mesh transformiert die Z-Achse — am Testgerät um bis zu
1,8 mm, positionsabhängig. Das wäre genau die Art Fehler, die eine
Eckenmessung ruiniert.

`probe.last_z_result` folgt aber der **rohen** Kinematikposition, nicht der
mesh-transformierten gcode-Position. An drei Punkten mit stark
unterschiedlicher Mesh-Korrektur gemessen:

| Punkt | `last_z_result` | Kinematik (roh) | gcode (mesh) | Mesh-Anteil |
|---|---:|---:|---:|---:|
| Mitte | −0,1658 | −0,1708 | −0,1158 | −0,055 |
| vorne links | −0,4308 | −0,4350 | −0,0906 | −0,344 |
| hinten rechts | −0,2783 | −0,2825 | −0,1153 | −0,167 |

Der Messwert folgt durchgehend der rohen Position. Es bleibt ein konstanter
Versatz von rund 0,004 mm, dessen Ursache offen ist — er ist an allen Punkten
gleich groß und fällt bei der relativen Auswertung heraus. Entscheidend ist,
dass der Messwert der **rohen** Position folgt und nicht der um bis zu 0,34 mm
verschobenen gcode-Position.

**Ein aktives Bed Mesh stört die Messung also nicht.** Das Tool lässt es in
Ruhe, prüft die Annahme aber bei jedem Lauf am ersten Messpunkt nach — falls
ein Firmware-Update das umdreht.

## `BED_MESH_CLEAR` ist wirkungslos

Das Kommando wird quittiert, das Mesh bleibt geladen:

```
vorher              aktiv=True  profil='default'  spanne=1.829
nach BED_MESH_CLEAR aktiv=True  profil='default'  spanne=1.829
```

Es zu senden würde nur Sicherheit vortäuschen. Das Tool sendet es deshalb
nicht — was dank des vorigen Punktes auch nicht nötig ist.

## Der Leerlauf schaltet Heizung und Motoren ab

**Statusabfragen über HTTP zählen nicht als Aktivität.** Ohne G-Code fällt der
Drucker in den Leerlauf, schaltet die Heizungen ab und macht die Motoren
stromlos — womit die Referenzfahrt verloren ist.

Das trifft jede Automatisierung, die auf etwas wartet. Beobachtet: die Düse
fiel mitten im Aufheizen von 105 °C zurück, während das Tool brav den Status
pollte.

Gegenmaßnahmen im Tool:

- ein **Keepalive**, das alle 15 s ein `M105` sendet, über den gesamten Lauf —
  besonders wichtig, während von Hand geschraubt wird
- **Sollwerte nachsetzen** beim Warten auf Temperatur
- **Homing prüfen** statt glauben: `G28` wird auch dann quittiert, wenn
  hinterher `homed_axes` leer ist

Der genaue Timeout ließ sich nicht ermitteln — `idle_timeout` ist nicht
konfiguriert, und der Wert `idle_timeout: 30` in der Konfiguration gehört zu
`[controller_fan]`, ist also die Lüfternachlaufzeit. Das Keepalive-Intervall
ist deshalb konservativ gewählt.

## Der G-Code-Puffer enthält keine Antworten

`/server/gcode_store` speichert nur die **Kommandos**, nicht die Ausgaben des
Druckers. Kommandos wie `GET_POSITION` oder `BED_MESH_OUTPUT` sind über HTTP
damit nicht auswertbar.

Antworten gibt es nur über den Websocket:

```python
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://<ip>:7125/websocket") as ws:
        await ws.send(json.dumps({"jsonrpc": "2.0", "method": "printer.gcode.script",
                                  "params": {"script": "BED_MESH_OUTPUT"}, "id": 1}))
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("method") == "notify_gcode_response":
                print(msg["params"])
            elif msg.get("id") == 1:
                break

asyncio.run(main())
```

## Die eigene Levelroutine des Druckers

Im Puffer einer vorangegangenen Kalibrierung gefunden — nützlich als Vorlage
für Temperaturen und die Wischsequenz:

```
BED_MESH_CLEAR
G28
MOVE_HEAT_POS
M140 S80
M109 S170
M190 S80
WIPE_ENTER
WIPE_NOZZLE
WIPE_EXIT
M109 S140
BED_MESH_CALIBRATE
```

Also: bei 170 °C wischen, bei 140 °C antasten. Die Wischmakros erwarten eine
passende Z-Höhe — am Testgerät streift die Düse die Wischvorrichtung bei
**Z 15**; die Makros selbst setzen kein Z.

## Relevante Werte aus `rinkhals_gklib.cfg`

| | |
|---|---|
| Kinematik | corexy, 250 × 250 × 250 mm |
| Achsgrenzen | X −6…265, Y 0…277, Z −4…253 |
| Probe | `[cs1237]` Kraftsensor, x/y-Offset 0, `samples: 2` |
| Bed Mesh | 5…245, `probe_count: 7,7`, `bicubic`, fade 1…10 |
| Z-Homing | `probe:z_virtual_endstop`, `safe_z_home` bei 125,125 |

Die Werte für `probe_count` und `algorithm` stammen im Testgerät aus einer
eigenen `printer.custom.cfg` (7 × 7 statt 5 × 5, `bicubic` statt `lagrange`) —
siehe README, *Optional: feineres Bed Mesh*. Rinkhals führt den Inhalt dieser
Datei beim Start mit der Werkskonfiguration zusammen; `gklib` liest die
zusammengeführte Fassung, weshalb nach einer Änderung ein Neustart nötig ist
und ein `FIRMWARE_RESTART` nicht genügt.
