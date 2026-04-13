import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv("log_fuente.csv")

plt.plot(df["voltage"], df["current"])
plt.xlabel("Voltaje (V)")
plt.ylabel("Corriente (A)")
plt.title("Curva I-V Simulada")
plt.grid()
plt.show()