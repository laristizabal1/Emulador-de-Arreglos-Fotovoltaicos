"""
pipeline/
=========
Módulos de procesamiento de datos y generación de perfiles de emulación.

    nasa_power  — descarga y parseo de la API NASA POWER
    profile     — cálculo de consignas V_set/I_set/P_set + estrategias
    seqlog      — exportación al formato CSV SeqLog de EA Power Control
"""
from pipeline import nasa_power, profile, seqlog

__all__ = ["nasa_power", "profile", "seqlog"]
