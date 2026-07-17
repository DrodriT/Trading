# Bot de alertas cripto (EMA13 / EMA200 + Estocástico → Telegram)

Vigila las criptos que tú elijas y te avisa por Telegram cuando:
- **EMA13 cruza EMA200** (al alza = señal alcista, a la baja = señal bajista), y/o
- **El Estocástico cruza saliendo de sobreventa (<20) o sobrecompra (>80)**

Por defecto avisa con cualquiera de las dos señales por separado. Si prefieres que solo
avise cuando ambas coincidan en la misma vela (señal más fuerte y menos frecuente),
cambia `REQUIRE_CONFLUENCE = True` en `config.py`.

## 1. Instalación

```bash
pip install ccxt pandas requests
```

## 2. Crear tu bot de Telegram

1. Abre Telegram y busca **@BotFather**.
2. Envía `/newbot` y sigue los pasos. Te dará un **token** (algo como `123456:ABC-...`).
3. Escríbele cualquier mensaje a tu bot recién creado (o añádelo a un grupo).
4. Visita en el navegador:
   `https://api.telegram.org/bot<TU_TOKEN>/getUpdates`
   Busca `"chat":{"id": ...}` — ese número es tu `chat_id`.

## 3. Configurar

Edita `config.py`:

```python
TELEGRAM_TOKEN = "123456:ABC..."
TELEGRAM_CHAT_ID = "987654321"

SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
]

TIMEFRAME = "4h"   # elige el que quieras: "15m", "1h", "4h", "1d"...
```

## 4. Ejecutar

**Modo continuo** (deja el bot corriendo, revisa cada 5 min por defecto):
```bash
python3 bot.py
```

**Una sola pasada** (ideal para programar con cron cada X tiempo):
```bash
python3 bot.py --once
```

Ejemplo de cron para revisar cada hora:
```bash
0 * * * * cd /ruta/al/bot && /usr/bin/python3 bot.py --once >> bot.log 2>&1
```

## 5. Alternativa gratis 24/7: GitHub Actions (sin PC encendido)

Con esto el bot corre en los servidores de GitHub cada 15 minutos, gratis, sin que
tengas que dejar tu ordenador encendido.

### Pasos

1. **Crea un repositorio en GitHub** (puede ser privado o público — los Secrets están
   cifrados en ambos casos).
2. **Sube estos archivos** a la raíz del repo, incluyendo la carpeta `.github/workflows/`
   tal cual está (no cambies su ruta, GitHub la detecta automáticamente ahí).
3. **Añade tus credenciales como Secrets** (nunca las escribas directamente en `config.py`
   si el repo va a subirse a GitHub):
   - Ve a tu repo → **Settings → Secrets and variables → Actions → New repository secret**.
   - Crea `TELEGRAM_TOKEN` con el token de tu bot.
   - Crea `TELEGRAM_CHAT_ID` con tu chat_id.
4. **Comprueba que el workflow está activo**: pestaña **Actions** de tu repo → deberías
   ver "Crypto Alert Bot" en la lista. Se ejecutará automáticamente cada 15 minutos.
5. Para probarlo ya mismo sin esperar: en la pestaña Actions, abre el workflow y pulsa
   **"Run workflow"** (botón manual, gracias a `workflow_dispatch`).

### Cómo funciona el estado sin servidor propio

Cada ejecución corre `python bot.py --once`, y al terminar el propio workflow hace
`commit` y `push` del archivo `state.json` actualizado al repositorio. Así la siguiente
ejecución (en una máquina nueva de GitHub) recupera qué señales ya se avisaron y no
repite el mismo aviso.

### Límites del plan gratuito

- Repos **públicos**: minutos de Actions ilimitados.
- Repos **privados**: 2.000 minutos/mes gratis (cada ejecución tarda ~30-60s, así que
  con esta frecuencia no deberías acercarte al límite).
- GitHub **no garantiza el minuto exacto** del cron (puede retrasarse varios minutos en
  horas de mucho tráfico en GitHub); para timeframes cortos (`5m`, `15m`) esto puede hacer
  que alguna vela se detecte un poco tarde, pero no se pierde ninguna señal.

## 6. Notas importantes

- Usa datos públicos de **Binance** por defecto (no necesita API key). Puedes cambiar
  `EXCHANGE_ID` en `config.py` a otro exchange soportado por [ccxt](https://github.com/ccxt/ccxt)
  (kraken, kucoin, coinbase...).
- El archivo `state.json` se crea automáticamente y guarda qué señales ya se avisaron,
  para no repetir el mismo aviso en la misma vela.
- Este bot **no ejecuta operaciones ni da consejo financiero**: solo te notifica cuando
  se cumplen las condiciones técnicas que definas. La decisión de operar es siempre tuya.
