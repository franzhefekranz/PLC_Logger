# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Aufräumen alter Aufzeichnungen – ohne Oberfläche (läuft im Logger und im Headless-Betrieb).

Zwei Grenzen, jede einzeln abschaltbar (0 = aus):

* **Zeitraum** – Aufzeichnungen, die älter als N Tage sind, werden gelöscht.
* **Speicherplatz** – belegen die Aufzeichnungen mehr als M MB, werden die ältesten gelöscht, bis die Grenze wieder
  eingehalten ist.

CSV
---
Betroffen sind nur Dateien dieses Loggers: ``<CSV-Name>_*.csv`` im CSV-Ordner und die ZIP-Dateien im Archiv unter
``<Archiv>/<CSV-Name>/…``. Die gerade beschriebene CSV-Datei wird nie gelöscht. Maßgeblich ist der Zeitpunkt der letzten
Änderung einer Datei (= Ende der darin enthaltenen Aufzeichnung). Leer gewordene Archiv-Unterordner werden entfernt.

Datenbank
---------
Das Löschen übernimmt der Schreib-Thread der Datenbank (``plc_db.DbWriter``) mit seiner Verbindung, siehe
``plc_db.cleanup``: Zeilen älter als N Tage löschen (alle SQL-Datenbanken, bei TimescaleDB ganze Zeitabschnitte, bei
QuestDB ganze Tagespartitionen); die Speicherplatz-Grenze gibt es nur für SQLite. InfluxDB 3 und VictoriaMetrics
verwalten die Aufbewahrungsdauer selbst (Einstellung am Server).

Die Prüfung läuft beim Start der Aufzeichnung und danach stündlich (``CleanupThread``).
"""
import glob
import os
import threading
import time

from plc_i18n import tr

MB = 1024 * 1024
INTERVAL_S = 3600.0                  # Abstand der Prüfungen


def settings(conn) -> dict:
    """Grenzen aus der Konfiguration: {"csv_tage", "csv_mb", "db_tage", "db_mb"} (0 = aus)."""
    def num(key):
        try:
            return max(0, int(float(conn.get(key, 0) or 0)))
        except (TypeError, ValueError):
            return 0
    return {"csv_tage": num("aufr_csv_tage"), "csv_mb": num("aufr_csv_mb"),
            "db_tage": num("aufr_db_tage"), "db_mb": num("aufr_db_mb")}


def csv_files(csv_dir, archive_dir, base):
    """Aufzeichnungsdateien dieses Loggers -> [(Pfad, Änderungszeit, Größe)], älteste zuerst."""
    paths = glob.glob(os.path.join(glob.escape(csv_dir), glob.escape(base) + "_*.csv"))
    root = os.path.join(archive_dir, base)
    for folder, _dirs, files in os.walk(root):
        paths += [os.path.join(folder, f) for f in files if f.lower().endswith(".zip")]
    out = []
    for p in paths:
        try:
            st = os.stat(p)
        except OSError:
            continue
        out.append((p, st.st_mtime, st.st_size))
    return sorted(out, key=lambda x: x[1])


def plan(files, now, days=0, max_mb=0, keep=()):
    """Welche Dateien sind zu löschen? ``files`` wie von ``csv_files`` (älteste zuerst); ``keep`` wird nie gelöscht.

    Erst alles älter als ``days`` Tage, dann – solange die Summe über ``max_mb`` liegt – die jeweils älteste Datei."""
    keep = {os.path.normcase(os.path.abspath(k)) for k in keep if k}
    files = [f for f in files if os.path.normcase(os.path.abspath(f[0])) not in keep]
    doomed = []
    if days > 0:
        limit = now - days * 86400.0
        doomed = [f for f in files if f[1] < limit]
    if max_mb > 0:
        rest = [f for f in files if f not in doomed]
        total = sum(f[2] for f in rest) + sum(os.path.getsize(k) for k in keep if os.path.exists(k))
        for f in rest:
            if total <= max_mb * MB:
                break
            doomed.append(f)
            total -= f[2]
    return [f[0] for f in doomed]


def _remove_empty_dirs(root):
    """Leere Unterordner unterhalb von ``root`` entfernen (von unten nach oben; ``root`` selbst bleibt)."""
    for folder, _dirs, _files in sorted(os.walk(root), key=lambda x: -len(x[0])):
        if folder != root:
            try:
                os.rmdir(folder)                     # gelingt nur bei leeren Ordnern
            except OSError:
                pass


def clean_csv(csv_dir, archive_dir, base, days=0, max_mb=0, keep=(), now=None):
    """CSV- und Archivdateien nach den Grenzen löschen -> (Anzahl, freigegebene Bytes, Fehlertexte)."""
    if days <= 0 and max_mb <= 0:
        return 0, 0, []
    files = csv_files(csv_dir, archive_dir, base)
    sizes = {f[0]: f[2] for f in files}
    n, freed, errors = 0, 0, []
    for p in plan(files, time.time() if now is None else now, days, max_mb, keep):
        try:
            os.remove(p)
            n += 1
            freed += sizes.get(p, 0)
        except OSError as e:
            errors.append(f"{os.path.basename(p)}: {e.strerror or e}")
    _remove_empty_dirs(os.path.join(archive_dir, base))
    return n, freed, errors


def size_text(n_bytes) -> str:
    """Größe für Meldungen: „12,3 MB“ bzw. „1,2 GB“."""
    if n_bytes >= 1024 * MB:
        return f"{n_bytes / 1024 / MB:.1f} GB".replace(".", ",")
    return f"{n_bytes / MB:.1f} MB".replace(".", ",")


class CleanupThread(threading.Thread):
    """Prüft beim Start und danach stündlich die CSV-/Archiv-Grenzen des Recorders und löscht alte Dateien.

    ``rec`` liefert csv_dir(), archive_dir(), csv_base, csv_path (wird nicht gelöscht) und emit() für Meldungen."""

    def __init__(self, rec, s, interval_s=INTERVAL_S):
        """Thread anlegen (noch nicht gestartet); ``s`` = ``settings(conn)``."""
        super().__init__(name="aufraeumen", daemon=True)
        self.rec, self.s, self.interval = rec, s, interval_s
        self.stop_evt = threading.Event()

    def run_once(self):
        """Eine Prüfung: CSV-Dateien und Archiv aufräumen, Ergebnis melden."""
        rec = self.rec
        n, freed, errors = clean_csv(rec.csv_dir(), rec.archive_root(), rec.csv_base, self.s["csv_tage"], self.s["csv_mb"],
                                     keep=[getattr(rec, "csv_path", "") or ""])
        if n:
            rec.emit(tr("[Aufräumen] {0} alte Aufzeichnungsdateien gelöscht ({1})").format(n, size_text(freed)))
        for e in errors[:3]:
            rec.emit(tr("⚠ [Aufräumen] {0}").format(e))

    def run(self):
        """Sofort prüfen, dann im Abstand ``interval`` bis ``stop``."""
        while True:
            try:
                self.run_once()
            except Exception as e:                   # Aufräumen darf die Aufzeichnung nie stören
                self.rec.emit(tr("⚠ [Aufräumen] {0}").format(e))
            if self.stop_evt.wait(self.interval):
                return

    def stop(self):
        """Thread beenden (wartet nicht auf eine laufende Prüfung)."""
        self.stop_evt.set()
