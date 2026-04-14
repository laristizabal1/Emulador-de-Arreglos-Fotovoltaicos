"""
models/
=======
Modelos electricos equivalentes del panel fotovoltaico.

    base          — ABC PVModel + dataclasses ModuleParams, MPPResult
    panel_factory — panel_from_datasheet(): convierte datasheet -> ModuleParams
                    con auto-deteccion de convencion de coeficientes (%/C o A/C)
    simplified    — modelo simplificado (ecs. 4-5 del documento)
    single_diode  — Villalva et al. 2009 — cualquier tecnologia cristalina
    two_diode     — Ishaque et al. 2011  — mayor precision a baja irradiancia
    thermal       — modelos NOCT y Faiman de temperatura de celda

Uso estandar:
    from models.panel_factory import panel_from_datasheet
    from models.single_diode  import SingleDiodeModel

    # Coeficientes en A/C y V/C (absolutos)
    params = panel_from_datasheet(
        Isc=13.5, Voc=49.8, Imp=13.35, Vmp=41.2,
        KI=0.00675, KV=-0.14442, Ns=144
    )

    # Coeficientes en %/C (relativos) — auto-detectados
    params = panel_from_datasheet(
        Isc=12.42, Voc=52.1, Imp=11.80, Vmp=43.7,
        KI=0.04, KV=-0.25, Ns=144
    )

    model = SingleDiodeModel(params)
    model.fit()
    mpp = model.get_mpp(G_poa=800, T_cell=35)
"""
from models.base import PVModel, ModuleParams, MPPResult

__all__ = ["PVModel", "ModuleParams", "MPPResult"]