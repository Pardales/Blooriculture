# Kaggriculture — Base de conocimiento de estrategia

> Documento vivo. Recoge **todas** las estrategias: las que funcionan (con evidencia
> medida), las que creemos que funcionan (hipótesis sin validar) y las que **no**
> funcionan (con la evidencia de por qué). Última actualización: 2026-09-27.

---

## 0. Estado actual

| Dato | Valor |
|---|---|
| Equipo | `Blooriculture` |
| Submission activa | `56496770` (subida 2026-09-23) |
| Récord en vivo | **24W – 31L – 0T** (43.6 % en 55 episodios) |
| Dinero medio nuestro | **$60 830** (min 21 480 · max 110 008) |
| Dinero medio rival | **$79 304** |
| Mejores rivales | 165 000 – **198 970** |
| Posición | **por debajo del puesto 200** (la API corta ahí) |
| Rating puesto 1 / 10 / 100 / 200 | 3053.6 / 2897.6 / 2621.9 / 2505.9 |
| Baseline local v3 (n=120) | $54 890 de media |
| **Local v4 (actual)** | **$59 056** de media, win rate 48.3 % |
| Deadline | **2026-09-30 23:59** |
| Premio | $50 000 — **los 10 primeros ganan $5 000 cada uno** |

> Realismo sobre el objetivo: entrar en el top 10 exige un rating ~2898, y estamos por
> debajo del puesto 200 (rating < 2506). La mejora verificada de la v4 (+$2.8k de margen,
> ~+8 pp de win rate) es real pero pequeña; no cambia la liga en la que jugamos. Lo que
> falta es estructural (§6), no de ajuste.

**El hueco es de 3×.** Los mejores agentes terminan en 175–199 k; nosotros en 55–65 k.
No es un problema de afinado de parámetros: es un error de estrategia estructural.

### Herramientas del repo

| Script | Para qué |
|---|---|
| `tools/kaggle_status.py` | Ranking, submissions, récord de episodios en vivo |
| `tools/fetch_replays.py` | Descarga replays (`--top N` = los N rivales con más dinero) |
| `tools/analyze_replay.py` | Ingeniería inversa de un replay: dinero/día, composición de la granja, órdenes de mercado, histograma de acciones |
| `tools/market_model.py` | Modelo cuantitativo del mercado: absorción, drenaje del pueblo, ingreso por ritmo de venta |
| `tools/bench.py` | Benchmark paralelo A vs B, N semillas × 2 asientos (~1.2 s/episodio con 18 workers) |
| `tools/sweep.py` | Barrido de constantes con intervalo de confianza y marca `**` de significancia |
| `tools/mkvariant.py` | Genera una variante de `main.py` con constantes sobrescritas |
| `tools/diag.py` | Corre un episodio local y guarda el replay para `analyze_replay.py` |

```bash
# Flujo de trabajo típico
python tools/kaggle_status.py                     # ¿dónde estamos?
python tools/fetch_replays.py --top 5             # ¿qué hacen los que ganan?
python tools/analyze_replay.py replays/*.json     # desmenuzarlo
python tools/sweep.py --ref variants/v3_nopace.py -n 100 ALGUNA_CONSTANTE=a,b,c
python tools/bench.py main.py variants/v3_nopace.py -n 60   # validación final
```

`variants/v3_nopace.py` es el agente v3 congelado: **es la referencia contra la que se
mide todo**. No lo toques.

---

## 1. El modelo económico: cuál es la restricción real

La intuición de "más producción = más dinero" **es falsa**. El factor limitante no es
la tierra ni la mano de obra: es **cuánto dinero puede pagar el mercado por cada producto**.

### 1a. Absorción instantánea (volcar unidades en un mercado intacto hasta tocar suelo)

| Producto | base | unidades hasta $1 | $ total | $/u medio |
|---|---:|---:|---:|---:|
| STRAWBERRY | 120 | **62** | 3 809 | 61 |
| WOOL | 200 | **59** | 7 928 | 134 |
| MILK | 160 | **76** | 6 181 | 81 |
| MELON | 250 | **158** | 26 485 | 168 |
| FERTILIZER | 100 | 493 | 25 045 | 51 |
| CARROT | 35 | 842 | 10 680 | 13 |
| TOMATO | 60 | 529 | 11 128 | 21 |
| EGG | 50 | ~20 000 | 692 954 | 35 |
| WHEAT | 25 | ~20 000 | 351 494 | 18 |

Los productos premium (fresa, leche, lana) **se hunden con 60–76 unidades**. Si vuelcas
el cobertizo, la fresa te paga $3 809 en total. Para siempre.

### 1b. El drenaje del pueblo: lo que regenera la capacidad de venta

Las tiendas consumen inventario **gratis** cada 4 turnos (6 veces/día), y nada repone
las estanterías. Eso empuja el inventario por debajo de `I0` y mantiene el precio **por
encima del base** toda la temporada.

| Producto | Tiendas que lo demandan | u/día por tienda | Drenaje estacional esperado |
|---|---|---:|---:|
| WHEAT | Bakery, Pizza, Brunch, IceCream, FarmersMkt | 3.75 | 525 |
| STRAWBERRY | Brunch, IceCream, Smoothie, FarmersMkt | 3.00 | 426 |
| CARROT | PetCafe (×2), FarmersMkt | 2.25 | 327 |
| MILK | Pizza, IceCream, Smoothie | 2.25 | 327 |
| TOMATO | Pizza, FarmersMkt | 1.50 | 228 |
| EGG | Bakery, Brunch | 1.50 | 228 |
| WOOL | YarnStore (×2) | 1.50 | 228 |
| MELON | — ninguna | 0.00 | 30 (solo town center) |
| FERTILIZER | — ninguna | 0.00 | **0** |

### 1c. Ingreso según el **ritmo** de venta (vendiendo del día 10 al 30)

| Producto | 2/día | 5/día | 10/día | 20/día | 30/día |
|---|---:|---:|---:|---:|---:|
| STRAWBERRY | 9 k | 22 k | 40 k | **46 k** | 17 k |
| MILK | 10 k | 25 k | **44 k** | 26 k | 18 k |
| WOOL | 9 k | 23 k | **43 k** | 20 k | 17 k |
| MELON | 10 k | 24 k | **32 k** | 31 k | 30 k |
| FERTILIZER | 4 k | 9 k | 16 k | 24 k | **25 k** |
| EGG | 2 k | 5 k | 10 k | 17 k | **25 k** |
| TOMATO | 3 k | 7 k | 12 k | 15 k | **17 k** |
| WHEAT | 2 k | 4 k | 7 k | 12 k | **14 k** |
| CARROT | 2 k | 4 k | 8 k | 11 k | **13 k** |

**Techo total del mercado ≈ $259 k**, repartido entre los dos jugadores. Los 199 k de
`Canon` son ≈ 77 % del pastel: consistente, no es un bug.

### 1d. Las tres conclusiones que gobiernan todo

1. **El ritmo vale más que el volumen.** Fresa volcada = $3.8 k; fresa a 20/día = $46 k.
   **Factor 12×.** Lo mismo con leche (6 k → 44 k) y lana (8 k → 43 k).
2. **Hay que diversificar por fuerza.** Ningún producto premium acepta más de ~10–20 u/día.
   Para llegar a 180 k hay que saturar *varios* mercados a la vez, no uno a tope.
3. **La mezcla óptima depende del episodio.** Las tiendas salen al azar con reemplazo.
   Una temporada con 3 yarn stores hace la lana rentabilísima; sin ninguna, la lana es
   basura. El agente **debe** leer `town.unlocked_shops` y pivotar. Las cifras de arriba
   son medias, no un plan fijo.

---

## 2. Estrategias que FUNCIONAN (evidencia medida)

### ✅ 2.1 Vaca + CARE es la mejor máquina de dinero del juego

`CARE` acumula +1 por día alimentado-y-cuidado, y se paga entero en la siguiente
producción programada. Leyendo `_daily_refresh_animals` en el motor: la producción
consume el banco **primero**, y luego el CARE de hoy vuelve a acumular.

| Animal | Intervalo | Sin CARE | **Con CARE** | Multiplicador | $/día (a precio de escasez) |
|---|---:|---:|---:|---:|---:|
| Vaca (leche) | 2 días | 0.50/día | **1.50/día** | **3×** | ~$330 |
| Oveja (lana) | 3 días | 0.33/día | **1.33/día** | **4×** | ~$287 |
| Ganso (huevo) | 1 día | 1.00/día | **2.00/día** | 2× | ~$100 |

Coste ≈ 3.25 acciones/animal/día (FEED + CARE + COLLECT_FERTILIZER + harvest amortizado)
→ **~$140 por acción**. Es el mejor retorno por acción del juego.

**Evidencia en replays:** los mejores agentes hacen 404 CARE (Canon) frente a nuestras
185. RB25det mantiene **18 vacas** y la leche le supone el 48 % de sus ingresos brutos.

> ⚠️ `max_held` limita el producto sin recoger: vaca 6, oveja 6, ganso 4. Con CARE la
> vaca hace 3 por producción → hay que cosechar **cada 4 días como máximo**; la oveja
> hace 4 por producción → cosechar **en cada producción (3 días)** o se pierde.

### ✅ 2.2 Fresa a escala (30–43 casillas)

Los cuatro agentes top tienen 28–43 casillas de fresa desde el día 12. Supone el
**30–36 % de los ingresos brutos de todos ellos**. Es el cultivo con mejor
combinación de precio base ($120), curva de escasez benigna (`sqrt`/0.70 → $204 en
`I0−T`) y drenaje alto del pueblo (4 tipos de tienda la demandan).

### ✅ 2.3 Comprar tierra PRONTO (día 4–7)

Dato externo sobre 55 000 episodios reales
([post-mortem de rangga-jakti](https://github.com/rangga-jakti/kaggriculture-agent)):

| Día de compra de tierra | Win rate |
|---|---:|
| **Días 4–7** | **0.49** |
| Más tarde o nunca | 0.12 – 0.19 |

**Confirmado en nuestros replays:** Canon/Pai compran en día 6 y 11; "leave you" en
día 6 y 8; RB25det en día 7, 10 y 11. **Nosotros compramos en día 10 y 18–21.**

### ✅ 2.4 Cuadrilla grande (8–13 manos/día)

El coste es `fib(n)`: 1, 1, 2, 3, 5, 8, 13, 21… Diez manos cuestan $143/día — nada
comparado con lo que produce una acción bien empleada (~$140 la acción en animales).
Los agentes top hacen 247–263 contrataciones (8.2–8.8/día); nosotros 186 (6.2/día).

### ✅ 2.5 Comprar trigo en lugar de cultivarlo (para alimentar)

17 animales comen 17 trigos/día. Cultivarlo cuesta casillas y acciones; comprarlo
cuesta $20–45. Canon compra **286 unidades de trigo** y aun así cultiva 24–37 casillas.
Alimentar una vaca ($25 de trigo) que produce $330/día de leche es obvio.

### ✅ 2.6 El fertilizante es dinero gratis

Cada animal vivo genera 1 fertilizante al final de cada día, **lo hayas cuidado o no**.
18 animales × 25 días = 450 unidades, y el mercado absorbe 493 antes de hundirse
(≈ $25 k). Canon lo convierte en el 8.8 % de sus ingresos; Pai en el 25.9 %. Nosotros
recogemos 133 frente a sus 379.

### ✅ 2.7 Pivotar a zanahoria al final de la temporada

Canon y Pai terminan con 26–35 casillas de zanahoria en el día 27. Tiene sentido:
la zanahoria da fruto en 2 días y llega al máximo en 3, así que es el único cultivo
que sigue pagando si lo plantas en el día 26. Además su curva de escasez es `hinge`
con `below_target` 1.00 — si el pueblo la ha dejado corta, el precio se dispara.
**Nosotros no hacemos esto.**

---

## 3. Estrategias que NO funcionan (y por qué)

### ⚠️ 3.1 Dosificar las ventas — **hipótesis mía, REFUTADA por medición**

Mi lectura inicial del modelo de mercado (§1c) decía que volcar el cobertizo era nuestro
error nº 1: la fresa volcada paga $3 809 y dosificada $46 000. El docstring de `main.py`
("*sell everything, every turn*") parecía claramente equivocado. **Lo medí y es al revés.**

| Variante (32 episodios cada una) | Nuestro dinero medio |
|---|---:|
| Volcar todo cada turno (original) | **$65 165** ✅ |
| Solo suelo de precio (no vender por debajo de 0.55 × base) | $51 278 |
| Suelo de precio + cupo diario según drenaje del pueblo | $29 750 |

**Por qué el modelo estático engaña:**

1. **El cobertizo tope a 100 objetos y lo que desborda al final del día se destruye.**
   Retener producto no es "vender más tarde", es tirarlo. Esa restricción no aparece en
   el modelo de mercado.
2. **El rival vende en la misma curva.** Lo que no vendes hoy lo vende él, y llegas tarde
   a la parte alta.
3. **Nosotros nunca saturamos el mercado** salvo en melón: producimos 582 unidades en
   total. La capacidad no es la restricción activa; la producción sí.

El consejo publicado de *"trickle-sell"* no se sostiene con nuestro volumen de producción.
El código del limitador sigue en `main.py` tras `SELL_PACED = False`, documentado, por si
alguna vez producimos lo bastante como para que vuelva a ser relevante.

### ⚠️ 3.2 Limitar nuestra propia producción — **hipótesis mía, REFUTADA**

Derivé un tope de producción por producto (capacidad de la curva + drenaje futuro, partido
por dos porque compartimos mercado). Los números eran preciosos: reproducían **exactamente**
la composición de granja de los ganadores desde primeros principios — melón 71 unidades
≈ 12 casillas (Canon planta 12), fresa 248 ≈ 31 casillas (top 28-43), leche 300 ≈ 12 vacas
(Pai tiene 12).

**Y aun así pierde:** −$3 666 de margen medio sobre 32 episodios.

Lo revelador es el efecto colateral: al limitarnos, **la media del rival subió de $61.7k a
$69.9k**. La curva que dejamos tranquila es la curva en la que vende él. En un mercado de
dos jugadores, **correr a producir y vender primero gana a moderarse**. La "cuota justa"
es un concepto de monopolista, no de duopolio.

> Lección transversal: el modelo de mercado (§1) describe bien *la física del precio*, pero
> no la competencia ni el tope de cobertizo. Sirve para entender, no para decidir. Toda
> conclusión suya hay que pasarla por `bench.py`.

### ❌ 3.2 Monocultivo de melón en la apertura — **nuestro error nº 2**

`main.py` dedica el cuadrante inicial entero a melón (23 casillas) en los días 0–10.

**Qué pasa de verdad, medido en los replays:**

| | Casillas de melón | Unidades vendidas | $ obtenidos | $/unidad |
|---|---:|---:|---:|---:|
| Nosotros | 23 | 138 | ~11 136 | **$81** |
| Canon | 12 | 72 | ~16 152 | **$224** |

Vendimos **el doble de melones por dos tercios del dinero**. El melón tiene
`above_func = sq`, `above_target = 3.60`: el mercado entero absorbe **158 unidades**
antes de tocar el suelo de $1 — *entre los dos jugadores*. Nosotros solos producimos 138.
Nos inundamos el propio mercado.

Peor aún: el melón no da fruto hasta el día 10. **Los días 0–10 no ingresamos nada.**

### ❌ 3.3 Quedarnos sin capital en todo el medio juego

Dinero en banco por día (mismo episodio, 113201739):

| Día | 0 | 4 | 8 | 10 | 12 | 16 | 20 | 24 | 28 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Nosotros** | 1.0 k | 1.0 k | 1.0 k | 3.1 k | 3.2 k | **0.3 k** | 9.9 k | 31.6 k | 55.4 k |
| **Canon** | 0.0 k | 0.7 k | 2.0 k | **19.0 k** | 24.5 k | 54.2 k | 97.2 k | 145.0 k | 187.2 k |

Estamos a **$300 el día 16**. Sin capital no se compran vacas, ni tierra, ni manos.
Canon lleva $19 k el día 10 y a partir de ahí compone a ~+$12 k/día.

El dato externo del "banking elbow" (día en que el banco cruza el 10 % del valor final)
dice: días 13–15 → win rate 0.59–0.64; día 10 → 0.44. Nosotros cruzamos hacia el día 20.

### ❌ 3.4 Perder el 20 % de las casillas por malas hierbas

Censo de nuestra granja: **WEED=16–18 el día 12**, y el día 27 tenemos 20 EMPTY + 8 WEED
= 28 casillas muertas de 100. Canon tiene 10 vacías y **cero** hierbas.

Causa: plantamos más de lo que la cuadrilla puede regar, y una planta sin regar dos días
seguidos se convierte en hierba. Es el bug nº 4 del post-mortem externo:
*"overplanting without labor capacity caused crop death via neglect"*.

### ❌ 3.5 Gastar el 60 % de las acciones caminando

| | Movimiento (N+S+E+O) | % del total | HARVEST | % del total |
|---|---:|---:|---:|---:|
| Nosotros | 3 010 / 4 973 | **60.5 %** | 147 | 3.0 % |
| Canon | 2 831 / 6 704 | **42.2 %** | 477 | **7.1 %** |

Canon saca 3.2× más cosechas con solo 1.35× más acciones. La distribución de la granja
(pens junto al cobertizo, cultivos agrupados) y la asignación de trabajos importan tanto
como qué plantar.

### ❌ 3.6 "El trigo domina" — afirmación externa que NO se sostiene

El post-mortem externo afirma que *"wheat is the dominant crop in 98.8 % of episodes"*.
Es cierto que se **planta** mucho trigo, pero nuestros replays de agentes de 180 k+
muestran que el trigo es el **2.4–6.6 % de los ingresos brutos**: es pienso para animales,
no una fuente de dinero. Ese autor terminó en una posición baja de la tabla; tomamos sus
correlaciones agregadas (tierra, elbow) pero no esta conclusión.

---

## 4. Hipótesis por validar (creemos que funcionan, sin medir aún)

| # | Hipótesis | Estado |
|---|---|---|
| H1 | Dosificar ventas al ritmo del drenaje del pueblo | ❌ **REFUTADA** — §3.1, −$35k |
| H2 | Limitar producción a "nuestra cuota" del mercado | ❌ **REFUTADA** — §3.2, −$3.7k y sube al rival |
| H3 | Comprar el rebaño antes que las semillas para que no lo desplacen | ❌ **REFUTADA** — −$29k. Los animales sin corral construido se quedan en el cobertizo, se mueren de hambre sin trigo, y la caja que consumen es la que necesitaban los cultivos para arrancar |
| H4 | Subir la puja de CARE en la subasta de trabajos | ✅ **CONFIRMADA** — §2.1. `CARE_BID` 1.15 → 6.0 da **+$4 085** de margen y 71 % de victorias, mejora monótona |
| H5 | `LABOR_EFFICIENCY = 0.65` es demasiado optimista: medido, solo el 39.5 % de las acciones son útiles (el 60.5 % es caminar). Plantamos más de lo que podemos regar → 16-22 hierbajos el día 12 | 🔬 en curso |
| H6 | Comprar el primer cuadrante en el día 5–6 (no en el 10) | 🔬 pendiente |
| H7 | Pivote a zanahoria en los días 24–28 con las casillas libres | 🔬 pendiente |
| H8 | Cuadrilla mayor (objetivo 8–11 manos/día) | 🔬 en curso |

### Ideas descartadas antes de probarlas (con motivo)

- **Acaparar y vender todo el último día** — el suelo de $1 llega a las 60–76 unidades en
  los premium; el volcado final solo vale para lo que sobre (H8), no como plan.
- **Comprar fertilizante para revenderlo** — el precio de compra se cotiza al inventario
  post-compra y el de venta al pre-venta, así que comprar y vender neto da exactamente
  cero. No hay arbitraje.
- **Bloquear al rival** — las granjas son independientes; no se puede interferir salvo
  compitiendo por el mismo mercado (llegar antes a la parte alta de la curva).
- **Ganso a escala** — 2 huevos/día × $50 = $100/día por $300 de coste. La vaca da $330/día
  por $400. El ganso solo compensa si salen muchas bakeries/brunch spots.

---

## 5. Mecánicas exactas del motor (referencia verificada en el código)

Leídas de `kaggle_environments/envs/kaggriculture/kaggriculture.py`.

### Curva de precio
```
price(inv) = base ± amp · f(|inv − I0|),  amp = target · base / f(T)
f ∈ {linear, sq, sqrt, log(1+x), hinge};  hinge(u=x/T) = u + 8·max(0, u−1)²
```
Suelo $1, redondeado. `I0 = 10 000` para todo.

### Producción animal (`_daily_refresh_animals`, orden exacto)
1. Si `fed_today` → `consecutive_unfed = 0`; si no, +1. Con 2 → **el animal escapa** (la
   estructura queda).
2. Si toca producción (`(día+1 − placed_day − first_yield) % interval == 0`):
   `yield_units = min(max_held, yield_units + 1 + banco)`, y el banco se vacía.
   El bono **solo se aplica si `fed_today`**.
3. *Después*, si `cared_today and fed_today` → banco += 1.
4. `fertilizer_available = True` **siempre** (aunque no se alimentara).

### Plantas
- Semilla nueva nace con `consecutive_unwatered = 1`: **si no la riegas el mismo día que
  la plantas, muere esa noche.** No hay periodo de gracia.
- Cultivos de una cosecha: regar durante la ventana de bonus (desde `ceil(max_yield_day/2)`)
  suma +1/día; fertilizado +2/día.
- Ongoing (tomate, fresa): 1 por producción programada, **2 si está fertilizado Y regado**.
- Decaimiento: pasado `max_lifespan_step`, `yield_units −= 1` cada 2 turnos hasta 0 → hierba.

### Otros
- Contratar: `fib(n)` con n = contrataciones ya hechas **hoy**; se reinicia cada día.
- Tierra: $1 000 / $2 000 / $4 000 en orden NE → SW → SE.
- Cobertizo: 100 objetos (las semillas no cuentan). Lo que desborda al final del día **se pierde**.
- Casillas bloqueadas: **se pueden atravesar**, pero ninguna acción de casilla funciona en ellas.
- Hierbas: 0.5 % por casilla vacía y día.
- Máximo 10 órdenes de mercado por turno; las demás se descartan en silencio.

---

## 6. Dónde está realmente el cuello de botella

Después de ~1 500 episodios de experimentos, **ningún ajuste de parámetro ha producido una
mejora significativa**. El agente v3 está en un óptimo local de su propia arquitectura.
Todas las pistas convergen en el mismo sitio:

```
Apertura sin caja  ──►  no hay dinero para contratar manos
      │                        │
      │                        └──►  no se riega todo lo plantado ──► 8-16 hierbajos
      │
      ├──►  no hay $1 000 + reserva para tierra hasta el día 10-11
      │      (el gate de mano de obra LAND_LABOR_SLACK nunca ata: es la CAJA)
      │
      └──►  no hay dinero para vacas hasta el día 12
             (Canon las tiene el día 0-3 y lleva $19 k el día 10)
```

Medido: tenemos **~$600 en banco del día 0 al día 10**, y $300 el día 16. Canon lleva
$19 k el día 10 y compone a +$12 k/día desde ahí. El resto de los síntomas (casillas
vacías, hierbajos, tierra tardía, rebaño pequeño) son consecuencias de eso, no causas
independientes.

### Lo que NO es el problema (descartado con medición)

- **No es la venta.** Volcar el cobertizo es correcto (§3.1).
- **No es el exceso de melón.** Todos los líderes plantan 9-13 melones; nosotros 11-23.
  Limitarlo no ayuda (§3.2).
- **No es la puja de CARE ni el presupuesto de contratación.** Sin efecto a n=80.
- **No es el gate de mano de obra para la tierra.** `LAND_LABOR_SLACK` 12 → 4 no cambia nada.
- **No es la puja de riego de supervivencia.** Ya está afinada: bajarla cuesta $40 k,
  subirla cuesta $5 k.

### Lo que queda por probar (por orden de mecanismo más claro)

| # | Idea | Mecanismo |
|---|---|---|
| 1 | **Apertura con flujo de caja**: dedicar ~1/3 del cuadrante inicial a trigo/zanahoria (cosecha el día 2) en vez de solo melón+fresa (día 10) | Financia manos y el primer cuadrante sin esperar al día 10. Ojo: `crop_score` da 4.8 al trigo frente a 119 al melón, así que hace falta un término de valor-temporal del dinero, no solo bajar el listón |
| 2 | **Pivote a zanahoria días 24-28** con las casillas libres | Único cultivo que aún paga si se planta el día 26 (2 días a fruto). Canon/Pai acaban con 26-35 casillas de zanahoria; nosotros con 1 |
| 3 | **Reducir caminata**: 60.5 % de nuestras acciones son movimiento frente al 42.2 % de Canon | Vale ~1 000 acciones/temporada. Requiere tocar la disposición de la granja y la subasta, no un parámetro |
| 4 | **Arquitectura**: el post-mortem externo concluye que las arquitecturas reactivas de asignación de trabajos tienen techo, y que pasar de ahí exige búsqueda o políticas aprendidas | Coincide con lo que estamos viendo |

---

## 7. Registro de experimentos

Todas las cifras son **margen medio** (nuestro dinero − el del rival) contra
`variants/v3_nopace.py`, que es el agente original congelado.

| Fecha | Cambio | Eps | Margen | Veredicto |
|---|---|---:|---:|---|
| 09-27 | Baseline self-play | 24 | 0 | media $55 378, σ 15 583 |
| 09-27 | Dosificar ventas (cupo + suelo) | 32 | **−35 415** | ❌ Refutado |
| 09-27 | Solo suelo de precio | 32 | **−10 278** | ❌ Refutado |
| 09-27 | Tope de producción por producto | 32 | −3 666 | ❌ Refutado (y sube al rival) |
| 09-27 | Comprar rebaño antes que semillas | 32 | **−29 272** | ❌ Refutado |
| 09-27 | Control de paridad tras revertir | 32 | 0 | ✅ Arnés validado |
| 09-27 | `CARE_BID` 1.15 → 6.0 | 24 | +4 085 | ⚠️ ruido (ver abajo) |
| 09-27 | `HIRE_BUDGET_SHARE` 0.16 → 0.24 | 28 | +5 352 | ⚠️ ruido |
| 09-27 | **Factorial CARE × HIRE** | **80 c/u** | ver abajo | ❌ Todo dentro del ruido |
| 09-27 | Puja de supervivencia = vida restante de la planta | 90 | **−5 074** ± 2 660 | ❌ Refutado (significativo) |
| 09-27 | Puja de supervivencia = suelo plano (control) | 90 | **−39 533** ± 3 885 | ⚠️ El riego de supervivencia vale ~$40k: ya está bien afinado |
| 09-27 | `LAND_LABOR_SLACK` 12 → 4 | 90 | 0 (idéntico) | ❌ Ese gate nunca ata; lo que ata es la caja |
| 09-27 | `LAND_CASH_MARGIN` 800 → 100 | 90 | +281 ± 1 146 | ❌ No significativo |
| 09-27 | `MIN_TILE_SCORE` 6.0 → 2.0 | 90 | 0 (idéntico) | ❌ Sin efecto |
| 09-27 | **`HIRE_BUDGET_SHARE` 0.16 → 0.28** | **200** | **+2 819** ± 1 866 | ✅ **ACEPTADO** |
| 09-27 | `HIRE_BUDGET_SHARE` 0.40 | 200 | +2 700 ± 1 801 | Igual que 0.28 → `HIRE_BUDGET_CAP` ata |
| 09-27 | Validación final v4 (0.28) | 120 | +4 166 (mediana −230) | ✅ media $59 056 vs $54 890 |
| 09-27 | **v5: `invest_floor` realista** | **90** | **+4 744**, mediana +3 594, **62.2 %** ± 10.0 | ✅ **ACEPTADO** |
| 09-27 | v5 confirmación, semillas nuevas | 202 | +3 542, mediana **+5 892**, **63.4 %** ± 6.6 | ✅ Confirmado (y subestimado, ver nota) |

### 🎯 v5 — el bug de la reserva de caja (la mejor mejora hasta ahora)

`invest_floor` reservaba **tres días del salario de `MAX_HANDS`**, o sea de las 13 manos
que el presupuesto *podría* pagar como techo teórico:

```
invest_floor = 700 + 3.0 × cumulative_hire_cost(target_hands)   # target_hands = 13
             = 700 + 3 × 609 = $2 527   ← ¡de un banco de $3 000!
```

Pero el bucle de contratación dimensiona la cuadrilla por el **trabajo disponible**, no
por el techo. En el día 0 eso son 5 manos: coste real **$12**.

> **Reservábamos $2 527 para pagar $12.** El 84 % del banco congelado.

Eso dejaba **$473** invertibles: menos que una oveja ($500), apenas una vaca ($400). De
ahí salían en cadena los tres síntomas que llevaba toda la sesión persiguiendo — sin
animales hasta el día 12, sin tierra hasta el día 10, y el banco plano en ~$600 durante
el primer tercio de la temporada.

**El arreglo** calcula la cuadrilla que el trabajo realmente implica, con la misma
expresión que usa el bucle de contratación, y reserva tres días de *eso*.

**Efecto medido en la granja** (semilla 1003): vaca en el **día 3** en vez de corral vacío
hasta el día 12; **$4.9k en el día 10** frente a $1.3k.

> **Nota:** en la corrida de confirmación, 9 episodios dieron exactamente $3 000 (dinero
> inicial) porque edité `main.py` mientras corría el test: los workers cargaron un fichero
> a medio escribir. Esos ceros contaron como **derrotas**, así que el 63.4 % real es una
> cota inferior. `bench.py` ahora hace una copia temporal del agente antes de empezar
> (`snapshot()`), de modo que editar durante una medición ya no puede contaminarla.

### ⚠️ Ojo: el ranking premia VICTORIAS, no dinero

La validación final deja claro un matiz que conviene no olvidar:

| Métrica | v4 | baseline |
|---|---:|---:|
| Dinero medio | **$59 056** | $54 890 |
| Dinero máximo | **$92 360** | $80 215 |
| **Mediana del margen** | **−230** | — |
| **Win rate** | **48.3 % ± 8.9** | ~40 % |

La ganancia media viene de la **cola alta** (partidas buenas que salen mejor), no de ganar
más partidas: la mediana del margen es prácticamente cero. Y el ranking de Kaggle es un
**rating de habilidad basado en victorias**, no en dinero acumulado.

**Consecuencia para el trabajo futuro: optimizar `win%`, no `margin` ni `our mean`.** Un
cambio que suba el dinero medio concentrando ganancias en partidas que ya ganábamos no
mueve el ranking. `tools/sweep.py` imprime ambas columnas; la que manda es `win%`, y para
distinguir 40 % de 50 % con confianza hacen falta ~200 episodios (SE de una proporción
≈ √(0.25/n), o sea ±7 pp a n=200).

### ⚠️ La lección de método más importante

El factorial a n=80 por celda:

| CARE_BID | HIRE_SHARE | Margen | Interpretación |
|---:|---:|---:|---|
| 1.15 | 0.16 | **−50** | baseline consigo mismo → el arnés no tiene sesgo |
| 1.15 | 0.24 | +2 468 | dentro de ±3 287 |
| 10.0 | 0.16 | +1 755 | dentro de ±3 287 |
| 10.0 | 0.24 | −750 | dentro de ±3 287 |

Con σ ≈ 15 000 por episodio, el error estándar del margen es **σ/√n**:

| n (episodios) | intervalo 95 % del margen |
|---:|---:|
| 24 | ± 6 000 |
| 32 | ± 5 200 |
| 80 | ± 3 290 |
| 200 | ± 2 080 |
| 450 | ± 1 390 |

**Por debajo de ~80 episodios no se puede distinguir una mejora de $4 000 de puro ruido.**
Los "+4 085" y "+5 352" de las primeras pruebas eran ruido: al repetirlos con potencia
desaparecieron. `tools/sweep.py` ahora imprime el intervalo y marca con `**` solo lo que
supera su propio intervalo. **Regla: ningún cambio entra sin n ≥ 80 y marca `**`.**

**Sobre el arnés:** la media local en self-play ($55 378) casa con la media real en Kaggle
($59 860), así que es representativo. Ojo con el `starter` local: es malísimo (pierde
69 k a 3 k) y medir contra él lleva a óptimos locales — es el error nº 1 del post-mortem
externo. Medir siempre contra `v3_nopace.py` o contra la versión anterior.

---

## 8. Fuentes

- [Kaggriculture — página de la competición](https://www.kaggle.com/competitions/kaggriculture)
- [rangga-jakti/kaggriculture-agent](https://github.com/rangga-jakti/kaggriculture-agent) — post-mortems y correlaciones sobre 55 000 episodios
- [Alloysj/Kaggriculture-agents](https://github.com/Alloysj/Kaggriculture-agents) — agentes basados en reglas
- [sidhulyalkar/kaggriculture](https://github.com/sidhulyalkar/kaggriculture)
- [LucachuTW/kaggriculture](https://github.com/LucachuTW/kaggriculture)
- Replays propios en `replays/` — la fuente más fiable: son partidas reales de los agentes
  de 165–199 k.
