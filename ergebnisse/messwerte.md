# Messwerte: NVMe-SSD, Arbeitsspeicher, Expert-Cache-Simulation

Die getestete DRAM-lose NVMe-SSD liest 63.432 IOPS bei 4 KiB und QD32 und 2,83 GB/s bei 1 MiB und QD32. Ab 64 KiB Blockgröße sättigt die Bandbreite bei 2,5 bis 2,8 GB/s, 72 % der PCIe-3.0-x4-Rohrate. Der Arbeitsspeicher liest 13,9 bis 17,5 GB/s unter Fremdlast. In der Cache-Simulation schlägt LRU die LFU-Strategie, sobald sich die Beliebtheit der Experten verschiebt.

Gemessen am 17.11.2026. Werkzeuge: `testbett/ssd_bench.c`, `testbett/ssd_bench.py`, `testbett/ssd_bench_extra.py`, `testbett/ram_bw.py`, `testbett/cache_sim.py`, `testbett/hitrate.py`.

## 1. SSD

Gerät: NVMe-SSD 1 TB, Controller Realtek RTS5765DL ohne DRAM, Host Memory Buffer aktiv. PCIe 8 GT/s x4 (PCIe 3.0, 3,94 GB/s roh). I/O-Scheduler kyber. Dateisystem btrfs mit zstd; die Testdatei war NOCOW (chattr +C), also ohne Kompression und Prüfsummen.

Methode: io_uring mit O_DIRECT auf einer 8-GiB-Datei mit Zufallsinhalt, Page Cache umgangen. Pflichtpunkte liefen 3-mal je 8 s, gezeigt ist der Median. Die Datei wurde nach jedem Lauf gelöscht. SSD-Temperatur 54 bis 60 °C. Rohdaten: `ssd_bench.json`, `ssd_bench_extra.json`. Diagramm: `ssd_qd_sweep.png`.

| Test | QD | IOPS (Median, Min. bis Max. von 3) | GB/s | mittlere Latenz | p50 | p99 |
|---|---|---|---|---|---|---|
| seq. Lesen 1 MiB | 1 | 2.112 | 2,21 | 473 µs | 423 µs | 1,40 ms |
| seq. Lesen 1 MiB | 32 | 2.885 | 3,03 | 11,1 ms | 10,7 ms | 26,0 ms |
| seq. Lesen 128 KiB | 32 | 22.526 | 2,95 | 1,42 ms | 1,34 ms | 3,16 ms |
| zuf. Lesen 4 KiB | 1 | 10.617 (10.544 bis 11.235) | 0,043 | 94 µs | 77 µs | 448 µs |
| zuf. Lesen 4 KiB | 32 | 63.432 (59.573 bis 66.325) | 0,26 | 504 µs | 415 µs | 1,99 ms |
| zuf. Lesen 16 KiB | 1 | 6.332 | 0,104 | 158 µs | 132 µs | 765 µs |
| zuf. Lesen 16 KiB | 32 | 59.800 (48.034 bis 60.443) | 0,98 | 535 µs | 454 µs | 1,74 ms |
| zuf. Lesen 64 KiB | 1 | 4.284 | 0,281 | 233 µs | 203 µs | 974 µs |
| zuf. Lesen 64 KiB | 32 | 35.066 | 2,30 | 912 µs | 802 µs | 2,68 ms |
| zuf. Lesen 1 MiB | 1 | 1.715 | 1,80 | 583 µs | 539 µs | 1,34 ms |
| zuf. Lesen 1 MiB | 32 | 2.699 | 2,83 | 11,8 ms | 11,6 ms | 29,4 ms |

- Höchste 4-KiB-Rate: 4 Prozesse x QD32 erreichten 164.532 IOPS (0,67 GB/s). Ein io_uring bei QD128 erreichte 121.132 IOPS.
- 64 KiB: 4 Prozesse x QD8 erreichten 2,55 GB/s.
- Python-Gegenprobe (32 Threads, os.preadv, O_DIRECT): 68.138 IOPS bei 4 KiB, 2,42 GB/s bei 64 KiB. Das deckt sich mit io_uring bei QD32.
- Die Streuung zwischen Läufen ist groß. 4 KiB QD32 lag über alle Läufe zwischen 53.000 und 143.000 IOPS. QD 2 bis 8 skalierte kaum (10.600 bis 13.500 IOPS), QD16 sprang auf 44.000.
- Der Spannweitentest ist nicht schlüssig. Erster Durchgang 143k, 135k, 123k, 103k IOPS über 256 MiB, 1, 4, 8 GiB; zweiter Durchgang 53k, 59k, 76k, 76k. Wahrscheinlich dominierte Garbage Collection nach dem Schreiben der Datei.
- Schreibrate beim Anlegen der Datei (O_DIRECT, 64-MiB-Blöcke, inklusive Zufallszahlen): 0,24 und 0,45 GB/s. Das ist kein sauberer Schreibtest.
- Einschränkung: 8 GiB Spannweite passen in den Mapping-Cache des Host Memory Buffer. Zufällige Lesezugriffe über eine Datei von mehreren TB treffen auf einer DRAM-losen SSD öfter Mapping-Fehlschläge. Dieser Fall ist nicht gemessen.

## 2. Arbeitsspeicher

`ram_bw.py`: P Prozesse summieren je ein 96-MB-float32-Array 12-mal. Der Rechner lief mit Fremdlast (Load Average etwa 14), die Werte sind Untergrenzen. Rohdaten: `ram_bw.json`.

| Prozesse | GB/s |
|---|---|
| 1 | 13,9 |
| 2 | 14,3 |
| 4 | 17,5 |
| 8 | 15,4 |

## 3. Cache-Simulation für MoE-Experten

`cache_sim.py`: eine Schicht pro Lauf, LRU und perfektes LFU, Aufwärmphase ausgenommen. Regime: statisches Zipf mit s in {0; 0,5; 0,8; 1,0; 1,2}; zeitliche Wiederverwendung p in {0; 0,3; 0,6}; "Drift" = global gleichverteilte, lokal Zipf-verteilte Beliebtheit (s = 1, Rangfolge alle 256 Tokens neu gezogen). Geometrien: E = 256 Experten mit k = 8 pro Token, E = 2048 mit k = 16. Tabellen: `cache_tables_moe.md`, Rohdaten: `cache_sim_moe.json`, Diagramm: `cache_moe_E2048_k16.png`.

Trefferquote bei E = 2048, k = 16:

| Cachegröße | gleichverteilt (s = 0) | s = 0,8 LRU / LFU | s = 1,0 LRU / LFU | s = 1,2 LRU / LFU | Drift LRU / LFU | s = 0, p = 0,6 LRU / LFU |
|---|---|---|---|---|---|---|
| 32 (1,6 %) | 0,012 | 0,103 / 0,270 | 0,224 / 0,410 | 0,356 / 0,538 | 0,224 / 0,036 | 0,604 / 0,020 |
| 128 (6,25 %) | 0,059 | 0,290 / 0,447 | 0,464 / 0,606 | 0,626 / 0,735 | 0,460 / 0,158 | 0,622 / 0,076 |
| 512 (25 %) | 0,246 | 0,572 / 0,682 | 0,720 / 0,800 | 0,833 / 0,884 | 0,697 / 0,450 | 0,697 / 0,286 |

- Gleichverteilte Beliebtheit gibt Trefferquote = Cache-Anteil.
- LFU schlägt LRU bei statischer Beliebtheit. LRU schlägt LFU unter Drift (0,460 gegen 0,158 bei 128 Experten) und bei zeitlicher Wiederverwendung (0,622 gegen 0,076).
- Wiederverwendung p addiert etwa p zur Trefferquote, sobald der Cache die k Experten eines Tokens hält.
- Simulation und Formeln stimmen überein, wenn die Formeln jedes Element höchstens einmal pro Token zählen (Korrektur in `hitrate.py`): LRU gegen Che-Näherung innerhalb 0,021 ab Cachegröße 2k, bis 0,058 bei Cachegröße k; LFU gegen Top-C innerhalb 0,020.
