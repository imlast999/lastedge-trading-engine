import os
import uuid
import logging
from typing import Optional, Dict, Any, List
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import mplfinance as mpf

logger = logging.getLogger(__name__)


def _make_filename(prefix='chart'):
    uid = uuid.uuid4().hex
    return f"{prefix}_{uid}.png"


def _calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate technical indicators (EMAs, RSI) for the chart."""
    df = df.copy()
    
    if 'ema50' not in df.columns:
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    if 'ema200' not in df.columns:
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    if 'rsi' not in df.columns:
        delta = df['close'].diff()
        up = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
        down = -delta.clip(upper=0).ewm(alpha=1/14, adjust=False).mean()
        rs = up / down.replace(0, np.nan)
        df['rsi'] = 100 - (100 / (1 + rs))
    
    return df


def fmt_price(val: float) -> str:
    """Format price dynamically according to magnitude (Crypto vs FX)."""
    try:
        fval = float(val)
        if abs(fval) >= 100:
            return f"{fval:,.2f}"
        elif abs(fval) >= 1:
            return f"{fval:.5f}"
        else:
            return f"{fval:.6f}"
    except (ValueError, TypeError):
        return str(val)


def generate_chart(
    df: pd.DataFrame,
    symbol: str = 'EURUSD',
    signal: Optional[Dict[str, Any]] = None,
    filename: Optional[str] = None,
    title: Optional[str] = None,
    dark_mode: bool = True,
    candlesticks: bool = True,
    projection_mode: bool = False
) -> str:
    """Generate a high-definition TradingView-style candlestick chart using mplfinance.

    - `df` must contain columns: ['time','open','high','low','close'] with 'time' as datetime
    - Dynamically expands Y-axis (`ylim`) so TP and SL levels are NEVER cut off
    - Adds institutional dark aesthetic, shaded Risk/Reward zones, and price badges
    """
    if hasattr(symbol, 'iloc'):
        symbol = str(symbol.iloc[0]) if len(symbol) > 0 else 'EURUSD'
    elif not isinstance(symbol, str):
        symbol = str(symbol)
    
    logger.debug(f"Generating chart for symbol: {symbol}")
    
    if filename is None:
        filename = _make_filename(symbol)

    try:
        # Prepare data for mplfinance
        time_col = None
        for col in ['time', 'datetime', 'timestamp']:
            if col in df.columns:
                time_col = col
                break
        
        if time_col is None:
            if isinstance(df.index, pd.DatetimeIndex):
                data = df.copy()
            else:
                raise ValueError(f"No time column found. Available columns: {list(df.columns)}")
        else:
            data = df.set_index(time_col).copy()
        
        try:
            data.index = pd.to_datetime(data.index)
        except Exception:
            logger.exception('Failed to convert index to datetime for chart')
            
        data = data.sort_index()

        required_cols = ['open', 'high', 'low', 'close']
        if not all(col in data.columns for col in required_cols):
            raise ValueError(f"Missing required OHLC columns. Available: {list(data.columns)}")
            
        mpf_df = data[required_cols].astype(float).dropna()
        if len(mpf_df) < 3:
            raise ValueError(f'Not enough OHLC bars to plot: {len(mpf_df)}')

        # Calculate indicators
        data_with_indicators = _calculate_indicators(data)

        # Institutional Modern Dark Palette
        if dark_mode:
            mc = mpf.make_marketcolors(
                up='#00c087',      # Clean emerald teal
                down='#ff3b69',    # Vivid crimson red
                edge='inherit',
                wick={'up': '#00c087', 'down': '#ff3b69'},
                ohlc='inherit'
            )
            s = mpf.make_mpf_style(
                base_mpf_style='nightclouds',
                marketcolors=mc,
                rc={
                    'font.size': 10,
                    'axes.labelcolor': '#94a3b8',
                    'axes.edgecolor': '#1e293b',
                    'xtick.color': '#64748b',
                    'ytick.color': '#94a3b8',
                    'figure.facecolor': '#090d16',
                    'axes.facecolor': '#0f172a',
                    'grid.color': '#1e293b',
                    'grid.linestyle': ':',
                    'grid.alpha': 0.6
                },
                y_on_right=True
            )
        else:
            mc = mpf.make_marketcolors(
                up='#089981', down='#f23645',
                edge='inherit', wick='inherit'
            )
            s = mpf.make_mpf_style(
                base_mpf_style='classic',
                marketcolors=mc,
                rc={'font.size': 10}
            )

        # Dynamic Y-axis limits: guarantees TP, SL & Entry are NEVER off-screen
        price_levels: List[float] = []
        if signal:
            for k in ['entry', 'price', 'entry_price', 'sl', 'sl_price', 'stopLoss', 'tp', 'tp_price', 'takeProfit']:
                val = signal.get(k)
                if val is not None:
                    try:
                        f_val = float(val)
                        if f_val > 0:
                            price_levels.append(f_val)
                    except (ValueError, TypeError):
                        pass

        candle_low = float(mpf_df['low'].min())
        candle_high = float(mpf_df['high'].max())
        all_levels = price_levels + [candle_low, candle_high]
        p_min = min(all_levels)
        p_max = max(all_levels)
        p_span = p_max - p_min
        p_pad_bottom = max(p_span * 0.08, 0.0005)
        p_pad_top = max(p_span * 0.18, 0.001)  # Extra headroom for header banner & top levels
        calculated_ylim = (p_min - p_pad_bottom, p_max + p_pad_top)

        # Prepare EMA addplots
        addplots = []
        if 'ema50' in data_with_indicators.columns:
            ema50_s = data_with_indicators['ema50'].dropna()
            if len(ema50_s) > 0:
                addplots.append(mpf.make_addplot(
                    data_with_indicators['ema50'],
                    color='#38bdf8',  # Sky Blue
                    width=1.4,
                    alpha=0.85
                ))

        if 'ema200' in data_with_indicators.columns:
            ema200_s = data_with_indicators['ema200'].dropna()
            if len(ema200_s) > 0:
                addplots.append(mpf.make_addplot(
                    data_with_indicators['ema200'],
                    color='#e879f9',  # Orchid Violet
                    width=1.4,
                    alpha=0.85
                ))

        mpf_kwargs = {
            'type': 'candle' if candlesticks else 'ohlc',
            'style': s,
            'figsize': (14, 8),
            'ylim': calculated_ylim,
            'volume': False,
            'tight_layout': True,
            'returnfig': True
        }
        if addplots:
            mpf_kwargs['addplot'] = addplots

        fig, axes = mpf.plot(mpf_df, **mpf_kwargs)
        ax = axes[0]
        xlim = ax.get_xlim()
        x_start = xlim[0]
        x_end_orig = xlim[1]

        if signal and signal.get("projection_mode") is not None:
            projection_mode = bool(signal["projection_mode"])

        n_bars = len(mpf_df)
        if projection_mode:
            # Right margin ONLY for new signal executions: adds 8 to 12 bars of forward breathing room
            right_pad_bars = max(8, int(n_bars * 0.12))
            x_end = x_end_orig + right_pad_bars
            ax.set_xlim(x_start, x_end)
        else:
            # Standard mode (user requested chart / ongoing positions): fills candles completely to the end
            x_end = x_end_orig

        x_badge = x_start + (x_end - x_start) * 0.012

        # Draw dotted line for last close price
        last_close = float(mpf_df['close'].iloc[-1])
        ax.axhline(last_close, color='#475569', linestyle=':', linewidth=1.1, alpha=0.8)

        # Extract signal levels
        entry_val = None
        sl_val = None
        tp_val = None
        sig_type = 'SIGNAL'

        if signal:
            for k in ['entry', 'price', 'entry_price']:
                if signal.get(k) is not None:
                    try:
                        entry_val = float(signal[k])
                        break
                    except (ValueError, TypeError):
                        pass
            for k in ['sl', 'sl_price', 'stopLoss']:
                if signal.get(k) is not None:
                    try:
                        sl_val = float(signal[k])
                        break
                    except (ValueError, TypeError):
                        pass
            for k in ['tp', 'tp_price', 'takeProfit']:
                if signal.get(k) is not None:
                    try:
                        tp_val = float(signal[k])
                        break
                    except (ValueError, TypeError):
                        pass
            sig_type = str(signal.get('type') or signal.get('direction') or 'SIGNAL').upper()

            # Shaded Risk / Reward zones (TradingView Position Tool aesthetic)
            if entry_val is not None:
                if tp_val is not None:
                    ax.axhspan(min(entry_val, tp_val), max(entry_val, tp_val), color='#10b981', alpha=0.04)
                if sl_val is not None:
                    ax.axhspan(min(entry_val, sl_val), max(entry_val, sl_val), color='#ef4444', alpha=0.04)

            # TradingView-style position projection box into the right margin (ONLY in projection mode)
            if projection_mode:
                x_box_start = max(0, n_bars - 1)
                x_box_end = x_end - 0.5
                if entry_val is not None:
                    if tp_val is not None:
                        ax.fill_between([x_box_start, x_box_end], min(entry_val, tp_val), max(entry_val, tp_val),
                                        color='#10b981', alpha=0.20, edgecolor='#10b981', linewidth=1.0)
                    if sl_val is not None:
                        ax.fill_between([x_box_start, x_box_end], min(entry_val, sl_val), max(entry_val, sl_val),
                                        color='#ef4444', alpha=0.20, edgecolor='#ef4444', linewidth=1.0)

            # Check collision between SL and ENTRY (e.g. Break-Even trade)
            y_span = calculated_ylim[1] - calculated_ylim[0]
            is_breakeven = (
                entry_val is not None and sl_val is not None and
                abs(entry_val - sl_val) < y_span * 0.035
            )

            # Horizontal Level Lines
            if entry_val is not None:
                ax.axhline(entry_val, color='#38bdf8', linestyle='--', linewidth=1.8, alpha=0.9)
            if sl_val is not None:
                ax.axhline(sl_val, color='#f43f5e', linestyle='--', linewidth=1.8, alpha=0.9)
            if tp_val is not None:
                ax.axhline(tp_val, color='#10b981', linestyle='--', linewidth=1.8, alpha=0.9)
                ax.text(x_badge, tp_val, f" TP  {fmt_price(tp_val)} ",
                        color='#0f172a', fontsize=9, fontweight='bold', va='center', ha='left',
                        bbox=dict(boxstyle='square,pad=0.25', facecolor='#10b981', edgecolor='none'))

            if is_breakeven:
                # Place SL first, then place ENTRY directly to the right of SL on the same line
                t_sl = ax.text(x_badge, sl_val, f" SL  {fmt_price(sl_val)} ",
                               color='white', fontsize=9, fontweight='bold', va='center', ha='left',
                               bbox=dict(boxstyle='square,pad=0.25', facecolor='#f43f5e', edgecolor='none'))
                try:
                    fig.canvas.draw()
                    renderer = fig.canvas.get_renderer()
                    bbox_sl = t_sl.get_window_extent(renderer=renderer)
                    inv = ax.transData.inverted()
                    x_entry = inv.transform(bbox_sl)[1][0] + (x_end - x_start) * 0.006
                except Exception:
                    x_entry = x_badge + (x_end - x_start) * 0.12

                ax.text(x_entry, entry_val, f" ENTRY  {fmt_price(entry_val)} ",
                        color='#0f172a', fontsize=9, fontweight='bold', va='center', ha='left',
                        bbox=dict(boxstyle='square,pad=0.25', facecolor='#38bdf8', edgecolor='none'))
            else:
                if sl_val is not None:
                    ax.text(x_badge, sl_val, f" SL  {fmt_price(sl_val)} ",
                            color='white', fontsize=9, fontweight='bold', va='center', ha='left',
                            bbox=dict(boxstyle='square,pad=0.25', facecolor='#f43f5e', edgecolor='none'))
                if entry_val is not None:
                    ax.text(x_badge, entry_val, f" ENTRY  {fmt_price(entry_val)} ",
                            color='#0f172a', fontsize=9, fontweight='bold', va='center', ha='left',
                            bbox=dict(boxstyle='square,pad=0.25', facecolor='#38bdf8', edgecolor='none'))

        # Header Title Banner (Top Left)
        if title:
            banner_text = title
        elif signal and (entry_val or sl_val or tp_val):
            parts = [f"{symbol} • {sig_type}"]
            if entry_val: parts.append(f"Entry: {fmt_price(entry_val)}")
            if sl_val: parts.append(f"SL: {fmt_price(sl_val)}")
            if tp_val: parts.append(f"TP: {fmt_price(tp_val)}")
            banner_text = " | ".join(parts)
        else:
            banner_text = f"{symbol} — Candlestick Chart ({len(mpf_df)} bars)"

        ax.text(0.015, 0.965, f" {banner_text} ", transform=ax.transAxes, color='#f8fafc',
                fontsize=11, fontweight='bold', va='top', ha='left',
                bbox=dict(boxstyle='round,pad=0.4', facecolor='#1e293b', edgecolor='#334155', alpha=0.92))

        # Indicator Legend (Top Right)
        ax.text(0.985, 0.965, "— EMA 50   — EMA 200", transform=ax.transAxes, color='#94a3b8',
                fontsize=9.5, va='top', ha='right',
                bbox=dict(boxstyle='round,pad=0.3', facecolor='#1e293b', edgecolor='#334155', alpha=0.85))

        # Save to disk
        fig.savefig(filename, dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor(), edgecolor='none')
        plt.close(fig)

        logger.info(f"Successfully generated institutional chart: {filename}")
        return filename

    except Exception as e:
        logger.exception(f'mplfinance plotting failed: {e}')
        
        # Robust Fallback
        try:
            plt.style.use('dark_background' if dark_mode else 'default')
            fig, ax = plt.subplots(figsize=(14, 8))
            
            if dark_mode:
                fig.patch.set_facecolor('#090d16')
                ax.set_facecolor('#0f172a')
                ax.grid(True, color='#1e293b', linestyle=':', alpha=0.6)
                text_color = '#f8fafc'
            else:
                ax.grid(True, alpha=0.3)
                text_color = 'black'
            
            if 'close' in data.columns:
                ax.plot(data.index, data['close'], color='#38bdf8', linewidth=2, label='Close Price')
            
            if 'ema50' in data_with_indicators.columns:
                ax.plot(data_with_indicators.index, data_with_indicators['ema50'], color='#38bdf8', linewidth=1.5, alpha=0.8, label='EMA 50')
            if 'ema200' in data_with_indicators.columns:
                ax.plot(data_with_indicators.index, data_with_indicators['ema200'], color='#e879f9', linewidth=1.5, alpha=0.8, label='EMA 200')
            
            if signal:
                if signal.get('entry') is not None:
                    ax.axhline(float(signal['entry']), color='#38bdf8', linestyle='--', linewidth=1.8, label='Entry')
                if signal.get('sl') is not None:
                    ax.axhline(float(signal['sl']), color='#f43f5e', linestyle='--', linewidth=1.8, label='Stop Loss')
                if signal.get('tp') is not None:
                    ax.axhline(float(signal['tp']), color='#10b981', linestyle='--', linewidth=1.8, label='Take Profit')
            
            ax.set_title(title or f"{symbol} - Price Chart", color=text_color, fontsize=14, fontweight='bold')
            ax.tick_params(colors=text_color)
            ax.legend(loc='upper left', fancybox=True, shadow=True)
            fig.autofmt_xdate()
            plt.tight_layout()
            plt.savefig(filename, dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor(), edgecolor='none')
            plt.close(fig)
            return filename
        except Exception as fallback_error:
            logger.exception(f'Fallback chart generation also failed: {fallback_error}')
            raise
