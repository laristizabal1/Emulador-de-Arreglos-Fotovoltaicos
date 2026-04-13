"""
comm/
=====
Comunicación con la fuente EA-PS 10060-170.

    scpi     — control por USB/COM (SCPI ASCII)  ← activo
    ethernet — control por TCP/IP port 5025      ← trabajo futuro Fase 3

Intercambiar el controlador activo en scpi_cb.py:
    from comm.scpi     import SCPIController   # USB/COM (actual)
    from comm.ethernet import EthernetSCPIController  # TCP/IP (futuro)
"""
from comm.scpi import SCPIController, list_ports, SERIAL_AVAILABLE

__all__ = ["SCPIController", "list_ports", "SERIAL_AVAILABLE"]
