"""
models/
=======
Modelos eléctricos equivalentes del panel fotovoltaico.

    base         — ABC PVModel + dataclasses ModuleParams, MPPResult
    simplified   — modelo actual (ecs. 4–5 del documento)      ← operativo
    single_diode — Villalva et al. 2009 (IEEE Trans. Power El.) ← Fase 1
    two_diode    — Ishaque et al. 2011 (Sol. Energy Mater.)     ← Fase 1
    thermal      — modelos NOCT y Faiman de temperatura de celda

Uso estándar:
    from models.base       import ModuleParams
    from models.simplified import SimplifiedModel

    params = ModuleParams(Isc_n=13.5, Voc_n=49.8, Imp_n=13.35,
                          Vmp_n=41.2, KI=0.00675, KV=-0.14442, Ns=144)
    model  = SimplifiedModel(params)
    model.fit()
    mpp = model.get_mpp(G_poa=800, T_cell=35)
    print(mpp.Vmp, mpp.Imp, mpp.Pmp)
"""
from models.base import PVModel, ModuleParams, MPPResult

__all__ = ["PVModel", "ModuleParams", "MPPResult"]
