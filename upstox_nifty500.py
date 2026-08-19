import os
import requests
import pandas as pd
import gzip
import json
import time
from io import StringIO
from datetime import datetime, timedelta

# ============================================================
# 🚀 JOBIN NIFTY 500 ENGULFING SCANNER V3
# ============================================================

TOKEN = os.environ.get("UPSTOX_ACCESS_TOKEN")

if not TOKEN:
    print("ERROR: UPSTOX_ACCESS_TOKEN not found.")
    input("Press Enter to exit...")
    raise SystemExit

HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {TOKEN}"
}

NIFTY500_URL = (
    "https://www.niftyindices.com/"
    "IndexConstituent/ind_nifty500list.csv"
)

INSTRUMENT_URL = (
    "https://assets.upstox.com/market-quote/"
    "instruments/exchange/NSE.json.gz"
)

TIMEFRAMES = [
    "5 MIN",
    "10 MIN",
    "1 HOUR",
    "DAILY"
]


# ============================================================
# HEADER
# ============================================================

print()
print("=" * 80)
print("             JOBIN NIFTY 500 ENGULFING SCANNER V3")
print("=" * 80)
print("Price filter : BELOW Rs 500")
print("Timeframes   : 5M | 10M | 1H | DAILY")
print("=" * 80)


# ============================================================
# 1. NIFTY 500
# ============================================================

print("\nDownloading Nifty 500 list...")

try:

    response = requests.get(
        NIFTY500_URL,
        headers={
            "User-Agent": "Mozilla/5.0"
        },
        timeout=30
    )

    response.raise_for_status()

    nifty500 = pd.read_csv(
        StringIO(response.text)
    )

except Exception as e:

    print("ERROR:", e)
    input("Press Enter to exit...")
    raise SystemExit


print(
    f"OK - Nifty 500 stocks: {len(nifty500)}"
)


# ============================================================
# 2. UPSTOX INSTRUMENTS
# ============================================================

print("Downloading Upstox instruments...")

try:

    response = requests.get(
        INSTRUMENT_URL,
        timeout=30
    )

    response.raise_for_status()

    instruments = json.loads(
        gzip.decompress(response.content)
    )

except Exception as e:

    print("ERROR:", e)
    input("Press Enter to exit...")
    raise SystemExit


# ============================================================
# 3. MATCH STOCKS
# ============================================================

print("Matching stocks with Upstox...")

symbol_to_key = {}

for item in instruments:

    if item.get("segment") != "NSE_EQ":
        continue

    if item.get("instrument_type") != "EQ":
        continue

    symbol = item.get("trading_symbol")
    key = item.get("instrument_key")

    if symbol and key:

        symbol_to_key[symbol] = key


stocks = []

for _, row in nifty500.iterrows():

    symbol = str(
        row["Symbol"]
    ).strip()

    if symbol in symbol_to_key:

        stocks.append({
            "symbol": symbol,
            "key": symbol_to_key[symbol]
        })


print(
    f"OK - Matched: {len(stocks)}"
)


# ============================================================
# 4. LIVE PRICES
# ============================================================

print("Getting live prices...")

prices = {}

for start in range(
    0,
    len(stocks),
    500
):

    batch = stocks[
        start:start + 500
    ]

    keys = ",".join(
        stock["key"]
        for stock in batch
    )

    try:

        response = requests.get(
            "https://api.upstox.com/v3/"
            "market-quote/ltp",
            headers=HEADERS,
            params={
                "instrument_key": keys
            },
            timeout=60
        )

        if response.status_code != 200:
            continue

        data = response.json().get(
            "data",
            {}
        )

        for quote_key, details in data.items():

            price = details.get(
                "last_price"
            )

            if price is not None:

                prices[quote_key] = float(
                    price
                )

    except Exception:
        pass


# ============================================================
# 5. BELOW Rs 500
# ============================================================

under_500 = []

for stock in stocks:

    symbol = stock["symbol"]
    key = stock["key"]

    quote_key = (
        "NSE_EQ:" + symbol
    )

    price = prices.get(
        quote_key
    )

    if price is not None and price < 500:

        under_500.append({
            "symbol": symbol,
            "key": key,
            "price": price
        })


under_500.sort(
    key=lambda x: x["price"]
)


print()
print("=" * 80)
print(
    f"Stocks below Rs 500: {len(under_500)}"
)
print("=" * 80)


# ============================================================
# 6. HISTORICAL CANDLES
# ============================================================

def get_candles(key, timeframe):

    encoded_key = key.replace(
        "|",
        "%7C"
    )

    today = datetime.now().date()

    from_date = (
        today - timedelta(days=5)
    )

    to_date = today


    if timeframe == "5 MIN":

        unit = "minutes"
        interval = "5"

    elif timeframe == "10 MIN":

        unit = "minutes"
        interval = "10"

    elif timeframe == "1 HOUR":

        unit = "hours"
        interval = "1"

    elif timeframe == "DAILY":

        unit = "days"
        interval = "1"

    else:

        return None


    url = (
        "https://api.upstox.com/v3/"
        "historical-candle/"
        f"{encoded_key}/"
        f"{unit}/"
        f"{interval}/"
        f"{to_date}/"
        f"{from_date}"
    )


    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30
        )

        if response.status_code != 200:
            return None


        candles = response.json().get(
            "data",
            {}
        ).get(
            "candles",
            []
        )


        if len(candles) < 3:
            return None


        df = pd.DataFrame(
            candles,
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "oi"
            ]
        )


        df = df.iloc[
            ::-1
        ].reset_index(
            drop=True
        )


        for column in [
            "open",
            "high",
            "low",
            "close",
            "volume"
        ]:

            df[column] = pd.to_numeric(
                df[column],
                errors="coerce"
            )


        return df


    except Exception:

        return None


# ============================================================
# 7. ENGULFING DETECTOR
# ============================================================

def detect_engulfing(df):

    if df is None:
        return None

    if len(df) < 3:
        return None


    # Use the last two completed candles.
    previous = df.iloc[-3]
    current = df.iloc[-2]


    previous_open = previous["open"]
    previous_close = previous["close"]

    current_open = current["open"]
    current_close = current["close"]


    if pd.isna(previous_open):
        return None

    if pd.isna(previous_close):
        return None

    if pd.isna(current_open):
        return None

    if pd.isna(current_close):
        return None


    # Ignore doji candles.

    if previous_open == previous_close:
        return None

    if current_open == current_close:
        return None


    previous_bearish = (
        previous_close < previous_open
    )

    previous_bullish = (
        previous_close > previous_open
    )

    current_bullish = (
        current_close > current_open
    )

    current_bearish = (
        current_close < current_open
    )


    previous_high = max(
        previous_open,
        previous_close
    )

    previous_low = min(
        previous_open,
        previous_close
    )

    current_high = max(
        current_open,
        current_close
    )

    current_low = min(
        current_open,
        current_close
    )


    # Bullish engulfing

    if (
        previous_bearish
        and current_bullish
        and current_high >= previous_high
        and current_low <= previous_low
    ):

        return "BULLISH"


    # Bearish engulfing

    if (
        previous_bullish
        and current_bearish
        and current_high >= previous_high
        and current_low <= previous_low
    ):

        return "BEARISH"


    return None


# ============================================================
# 8. SCAN
# ============================================================

print()
print("Starting multi-timeframe scan...")
print()

results = {}

for timeframe in TIMEFRAMES:

    print(
        f"Scanning {timeframe}..."
    )

    results[timeframe] = {}


    for number, stock in enumerate(
        under_500,
        start=1
    ):

        symbol = stock["symbol"]
        key = stock["key"]


        df = get_candles(
            key,
            timeframe
        )


        signal = detect_engulfing(
            df
        )


        if signal:

            results[timeframe][symbol] = signal


        # Progress indicator

        print(
            f"\r{timeframe}: "
            f"{number}/{len(under_500)}",
            end="",
            flush=True
        )


        time.sleep(0.05)


    print()

    print(
        f"  Signals found: "
        f"{len(results[timeframe])}"
    )

    print()


# ============================================================
# 9. BUILD MASTER RESULT
# ============================================================

master = {}


for stock in under_500:

    symbol = stock["symbol"]

    row = {
        "STOCK": symbol,
        "PRICE": stock["price"],
        "5 MIN": results["5 MIN"].get(
            symbol,
            ""
        ),
        "10 MIN": results["10 MIN"].get(
            symbol,
            ""
        ),
        "1 HOUR": results["1 HOUR"].get(
            symbol,
            ""
        ),
        "DAILY": results["DAILY"].get(
            symbol,
            ""
        )
    }


    signals = [
        row["5 MIN"],
        row["10 MIN"],
        row["1 HOUR"],
        row["DAILY"]
    ]


    bullish = signals.count(
        "BULLISH"
    )

    bearish = signals.count(
        "BEARISH"
    )


    row["BULLISH_COUNT"] = bullish
    row["BEARISH_COUNT"] = bearish

    row["TOTAL_SIGNALS"] = (
        bullish + bearish
    )


    # Strength score

    if bullish >= 4 or bearish >= 4:

        row["STRENGTH"] = "⭐⭐⭐⭐"

    elif bullish >= 3 or bearish >= 3:

        row["STRENGTH"] = "⭐⭐⭐"

    elif bullish >= 2 or bearish >= 2:

        row["STRENGTH"] = "⭐⭐"

    elif bullish >= 1 or bearish >= 1:

        row["STRENGTH"] = "⭐"

    else:

        row["STRENGTH"] = ""


    master[symbol] = row


# ============================================================
# 10. FINAL SIGNAL TABLE
# ============================================================

signal_rows = [
    row
    for row in master.values()
    if row["TOTAL_SIGNALS"] > 0
]


signal_rows.sort(
    key=lambda x: (
        x["TOTAL_SIGNALS"],
        x["BULLISH_COUNT"],
        x["BEARISH_COUNT"]
    ),
    reverse=True
)


print()
print()
print("=" * 100)
print("                     FINAL SIGNALS")
print("=" * 100)


if not signal_rows:

    print()
    print(
        "No engulfing signals found."
    )

else:

    print()
    print(
        f"{'STOCK':<14}"
        f"{'PRICE':>10} "
        f"{'5M':>9} "
        f"{'10M':>9} "
        f"{'1H':>9} "
        f"{'DAILY':>9} "
        f"{'SCORE':>7}"
    )

    print("-" * 100)


    for row in signal_rows:

        print(
            f"{row['STOCK']:<14}"
            f"{row['PRICE']:>10.2f} "
            f"{row['5 MIN'] or '-':>9} "
            f"{row['10 MIN'] or '-':>9} "
            f"{row['1 HOUR'] or '-':>9} "
            f"{row['DAILY'] or '-':>9} "
            f"{row['STRENGTH']:>7}"
        )


# ============================================================
# 11. TOP SETUPS
# ============================================================

print()
print()
print("=" * 80)
print("                     TOP SETUPS")
print("=" * 80)


top_setups = [
    row
    for row in signal_rows
    if row["TOTAL_SIGNALS"] >= 2
]


if not top_setups:

    print()
    print(
        "No multi-timeframe setups found."
    )

else:

    print()

    for row in top_setups:

        active = []

        for timeframe in TIMEFRAMES:

            signal = row[
                timeframe
            ]

            if signal:

                active.append(
                    f"{timeframe}={signal}"
                )


        print(
            f"{row['STOCK']:<14}"
            f"Rs {row['PRICE']:<10.2f}"
            f"{row['STRENGTH']}   "
            f"{', '.join(active)}"
        )


# ============================================================
# 12. SAVE CSV
# ============================================================

date_string = datetime.now().strftime(
    "%Y-%m-%d_%H-%M"
)


filename = (
    f"jobin_engulfing_"
    f"{date_string}.csv"
)


all_rows = list(
    master.values()
)


csv_df = pd.DataFrame(
    all_rows
)


csv_df = csv_df.sort_values(
    by=[
        "TOTAL_SIGNALS",
        "BULLISH_COUNT",
        "BEARISH_COUNT"
    ],
    ascending=False
)


csv_df.to_csv(
    filename,
    index=False
)


# ============================================================
# FINAL SUMMARY
# ============================================================

print()
print()
print("=" * 80)
print("                     SUMMARY")
print("=" * 80)


for timeframe in TIMEFRAMES:

    print(
        f"{timeframe:<15}"
        f": {len(results[timeframe])} signal(s)"
    )


print("-" * 80)

print(
    f"Stocks below Rs 500 : "
    f"{len(under_500)}"
)

print(
    f"Stocks with signals  : "
    f"{len(signal_rows)}"
)

print(
    f"Multi-timeframe     : "
    f"{len(top_setups)}"
)

print()
print(
    f"CSV report saved as:"
)

print(
    filename
)

print("=" * 80)

print()
print("SCAN COMPLETED.")

