"""
comm/
=====
Comunicacion con la fuente EA-PS 10060-170.

    scpi     — control por USB/COM (SCPI ASCII)  <- activo
    ethernet — control por TCP/IP port 5025      <- trabajo futuro Fase 3
    bridge   — puente SCPI <-> Modbus TCP        <- microrred DC

No importar nada aqui directamente — cada modulo importa lo que necesita
desde comm.scpi, comm.bridge, etc. para evitar importaciones circulares.
"""