REST API 
HTTP
Download price history with your key
The same key that streams live prices also pulls history over plain HTTP. You get price candles for any instrument, live option chains with greeks, plus the economic calendar, insider trades, dividends and splits. Every response can come back as JSON or CSV.

INSTALL
The client is open source and published to PyPI. It has one dependency.

Copy
pip install lse-data
github.com/londonstrategicedge/lse-data
PULL CANDLES
A candle is one OHLCV bar: the open, high, low, close and volume over a slice of time. Pass a symbol and a timeframe. Timeframes are 1m, 5m, 15m, 1h, 4h and 1d. Use start and end for a date range, or limit for the most recent rows.

Copy
from lse import LSE
 
client = LSE(api_key="lse_live_xxxxxxxxxxxxxxxx")
 
# daily candles for BTC since Jan 1, then the last 200 hourly candles for AAPL
daily  = client.candles("BTC/USD", "1d", start="2026-01-01")
hourly = client.candles("AAPL", "1h", limit=200, order="desc")
OPTIONS
NEW
Pass a company name or a ticker and get the whole chain: every contract with its latest price, implied volatility, greeks, and the volume and premium traded today. From there pull the prints or one contract's minute bars. You never type a contract ticker by hand; the chain hands them to you, and the bars call builds one from strike, expiry and type.

Copy
chain  = client.options("apple", type="call", max_dte=30)
prints = client.options_flow("NVDA", min_premium=100_000)
bars   = client.option_candles("AAPL", strike=205, expiry="2026-06-12", type="call")
The whole AAPL chain as CSV, no Python at all
Copy
curl -H "x-api-key: lse_live_xxxxxxxxxxxxxxxx" \
     -H "Accept: text/csv" \
     "https://api.londonstrategicedge.com/iso/x_options_chain?underlying=eq.AAPL" \
     -o aapl_chain.csv
SAVE IT AS CSV
Each call returns a list of rows. Write them to a CSV with pandas, with the standard library, or skip Python and ask the API for CSV directly.

With pandas
Copy
import pandas as pd
 
rows = client.candles("BTC/USD", "1d", start="2026-01-01")
pd.DataFrame(rows).to_csv("btc.csv", index=False)
Standard library only, no pandas
Copy
import csv
 
rows = client.candles("BTC/USD", "1d", start="2026-01-01")
with open("btc.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
Straight from the API, no Python at all
Copy
curl -H "x-api-key: lse_live_xxxxxxxxxxxxxxxx" \
     -H "Accept: text/csv" \
     "https://api.londonstrategicedge.com/iso/x_candles_1d?symbol=eq.BTC/USD&limit=5000" \
     -o btc.csv
THE OTHER FEEDS
The same key reaches the event feeds. Each one returns a list of rows, so the CSV steps above work on all of them.

Copy
events   = client.economic_calendar(region="US", start="2026-04-01")
insiders = client.insider_trades("AAPL", type="P-Purchase")
divs     = client.dividends("AAPL")
splits   = client.splits("NVDA")
FIND INSTRUMENTS
catalog lists everything you can stream or download, no key needed. Categories are stock, forex, crypto, etf, commodity and index. Stocks with listed options have their own list.

Copy
client.catalog()              # every instrument
client.catalog("crypto")      # just the crypto pairs
client.options_underlyings()  # every stock with listed options










Real-time streaming over WebSocket. Subscribe to live prices for stocks, forex, crypto, indices, commodities, ETFs, and options.

Install

pip install lse-data
bash
That's it. One dependency (websockets), installed automatically.

Quickstart

from lse import LSE

client = LSE(api_key="your_api_key")

for tick in client.stream(["BTC/USD", "AAPL", "EUR/USD"]):
    print(f"{tick.timestamp}  {tick.symbol}: ${tick.price}")
python
Three lines. Connect, authenticate, subscribe, receive ticks. The SDK handles everything. Every tick carries a timestamp (Unix seconds) alongside the price; the Tick Object table below lists the full set of fields.

Get your API key at londonstrategicedge.com/websockets.

How It Works

You open a persistent WebSocket connection to wss://data-ws.londonstrategicedge.com
You authenticate with your API key
You subscribe to the symbols you want
The server pushes you every price update the moment it happens
No polling, no REST calls. One connection, prices stream in real-time until you disconnect.

Tick Object

Each tick has these fields:

Field	Type	Description
symbol	str	Instrument symbol (e.g. BTC/USD, AAPL)
price	float	Latest price
bid	float	Bid price (if available)
ask	float	Ask price (if available)
volume	float	Trade volume (if available)
timestamp	float	Unix timestamp
name	str	Human-readable name (e.g. Apple Inc.)
Examples

Stream to terminal

from lse import LSE

client = LSE(api_key="your_key")

for tick in client.stream(["BTC/USD", "ETH/USD", "AAPL", "NVDA"]):
    print(f"{tick.symbol:12s} ${tick.price:>12,.2f}")
python
Callback style

from lse import LSE

def on_tick(tick):
    print(f"{tick.symbol}: {tick.price}")

client = LSE(api_key="your_key")
client.on("tick", on_tick)
client.on("connected", lambda: print("Connected"))
client.on("authenticated", lambda: print("Authenticated"))

client.connect(symbols=["BTC/USD", "ETH/USD", "SOL/USD"])
python
Async streaming

import asyncio
from lse import LSE

async def main():
    client = LSE(api_key="your_key")
    async for tick in client.stream_async(["BTC/USD", "AAPL"]):
        print(f"{tick.symbol} {tick.price}")

asyncio.run(main())
python
Replay + Live (seamless history-to-live)

Subscribe with a start time and the server replays historical ticks from that point, then seamlessly transitions to live. No gap, no second connection, same Tick object throughout. Replay ticks have tick.replay = True.

from lse import LSE
from datetime import datetime, timezone, timedelta

client = LSE(api_key="your_key")

# Replay last 2 hours, then continue live
start = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()

for tick in client.stream(["BTC/USD"], start=start):
    label = "REPLAY" if tick.replay else "LIVE"
    print(f"[{label}] {tick.symbol} ${tick.price:,.2f}")
python
Use cases:

Bot recovery: bot crashed at 14:00, restarts at 14:05. Pass start="2026-04-18T14:00:00" and it replays the 5 minutes it missed, then goes live. No data gap.
Strategy warmup: your strategy needs 200 data points before making decisions. Pass start far enough back, let replay fill the buffer, then go live with a hot strategy.
Same code for backtest and live: replace start with a historical range for backtesting, remove it for production. One loop, one handler.
Max lookback: 24 hours. Ticks replay at full speed (not real-time pace).

Save to CSV

import csv, datetime
from lse import LSE

client = LSE(api_key="your_key")

with open("ticks.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["timestamp", "symbol", "price", "bid", "ask"])

    for tick in client.stream(["BTC/USD", "ETH/USD"]):
        now = datetime.datetime.now().isoformat()
        writer.writerow([now, tick.symbol, tick.price, tick.bid, tick.ask])
        f.flush()
python
Events

When using the callback style with .on():

Event	Callback args	Description
tick	Tick	New price tick (check tick.replay for historical vs live)
connected	(none)	WebSocket connected
authenticated	(none)	API key accepted
replay_started	dict	Historical replay has begun for a symbol
replay_complete	dict	Replay finished, live ticks follow
disconnected	(none)	Connection lost (auto-reconnects)
error	str	Error message
Symbol Catalog

Query available instruments before subscribing. No WebSocket connection needed.

from lse import LSE

client = LSE(api_key="your_key")

# Get all available symbols
all_symbols = client.catalog()
print(f"{len(all_symbols)} instruments available")

# Filter by category
stocks = client.catalog(category="stock")
crypto = client.catalog(category="crypto")
forex = client.catalog(category="forex")

# Each entry has: symbol, name, category
for s in stocks[:5]:
    print(f"{s['symbol']:12s} {s['name']:30s} {s['category']}")
python
The catalog returns every subscribable instrument with its display name and category. Use it to build symbol pickers, validate user input, or discover what is available before opening a WebSocket.

Available Instruments

Over 4,100 instruments across 6 asset classes:

Category	Count	Examples
Stocks	~3,987	AAPL, NVDA, TSLA, 0005.HK, 7203.T
Forex	~62	EUR/USD, GBP/JPY, USD/CHF
Crypto	~58	BTC/USD, ETH/USD, SOL/USD
ETFs	~25	SPY, QQQ, IWM, GLD
Commodities	~23	XAU/USD, WTICO/USD, NATGAS/USD
Indices	~13	US30, NAS100, UK100
Options	~263,000 live contracts	56 underlyings, all listed strikes and expiries
Regional Stocks

UK stocks end in .L, German in .DE, French in .PA, Japanese in .T, Hong Kong in .HK, Korean in .KS, Australian in .AX, Canadian in .TO, Indian in .NS, Taiwanese in .TW.

Subscribing to Options

Subscribe to ALL option contracts for an underlying with a single call:

from lse import LSE

client = LSE(api_key="your_key")

def on_tick(tick):
    print(f"{tick.symbol}: ${tick.price:.2f}")

client.on("tick", on_tick)
client.subscribe_options(["AAPL", "TSLA"])
client.connect()
python
This subscribes you to every AAPL and TSLA put and call across all strikes and expiries. One call per underlying, not 1,306 individual subscriptions.

To stop receiving a chain:

client.unsubscribe_options(["TSLA"])
python
Option symbols use OSI format: ROOT + YYMMDD + C/P + 8-digit strike. For example, AAPL260417C00200000 is AAPL $200 Call expiring April 17, 2026.

Unsubscribe and Disconnect

Remove symbols at runtime without reconnecting:

client.unsubscribe(["BTC/USD"])      # stop one symbol
client.subscribe(["SOL/USD"])        # add another
python
Exit cleanly from a callback or another thread:

tick_count = 0

def on_tick(tick):
    global tick_count
    tick_count += 1
    if tick_count >= 100:
        client.disconnect()  # connect() returns

client.on("tick", on_tick)
client.connect(symbols=["BTC/USD"])
print("Done, collected 100 ticks")
python
Historical data (download)

The same key downloads history over REST. See the Data API reference for the full grammar; the Python SDK wraps it:

from lse import LSE

client = LSE(api_key="your_key")

candles  = client.candles("BTC/USD", "1d", start="2026-01-01")  # 1m,5m,15m,1h,4h,1d
events   = client.economic_calendar(region="US")
insiders = client.insider_trades("AAPL", type="P-Purchase")
divs     = client.dividends("AAPL")
splits   = client.splits("NVDA")
python
Candles cover stocks, FX, crypto, commodities, indices, and ETFs. Options have their own download methods below. Up to 5,000 rows per call, 100 calls per minute, and download bytes count against the same monthly data allowance as streaming.

Options data (download)

Start from a ticker or a plain company name and get the chain, then drill into a single contract. The chain gives you each contract's ticker, and the SDK builds one from its parts when you address a contract directly.

chain  = client.options("apple", type="call", max_dte=30)   # live chain with IV and greeks
prints = client.options_flow("NVDA", min_premium=100_000)   # recent prints (time and sales)
bars   = client.option_candles("AAPL", strike=205,
                               expiry="2026-06-12", type="call")
names  = client.options_underlyings()                       # every underlying with options
python
options() returns one row per contract with the latest traded price, implied volatility, greeks, and the volume and premium traded today. Underlyings resolve from tickers or company names in any case, so "apple" works as well as "AAPL". Filter with type, expiry, a single strike or a (low, high) strike window, and min_dte / max_dte.

options_flow() returns individual prints from the trailing week, each carrying premium, IV, and greeks at print time. Omit the underlying to see every name at once, for example every print above $250k premium.

option_candles() returns 1 minute bars with OHLC on the contract price and averaged greeks for one contract. Address it with an OSI ticker straight from the chain, or by parts and the SDK assembles the ticker. Recent bars are built from the trailing week of raw prints and older bars come from the compacted archive. The SDK merges the two into one continuous series.

Implied volatility and greeks come from our own pricing models. The raw routes (/iso/x_options_chain, /iso/x_options_flow, /iso/x_options_flow_1m) are documented in the Data API reference for use from any language.

Plans and Limits

Included with the Standard plan. One key streams up to 16 symbols at a time, picked from the full catalog (any stock, forex pair, crypto, index, commodity, ETF, or option). Subscribe and unsubscribe at runtime to rotate within the 16 slots without reconnecting.

Exceeding 16 active subscriptions returns a LIMIT_REACHED error; drop a symbol with client.unsubscribe(...) to make room.

Error Codes

Code	Meaning
MISSING_KEY	No api_key provided in auth message
INVALID_KEY	API key not found or inactive
NOT_AUTHENTICATED	Tried to subscribe before authenticating
INVALID_SYMBOL	Symbol not in the catalog. Use client.catalog() to see valid symbols
RATE_LIMITED	Too many messages, slow down
LIMIT_REACHED	You already have 16 active subscriptions. Unsubscribe one to add another
MISSING_SYMBOL	Subscribe/unsubscribe without a symbol
UNKNOWN_ACTION	Unrecognized action name
INVALID_START	Invalid start timestamp for replay
REPLAY_UNAVAILABLE	Replay service is temporarily down
REPLAY_NO_DATA	No historical data available for this symbol
REPLAY_ERROR	Replay query failed (try a shorter lookback)
Data Sources

Asset Class	Feed	Latency
US Stocks / ETFs	US equities consolidated tape	Live
International Stocks	Global equities feed	Streaming
Crypto	Digital asset spot feed	Live
Forex	Aggregated interbank FX feed	Live
Options	US options feed (OPRA)	Live
Indices	Global index feed	Live
Commodities	Spot commodities feed	Live
CME Futures	CME futures feed	Live
All feeds are aggregated, cleaned, and normalized on our own infrastructure before they reach you.

Raw WebSocket Protocol

If you are not using Python, you can connect directly to the WebSocket endpoint from any language. The SDK is just a thin wrapper around this protocol.

Endpoint

wss://data-ws.londonstrategicedge.com
Authentication

After connecting, you receive a welcome message. Then send your API key:

{ "action": "auth", "api_key": "your_api_key_here" }
json
Subscribe / Unsubscribe

{ "action": "subscribe", "symbol": "BTC/USD" }
{ "action": "subscribe", "symbol": "BTC/USD", "start": "2026-04-18T09:00:00" }
{ "action": "unsubscribe", "symbol": "BTC/USD" }
{ "action": "subscribe_options", "underlying": "AAPL" }
{ "action": "unsubscribe_options", "underlying": "AAPL" }
json
When start is included, the server replays historical ticks from that time (with "replay": true on each tick), then sends replay_complete, then continues with live ticks. Max 24 hours lookback. Accepts ISO 8601 or epoch timestamps.

List Symbols

{ "action": "list_symbols" }
{ "action": "list_symbols", "category": "options" }
{ "action": "list_symbols", "category": "all" }
json
Tick Format

{
  "type": "tick",
  "symbol": "AAPL",
  "price": 213.78,
  "bid": 213.77,
  "ask": 213.79,
  "volume": 100,
  "ts": "2026-04-10T16:32:00Z"
}
json
Keepalive

{ "action": "ping" }
json
JavaScript Example

const ws = new WebSocket("wss://data-ws.londonstrategicedge.com");

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  if (data.type === "welcome") {
    ws.send(JSON.stringify({ action: "auth", api_key: "your_key" }));
  }

  if (data.type === "authenticated") {
    console.log(`Connected: ${data.symbols.length} symbols`);
    ws.send(JSON.stringify({ action: "subscribe", symbol: "BTC/USD" }));
    ws.send(JSON.stringify({ action: "subscribe", symbol: "AAPL" }));
  }

  if (data.type === "tick") {
    console.log(`${data.symbol} ${data.price}`);
  }
};
javascript
Source Code

The Python SDK is published on PyPI: pypi.org/project/lse-data