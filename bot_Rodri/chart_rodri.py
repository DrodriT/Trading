"""
Generación de gráficos de velas para las señales del bot "Rodri v1.0".

Dibuja las últimas N velas del símbolo (mismo timeframe de escaneo) junto
con los niveles de la señal — entrada, stop loss y TP1/TP2/TP3 — como
líneas horizontales, y un título con símbolo/dirección/score/prob/
estrategia(s). Es el mismo estilo de gráfico que manda el bot
"Portero V9 Sniper" al abrir cada señal.

Archivo independiente para no mezclar la parte de "dibujar" con la lógica
de trading de bot_rodri.py.
"""
import os
import tempfile

import matplotlib
matplotlib.use("Agg")  # sin display, solo generar PNG
import mplfinance as mpf
import pandas as pd


def display_symbol(symbol: str) -> str:
    return symbol.split(":")[0].replace("/", "")


def generate_signal_chart(df: pd.DataFrame, symbol: str, direction: str,
                           score: float, prob: float, strategies: list,
                           entry: float, sl: float, tps: list,
                           lookback_candles: int = 150,
                           out_dir: str = None) -> str:
    """
    Genera un PNG con las últimas 'lookback_candles' velas de 'df' (que
    debe traer ya la columna 'datetime', como la que devuelve fetch_ohlcv
    en bot_rodri.py) más líneas horizontales:
      - SL en rojo
      - Entrada en azul
      - TP1/TP2/TP3 en verde

    tps: lista de precios [tp1, tp2, tp3] en ese orden (o los que haya).
    Devuelve la ruta al PNG generado (queda en un directorio temporal si
    no se indica out_dir).
    """
    plot_df = df.tail(lookback_candles).copy()
    plot_df = plot_df.set_index(pd.DatetimeIndex(plot_df["datetime"]))
    plot_df = plot_df[["open", "high", "low", "close", "volume"]]

    dir_label = "LONG" if direction == "ALCISTA" else "SHORT"
    strat_label = "+".join(strategies)
    title = (f"{display_symbol(symbol)} {dir_label} | Score {score:.0f} | "
             f"Prob {prob:.2f} | {strat_label}")

    levels = [sl, entry] + list(tps)
    colors = ["red", "royalblue"] + ["seagreen"] * len(tps)

    mc = mpf.make_marketcolors(up="tab:green", down="tab:red", inherit=True)
    style = mpf.make_mpf_style(base_mpf_style="nightclouds", marketcolors=mc, gridstyle=":")

    if out_dir is None:
        out_dir = tempfile.gettempdir()
    os.makedirs(out_dir, exist_ok=True)
    ts = int(plot_df.index[-1].timestamp())
    out_path = os.path.join(out_dir, f"chart_{display_symbol(symbol)}_{ts}.png")

    mpf.plot(
        plot_df,
        type="candle",
        style=style,
        hlines=dict(hlines=levels, colors=colors, linestyle="--", linewidths=1.0),
        title=title,
        volume=False,
        figsize=(9, 6),
        savefig=dict(fname=out_path, dpi=110, bbox_inches="tight"),
    )

    return out_path
