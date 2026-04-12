from pymodbus.client import ModbusTcpClient

IP = "192.168.0.150"   # cambia esto
PORT = 502             # puerto típico Modbus TCP
SLAVE_ID = 1

client = ModbusTcpClient(IP, port=PORT)

ok = client.connect()
print("Conexión TCP:", ok)

if ok:
    try:
        result = client.read_holding_registers(address=0, count=2, slave=SLAVE_ID)
        if result.isError():
            print("El equipo respondió, pero la lectura devolvió error Modbus:", result)
        else:
            print("Lectura exitosa:", result.registers)
    except Exception as e:
        print("Excepción durante lectura:", e)

client.close()