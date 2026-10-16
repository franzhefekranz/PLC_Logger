"""PID-Regler-Optimierung aus aufgezeichneten Daten – ohne Oberfläche (nur numpy).

Ablauf
------
1. **Streckenmodell bestimmen** (``identify``): Aus Stellwert u(t) und Istwert y(t) eines Zeitbereichs wird ein Modell
   der Regelstrecke geschätzt:

   * PT1 mit Totzeit (FOPDT): ``K · e^(−θs) / (T·s + 1)`` – Verstärkung K, Zeitkonstante T, Totzeit θ; passt für die
     meisten Temperatur-, Druck-, Durchfluss- und Drehzahlstrecken;
   * I-Strecke mit Totzeit (IPDT): ``Ki · e^(−θs) / s`` – z. B. Füllstand; wird gewählt, wenn sie die Daten besser
     beschreibt oder T über den Zeitbereich hinaus wächst.

   Geschätzt wird mit dem Ausgangsfehler-Verfahren: Das Modell wird mit dem gemessenen Stellwert simuliert, T und θ werden
   so gesucht, dass die simulierte Kurve möglichst gut auf der gemessenen liegt (K und Arbeitspunkt per kleinsten
   Quadraten). Das ist unempfindlich gegen Messrauschen. Die Güte steht als "Übereinstimmung" in % (100 % = perfekt).

2. **Reglerparameter berechnen** (``tune``) nach mehreren bekannten Einstellregeln (SIMC/Skogestad, IMC/Lambda,
   AMIGO, Chien-Hrones-Reswick, Ziegler-Nichols). Ergebnis je Regel: Kp, Ti, Td in der Standardform
   ``u = Kp · (e + 1/Ti ∫e dt + Td · de/dt)``.

3. **Regelkreis simulieren** (``simulate_loop``): Sollwertsprung mit dem Modell und dem Regler -> Überschwingen und
   Ausregelzeit, damit die Regeln vergleichbar sind.

Voraussetzung für gute Ergebnisse: Der Stellwert muss sich im gewählten Zeitbereich deutlich ändern (z. B. Sprung im
Handbetrieb oder Sollwertsprung im Automatikbetrieb), der Prozess sollte vorher in Ruhe sein und es sollten keine
großen Störungen auftreten.
"""
import math
from dataclasses import dataclass, field

import numpy as np
from tia_i18n import N_, tr

METHODS = [tr("SIMC (Skogestad)"), tr("IMC / Lambda"), tr("AMIGO"), tr("CHR (aperiodisch)"), tr("Ziegler-Nichols")]
BEHAVIOURS = {"schnell": tr("schnell (aggressiv)"), "normal": tr("normal"), "robust": tr("robust (langsam, sicher)")}
CONTROLLER_TYPES = ["PI", "PID"]
MAX_POINTS = 3000          # mehr Punkte werden für die Modellsuche nicht verwendet (gleichmäßig neu abgetastet)

# Hinweis zur Übernahme in die Steuerung (je Projekt verschieden).
PLC_HINT = tr('<b>Übernahme:</b> PID_Compact/PID_3Step: Retain.CtrlParams.Gain = Kp, .Ti = Ti [s], .Td = Td [s] (PI: Td = 0), TdFiltRatio z. B. 0.2; bei negativem Kp „Regelsinn invertieren“. CONT_C (FB 41): GAIN, TI, TD als TIME. Die Werte gelten für die Standardform u = Kp·(e + 1/Ti·∫e dt + Td·de/dt) in den aufgezeichneten Einheiten (Kp = Stellwert-Einheit je Istwert-Einheit, z. B. %/°C). Rechnet der Regler mit normierten Werten: Kp_norm = Kp · Istwert-Spanne / Stellwert-Spanne. Negatives Kp: Wirksinn umkehren und den Betrag eintragen. Die Simulation berücksichtigt keine Stellwertbegrenzung.')


class PidError(Exception):
    """Fehler bei der Optimierung mit verständlicher Meldung (wird im Dialog angezeigt)."""


@dataclass
class Model:
    kind: str                  # "FOPDT" (PT1 + Totzeit) oder "IPDT" (I-Strecke + Totzeit)
    K: float                   # Verstärkung (FOPDT) bzw. Integrierbeiwert Ki in 1/s (IPDT)
    T: float                   # Zeitkonstante in s (nur FOPDT)
    theta: float               # Totzeit in s
    offset: float              # Arbeitspunkt: y = offset + K·x
    fit: float                 # Übereinstimmung in % (NRMSE-Fit)
    dt: float                  # Abtastzeit der Auswertung in s
    t: np.ndarray = field(default=None, repr=False)        # Zeiten (Gitter)
    u: np.ndarray = field(default=None, repr=False)        # Stellwert auf dem Gitter
    y: np.ndarray = field(default=None, repr=False)        # Istwert auf dem Gitter
    y_model: np.ndarray = field(default=None, repr=False)  # simulierter Istwert
    warnings: list = field(default_factory=list)

    def describe(self):
        if self.kind == "IPDT":
            return (tr("I-Strecke mit Totzeit: Ki = {0:.4g} 1/s, Totzeit θ = {1:.3g} s – Übereinstimmung {2:.0f} %").format(self.K, self.theta, self.fit))
        return (tr("PT1 mit Totzeit: K = {0:.4g}, T = {1:.3g} s, Totzeit θ = {2:.3g} s – Übereinstimmung {3:.0f} %").format(self.K, self.T, self.theta, self.fit))


@dataclass
class Tuning:
    method: str
    kp: float
    ti: float                  # s (inf = kein I-Anteil)
    td: float                  # s
    overshoot: float = float("nan")    # % (Sollwertsprung, Simulation)
    settling: float = float("nan")     # s (2-%-Band)
    note: str = ""

    @property
    def ki(self):
        """Integralverstärkung der Parallelform Kp/Ti (1/s)."""
        return self.kp / self.ti if self.ti and math.isfinite(self.ti) else 0.0

    @property
    def kd(self):
        """Differentialverstärkung der Parallelform Kp·Td (s)."""
        return self.kp * self.td


# ---------------------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------------------
def _lowpass(u, alpha, x0):
    """PT1 in Differenzengleichung: x[k+1] = α·x[k] + (1−α)·u[k]; x[0] = x0."""
    try:                                     # schnell mit scipy, wenn vorhanden
        from scipy.signal import lfilter
        b, a = [0.0, 1.0 - alpha], [1.0, -alpha]
        zi = np.array([alpha * x0])
        out, _ = lfilter(b, a, u, zi=zi)
        out = out.copy()
        out[0] = x0
        return out
    except ImportError:
        pass
    out = np.empty(len(u))
    x, beta = float(x0), 1.0 - alpha
    ul = u.tolist()
    for k in range(len(ul)):
        out[k] = x
        x = alpha * x + beta * ul[k]
    return out


def _delayed(t, u, theta):
    """u(t − θ) auf dem Gitter t (vor dem Anfang: erster Wert)."""
    return np.interp(t - theta, t, u)


def _ls(cols, y):
    """Kleinste Quadrate y ≈ Σ p_i · cols_i -> (Parameter, Fehlerquadratsumme)."""
    A = np.column_stack(cols)
    p, *_ = np.linalg.lstsq(A, y, rcond=None)
    r = y - A @ p
    return p, float(r @ r)


def resample(t, u, y, max_points=MAX_POINTS):
    """Messdaten auf ein gleichmäßiges Zeitgitter bringen (fehlende Werte werden überbrückt)."""
    t, u, y = (np.asarray(a, dtype=float) for a in (t, u, y))
    ok = np.isfinite(t) & np.isfinite(u) & np.isfinite(y)
    t, u, y = t[ok], u[ok], y[ok]
    if len(t) < 20:
        raise PidError(tr("Zu wenige gültige Messwerte im Zeitbereich (mindestens 20 nötig)."))
    order = np.argsort(t, kind="stable")
    t, u, y = t[order], u[order], y[order]
    span = t[-1] - t[0]
    if span <= 0:
        raise PidError(tr("Der Zeitbereich ist leer."))
    d = np.diff(t)
    d = d[d > 0]
    dt = max(float(np.median(d)) if len(d) else span / len(t), span / max_points)
    grid = np.arange(t[0], t[-1] + dt * 0.5, dt)
    return grid, np.interp(grid, t, u), np.interp(grid, t, y), dt


def _fit_percent(y, ym):
    den = np.linalg.norm(y - y.mean())
    return 100.0 * (1.0 - np.linalg.norm(y - ym) / den) if den > 0 else 0.0


# ---------------------------------------------------------------------------------------
# 1. Modell
# ---------------------------------------------------------------------------------------
def _fopdt_error(t, u, y, T, theta, dt):
    ud = _delayed(t, u, theta)
    x = _lowpass(ud, math.exp(-dt / T), ud[0])        # Strecke zu Beginn im Gleichgewicht
    p, sse = _ls([np.ones_like(x), x], y)
    return sse, p, x


def _ipdt_error(t, u, y, theta, dt):
    ud = _delayed(t, u, theta)
    integ = np.concatenate([[0.0], np.cumsum(ud[:-1]) * dt])      # ∫ u(τ−θ) dτ
    tt = t - t[0]
    # y = c + Ki·∫u dt − Ki·u0·t  (u0 = Stellwert, bei dem der Istwert konstant bleibt)
    p, sse = _ls([np.ones_like(tt), integ, tt], y)
    return sse, p, integ, tt


def identify(t, u, y):
    """Streckenmodell aus Stellwert u und Istwert y (gleich lange Folgen, Zeiten t in s) -> Model."""
    t, u, y, dt = resample(t, u, y)
    span = t[-1] - t[0]
    warnings = []
    u_rng = float(np.ptp(u))
    y_rng = float(np.ptp(y))
    if u_rng <= 1e-9 * max(1.0, abs(float(np.mean(u)))):
        raise PidError(tr("Der Stellwert ändert sich im gewählten Zeitbereich nicht – ohne Anregung lässt sich die "
                       "Strecke nicht bestimmen.\nBitte einen Bereich mit Stellwertsprung (Handbetrieb) oder "
                       "Sollwertsprung wählen."))
    if y_rng <= 1e-12:
        raise PidError(tr("Der Istwert ändert sich im gewählten Zeitbereich nicht."))

    # --- grobe Suche auf einem Raster (mit reduzierter Punktzahl), dann Verfeinerung
    step = max(1, len(t) // 800)
    tc, uc, yc, dtc = t[::step], u[::step], y[::step], dt * step
    thetas = np.linspace(0.0, 0.5 * span, 26)
    Ts = np.geomspace(max(dt, span / 2000), 3.0 * span, 28)
    best = (math.inf, None, None)
    for th in thetas:
        for T in Ts:
            sse = _fopdt_error(tc, uc, yc, T, th, dtc)[0]
            if sse < best[0]:
                best = (sse, T, th)
    _, T, th = best
    # Verfeinerung (Mustersuche mit kleiner werdenden Schritten) auf allen Punkten.
    cur = _fopdt_error(t, u, y, T, th, dt)[0]
    fT, dth = 1.5, max(span / 50, dt)
    for _ in range(60):
        improved = False
        for T2, th2 in ((T * fT, th), (T / fT, th), (T, th + dth), (T, max(0.0, th - dth))):
            if T2 < dt * 0.2 or T2 > 10 * span or th2 > 0.8 * span:
                continue
            e = _fopdt_error(t, u, y, T2, th2, dt)[0]
            if e < cur:
                cur, T, th, improved = e, T2, th2, True
        if not improved:
            fT, dth = math.sqrt(fT), dth / 2
            if fT < 1.002 and dth < dt / 10:
                break
    sse_f, p_f, x_f = _fopdt_error(t, u, y, T, th, dt)
    y_f = p_f[0] + p_f[1] * x_f

    # --- I-Strecke zum Vergleich (nur Totzeit gesucht)
    best_i = (math.inf, 0.0)
    for th_i in np.linspace(0.0, 0.5 * span, 51):
        e = _ipdt_error(t, u, y, th_i, dt)[0]
        if e < best_i[0]:
            best_i = (e, th_i)
    sse_i, p_i, integ, tt = _ipdt_error(t, u, y, best_i[1], dt)
    y_i = p_i[0] + p_i[1] * integ + p_i[2] * tt

    use_ipdt = (T > 2.0 * span and sse_i <= sse_f * 1.2) or sse_i < 0.8 * sse_f
    if use_ipdt:
        m = Model("IPDT", float(p_i[1]), float("inf"), float(best_i[1]), float(p_i[0]), _fit_percent(y, y_i), dt,
                  t, u, y, y_i, warnings)
        if m.K == 0:
            raise PidError(tr("Kein Zusammenhang zwischen Stellwert und Istwert erkennbar."))
    else:
        m = Model("FOPDT", float(p_f[1]), float(T), float(th), float(p_f[0]), _fit_percent(y, y_f), dt,
                  t, u, y, y_f, warnings)
        if m.K == 0:
            raise PidError(tr("Kein Zusammenhang zwischen Stellwert und Istwert erkennbar."))
        if T > span:
            warnings.append(tr("Die Zeitkonstante ist länger als der Zeitbereich – für ein genaueres Modell einen "
                            "längeren Bereich wählen (bis der Istwert eingeschwungen ist)."))
    if m.fit < 50:
        warnings.append(tr("Das Modell passt nur mäßig zu den Daten ({0:.0f} %). Ursachen: Störungen, Nichtlinearität, Stellwertbegrenzung oder zu wenig Anregung. Die Parameter vorsichtig verwenden.").format(m.fit))
    if m.theta < 2 * dt:
        warnings.append(tr("Totzeit nicht messbar (kleiner als die Abtastzeit). Für die Berechnung wird eine kleine "
                        "Ersatztotzeit angenommen."))
    if m.K < 0:
        warnings.append(tr("Negative Streckenverstärkung (Istwert sinkt bei steigendem Stellwert, z. B. Kühlung): "
                        "die Reglerverstärkung ist negativ – in der Steuerung den Wirksinn umkehren und den Betrag "
                        "verwenden."))
    return m


# ---------------------------------------------------------------------------------------
# 2. Einstellregeln
# ---------------------------------------------------------------------------------------
def _series_to_ideal(kp, ti, td):
    """Reihenform (Kp·(1+1/(Ti s))·(1+Td s)) -> Standardform."""
    if td <= 0 or not math.isfinite(ti):
        return kp, ti, td
    f = 1.0 + td / ti
    return kp * f, ti * f, td / f


def _theta_eff(m):
    """Totzeit für die Regeln: mindestens eine halbe Abtastzeit und 1 % von T (sonst unendliche Verstärkung)."""
    th = max(m.theta + m.dt / 2, m.dt)
    if m.kind == "FOPDT":
        th = max(th, 0.01 * m.T)
    return th


def tune(m: Model, ctype="PID", behaviour="normal"):
    """Reglerparameter nach allen Regeln -> Liste von Tuning (zuerst die empfohlene Regel)."""
    K, th = m.K, _theta_eff(m)
    pid = ctype == "PID"
    fac = {"schnell": 0.5, "normal": 1.0, "robust": 3.0}.get(behaviour, 1.0)
    out = []
    if m.kind == "IPDT":
        tc = fac * th
        # SIMC für I-Strecken; PID: halbe Totzeit als Vorhalt.
        if pid:
            th2 = th / 2
            kp, ti, td = 1.0 / (K * (tc + th2)), 4 * (tc + th2), th2
            out.append(Tuning(METHODS[0], *_series_to_ideal(kp, ti, td)))
        else:
            out.append(Tuning(METHODS[0], 1.0 / (K * (tc + th)), 4 * (tc + th), 0.0))
        lam = {"schnell": 1.0, "normal": 2.0, "robust": 4.0}.get(behaviour, 2.0) * th
        ti = 2 * lam + th
        out.append(Tuning(METHODS[1], ti / (K * (lam + th) ** 2), ti, 0.0,
                          note=N_("Lambda-Regel für I-Strecken (PI)")))
        # Ziegler-Nichols für I-Strecken (Ersatz: T/K -> 1/Ki)
        if pid:
            out.append(Tuning(METHODS[4], 1.2 / (K * th), 2 * th, 0.5 * th))
        else:
            out.append(Tuning(METHODS[4], 0.9 / (K * th), 3.33 * th, 0.0))
        return out

    T = m.T
    # SIMC (Skogestad 2003): τc = θ (normal); PID über Aufteilung der Totzeit.
    tc = max(fac * th, {"schnell": 0.05, "normal": 0.1, "robust": 0.3}.get(behaviour, 0.1) * T)
    if pid:
        T2, th2 = T + th / 2, th / 2
        kp, ti, td = T2 / (K * (tc + th2)), min(T2, 4 * (tc + th2)), th / 2
        out.append(Tuning(METHODS[0], *_series_to_ideal(kp, ti, td)))
    else:
        out.append(Tuning(METHODS[0], T / (K * (tc + th)), min(T, 4 * (tc + th)), 0.0))
    # IMC / Lambda
    lam = {"schnell": max(th, 0.25 * T), "normal": max(1.5 * th, 0.6 * T),
           "robust": max(3 * th, 1.5 * T)}.get(behaviour, max(1.5 * th, 0.6 * T))
    if pid:
        out.append(Tuning(METHODS[1], (T + th / 2) / (K * (lam + th / 2)), T + th / 2, T * th / (2 * T + th)))
    else:
        out.append(Tuning(METHODS[1], T / (K * (lam + th)), T, 0.0))
    # AMIGO (Åström & Hägglund)
    if pid:
        out.append(Tuning(METHODS[2], (0.2 + 0.45 * T / th) / K, (0.4 * th + 0.8 * T) / (th + 0.1 * T) * th,
                          0.5 * th * T / (0.3 * th + T)))
    else:
        out.append(Tuning(METHODS[2], 0.15 / K + (0.35 - th * T / (th + T) ** 2) * T / (K * th),
                          0.35 * th + 13 * th * T ** 2 / (T ** 2 + 12 * th * T + 7 * th ** 2), 0.0))
    # Chien-Hrones-Reswick, Führungsverhalten ohne Überschwingen
    if pid:
        out.append(Tuning(METHODS[3], 0.6 * T / (K * th), T, 0.5 * th))
    else:
        out.append(Tuning(METHODS[3], 0.35 * T / (K * th), 1.2 * T, 0.0))
    # Ziegler-Nichols (Sprungantwort) – schnell, schwach gedämpft
    if pid:
        out.append(Tuning(METHODS[4], 1.2 * T / (K * th), 2 * th, 0.5 * th, note=N_("schwach gedämpft")))
    else:
        out.append(Tuning(METHODS[4], 0.9 * T / (K * th), 3.33 * th, 0.0, note=N_("schwach gedämpft")))
    return out


# ---------------------------------------------------------------------------------------
# 3. Simulation des Regelkreises
# ---------------------------------------------------------------------------------------
def horizon(m: Model):
    """Sinnvolle Simulationsdauer in s."""
    th = _theta_eff(m)
    if m.kind == "IPDT":
        return 40 * th
    return max(6 * (m.T + th), 20 * th)


def simulate_loop(m: Model, tn: Tuning, duration=None, step=1.0, n=1500):
    """Sollwertsprung (Höhe ``step``) mit Modell und Regler simulieren.

    Rückgabe: (t, Sollwert, Istwert, Stellwert) als Abweichung vom Arbeitspunkt. Der D-Anteil wirkt auf den Istwert
    (kein Stoß bei Sollwertsprung) und ist mit Td/10 gefiltert – wie bei den meisten SPS-Reglern."""
    duration = duration or horizon(m)
    dt = duration / n
    nd = int(round(m.theta / dt))
    a = math.exp(-dt / m.T) if m.kind == "FOPDT" else 1.0
    buf = [0.0] * (nd + 1)                     # Totzeit-Puffer des Stellwerts
    y = x = integ = d_state = 0.0
    tf = tn.td / 10 if tn.td > 0 else 0.0
    ts, sps, ys, us = [], [], [], []
    y_prev = 0.0
    for k in range(n + 1):
        t = k * dt
        sp = step if t >= 0.02 * duration else 0.0
        e = sp - y
        # D-Anteil auf den Istwert, gefiltert
        if tn.td > 0:
            d_raw = -(y - y_prev) / dt
            d_state += (dt / (tf + dt)) * (d_raw - d_state)
        y_prev = y
        u = tn.kp * (e + integ + tn.td * d_state)
        if math.isfinite(tn.ti) and tn.ti > 0:
            integ += e * dt / tn.ti
        ts.append(t)
        sps.append(sp)
        ys.append(y)
        us.append(u)
        buf.append(u)
        ud = buf.pop(0)
        # Strecke
        if m.kind == "FOPDT":
            x = a * x + (1 - a) * ud
            y = m.K * x
        else:
            y += m.K * ud * dt
        if not math.isfinite(y) or abs(y) > 1e6 * abs(step):
            break                               # instabil
    return np.array(ts), np.array(sps), np.array(ys), np.array(us)


def assess(m: Model, tn: Tuning):
    """Überschwingen (%) und Ausregelzeit (2 %) aus der Simulation in tn eintragen."""
    t, sp, y, _u = simulate_loop(m, tn)
    t_step = 0.02 * t[-1] if len(t) else 0.0
    if len(t) < 1501 or not np.all(np.isfinite(y)):           # Simulation abgebrochen: instabil
        tn.overshoot, tn.settling = float("inf"), float("inf")
        tn.note = (tn.note + "; " if tn.note else "") + N_("instabil")
        return tn
    tn.overshoot = max(0.0, float(np.max(y)) - 1.0) * 100
    outside = np.nonzero(np.abs(y - 1.0) > 0.02)[0]
    if len(outside) and outside[-1] >= len(y) - 2:
        tn.settling = float("inf")
        if np.max(np.abs(y[len(y) // 2:] - 1.0)) > 0.5:
            tn.note = (tn.note + "; " if tn.note else "") + N_("instabil")
    else:
        tn.settling = float(t[outside[-1] + 1] - t_step) if len(outside) else 0.0
    return tn


def optimize(t, u, y, ctype="PID", behaviour="normal"):
    """Alles in einem: Modell bestimmen, Regeln berechnen, bewerten -> (Model, [Tuning])."""
    m = identify(t, u, y)
    tunings = [assess(m, tn) for tn in tune(m, ctype, behaviour)]
    return m, tunings


def guess_roles(names):
    """Sollwert, Istwert, Stellwert anhand üblicher Namen erraten -> (sw, iw, stw), leer wenn unbekannt."""
    keys = {"sw": ("soll", "sp", "setpoint", "sollwert", "w_", "ref"),
            "iw": ("ist", "pv", "istwert", "x_", "messwert", "actual"),
            "stw": ("stell", "cv", "out", "mv", "y_", "stellwert", "ausgang", "output", "lmn")}
    found = {}
    for role, words in keys.items():
        for n in names:
            low = n.lower()
            if n not in found.values() and any(w in low for w in words):
                found[role] = n
                break
    return found.get("sw", ""), found.get("iw", ""), found.get("stw", "")


def format_params(tn: Tuning):
    """Parameter als Text (für Zwischenablage)."""
    ti = tr("∞ (kein I-Anteil)") if not math.isfinite(tn.ti) else f"{tn.ti:.4g} s ({tn.ti / 60:.4g} min)"
    td = f"{tn.td:.4g} s ({tn.td / 60:.4g} min)"
    return (tr("{0}: Kp = {1:.4g}, Ti = {2}, Td = {3}; Parallelform Ki = {4:.4g} 1/s, Kd = {5:.4g} s").format(tn.method, tn.kp, ti, td, tn.ki, tn.kd))
