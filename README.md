# Synapse Trail Pro — Bot Python (réplica del Pine Script)

Réplica en Python de `Synapse Trail Pro [WillyAlgoTrader]` v1.2.0,
pensada para ejecutarse periódicamente vía **cron-job.org** y enviar
señales a **Telegram**.

> Por petición explícita, **no se implementa el dashboard/tabla**
> (sección 15 del Pine) ni el watermark (sección 16). Tampoco se
> implementan las líneas SL/TP dibujadas en el gráfico (sección 13) ni
> las estadísticas de sesión para la tabla (win rate, avg R, BE saves
> acumulados — sección 10a/14): esas piezas son puramente visuales y
> **no alteran ninguna señal**. Todo lo que SÍ afecta a qué señal se
> dispara y cuándo está implementado.

---

## FASE 1 — Análisis (resumen)

**Qué hace la estrategia, en lenguaje simple:**

Es un *trailing stop* tipo SuperTrend (EMA ± ATR×multiplicador, con
"ratchet" opcional para que la banda solo se mueva a favor de la
posición) que genera señales BUY/SELL cuando el precio cruza la banda
contraria. Cada señal se puntúa con un **Quality Score 0-100**
(sesgo de temporalidad superior, volumen, RSI, régimen de mercado,
fuerza de la ruptura) que determina un grado A/B/C. Además clasifica
el mercado en Trending/Mixed/Choppy (mezcla de ADX, Choppiness Index
y R²) y gestiona una posición simulada con SL/TP1/TP2/TP3 basados en
múltiplos de ATR, con opción de mover el stop a break-even tras TP1.

**Indicadores usados:**

| Indicador | Periodo (default) | Fuente Pine |
|---|---|---|
| ATR | 13 | `ta.atr(atrLenInput)` (Wilder RMA de True Range) |
| EMA (trail center) | 21 | `ta.ema(close, trailLenInput)` |
| EMA (HTF bias) | 50 | dentro de `request.security` |
| ADX / DMI | 14 | `ta.dmi(adxLen, adxLen)` (Wilder) |
| Choppiness Index | 14 | fórmula manual (log10 de suma TR / rango) |
| R² (linealidad) | 50 | `correlation(close, bar_index, len)^2` |
| RSI | 14 (fijo, no input) | `ta.rsi(close, 14)` (Wilder) |
| Percentrank(ATR) | 100 (fijo) | solo si `useAdaptiveMultInput` |

**Variables persistentes (`var`) replicadas:** `upperBand`,
`lowerBand`, `dir`, y todo el bloque de la posición activa
(`activeEntry/SL/TP1-3/Dir/Bar`, `tp1/2/3Reached`, `beActive`).

**Señales:**
- `rawBuy`: `dir` pasa de -1 a 1 (cruce de banda) y `isWarmedUp`.
- `rawSell`: `dir` pasa de 1 a -1.
- `buyPasses`/`sellPasses`: el raw signal más los filtros de
  `minQualityInput` y `skipChoppyInput`.

**Multi-timeframe:** el filtro HTF usa
`request.security(..., [close[1], ema(close,50)[1]], lookahead_on)`,
que es el patrón no-repintante estándar de TradingView (lee la
**última vela HTF ya cerrada**). Ver más abajo cómo se replica.

**Riesgos de repainting identificados y cómo se evitan aquí:**
1. El HTF bias — replicado leyendo el HTF con `shift(1)` antes del
   merge (ver `Strategies/synapse_trail_pro.py`).
2. Trabajar con la vela en formación — `MarketData.fetch_ohlcv`
   descarta explícitamente la última vela si no ha cerrado.
3. El ratchet/estado de posición — se recalcula desde cero cada
   ejecución sobre TODO el histórico descargado (no se persiste
   parcialmente), así que no hay drift de estado entre ejecuciones.

---

## Tabla de equivalencias

| Elemento Pine | Implementación Python |
|---|---|
| `ta.ema()` | `Indicators/indicators.py::ema` (seed con SMA + recursión) |
| `ta.rma()` / `ta.atr()` | `rma()` / `atr()` (Wilder, seed con SMA) |
| `ta.rsi()` | `rsi()` (Wilder, gestiona avgLoss=0 y ambos=0) |
| `ta.dmi()` | `dmi()` (+DI/-DI/ADX, Wilder) |
| Choppiness Index (fórmula manual) | `choppiness_index()` (misma fórmula exacta) |
| `correlation(close, bar_index, len)^2` | `r_squared()` (correlación con secuencia entera, matemáticamente equivalente) |
| `ta.percentrank()` | `percentrank()` (ventana `length`, cuenta de menores) |
| `request.security(...) lookahead_on` con `[1]` | HTF fetch aparte + `shift(1)` + `merge_asof(direction="backward")` |
| `var` (estado persistente) | atributos locales dentro del bucle `for` en `calculate()` |
| `barstate.isconfirmed` | garantizado aguas arriba: `MarketData` nunca entrega la vela en curso |
| `alert(...)` | `Alert` (dataclass) + `Core/engine.py::format_alert_message` |
| Sección 11/13/15/16 (plots, líneas, tabla, watermark) | **NO implementado** (sin efecto en señales, y la tabla se pidió omitir explícitamente) |

---

## Diferencias / puntos de atención Pine vs Python

1. **HTF vía merge_asof, no `request.security` real.** Es una
   aproximación fiel al patrón no-repintante, pero si tu HTF
   configurado no es exactamente un múltiplo limpio de tu TF base
   (o el exchange no ofrece esa vela nativamente), puede haber
   pequeños desfases de alineación temporal. Recomendado: validar
   con `tests_smoke.py`-style comparación contra TradingView real
   antes de operar con dinero real (ver sección Validación).

2. **Reconstrucción completa de estado en cada ejecución.** Para
   máxima fidelidad (evitar drift de estado entre invocaciones cron
   independientes), cada corrida recalcula TODA la estrategia desde
   el inicio del histórico descargado (`LOOKBACK_BARS`). Esto es
   intencional y más seguro que intentar persistir el estado del
   ratchet/posición activa entre ejecuciones, pero exige un
   `LOOKBACK_BARS` suficientemente grande (por defecto 1500) para
   que el warm-up de R² (hasta 200), el ratchet y la posición activa
   se hayan estabilizado mucho antes de la vela actual.

3. **RSI fijo en longitud 14.** El Pine no expone `rsiLen` como
   input (está hardcodeado a 14 dentro del script), así que aquí
   también está fijo.

4. **`isChoppy`/`isTrending` con el mismo umbral, pero calculados
   sobre datos que pueden no tener exactamente el mismo warm-up que
   TradingView** si tu exchange no tiene tanto histórico como el
   gráfico de TradingView. Con 1500 velas de sobra para timeframes
   de 5m-4h esto no debería ser un problema práctico.

---

## Avisos por Telegram y diario de operaciones (JSON)

### Avisos de TP / SL / Break-Even

El bot avisa por Telegram en estos momentos (todo activado por
defecto en `Config/config.py::PineConfig`):

- **BUY / SELL** — siempre (igual que el Pine original).
- **SL HIT** — siempre (`alertSlHitInput = True`).
- **TP1 / TP2 / TP3 HIT** — siempre (`alertTpHitInput = True`, a
  diferencia del Pine original que trae este input en `False` por
  defecto — se cambió aquí a petición explícita, es una decisión de
  notificación y no afecta a ninguna condición de la estrategia).
- **Break-Even activado** — siempre (usa el mismo
  `alertTpHitInput`, igual que en el Pine).
- **FLIP** — siempre (`alertFlipInput = True`).

Si en algún momento quieres silenciar alguno de estos tipos de aviso
sin perder el registro para las estadísticas, pon el input
correspondiente a `False` en `PineConfig` — el diario de operaciones
seguirá registrando el evento igualmente, solo deja de mandarse el
mensaje de Telegram.

### Formato de los mensajes

**Entrada (BUY/SELL):**

```
🟢 HBARUSDT | LONG
Score 64 | Grade B | Mixed

💰 Entrada: 0.0768
🛑 Stop Loss: 0.0764 (-0.52%)

🎯 TP1: 0.0772 (+0.52%) · RR 1.00
🎯 TP2: 0.0777 (+1.17%) · RR 2.00
🏆 TP3: 0.0781 (+1.69%) · RR 3.00

⏰ HBAR/USDT · 5m · 2026-08-21 20:20:00+00:00
```

**Eventos durante el trade (TP1/TP2/BE — no cierran la posición):**

```
✅ HBARUSDT — TP1 alcanzado (0.0772).
🔒 HBARUSDT — SL movido a BE (0.0768).
🔥 HBARUSDT — TP2 alcanzado. Runner hacia TP3.
0.0777
```

**Cierre del trade (TP3 / SL / BE-stop / FLIP):**

```
💎 HBARUSDT — TP3 alcanzado. Trade cerrado.
Entrada: 0.0768 | Cierre: 0.0781
Resultado: ✅ GANADORA (+2.00R)

🛑 HBARUSDT — SL alcanzado. Trade cerrado.
Entrada: 0.0768 | Cierre: 0.0764
Resultado: ❌ PERDEDORA (-1.00R)

🛡️ HBARUSDT — Cierre en Break-Even. Trade cerrado.
Entrada: 0.0768 | Cierre: 0.0768
Resultado: ✅ GANADORA (+0.33R)
```

El **R-múltiplo** mostrado usa la misma regla que el propio Pine
documenta internamente (`classifyClosedTrade`, sección 10a del
script original): la posición se reparte en 3 tercios, uno por cada
TP; si TP1 nunca se alcanzó, la operación es -1R plano. Este mismo
valor se guarda en `state/trades.json` (`r_multiple`) y se usa en
`journal_stats.py` para calcular el Avg R.

> No se incluye "Apalancamiento sugerido" porque el Pine original no
> lo calcula — no se quiso inventar un dato que no sale de la
> estrategia. Si quieres añadirlo con algún criterio propio (fijo,
> o en función del % de riesgo al SL), se puede agregar en
> `format_alert_message`.

---

## Diario de operaciones — `state/trades.json`

Cada vez que se abre una operación (BUY/SELL) se crea una entrada en
`state/trades.json`. A medida que en ejecuciones posteriores se van
tocando TP1/TP2/TP3/SL/BE, esa misma entrada se va actualizando
(vinculada por símbolo + timeframe + hora de entrada), hasta que la
operación se cierra (por SL, por BE-stop, por llegar a TP3, o por un
FLIP).

Estructura de cada trade — ver docstring completo en
`Core/trade_journal.py`:

```json
{
  "id": "BTC/USDT|15m|2026-08-20 10:35:00+00:00",
  "symbol": "BTC/USDT",
  "direction": "LONG",
  "entry_price": 65420.5,
  "sl": 65100.0, "tp1": 65740.0, "tp2": 66060.0, "tp3": 66380.0,
  "grade": "A", "quality": 82.0, "regime": "Trending",
  "tp1_hit": true, "tp1_hit_time": "...",
  "tp2_hit": false, "tp3_hit": false,
  "be_activated": true, "be_time": "...",
  "sl_hit": true, "sl_hit_time": "...",
  "closed": true, "close_reason": "be_stop", "close_time": "...",
  "result": "win"
}
```

**Regla de acierto** (idéntica a la lógica interna del propio Pine):
si TP1 se alcanzó en algún momento, la operación cuenta como **WIN**
sin importar cómo se cerró después (BE-stop, flip o TP3). Si TP1
nunca se alcanzó, es **LOSS**.

### Calcular el % de acierto

```bash
python journal_stats.py
# o filtrando por moneda:
python journal_stats.py --symbol BTC/USDT
# o en JSON, para integrarlo en otra herramienta:
python journal_stats.py --json
```

Da un desglose de: trades abiertos/cerrados, win rate global, cuántos
llegaron a TP1/TP2/TP3, BE saves, y el win rate por grade (A/B/C) y
por símbolo.

---

## Arquitectura

```
trading_bot/
├── Config/
│   └── config.py          # Inputs Pine (PineConfig) + infra (InfraConfig)
├── Indicators/
│   └── indicators.py       # ema, rma, atr, rsi, dmi, choppiness, r2, percentrank
├── Strategies/
│   └── synapse_trail_pro.py  # Motor secuencial: trail, régimen, quality, riesgo, alerts
├── Telegram/
│   └── bot.py               # send_signal() — solo IO, sin lógica de estrategia
├── Core/
│   ├── engine.py             # Orquestación: datos -> estrategia -> diario -> dedupe -> Telegram
│   ├── state.py              # Persistencia anti-duplicados (state/state.json)
│   └── trade_journal.py      # Diario de operaciones (state/trades.json)
├── Data/
│   └── market_data.py        # ccxt: fetch_ohlcv (excluye vela en curso) + auto HTF
├── state/
│   ├── state.json
│   └── trades.json
├── main.py                   # Entry point (para cron / wrapper HTTP)
├── requirements.txt
├── journal_stats.py          # Calcula % de acierto a partir de trades.json
├── tests_smoke.py            # Tests sin red: indicadores, estrategia, no-repaint, dedupe, diario
└── README.md
```

**Flujo de ejecución (`main.py` → `Engine.run()`):**
1. `MarketData.get_base_and_htf()` descarga TF base + HTF (auto 4x
   o el configurado), excluyendo siempre la vela en formación.
2. `SynapseTrailPro.calculate()` recorre bar-a-bar todo el histórico
   y devuelve `(BarResult[], Alert[])`.
3. Se filtra para no reenviar alertas antiguas ya notificadas
   (usando `state.json`) y, en la primera ejecución, solo se
   consideran las alertas de la última vela cerrada.
4. Cada alerta nueva se formatea y se envía por Telegram.
5. Se guarda el estado actualizado (`last_processed_timestamp` +
   IDs de alertas ya enviadas).

---

## Configuración

### Monedas a analizar y timeframe

Hay dos formas de configurarlo, elige la que prefieras:

**Opción A — editando `Config/config.py` directamente** (recomendado
si la lista no va a cambiar a menudo). Busca estas dos constantes al
principio del archivo:

```python
DEFAULT_SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
]

DEFAULT_TIMEFRAME = "15m"
```

**Opción B — por variables de entorno** (útil en cron-job.org si no
quieres tocar código):

```bash
SYMBOLS=BTC/USDT,ETH/USDT,SOL/USDT,XRP/USDT
TIMEFRAME=1h
```

El formato de cada símbolo es el que usa `ccxt`: `BASE/QUOTE` (p.ej.
`BTC/USDT`, no `BTCUSDT`). El bot analiza **cada moneda de la lista
de forma independiente** en cada ejecución — cada una con su propio
estado (dedupe de señales), así que añadir o quitar monedas de la
lista no afecta al historial de las demás.

El `TIMEFRAME` debe ser uno reconocido por tu exchange en ccxt:
`1m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 1w`. Es el mismo
timeframe que pondrías en el gráfico de TradingView — recuerda que
el filtro HTF del Pine se calcula automáticamente como 4× este valor
(salvo que fijes `htfTfInput` manualmente en `PineConfig`).

### Resto de variables de entorno

Crea un `.env` en la raíz, o configúralas en cron-job.org / tu
proveedor:

```bash
# Infraestructura
EXCHANGE_ID=binance
LOOKBACK_BARS=1500

# Telegram
TELEGRAM_BOT_TOKEN=xxxxx:yyyyy
TELEGRAM_CHAT_ID=123456789

STATE_FILE=./state/state.json
DEBUG=false
```

Los parámetros de la ESTRATEGIA (`Config/config.py::PineConfig`) son
copia exacta de los inputs del Pine y **no deben tocarse** salvo que
cambies el Pine original — no están pensados para configurarse por
entorno.

---

## Ejecución

```bash
pip install -r requirements.txt
python main.py
```

### cron-job.org

Como cron-job.org necesita golpear una URL HTTP (no ejecutar un
script directamente), la forma más simple es desplegar `main.py`
detrás de un wrapper mínimo, por ejemplo con Flask:

```python
# wsgi_endpoint.py (ejemplo mínimo, no incluido por defecto)
from flask import Flask
from main import run_once, _setup_logging

app = Flask(__name__)
_setup_logging()

@app.route("/run", methods=["GET", "POST"])
def run():
    code = run_once()
    return ("OK", 200) if code == 0 else ("ERROR", 500)
```

Despliega esto en cualquier servicio compatible (Render, Railway,
PythonAnywhere, un VPS pequeño, etc.), y en cron-job.org apunta a
`https://tu-servicio/run` con la periodicidad que corresponda al
timeframe (por ejemplo, cada 5 minutos si usas velas de 15m — sobra
margen para que la vela ya haya cerrado cuando se ejecuta).

---

## Validación contra TradingView (obligatorio antes de producción)

No se puede automatizar sin datos reales exportados de TradingView.
Pasos recomendados:

1. En TradingView, activa alertas o anota manualmente las señales
   BUY/SELL (con timestamp exacto de vela) durante un periodo de
   prueba, para el símbolo/timeframe que vayas a usar en Python.
2. Ejecuta `strategy.calculate(df, htf_df)` en Python sobre el
   mismo rango exacto de velas (mismo exchange/fuente si es
   posible, para minimizar diferencias de datos entre proveedores).
3. Compara timestamp a timestamp:

```text
timestamp             | TradingView | Python | match
2026-08-20 10:35 UTC  | BUY         | BUY    | OK
2026-08-20 11:20 UTC  | SELL        | SELL   | OK
```

4. Si hay discrepancias, lo primero a revisar (por orden de
   probabilidad) es: (a) diferencias de datos OHLCV entre tu
   exchange/fuente y la fuente de datos de TradingView, (b) el
   alineamiento del HTF (`merge_asof`), (c) el warm-up (`LOOKBACK_BARS`
   insuficiente para que el ratchet/R² ya estén estabilizados).

---

## Tests

```bash
python tests_smoke.py
```

Cubre: rangos válidos de indicadores, ciclo de vida completo de la
estrategia sobre datos sintéticos, ausencia de lookahead (comparando
resultado sobre prefijo del histórico vs histórico completo — deben
coincidir en las barras compartidas), y dedupe de estado.

No incluye tests contra red real (Telegram/exchange) — eso se prueba
manualmente en un entorno de staging con credenciales de prueba.

---

## Posibles mejoras futuras

*(NO implementadas — solo mencionadas, tal como se pidió)*

- Persistir el estado de la posición activa entre ejecuciones en vez
  de recalcular todo el histórico cada vez (más rápido, pero exige
  cuidado extra para no desincronizarse si el cron falla varias
  veces seguidas).
- Cache local de velas para reducir llamadas al exchange.
- Reintentos con backoff en el envío a Telegram.
- Métricas de estadísticas de sesión (win rate, avg R, BE saves) si
  en algún momento se quisiera recuperar esa parte del dashboard,
  ahora omitida a propósito.
- Soporte multi-símbolo/multi-timeframe en una sola ejecución.
- Endpoint HTTP con autenticación (actualmente el ejemplo de Flask
  no tiene ningún control de acceso; en producción debería tenerlo).
