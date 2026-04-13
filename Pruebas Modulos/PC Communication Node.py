from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

import serial

from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
from pymodbus.server import StartTcpServer
from pymodbus.datastore import ModbusDeviceIdentification

# =========================================================
# YOUR EXISTING SCPI LAYER
# =========================================================
@dataclass
class EAConfig:
    port: str = "COM3"
    baudrate: int = 115200
    timeout_s: float = 0.2
    write_delay_s: float = 0.002
    query_delay_s: float = 0.003
    newline: str = "\n"
    use_readline: bool = True


class EAPowerSupply:
    def __init__(self, cfg: EAConfig):
        self.cfg = cfg
        self.ser: Optional[serial.Serial] = None
        self._lock = threading.Lock()

        self._power_cmd: Optional[str] = None
        self._voltage_meas_cmd: Optional[str] = "MEAS:VOLT?"
        self._current_meas_cmd: Optional[str] = "MEAS:CURR?"

    def open(self) -> None:
        self.ser = serial.Serial(
            self.cfg.port,
            self.cfg.baudrate,
            timeout=self.cfg.timeout_s,
            write_timeout=self.cfg.timeout_s,
        )
        time.sleep(0.05)

    def close(self) -> None:
        if self.ser is not None and self.ser.is_open:
            self.ser.close()

    def _ensure_open(self) -> serial.Serial:
        if self.ser is None or not self.ser.is_open:
            raise RuntimeError("Serial port not open. Call open() first.")
        return self.ser

    def write(self, cmd: str) -> None:
        with self._lock:
            ser = self._ensure_open()
            ser.write((cmd.strip() + self.cfg.newline).encode("ascii"))
            time.sleep(self.cfg.write_delay_s)

    def query(self, cmd: str) -> str:
        with self._lock:
            ser = self._ensure_open()
            ser.write((cmd.strip() + self.cfg.newline).encode("ascii"))
            time.sleep(self.cfg.query_delay_s)

            if self.cfg.use_readline:
                resp = ser.readline().decode("ascii", errors="ignore").strip()
            else:
                resp = ser.read(256).decode("ascii", errors="ignore").strip()
            return resp

    def idn(self) -> str:
        return self.query("*IDN?")

    def output(self, on: bool) -> None:
        self.write(f"OUTP {'ON' if on else 'OFF'}")

    def set_voltage(self, v: float) -> None:
        self.write(f"VOLT {v}")

    def set_current_limit(self, a: float) -> None:
        self.write(f"CURR {a}")

    def try_set_power_limit(self, w: float) -> bool:
        if self._power_cmd is not None:
            try:
                self.write(self._power_cmd.format(w=w))
                return True
            except Exception:
                self._power_cmd = None

        for c in [f"POW {w}", f"SOUR:POW {w}", f"POWer {w}"]:
            try:
                self.write(c)
                self._power_cmd = c.replace(str(w), "{w}")
                return True
            except Exception:
                pass
        return False

    def try_read_meas(self):
        v = None
        i = None

        try:
            r = self.query(self._voltage_meas_cmd)
            if r:
                v = float(r.split(",")[0])
        except Exception:
            for q in ["VOLT?", "MEAS:SCAL:VOLT?"]:
                try:
                    r = self.query(q)
                    if r:
                        v = float(r.split(",")[0])
                        self._voltage_meas_cmd = q
                        break
                except Exception:
                    pass

        try:
            r = self.query(self._current_meas_cmd)
            if r:
                i = float(r.split(",")[0])
        except Exception:
            for q in ["CURR?", "MEAS:SCAL:CURR?"]:
                try:
                    r = self.query(q)
                    if r:
                        i = float(r.split(",")[0])
                        self._current_meas_cmd = q
                        break
                except Exception:
                    pass

        return v, i


# =========================================================
# GATEWAY STATE
# =========================================================
class GatewayState:
    """
    Shared state between:
    - SCPI polling/control thread
    - Modbus TCP server
    """
    def __init__(self):
        self.lock = threading.Lock()

        # Measurements
        self.v_meas = 0.0
        self.i_meas = 0.0
        self.p_meas = 0.0
        self.output_state = 0
        self.comm_ok = 0

        # Commands received from Modbus
        self.v_set = 0.0
        self.i_set = 0.0
        self.output_cmd = 0

        # Internal
        self.last_error = 0


# =========================================================
# MODBUS REGISTER MAP
# =========================================================
"""
Holding registers (4xxxx) used here:

HR0  = V_meas * 100      [V]
HR1  = I_meas * 100      [A]
HR2  = P_meas * 10       [W]
HR3  = output_state      [0/1]
HR4  = comm_ok           [0/1]

HR10 = V_set_cmd * 100   [V]
HR11 = I_set_cmd * 100   [A]
HR12 = output_cmd        [0/1]

HR20 = last_error
"""

REG_V_MEAS = 0
REG_I_MEAS = 1
REG_P_MEAS = 2
REG_OUT_STATE = 3
REG_COMM_OK = 4

REG_V_SET_CMD = 10
REG_I_SET_CMD = 11
REG_OUT_CMD = 12

REG_LAST_ERROR = 20


# =========================================================
# SCPI <-> MODBUS BRIDGE LOOP
# =========================================================
def scpi_gateway_loop(
    ps: EAPowerSupply,
    state: GatewayState,
    context: ModbusServerContext,
    poll_s: float = 0.2,
):
    """
    Main loop:
    1. read Modbus commands
    2. send commands to EA via SCPI if changed
    3. poll EA measurements
    4. publish measurements into Modbus registers
    """
    slave_id = 0x00

    last_v_set = None
    last_i_set = None
    last_out = None

    while True:
        try:
            hr = context[slave_id].getValues(3, 0, count=32)

            v_set_cmd = hr[REG_V_SET_CMD] / 100.0
            i_set_cmd = hr[REG_I_SET_CMD] / 100.0
            out_cmd = int(hr[REG_OUT_CMD])

            # Send only on change
            if last_v_set != v_set_cmd:
                ps.set_voltage(v_set_cmd)
                last_v_set = v_set_cmd

            if last_i_set != i_set_cmd:
                ps.set_current_limit(i_set_cmd)
                last_i_set = i_set_cmd

            if last_out != out_cmd:
                ps.output(bool(out_cmd))
                last_out = out_cmd

            # Read measurements
            v, i = ps.try_read_meas()
            if v is None:
                v = 0.0
            if i is None:
                i = 0.0
            p = v * i

            with state.lock:
                state.v_meas = v
                state.i_meas = i
                state.p_meas = p
                state.output_state = out_cmd
                state.comm_ok = 1
                state.last_error = 0

            context[slave_id].setValues(3, REG_V_MEAS, [int(round(v * 100))])
            context[slave_id].setValues(3, REG_I_MEAS, [int(round(i * 100))])
            context[slave_id].setValues(3, REG_P_MEAS, [int(round(p * 10))])
            context[slave_id].setValues(3, REG_OUT_STATE, [out_cmd])
            context[slave_id].setValues(3, REG_COMM_OK, [1])
            context[slave_id].setValues(3, REG_LAST_ERROR, [0])

        except Exception:
            with state.lock:
                state.comm_ok = 0
                state.last_error = 1

            context[slave_id].setValues(3, REG_COMM_OK, [0])
            context[slave_id].setValues(3, REG_LAST_ERROR, [1])

        time.sleep(poll_s)


# =========================================================
# STARTUP
# =========================================================
def build_modbus_context() -> ModbusServerContext:
    block = ModbusSequentialDataBlock(0, [0] * 100)
    store = ModbusSlaveContext(hr=block, zero_mode=True)
    return ModbusServerContext(slaves=store, single=True)


def run_gateway():
    cfg = EAConfig(port="COM3", baudrate=115200, timeout_s=0.2)
    ps = EAPowerSupply(cfg)
    state = GatewayState()
    context = build_modbus_context()

    identity = ModbusDeviceIdentification()
    identity.VendorName = "Uniandes"
    identity.ProductCode = "PVGW"
    identity.ProductName = "PV Emulator SCPI-Modbus Gateway"
    identity.ModelName = "EA PS 10060-170 Gateway"
    identity.MajorMinorRevision = "1.0"

    ps.open()
    print("Connected to EA:", ps.idn())

    # Safe defaults
    context[0x00].setValues(3, REG_V_SET_CMD, [0])
    context[0x00].setValues(3, REG_I_SET_CMD, [100])   # 1.00 A
    context[0x00].setValues(3, REG_OUT_CMD, [0])

    worker = threading.Thread(
        target=scpi_gateway_loop,
        args=(ps, state, context, 0.2),
        daemon=True,
    )
    worker.start()

    print("Modbus TCP server running on 0.0.0.0:5020")
    StartTcpServer(
        context=context,
        identity=identity,
        address=("0.0.0.0", 5020),
    )


if __name__ == "__main__":
    run_gateway()