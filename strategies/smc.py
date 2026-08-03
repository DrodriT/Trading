"""
SMC_REVERSAL — barrido de liquidez + cambio de estructura (CHoCH).

Extraída de strategy.py sin cambios de cálculo. Contrato rico: devuelve
{direction, score, confidence, reason, metadata} o None, en vez de la
tupla (direction, score) que se usaba antes.
"""
import pandas as pd

from indicators import last_confirmed_swing


def detect_smc_reversal(df, cfg):
    """Barrido de liquidez bajo/sobre un swing anterior seguido de un
    cambio de estructura (CHoCH) en la dirección contraria al barrido."""
    last = df.iloc[-1]
    last_pos = len(df) - 1
    atr = last["ATR"]
    if pd.isna(atr) or atr == 0:
        return None

    pos_low, swing_low_price = last_confirmed_swing(df, "low", last_pos, cfg.SMC_LOOKBACK)
    if (pos_low is not None and last["low"] < swing_low_price
            and last["close"] > swing_low_price and last["close"] > last["open"]):
        _, swing_high_price = last_confirmed_swing(df, "high", pos_low, cfg.SMC_LOOKBACK)
        structure_shift = swing_high_price is not None and last["close"] > swing_high_price
        if not structure_shift:
            return None

        wick = swing_low_price - last["low"]
        sweep_score = min(wick / atr, 1.0) * cfg.SMC_SWEEP_WEIGHT

        rejection = max(last["close"] - swing_low_price, 0.0)
        rejection_score = min(rejection / atr, 1.0) * cfg.SMC_REJECTION_WEIGHT

        body = abs(last["close"] - last["open"])
        body_score = min(body / atr, 1.0) * cfg.SMC_BODY_WEIGHT

        choch_score = cfg.SMC_CHOCH_WEIGHT

        vol_ratio = last["VOL_RATIO"] if pd.notna(last["VOL_RATIO"]) else 1.0
        volume_score = min(max(vol_ratio - 1.0, 0.0), 1.0) * cfg.SMC_VOLUME_WEIGHT

        score = min(sweep_score + rejection_score + body_score + choch_score + volume_score, 100.0)

        return {
            "direction": "ALCISTA",
            "score": score,
            "confidence": score / 100.0,
            "reason": "Barrido de liquidez bajo swing anterior + rechazo alcista + cambio de estructura (CHoCH)",
            "metadata": {
                "sweep_score": sweep_score, "rejection_score": rejection_score,
                "body_score": body_score, "choch_score": choch_score,
                "volume_score": volume_score,
                "swing_low_price": swing_low_price, "swing_high_price": swing_high_price,
            },
        }

    pos_high, swing_high_price = last_confirmed_swing(df, "high", last_pos, cfg.SMC_LOOKBACK)
    if (pos_high is not None and last["high"] > swing_high_price
            and last["close"] < swing_high_price and last["close"] < last["open"]):
        _, swing_low_price2 = last_confirmed_swing(df, "low", pos_high, cfg.SMC_LOOKBACK)
        structure_shift = swing_low_price2 is not None and last["close"] < swing_low_price2
        if not structure_shift:
            return None

        wick = last["high"] - swing_high_price
        sweep_score = min(wick / atr, 1.0) * cfg.SMC_SWEEP_WEIGHT

        rejection = max(swing_high_price - last["close"], 0.0)
        rejection_score = min(rejection / atr, 1.0) * cfg.SMC_REJECTION_WEIGHT

        body = abs(last["close"] - last["open"])
        body_score = min(body / atr, 1.0) * cfg.SMC_BODY_WEIGHT

        choch_score = cfg.SMC_CHOCH_WEIGHT

        vol_ratio = last["VOL_RATIO"] if pd.notna(last["VOL_RATIO"]) else 1.0
        volume_score = min(max(vol_ratio - 1.0, 0.0), 1.0) * cfg.SMC_VOLUME_WEIGHT

        score = min(sweep_score + rejection_score + body_score + choch_score + volume_score, 100.0)

        return {
            "direction": "BAJISTA",
            "score": score,
            "confidence": score / 100.0,
            "reason": "Barrido de liquidez sobre swing anterior + rechazo bajista + cambio de estructura (CHoCH)",
            "metadata": {
                "sweep_score": sweep_score, "rejection_score": rejection_score,
                "body_score": body_score, "choch_score": choch_score,
                "volume_score": volume_score,
                "swing_high_price": swing_high_price, "swing_low_price": swing_low_price2,
            },
        }

    return None
