#!/usr/bin/env python3
import os
import sys
import json
import logging
import argparse
from datetime import datetime,timezone
from pathlib import Path
from collections.abc import Mapping

import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def generate_dashboard(ticker: str, info: Mapping[str, object], history: pd.DataFrame, output_path: str) -> bool:
    """Generate a high-fidelity Plotly dashboard WebP."""
    try:
        name = info.get('longName', ticker)
        exchange = info.get('exchange', 'NYSE')
        currency = info.get('currency', 'USD')
        price = info.get('currentPrice', history['Close'].iloc[-1] if not history.empty else 0)
        change_pct = info.get('regularMarketChangePercent', 0)
        
        # Financial Metrics (TTM)
        pe = info.get('trailingPE', 0)
        pb = info.get('priceToBook', 0)
        ps = info.get('priceToSalesTrailing12Months', 0)
        roe = info.get('returnOnEquity', 0) * 100
        fcf = info.get('freeCashflow', 0)
        eps = info.get('trailingEps', 0)
        growth = info.get('revenueGrowth', 0) * 100

        def format_val(val: object, fmt: str = ".2f", suffix: str = "") -> str:
            if not isinstance(val, (int, float)) or val == 0: return "--"
            return f"{val:{fmt}}{suffix}"

        def format_compact(n: object) -> str:
            if not isinstance(n, (int, float)) or not n: return "--"
            if abs(n) >= 1e12: return f"{n/1e12:.1f}T"
            if abs(n) >= 1e9: return f"{n/1e9:.2f}B"
            if abs(n) >= 1e6: return f"{n/1e6:.1f}M"
            return f"{n:,.0f}"

        # Setup Canvas
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_width=[0.25, 0.75])

        # Professional Candlestick (1Y)
        fig.add_trace(go.Candlestick(
            x=history.index, open=history['Open'], high=history['High'], low=history['Low'], close=history['Close'],
            increasing_line_color='#10b981', decreasing_line_color='#ef4444',
            increasing_fillcolor='#10b981', decreasing_fillcolor='#ef4444',
            name='Price'
        ), row=1, col=1)

        # Volume
        fig.add_trace(go.Bar(
            x=history.index, y=history['Volume'], marker_color='rgba(148, 163, 184, 0.1)', name='Volume'
        ), row=2, col=1)

        # UI Layout Elements
        m_list = [
            ("P/E", format_val(pe), 0.46), ("P/B", format_val(pb), 0.54),
            ("P/S", format_val(ps), 0.62), ("ROE", format_val(roe, suffix="%"), 0.71, "#10b981"),
            ("FCF", format_compact(fcf), 0.80, "#3b82f6"), ("EPS", format_val(eps), 0.89),
            ("Growth", format_val(growth, suffix="%"), 0.97, "#3b82f6")
        ]
        
        for label, val, x_center, *color in m_list:
            # Drawing the box (Slate-50 style)
            fig.add_shape(type="rect", xref="paper", yref="paper",
                         x0=x_center - 0.038, y0=1.07, x1=x_center + 0.038, y1=1.19,
                         fillcolor="#f8fafc", line=dict(color="#e2e8f0", width=1), layer="below")
            # Label
            fig.add_annotation(text=f"<b style='color:#64748b; font-size:11px;'>{label}</b>",
                             x=x_center, y=1.16, xref="paper", yref="paper", showarrow=False, xanchor="center")
            # Value
            c = color[0] if color else "#0f172a"
            fig.add_annotation(text=f"<b style='color:{c}; font-size:17px;'>{val}</b>",
                             x=x_center, y=1.11, xref="paper", yref="paper", showarrow=False, xanchor="center")

        # Header
        fig.add_annotation(text=f"<b style='color:#3b82f6; font-size:12px;'>{exchange}</b>",
                         x=0.005, y=1.26, xref="paper", yref="paper", showarrow=False, align="left", xanchor="left")
        
        fig.add_annotation(text=f"<b style='color:#0f172a; font-size:30px;'>{name}</b>",
                         x=0.07, y=1.26, xref="paper", yref="paper", showarrow=False, align="left", xanchor="left")
        
        fig.add_annotation(text=f"<span style='color:#64748b; font-size:17px;'>{ticker}</span>",
                         x=0, y=1.17, xref="paper", yref="paper", showarrow=False, align="left", xanchor="left")
        
        fig.add_annotation(text=f"<span style='color:#64748b; font-size:17px;'>{currency}</span> <b style='color:#0f172a; font-size:44px;'>{price:,.2f}</b>",
                         x=0, y=1.10, xref="paper", yref="paper", showarrow=False, align="left", xanchor="left")
        
        fig.add_annotation(text=f"<b style='color:{'#10b981' if change_pct >= 0 else '#ef4444'}; font-size:24px;'>{'+' if change_pct >= 0 else ''}{change_pct:.2f}%</b>",
                         x=0.26, y=1.10, xref="paper", yref="paper", showarrow=False, align="left", xanchor="left")

        fig.update_layout(
            template='plotly_white', margin=dict(l=60, r=60, t=280, b=80), width=1300, height=920,
            showlegend=False, xaxis_rangeslider_visible=False,
            font=dict(family="Arial, Helvetica, sans-serif")
        )
        fig.update_xaxes(showgrid=True, gridcolor='#f1f5f9', zeroline=False, row=1, col=1)
        fig.update_yaxes(showgrid=True, gridcolor='#f1f5f9', zeroline=False, side='right', row=1, col=1)

        fig.write_image(output_path, format='webp', scale=2.0)
        return True
    except Exception as e:
        logger.error(f"Chart generation failed: {e}")
        return False

def get_5y_financials(stock: yf.Ticker) -> list[dict[str, object]]:
    """Fetch and process 5 years of financial statements."""
    try:
        financials = stock.financials
        cashflow = stock.cashflow
        balance = stock.balance_sheet
        
        if financials.empty or cashflow.empty:
            return []

        years = financials.columns[:5]
        data: list[dict[str, object]] = []
        for year in years:
            year_str = year.strftime('%Y')
            row = {
                "Year": year_str,
                "Revenue": financials.loc['Total Revenue', year] if 'Total Revenue' in financials.index else 0,
                "Net Income": financials.loc['Net Income', year] if 'Net Income' in financials.index else 0,
                "Operating Cash Flow": cashflow.loc['Operating Cash Flow', year] if 'Operating Cash Flow' in cashflow.index else 0,
                "Free Cash Flow": (cashflow.loc['Operating Cash Flow', year] + cashflow.loc['Capital Expenditure', year]) 
                                  if ('Operating Cash Flow' in cashflow.index and 'Capital Expenditure' in cashflow.index) else 0,
                "ROE": (financials.loc['Net Income', year] / balance.loc['Stockholders Equity', year]) 
                       if ('Net Income' in financials.index and 'Stockholders Equity' in balance.index) else 0
            }
            # Clean data (handle NaN)
            for k, v in row.items():
                if pd.isna(v): row[k] = 0
            data.append(row)
        return data
    except Exception as e:
        logger.error(f"Financials fetch failed: {e}")
        return []

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--output-dir", default=".")
    args = parser.parse_args()

    ticker = args.ticker.upper()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Fetching data for {ticker}...")
    stock = yf.Ticker(ticker)
    
    # 1. TTM Info
    info = stock.info
    if not info or 'symbol' not in info:
        # Fallback if yfinance info is empty
        history_test = stock.history(period="1d")
        if history_test.empty:
            print(json.dumps({"error": f"Ticker {ticker} not found."}))
            return

    # 2. Historical Price (1Y for chart)
    history = stock.history(period="1y")

    # 3. 5Y Financials
    five_year_data = get_5y_financials(stock)

    # 4. Generate Chart
    chart_filename = f"{ticker}_audit_{datetime.now().strftime('%Y%m%d')}.webp"
    chart_path = output_dir / chart_filename
    chart_success = generate_dashboard(ticker, info, history, str(chart_path))

    # 5. Build Result
    result = {
        "ticker": ticker,
        "name": info.get('longName', ticker),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "currency": info.get('currency', 'USD'),
        "ttm_metrics": {
            "price": info.get('currentPrice', history['Close'].iloc[-1] if not history.empty else 0),
            "pe": info.get('trailingPE'),
            "pb": info.get('priceToBook'),
            "roe": info.get('returnOnEquity'),
            "fcf": info.get('freeCashflow'),
            "eps": info.get('trailingEps')
        },
        "historical_financials": five_year_data,
        "chart_path": str(chart_path) if chart_success else None
    }

    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
