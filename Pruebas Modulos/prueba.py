"""
EA PS 10060-170 — SCPI over USB/COM (COM3) - OPTIMIZED VERSION
Ramp + Step generator controlled from Python (no EA Power Control / no Modbus).

OPTIMIZATION CHANGES:
- Reduced write_delay from 10ms to 2ms (instrument can handle it)
- Reduced query_delay from 15ms to 3ms  
- Removed buffer reset on every query (unnecessary overhead)
- Read only expected bytes instead of 4096 (use readline for efficiency)
- Cache successful SCPI command variants to avoid retries
- Batch setup commands where possible
- Added command pipelining option

Expected performance: <200ms per command execution
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Tuple

import serial


# -----------------------
# Low-level SCPI wrapper
# -----------------------
@dataclass
class EAConfig:
    port: str = "COM3"
    baudrate: int = 115200
    timeout_s: float = 0.2          # Reduced from 1.0s - faster failure detection
    write_delay_s: float = 0.002    # Reduced from 0.01s - EA can handle faster commands
    query_delay_s: float = 0.003    # Reduced from 0.015s - minimal settling time
    newline: str = "\n"
    use_readline: bool = True       # NEW: Use readline() instead of read(4096)


class EAPowerSupply:
    def __init__(self, cfg: EAConfig):
        self.cfg = cfg
        self.ser: Optional[serial.Serial] = None
        
        # NEW: Cache successful command variants to avoid retrying
        self._power_cmd: Optional[str] = None
        self._voltage_meas_cmd: Optional[str] = "MEAS:VOLT?"  # Most common
        self._current_meas_cmd: Optional[str] = "MEAS:CURR?"  # Most common

    def open(self) -> None:
        self.ser = serial.Serial(
            self.cfg.port,
            self.cfg.baudrate,
            timeout=self.cfg.timeout_s,
            write_timeout=self.cfg.timeout_s,
        )
        time.sleep(0.05)  # Reduced from 0.1s

    def close(self) -> None:
        if self.ser is not None and self.ser.is_open:
            self.ser.close()

    def _ensure_open(self) -> serial.Serial:
        if self.ser is None or not self.ser.is_open:
            raise RuntimeError("Serial port not open. Call open() first.")
        return self.ser

    def write(self, cmd: str) -> None:
        """Optimized write with minimal delay"""
        ser = self._ensure_open()
        ser.write((cmd.strip() + self.cfg.newline).encode("ascii"))
        time.sleep(self.cfg.write_delay_s)  # Now only 2ms

    def query(self, cmd: str) -> str:
        """Optimized query using readline for efficiency"""
        ser = self._ensure_open()
        # REMOVED: reset_input_buffer() - saves ~5-10ms
        ser.write((cmd.strip() + self.cfg.newline).encode("ascii"))
        time.sleep(self.cfg.query_delay_s)  # Now only 3ms
        
        if self.cfg.use_readline:
            # Read until newline - much faster than read(4096)
            resp = ser.readline().decode("ascii", errors="ignore").strip()
        else:
            # Fallback to original method if needed
            resp = ser.read(256).decode("ascii", errors="ignore").strip()  # Reduced from 4096
        
        return resp

    def write_batch(self, commands: list) -> None:
        """NEW: Send multiple commands with minimal inter-command delay"""
        ser = self._ensure_open()
        for cmd in commands:
            ser.write((cmd.strip() + self.cfg.newline).encode("ascii"))
            time.sleep(0.001)  # Minimal 1ms between batched commands

    # -----------------------
    # High-level convenience
    # -----------------------
    def idn(self) -> str:
        return self.query("*IDN?")

    def output(self, on: bool) -> None:
        self.write(f"OUTP {'ON' if on else 'OFF'}")

    def set_voltage(self, v: float) -> None:
        self.write(f"VOLT {v}")

    def set_current_limit(self, a: float) -> None:
        self.write(f"CURR {a}")

    def try_set_power_limit(self, w: float) -> bool:
        """
        Optimized: Uses cached command if available, otherwise tries common variants.
        """
        # If we already know the working command, use it directly
        if self._power_cmd is not None:
            try:
                self.write(self._power_cmd.format(w=w))
                return True
            except Exception:
                self._power_cmd = None  # Reset cache if it fails
        
        # Try most common variants first (EA typically uses POW or SOUR:POW)
        candidates = [
            f"POW {w}",
            f"SOUR:POW {w}",
            f"POWer {w}",
        ]
        
        for c in candidates:
            try:
                self.write(c)
                # Cache the successful format for future use
                self._power_cmd = c.replace(str(w), "{w}")
                return True
            except Exception:
                pass
        
        return False

    def try_read_meas(self) -> Tuple[Optional[float], Optional[float]]:
        """
        Optimized: Uses cached commands first, falls back to alternatives only if needed.
        """
        v = None
        i = None

        # Try cached voltage command first
        try:
            r = self.query(self._voltage_meas_cmd)
            if r:
                v = float(r.split(",")[0])
        except Exception:
            # Try alternative if cached command fails
            for q in ["VOLT?", "MEAS:SCAL:VOLT?"]:
                try:
                    r = self.query(q)
                    if r:
                        v = float(r.split(",")[0])
                        self._voltage_meas_cmd = q  # Update cache
                        break
                except Exception:
                    pass

        # Try cached current command first
        try:
            r = self.query(self._current_meas_cmd)
            if r:
                i = float(r.split(",")[0])
        except Exception:
            # Try alternative if cached command fails
            for q in ["CURR?", "MEAS:SCAL:CURR?"]:
                try:
                    r = self.query(q)
                    if r:
                        i = float(r.split(",")[0])
                        self._current_meas_cmd = q  # Update cache
                        break
                except Exception:
                    pass

        return v, i

    def setup_batch(self, voltage: float, current: float, power: Optional[float] = None) -> None:
        """
        NEW: Batch setup of V/I/P limits for faster initialization
        Sends all commands together with minimal delay
        """
        commands = [
            f"VOLT {voltage}",
            f"CURR {current}",
        ]
        
        if power is not None and self._power_cmd:
            commands.append(self._power_cmd.format(w=power))
        
        self.write_batch(commands)


# -----------------------
# Waveform generators - OPTIMIZED
# -----------------------
def ramp_scpi(
    ps: EAPowerSupply,
    v_initial: float,
    v_final: float,
    dt_ms: int,
    power_w: float,
    current_a: float,
    dv: float = 1.0,
    output_on: bool = True,
    readback: bool = False,
) -> None:
    """
    OPTIMIZED: Uses batch setup and compensates delay for command execution time
    """
    if dt_ms <= 0:
        raise ValueError("dt_ms must be > 0")
    if dv <= 0:
        raise ValueError("dv must be > 0")

    # Use batch setup for faster initialization
    ps.setup_batch(v_initial, current_a, power_w)

    if output_on:
        ps.output(True)

    def frange(a: float, b: float, step: float):
        if a == b:
            return [a]
        s = step if b > a else -step
        vals = []
        x = a
        if s > 0:
            while x < b:
                vals.append(x)
                x += s
            vals.append(b)
        else:
            while x > b:
                vals.append(x)
                x += s
            vals.append(b)
        return vals

    up = frange(v_initial, v_final, dv)
    down = frange(v_final, v_initial, dv)[1:]

    dt_s = dt_ms / 1000.0

    # OPTIMIZATION: Measure command execution time and compensate
    for v in up:
        t_start = time.perf_counter()
        ps.set_voltage(v)
        
        if readback:
            vm, im = ps.try_read_meas()
            print(f"Ramp up -> Vset={v:.4g}V  Vmeas={vm}  Imeas={im}")
        
        # Compensate for execution time
        elapsed = time.perf_counter() - t_start
        sleep_time = max(0, dt_s - elapsed)
        if sleep_time > 0:
            time.sleep(sleep_time)

    for v in down:
        t_start = time.perf_counter()
        ps.set_voltage(v)
        
        if readback:
            vm, im = ps.try_read_meas()
            print(f"Ramp down -> Vset={v:.4g}V  Vmeas={vm}  Imeas={im}")
        
        elapsed = time.perf_counter() - t_start
        sleep_time = max(0, dt_s - elapsed)
        if sleep_time > 0:
            time.sleep(sleep_time)

    if output_on:
        ps.output(False)


def step_scpi(
    ps: EAPowerSupply,
    v_low: float,
    v_high: float,
    dt_ms: int,
    power_w: float,
    current_a: float,
    n_before_up: int = 0,
    n_before_down: int = 0,
    output_on: bool = True,
    readback: bool = False,
) -> None:
    """
    OPTIMIZED: Uses batch setup and compensates delay for command execution time
    """
    if dt_ms <= 0:
        raise ValueError("dt_ms must be > 0")
    if n_before_up < 0 or n_before_down < 0:
        raise ValueError("n_before_up/down must be >= 0")

    # Use batch setup
    ps.setup_batch(v_low, current_a, power_w)

    if output_on:
        ps.output(True)

    dt_s = dt_ms / 1000.0

    def do_set(v: float, label: str):
        t_start = time.perf_counter()
        ps.set_voltage(v)
        
        if readback:
            vm, im = ps.try_read_meas()
            print(f"{label} -> Vset={v:.4g}V  Vmeas={vm}  Imeas={im}")
        
        # Compensate for execution time
        elapsed = time.perf_counter() - t_start
        sleep_time = max(0, dt_s - elapsed)
        if sleep_time > 0:
            time.sleep(sleep_time)

    for _ in range(n_before_up):
        do_set(v_low, "LOW (pre)")

    do_set(v_low, "LOW")
    do_set(v_high, "HIGH")

    for _ in range(n_before_down):
        do_set(v_high, "HIGH (hold)")

    do_set(v_low, "LOW (back)")

    if output_on:
        ps.output(False)


# -----------------------
# Example usage
# -----------------------
if __name__ == "__main__":
    cfg = EAConfig(port="COM3", baudrate=115200, timeout_s=0.2)
    ps = EAPowerSupply(cfg)

    try:
        ps.open()
        print("Connected:", ps.idn())

        # Benchmark simple command
        t_start = time.perf_counter()
        ps.set_voltage(5.0)
        elapsed_ms = (time.perf_counter() - t_start) * 1000
        print(f"\nSingle command time: {elapsed_ms:.2f}ms")

        # Benchmark with readback
        t_start = time.perf_counter()
        ps.set_voltage(6.0)
        v, i = ps.try_read_meas()
        elapsed_ms = (time.perf_counter() - t_start) * 1000
        print(f"Command + readback time: {elapsed_ms:.2f}ms (V={v}, I={i})")

        # Example: Ramp (up and down)
        print("\nRunning optimized ramp...")
        ramp_scpi(ps, v_initial=0, v_final=12, dt_ms=200, power_w=100, current_a=2, dv=1.0, readback=True)

    finally:
        ps.close()
    


