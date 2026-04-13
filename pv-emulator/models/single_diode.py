"""
Single-Diode Photovoltaic Model

Implementation following:
    Villalva, M.G., Gazoli, J.R. & Filho, E.R. (2009).
    "Comprehensive Approach to Modeling and Simulation of Photovoltaic Arrays."
    IEEE Transactions on Power Electronics, 24(5), 1198-1208.

All equation references (ec. X) refer to the above paper.
"""

import math
import numpy as np
from .base import PVModel, ModuleParams, MPPResult

# ── Physical constants ──────────────────────────────────────────────
k     = 1.380649e-23      # J/K  — Boltzmann constant
q     = 1.602176634e-19   # C    — electron charge
T_STC = 298.15            # K    — 25 °C
G_STC = 1000.0            # W/m²


def _effective_ns(Ns: int, Voc_n: float, Isc_n: float,
                  Vmp_n: float, Imp_n: float, a: float) -> int:
    """Determine the effective series cell count for the thermal voltage.

    For standard modules where Voc/Ns ≥ 0.50 V, Ns is returned as-is.

    For half-cell modules (Voc/Ns < 0.50 V), the physical Ns includes cells
    in internal parallel sub-strings.  This function finds the largest Ns_eff
    (≤ Ns) for which the ideal single-diode Pmax (Rs = 0, Rp → ∞) still
    exceeds the datasheet Pmax_e, ensuring the Villalva iterative algorithm
    can converge.
    """
    if Ns <= 0:
        return 1
    voc_per_cell = Voc_n / Ns
    if voc_per_cell >= 0.50:
        return Ns  # normal module — no correction needed

    Pmax_e = Vmp_n * Imp_n
    target = Pmax_e + 5.0  # margin for Rs/Rp iteration and shunt losses

    # Binary search: find the largest Ns_eff where Pmax_ideal ≥ target
    lo, hi = max(Ns // 4, 1), Ns
    best = Ns // 2  # fallback

    while lo <= hi:
        mid = (lo + hi) // 2
        Vt = mid * k * T_STC / q
        aVt = a * Vt
        if aVt <= 0:
            hi = mid - 1
            continue
        denom_exp = math.exp(min(Voc_n / aVt, 500.0)) - 1.0
        if denom_exp < 1e-30:
            hi = mid - 1
            continue
        I0 = Isc_n / denom_exp

        # Quick sweep for ideal Pmax (Rs=0, Rp=∞)
        Pmax = 0.0
        for i in range(400):
            V = Voc_n * i / 400.0
            exp_v = math.exp(min(V / aVt, 500.0))
            I = Isc_n - I0 * (exp_v - 1.0)
            if I > 0:
                P = V * I
                if P > Pmax:
                    Pmax = P

        if Pmax >= target:
            best = mid
            lo = mid + 1   # try larger Ns_eff (less correction)
        else:
            hi = mid - 1   # need smaller Ns_eff (more correction)

    return best


class SingleDiodeModel(PVModel):
    """Single-diode PV model with Rs and Rp (Villalva et al. 2009).

    Parameters
    ----------
    params : ModuleParams
        Datasheet parameters of the PV module.
    a : float, optional
        Diode ideality factor (default 1.3, valid range 1.0–1.5 for mono-Si).
    """

    def __init__(self, params: ModuleParams, a: float = 1.3):
        super().__init__(params)
        self.a = a
        self._Ns_eff = _effective_ns(
            params.Ns, params.Voc_n, params.Isc_n,
            params.Vmp_n, params.Imp_n, a
        )
        # Parameters determined by fit()
        self.Rs: float = 0.0
        self.Rp: float = 0.0
        self.Ipv_stc: float = 0.0
        self.I0_stc: float = 0.0
        self.Vt_stc: float = 0.0

    # ────────────────────────────────────────────────────────────────
    # fit() — Iterative determination of Rs and Rp at STC (Fig. 13)
    # ────────────────────────────────────────────────────────────────
    def fit(self) -> None:
        """Adjust Rs and Rp at STC using the iterative algorithm of Fig. 13.

        Implements the Pmax-matching loop: increment Rs from 0 in steps of
        0.001 Ω, recalculate Rp with ec. 9, evaluate Pmax with Newton-Raphson,
        and stop when Pmax_model ≥ Pmax_datasheet = Vmp_n × Imp_n.
        """
        if self._fitted:
            return

        p = self.p
        Pmax_e = p.Vmp_n * p.Imp_n

        # Thermal voltage at STC
        self.Vt_stc = self._Ns_eff * k * T_STC / q
        Vt = self.Vt_stc
        a  = self.a
        dT = 0.0

        # Initial Rp — ec. 11
        Rp = (p.Vmp_n / (p.Isc_n - p.Imp_n)
              - (p.Voc_n - p.Vmp_n) / p.Imp_n)
        if Rp <= 0:
            Rp = 500.0

        Rs = 0.0
        step = 0.001
        max_Rs = 3.0

        best_Rs, best_Rp = 0.0, Rp
        best_Ipv, best_I0 = p.Isc_n, 0.0
        best_err = float('inf')

        while Rs < max_Rs:
            # Saturation current — ec. 7 (improved)
            I0 = (p.Isc_n + p.KI * dT) / (
                math.exp(min((p.Voc_n + p.KV * dT) / (a * Vt), 500.0)) - 1.0
            )

            # Photovoltaic current — ec. 10 refinement
            Ipv_n = ((Rp + Rs) / Rp) * p.Isc_n if Rp > 0 else p.Isc_n
            Ipv = (Ipv_n + p.KI * dT)

            # Rp from ec. 9
            exp_arg = min((p.Vmp_n + p.Imp_n * Rs) / (a * Vt), 500.0)
            exp_mpp = math.exp(exp_arg)
            denom = (p.Vmp_n * Ipv
                     - p.Vmp_n * I0 * exp_mpp
                     + p.Vmp_n * I0
                     - Pmax_e)
            if abs(denom) > 1e-15:
                Rp_new = p.Vmp_n * (p.Vmp_n + p.Imp_n * Rs) / denom
                if Rp_new > 0:
                    Rp = Rp_new

            # Evaluate Pmax by sweeping V
            Pmax_m = self._calc_pmax(Ipv, I0, Rs, Rp, Vt, a, p.Voc_n)

            err = abs(Pmax_m - Pmax_e)
            if err < best_err:
                best_err = err
                best_Rs = Rs
                best_Rp = Rp
                best_Ipv = Ipv
                best_I0 = I0

            if Pmax_m >= Pmax_e:
                break
            Rs += step

        self.Rs = best_Rs
        self.Rp = best_Rp
        self.Ipv_stc = best_Ipv
        self.I0_stc = best_I0
        self._fitted = True

    # ────────────────────────────────────────────────────────────────
    # get_mpp()
    # ────────────────────────────────────────────────────────────────
    def get_mpp(self, G_poa: float, T_cell: float,
                Ns_arr: int = 1, Np_arr: int = 1,
                V_max_hw: float = 60.0, I_max_hw: float = 170.0) -> MPPResult:
        """Return the MPP of the array for given G and T.

        Scales module parameters to the array and sweeps the I-V curve.
        """
        if G_poa < 5:
            return MPPResult(0.0, 0.0, 0.0)

        Ipv, I0, Rs, Rp, Vt, a, Voc_est = self._scale_to_conditions(
            G_poa, T_cell, Ns_arr, Np_arr
        )

        n_pts = 500
        V_arr = np.linspace(0.0, Voc_est * 1.05, n_pts)
        I_arr = np.array([
            self._newton_raphson(v, Ipv, I0, Rs, Rp, Vt, a) for v in V_arr
        ])
        I_arr = np.clip(I_arr, 0.0, None)

        P_arr = V_arr * I_arr
        idx = int(np.argmax(P_arr))
        Vmp = float(np.clip(V_arr[idx], 0.0, V_max_hw))
        Imp = float(np.clip(I_arr[idx], 0.0, I_max_hw))

        return MPPResult(round(Vmp, 3), round(Imp, 3), round(Vmp * Imp, 1))

    # ────────────────────────────────────────────────────────────────
    # iv_curve()
    # ────────────────────────────────────────────────────────────────
    def iv_curve(self, G_poa: float, T_cell: float,
                 Ns_arr: int = 1, Np_arr: int = 1,
                 n_pts: int = 200) -> MPPResult:
        """Return the full I-V curve and MPP. Implements ec. 3 via Newton-Raphson."""
        if G_poa < 5:
            return MPPResult(0.0, 0.0, 0.0)

        Ipv, I0, Rs, Rp, Vt, a, Voc_est = self._scale_to_conditions(
            G_poa, T_cell, Ns_arr, Np_arr
        )

        V_arr = np.linspace(0.0, Voc_est * 1.05, n_pts)
        I_arr = np.array([
            self._newton_raphson(v, Ipv, I0, Rs, Rp, Vt, a) for v in V_arr
        ])
        I_arr = np.clip(I_arr, 0.0, None)

        P_arr = V_arr * I_arr
        idx = int(np.argmax(P_arr))
        Vmp = float(V_arr[idx])
        Imp = float(I_arr[idx])

        return MPPResult(round(Vmp, 3), round(Imp, 3), round(Vmp * Imp, 1),
                         V_arr, I_arr)

    # ================================================================
    # Private helpers
    # ================================================================

    def _scale_to_conditions(self, G_poa, T_cell, Ns_arr, Np_arr):
        """Scale module parameters to operating conditions and array.

        Implements ec. 4 (Ipv), ec. 7 (I0), and array scaling.
        """
        p  = self.p
        T  = T_cell + 273.15
        dT = T_cell - 25.0
        a  = self.a

        Vt_mod = self._Ns_eff * k * T / q

        # ec. 10 + ec. 4
        Ipv_n = ((self.Rp + self.Rs) / self.Rp) * p.Isc_n if self.Rp > 0 else p.Isc_n
        Ipv = (Ipv_n + p.KI * dT) * (G_poa / G_STC)

        # ec. 7
        Voc_T = p.Voc_n + p.KV * dT
        denom_exp = math.exp(min(Voc_T / (a * Vt_mod), 500.0)) - 1.0
        if denom_exp < 1e-30:
            denom_exp = 1e-30
        I0 = (p.Isc_n + p.KI * dT) / denom_exp

        # Array scaling
        Ipv_arr = Ipv * Np_arr
        I0_arr  = I0  * Np_arr
        Rs_arr  = self.Rs * Ns_arr / max(Np_arr, 1)
        Rp_arr  = self.Rp * Ns_arr / max(Np_arr, 1)
        Vt_arr  = Vt_mod  * Ns_arr

        Voc_est = max(Voc_T, 1.0) * Ns_arr
        return Ipv_arr, I0_arr, Rs_arr, Rp_arr, Vt_arr, a, Voc_est

    @staticmethod
    def _newton_raphson(V, Ipv, I0, Rs, Rp, Vt, a,
                        tol=1e-9, max_iter=50):
        """Solve ec. 3 implicitly for I at given V using Newton-Raphson.

        f(I)  = I − Ipv + I0·(exp((V+I·Rs)/(a·Vt)) − 1) + (V+I·Rs)/Rp
        df/dI = 1 + I0·Rs/(a·Vt)·exp(…) + Rs/Rp
        """
        I = (Ipv - V / Rp) if Rp > 0 else Ipv
        I = max(I, 0.0)
        aVt = a * Vt
        if aVt <= 0:
            return max(I, 0.0)

        for _ in range(max_iter):
            z = V + I * Rs
            exp_x = math.exp(min(z / aVt, 500.0))
            f  = I - Ipv + I0 * (exp_x - 1.0) + z / Rp
            df = 1.0 + I0 * Rs / aVt * exp_x + Rs / Rp
            if abs(df) < 1e-30:
                break
            dI = f / df
            I -= dI
            if abs(dI) < tol:
                break
        return max(I, 0.0)

    def _calc_pmax(self, Ipv, I0, Rs, Rp, Vt, a, Voc):
        """Sweep the module I-V curve and return the peak power."""
        n_pts = 500
        V_arr = np.linspace(0.0, Voc, n_pts)
        Pmax = 0.0
        for v in V_arr:
            i = max(self._newton_raphson(v, Ipv, I0, Rs, Rp, Vt, a), 0.0)
            pv = v * i
            if pv > Pmax:
                Pmax = pv
        return Pmax
