# models/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import numpy as np

@dataclass
class ModuleParams:
    """Parámetros del datasheet del módulo PV."""
    Isc_n: float          # A  — corriente de cortocircuito STC
    Voc_n: float          # V  — voltaje de circuito abierto STC
    Imp_n: float          # A  — corriente en MPP STC
    Vmp_n: float          # V  — voltaje en MPP STC
    KI:    float          # A/°C — coef. temperatura de corriente
    KV:    float          # V/°C — coef. temperatura de voltaje
    Ns:    int            # celdas en serie dentro del módulo
    noct:  float = 45.0   # °C — temperatura nominal de operación

@dataclass
class MPPResult:
    """Resultado del punto de máxima potencia."""
    Vmp: float
    Imp: float
    Pmp: float
    V_arr: np.ndarray = field(default=None, repr=False)
    I_arr: np.ndarray = field(default=None, repr=False)

class PVModel(ABC):
    """
    Interfaz común para todos los modelos eléctricos PV.
    Todos los modelos (simplified, single_diode, two_diode) la heredan.
    """
    def __init__(self, params: ModuleParams):
        self.p = params
        self._fitted = False

    @abstractmethod
    def fit(self) -> None:
        """
        Ajustar parámetros internos a STC.
        Se llama UNA sola vez antes de usar get_mpp().
        """

    @abstractmethod
    def get_mpp(self,
                G_poa:    float,
                T_cell:   float,
                Ns_arr:   int   = 1,
                Np_arr:   int   = 1,
                V_max_hw: float = 60.0,
                I_max_hw: float = 170.0) -> MPPResult:
        """
        Calcula el punto de máxima potencia para las condiciones dadas.
        Debe respetar los límites de hardware V_max_hw e I_max_hw.
        """

    def iv_curve(self,
                 G_poa:  float,
                 T_cell: float,
                 Ns_arr: int = 1,
                 Np_arr: int = 1,
                 n_pts:  int = 200) -> MPPResult:
        """Curva I-V completa. Opcional — no todos los modelos la implementan."""
        raise NotImplementedError(f"{type(self).__name__} no implementa iv_curve()")