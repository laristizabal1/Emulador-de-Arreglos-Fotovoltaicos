import schemdraw
import schemdraw.elements as elm
import matplotlib.pyplot as plt # Importante para controlar la visualización

# 1. Configurar el dibujo profesional
# fontsize mayor ayuda a la legibilidad en formatos de imagen como PNG
d = schemdraw.Drawing()
d.config(unit=2.5, fontsize=12)

# 2. Construir el modelo fotovoltaico de 2 diodos
# Usamos etiquetas matemáticas estándar ($...$)

# Rama de la Fuente de Corriente ($I_{ph}$)
# loc='left' coloca la etiqueta al lado para no solapar líneas
Iph = elm.SourceI().up().label('$I_{ph}$', loc='left')
d += Iph
d += elm.Ground().at(Iph.start)

d += elm.Line().right().length(d.unit*0.8)

# Rama Diodo 1 (Difusión, $D_1$)
d.push()
d += elm.Diode().down().label('$D_1$')
d += elm.Ground()
d.pop()

d += elm.Line().right().length(d.unit*0.8)

# Rama Diodo 2 (Recombinación, $D_2$)
d.push()
d += elm.Diode().down().label('$D_2$')
d += elm.Ground()
d.pop()

d += elm.Line().right().length(d.unit*0.8)

# Rama Resistencia Shunt ($R_p$ o $R_{sh}$)
d.push()
d += elm.Resistor().down().label('$R_p$')
d += elm.Ground()
d.pop()

# Rama Resistencia Serie ($R_s$) y Salida
d += elm.Line().right().length(d.unit*0.4)
Rs = elm.Resistor().right().label('$R_s$')
d += Rs

# 3. GESTIÓN PROFESIONAL DE TERMINALES DE SALIDA
# Este bloque evita los TypeErrors en Python 3.13 al usar coordenadas puras (float)

# Definir la extensión de los terminales y sus coordenadas
term_ext = 0.8
term_x = float(Rs.end[0] + term_ext) # Punto final X para la salida
y_top = float(Rs.end[1])             # Altura superior de salida
y_bot = float(Iph.start[1])          # Altura inferior (referencia de tierra)

# Dibujar líneas de terminales con bornes de conexión (.dot())
# Línea Superior
d += elm.Line().at(Rs.end).to((term_x, y_top)).dot()
# Línea Inferior (referencia)
d += elm.Line().at((float(Iph.start[0]), y_bot)).to((term_x, y_bot)).dot()

# Añadir indicadores de polaridad seguros
# loc y ofst (offset) ajustan la posición del texto respecto al punto
d += elm.Label().at((term_x, y_top)).label('+', loc='bottom', ofst=0.15)
d += elm.Label().at((term_x, y_bot)).label('-', loc='top', ofst=0.15)

# Añadir la etiqueta de Voltaje $V$ usando Gap con sintaxis .at().to()
d += elm.Gap().at((term_x, y_top)).to((term_x, y_bot)).label('$V$')

# --- SECCIÓN DE VISUALIZACIÓN INTERACTIVA ---

print("Abriendo ventana interactiva... Revisa el circuito.")
print("Cierra la ventana gráfica para ver opciones de guardado en la terminal.")

# d.draw() por defecto abre una ventana gráfica de Matplotlib de forma interactiva
d.draw()

# --- SECCIÓN DE GUARDADO (POST-VISUALIZACIÓN) ---

# Para guardar como imagen (PNG) después de verificarla, descomenta las líneas de abajo:

# print("Guardando imagen PNG en alta resolución...")
# # dpi=300 asegura calidad de impresión profesional
# d.save('modelo_fv_dos_diodos.png', dpi=300)
# print("Imagen guardada como 'modelo_fv_dos_diodos.png'")