# Manifest: Testbett Speicher- und Cache-Messung

Alle geteilten Dateien. Freigegeben sind SSD- und RAM-Benchmarks, der generische Cache-Simulator mit Trefferquoten-Formeln, ihre Ergebnisse und zwei Diagramme.

| Pfad | Zweck | Herkunft | Größe (Bytes) |
|---|---|---|---|
| `.gitignore` | schließt Caches, Testdatei, Binärdatei und Ausgaben aus | neu erstellt | 179 |
| `requirements.txt` | Python-Pakete der Testbett-Skripte | neu erstellt | 28 |
| `testbett/ssd_bench.c` | io_uring-O_DIRECT-Lesebenchmark, eine JSON-Zeile pro Lauf | Prototyp, unverändert | 5.011 |
| `testbett/ssd_bench.py` | Testdatei anlegen, Pflichtpunkte und Queue-Tiefen-Sweep messen, Python-Gegenprobe, Datei löschen; Option --quick | Prototyp, Pfade generisch, Ausgabe nach out/, Schnellmodus ergänzt | 8.878 |
| `testbett/ssd_bench_extra.py` | Spannweitentest und parallele Prozesse; Option --quick | Prototyp, Ausgabe nach out/, Schnellmodus ergänzt | 3.127 |
| `testbett/ram_bw.py` | Lesebandbreite des Arbeitsspeichers mit 1 bis 8 Prozessen | Prototyp, Kopfkommentar bereinigt, Ausgabe nach out/ | 1.394 |
| `testbett/hitrate.py` | analytische Trefferquoten unter Zipf-Verteilung (ideales LFU, LRU nach Che) mit Korrektur für k verschiedene Elemente pro Token | Prototyp, eine designspezifische Funktion entfernt | 4.813 |
| `testbett/cache_sim.py` | Simulation von LRU- und LFU-Caches für MoE-Experten unter statischer, driftender und wiederverwendeter Beliebtheit; Option --quick | Prototyp, auf generische MoE-Geometrien gekürzt | 11.715 |
| `testbett/plot_ssd.py` | Diagramm des Queue-Tiefen-Sweeps aus ssd_bench.json | Prototyp, nur der SSD-Teil | 2.146 |
| `ergebnisse/messwerte.md` | Zusammenfassung: SSD-Tabelle, RAM-Bandbreite, Cache-Trefferquoten | neu geschrieben aus der Prototyp-Auswertung | 5.262 |
| `ergebnisse/ssd_bench.json` | Rohdaten SSD-Messung 17.11.2026 | Prototyp, Dateipfad entfernt | 16.383 |
| `ergebnisse/ssd_bench_extra.json` | Rohdaten Spannweite und parallele Prozesse | Prototyp, Dateipfad entfernt | 3.362 |
| `ergebnisse/ram_bw.json` | Rohdaten RAM-Bandbreite | Prototyp, unverändert | 162 |
| `ergebnisse/cache_sim_moe.json` | Trefferquoten aller Simulationsläufe (E = 256 und E = 2048) | erzeugt mit cache_sim.py, identisch mit dem Prototyp-Lauf | 52.924 |
| `ergebnisse/cache_tables_moe.md` | dieselben Werte als Tabellen | erzeugt mit cache_sim.py | 8.045 |
| `ergebnisse/ssd_qd_sweep.png` | Diagramm: IOPS und GB/s über Queue-Tiefe und Blockgröße | Prototyp, unverändert | 115.974 |
| `ergebnisse/cache_moe_E2048_k16.png` | Diagramm: Trefferquote über Cachegröße für E = 2048, k = 16 | erzeugt mit cache_sim.py | 189.050 |
| `MANIFEST.md` | diese Liste | neu erstellt | - |

Summe der aufgeführten Dateien: 428.453 Bytes (0,43 MB). `README.md` und `assets/` werden getrennt gepflegt und sind hier nicht aufgeführt.

## Voraussetzungen

- Linux mit NVMe, Python 3.10+, `pip install -r requirements.txt`
- gcc und liburing (Header und Bibliothek) für `ssd_bench.c`; `ssd_bench.py` baut es beim ersten Lauf
- freier Platz in Größe der Testdatei (Standard 8 GiB, --quick 512 MiB); die Datei wird einmal geschrieben und danach gelöscht
- Aufrufe aus `testbett/`: `python ssd_bench.py --quick` (etwa 15 s), `python ssd_bench_extra.py --quick` (etwa 10 s), `python ram_bw.py`, `python hitrate.py`, `python cache_sim.py` (etwa 10 s), `python plot_ssd.py out/ssd_bench.json out/ssd.png`

## Nicht enthalten

- Rechenmodell und Dimensionierung der vorgeschlagenen Architektur
- architekturspezifische Simulationen, Zugriffsmuster und Zeitmodelle
- Auswertungsskripte der Verbesserungsrunden, die das Design betreffen
- weitere Diagramme, Register, Messprotokolle und Entwurfsnotizen
