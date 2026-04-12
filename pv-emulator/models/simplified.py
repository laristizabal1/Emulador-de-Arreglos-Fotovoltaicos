# models/simplified.py
import math
import numpy as np
from .base import PVModel, ModuleParams, MPPResult

class SimplifiedModel(PVModel):
    """
    Modelo simplificado del pipeline original (ecs. 4–5 del documento).
    Calcula Vset e Iset directamente desde coeficientes de temperatura.
    No resuelve la ecuación implícita del diodo.

    Referencia: pipeline actual del notebook / App.jsx computePV()
    """

    def fit(self) -> None:
        self._fitted = True   # sin parámetros que ajustar

    def get_mpp(self, G_poa, T_cell, Ns_arr=1, Np_arr=1,
                V_max_hw=60.0, I_max_hw=170.0) -> MPPResult:
        if G_poa < 5:
            return MPPResult(0.0, 0.0, 0.0)

        p  = self.p
        dT = T_cell - 25.0
        Vt_arr = 0.026 * p.Ns * Ns_arr

        # Ecuación de corriente (Isc escala con G y temperatura)
        Imp = (p.Isc_n * Np_arr) * (G_poa / 1000.0) * (1.0 + p.KI * dT)

        # Ecuación de voltaje (Voc con corrección de temperatura y log de G)
        Vmp = ((p.Voc_n * Ns_arr)
               + p.KV * dT
               + Vt_arr * math.log(max(G_poa, 1.0) / 1000.0))

        Vmp = float(np.clip(Vmp, 0.0, V_max_hw))
        Imp = float(np.clip(Imp, 0.0, I_max_hw))
        return MPPResult(round(Vmp, 3), round(Imp, 3), round(Vmp * Imp, 1))