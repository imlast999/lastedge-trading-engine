import os
import uuid
import logging
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import mplfinance as mpf

logger = logging.getLogger(__name__)


def _make_filename(prefix='chart'):
    uid = uuid.uuid4().hex
    return f"{prefix}_{uid}.png"


def _calculate_indicators(df):
    """Calculate technical indicators for the chart"""
    df = df.copy()
    
    # Calculate EMAs if not present
    if 'ema50' not in df.columns:
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    if 'ema200' not in df.columns:
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # Calculate RSI if not present
    if 'rsi' not in df.columns:
        delta = df['close'].diff()
        up = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
        down = -delta.clip(upper=0).ewm(alpha=1/14, adjust=False).mean()
        rs = up / down.replace(0, np.nan)
        df['rsi'] = 100 - (100 / (1 + rs))
    
    return df


def generate_chart(df, symbol='EURUSD', signal=None, filename=None, title=None, dark_mode=True, candlesticks=True):
    """Generate a professional candlestick chart using mplfinance.

    - `df` must contain columns: ['time','open','high','low','close'] with 'time' as datetime
    - returns path to PNG file
    """
    # Asegurar que symbol sea un string
    if hasattr(symbol, 'iloc'):  # Es una Serie de pandas
        symbol = str(symbol.iloc[0]) if len(symbol) > 0 else 'EURUSD'
    elif not isinstance(symbol, str):
        symbol = str(symbol)
    
    logger.debug(f"Generating chart for symbol: {symbol}")
    
    if filename is None:
        filename = _make_filename(symbol)

    try:
        # Prepare data for mplfinance: set index to datetime and use OHLC columns
        # Ser flexible con el nombre de la columna de tiempo
        time_col = None
        for col in ['time', 'datetime', 'timestamp']:
            if col in df.columns:
                time_col = col
                break
        
        if time_col is None:
            # Si no hay columna de tiempo, usar el índice si es datetime
            if isinstance(df.index, pd.DatetimeIndex):
                data = df.copy()
            else:
                raise ValueError(f"No time column found. Available columns: {list(df.columns)}")
        else:
            data = df.set_index(time_col).copy()
        
        # Ensure datetime index and sort ascending (mplfinance expects increasing time)
        try:
            data.index = pd.to_datetime(data.index)
        except Exception:
            logger.exception('Failed to convert index to datetime for chart')
            
        data = data.sort_index()

        # Ensure OHLC columns exist and are numeric; drop rows with NaNs
        required_cols = ['open', 'high', 'low', 'close']
        if not all(col in data.columns for col in required_cols):
            raise ValueError(f"Missing required OHLC columns. Available: {list(data.columns)}")
            
        # Clean and prepare OHLC data
        mpf_df = data[required_cols].astype(float).dropna()
        
        if len(mpf_df) < 3:
            raise ValueError(f'Not enough OHLC bars to plot: {len(mpf_df)}')

        # Calculate indicators
        data_with_indicators = _calculate_indicators(data)

        # Define professional style
        if dark_mode:
            mc = mpf.make_marketcolors(
                up='#00ff88',      # Bright green for up candles
                down='#ff4444',    # Bright red for down candles
                edge='inherit',
                wick={'up': '#00ff88', 'down': '#ff4444'},
                ohlc='inherit'
            )
            s = mpf.make_mpf_style(
                base_mpf_style='nightclouds',
                marketcolors=mc,
                rc={
                    'font.size': 10,
                    'axes.labelcolor': 'white',
                    'axes.edgecolor': 'white',
                    'xtick.color': 'white',
                    'ytick.color': 'white',
                    'figure.facecolor': '#1e1e1e',
                    'axes.facecolor': '#2d2d2d'
                },
                gridcolor='#404040',
                gridstyle='-',
                y_on_right=True
            )
        else:
            mc = mpf.make_marketcolors(
                up='green', 
                down='red', 
                edge='inherit',
                wick='black'
            )
            s = mpf.make_mpf_style(
                base_mpf_style='classic', 
                marketcolors=mc, 
                rc={'font.size': 10}
            )

        # Title with symbol and timeframe info
        if title is None:
            title = f"{symbol} - Candlestick Chart ({len(mpf_df)} bars)"

        # Prepare addplots for indicators
        addplots = []
        
        # Add EMAs if available
        if 'ema50' in data_with_indicators.columns:
            ema50_clean = data_with_indicators['ema50'].dropna()
            if len(ema50_clean) > 0:
                addplots.append(mpf.make_addplot(
                    data_with_indicators['ema50'], 
                    color='cyan', 
                    width=2,
                    alpha=0.8
                ))
                
        if 'ema200' in data_with_indicators.columns:
            ema200_clean = data_with_indicators['ema200'].dropna()
            if len(ema200_clean) > 0:
                addplots.append(mpf.make_addplot(
                    data_with_indicators['ema200'], 
                    color='magenta', 
                    width=2,
                    alpha=0.8
                ))

        # Prepare horizontal lines for signals
        hlines = None
        if signal:
            lines = []
            colors = []
            linestyles = []
            linewidths = []
            
            if signal.get('entry') is not None:
                lines.append(float(signal.get('entry')))
                colors.append('#00ff00')  # Bright green for entry
                linestyles.append('--')
                linewidths.append(2)
                
            if signal.get('sl') is not None:
                lines.append(float(signal.get('sl')))
                colors.append('#ff0000')  # Red for stop loss
                linestyles.append('--')
                linewidths.append(2)
                
            if signal.get('tp') is not None:
                lines.append(float(signal.get('tp')))
                colors.append('#0080ff')  # Blue for take profit
                linestyles.append('--')
                linewidths.append(2)
                
            if lines:
                hlines = dict(
                    hlines=lines, 
                    colors=colors, 
                    linestyle=linestyles,
                    linewidths=linewidths,
                    alpha=0.8
                )

        # Configure plot parameters
        mpf_kwargs = {
            'type': 'candle' if candlesticks else 'ohlc',
            'style': s,
            'title': title,
            'savefig': dict(fname=filename, dpi=150, bbox_inches='tight'),
            'figsize': (14, 8),
            'volume': False,  # Disable volume for cleaner look
            'tight_layout': True,
            'scale_padding': {'left': 0.3, 'top': 0.8, 'right': 0.5, 'bottom': 0.8},
            'update_width_config': dict(
                candle_linewidth=0.8,
                candle_width=0.8,
                volume_linewidth=0.8,
                volume_width=0.8
            )
        }
        
        # Add plots and lines if available
        if addplots:
            mpf_kwargs['addplot'] = addplots
            
        if hlines:
            mpf_kwargs['hlines'] = hlines

        # Generate the chart
        mpf.plot(mpf_df, **mpf_kwargs)
        
        logger.info(f"Successfully generated chart: {filename}")
        return filename

    except Exception as e:
        logger.exception(f'mplfinance plotting failed: {e}')
        
        # Enhanced fallback with better styling
        try:
            plt.style.use('dark_background' if dark_mode else 'default')
            fig, ax = plt.subplots(figsize=(14, 8))
            
            if dark_mode:
                fig.patch.set_facecolor('#1e1e1e')
                ax.set_facecolor('#2d2d2d')
                ax.grid(True, color='#404040', linestyle='-', alpha=0.3)
                text_color = 'white'
            else:
                ax.grid(True, alpha=0.3)
                text_color = 'black'
            
            # Plot price line
            if 'close' in data.columns:
                ax.plot(data.index, data['close'], 
                       color='white' if dark_mode else 'black', 
                       linewidth=2, label='Close Price')
            
            # Add EMAs if available
            if 'ema50' in data.columns:
                ax.plot(data.index, data['ema50'], 
                       color='cyan', linewidth=2, alpha=0.8, label='EMA 50')
            if 'ema200' in data.columns:
                ax.plot(data.index, data['ema200'], 
                       color='magenta', linewidth=2, alpha=0.8, label='EMA 200')
            
            # Add signal lines
            if signal:
                if signal.get('entry') is not None:
                    ax.axhline(signal.get('entry'), color='#00ff00', 
                              linestyle='--', linewidth=2, alpha=0.8, label='Entry')
                if signal.get('sl') is not None:
                    ax.axhline(signal.get('sl'), color='#ff0000', 
                              linestyle='--', linewidth=2, alpha=0.8, label='Stop Loss')
                if signal.get('tp') is not None:
                    ax.axhline(signal.get('tp'), color='#0080ff', 
                              linestyle='--', linewidth=2, alpha=0.8, label='Take Profit')
            
            # Styling
            ax.set_title(title or f"{symbol} - Price Chart", 
                        color=text_color, fontsize=14, fontweight='bold')
            ax.set_xlabel('Time', color=text_color)
            ax.set_ylabel('Price', color=text_color)
            ax.tick_params(colors=text_color)
            
            # Add legend
            ax.legend(loc='upper left', fancybox=True, shadow=True)
            
            # Format x-axis for better date display
            fig.autofmt_xdate()
            
            plt.tight_layout()
            plt.savefig(filename, dpi=150, bbox_inches='tight', 
                       facecolor=fig.get_facecolor(), edgecolor='none')
            plt.close()
            
            logger.info(f"Generated fallback chart: {filename}")
            return filename
            
        except Exception as fallback_error:
            logger.exception(f'Fallback chart generation also failed: {fallback_error}')
            raise

    return filename
