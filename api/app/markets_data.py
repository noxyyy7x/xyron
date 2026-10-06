"""The instruments XYRON tracks: names, tickers and the stock exchanges shown on the globe.
Edit these lists to add or remove things. A ticker that turns out not to exist is simply hidden."""

# (ticker, name, sector). US-listed, priced live through Finnhub.
US_STOCKS = [
    # technology
    ("AAPL", "Apple", "Technology"), ("MSFT", "Microsoft", "Technology"), ("NVDA", "NVIDIA", "Technology"),
    ("GOOGL", "Alphabet", "Technology"), ("AMZN", "Amazon", "Consumer"), ("META", "Meta Platforms", "Technology"),
    ("TSLA", "Tesla", "Autos"), ("AVGO", "Broadcom", "Technology"), ("ORCL", "Oracle", "Technology"),
    ("NFLX", "Netflix", "Media"), ("AMD", "Advanced Micro Devices", "Technology"), ("CRM", "Salesforce", "Technology"),
    ("ADBE", "Adobe", "Technology"), ("CSCO", "Cisco", "Technology"), ("INTC", "Intel", "Technology"),
    ("QCOM", "Qualcomm", "Technology"), ("TXN", "Texas Instruments", "Technology"), ("IBM", "IBM", "Technology"),
    ("NOW", "ServiceNow", "Technology"), ("INTU", "Intuit", "Technology"), ("AMAT", "Applied Materials", "Technology"),
    ("MU", "Micron", "Technology"), ("PANW", "Palo Alto Networks", "Technology"), ("CRWD", "CrowdStrike", "Technology"),
    ("SNOW", "Snowflake", "Technology"), ("PLTR", "Palantir", "Technology"), ("SHOP", "Shopify", "Technology"),
    ("UBER", "Uber", "Technology"), ("ABNB", "Airbnb", "Consumer"), ("BKNG", "Booking Holdings", "Consumer"),
    ("PYPL", "PayPal", "Financials"), ("XYZ", "Block", "Financials"), ("COIN", "Coinbase", "Financials"),
    ("HOOD", "Robinhood", "Financials"), ("SPOT", "Spotify", "Media"), ("DASH", "DoorDash", "Consumer"),
    ("LRCX", "Lam Research", "Technology"), ("KLAC", "KLA", "Technology"), ("MRVL", "Marvell", "Technology"),
    ("ARM", "Arm Holdings", "Technology"), ("DELL", "Dell Technologies", "Technology"), ("ACN", "Accenture", "Technology"),
    # games and media
    ("TTWO", "Take-Two Interactive", "Games"), ("EA", "Electronic Arts", "Games"), ("RBLX", "Roblox", "Games"),
    ("U", "Unity Software", "Games"), ("DIS", "Walt Disney", "Media"), ("WBD", "Warner Bros. Discovery", "Media"),
    ("SONY", "Sony Group", "Games"),
    # finance
    ("JPM", "JPMorgan Chase", "Financials"), ("BAC", "Bank of America", "Financials"), ("WFC", "Wells Fargo", "Financials"),
    ("C", "Citigroup", "Financials"), ("GS", "Goldman Sachs", "Financials"), ("MS", "Morgan Stanley", "Financials"),
    ("SCHW", "Charles Schwab", "Financials"), ("BLK", "BlackRock", "Financials"), ("V", "Visa", "Financials"),
    ("MA", "Mastercard", "Financials"), ("AXP", "American Express", "Financials"), ("BRK.B", "Berkshire Hathaway", "Financials"),
    ("SPGI", "S&P Global", "Financials"),
    # healthcare
    ("LLY", "Eli Lilly", "Healthcare"), ("UNH", "UnitedHealth", "Healthcare"), ("JNJ", "Johnson & Johnson", "Healthcare"),
    ("ABBV", "AbbVie", "Healthcare"), ("MRK", "Merck", "Healthcare"), ("PFE", "Pfizer", "Healthcare"),
    ("TMO", "Thermo Fisher", "Healthcare"), ("ABT", "Abbott", "Healthcare"), ("AMGN", "Amgen", "Healthcare"),
    ("ISRG", "Intuitive Surgical", "Healthcare"), ("NVO", "Novo Nordisk", "Healthcare"), ("DHR", "Danaher", "Healthcare"),
    ("BMY", "Bristol Myers Squibb", "Healthcare"), ("GILD", "Gilead Sciences", "Healthcare"),
    # consumer
    ("WMT", "Walmart", "Consumer"), ("COST", "Costco", "Consumer"), ("HD", "Home Depot", "Consumer"),
    ("LOW", "Lowe's", "Consumer"), ("PG", "Procter & Gamble", "Consumer"), ("KO", "Coca-Cola", "Consumer"),
    ("PEP", "PepsiCo", "Consumer"), ("MCD", "McDonald's", "Consumer"), ("SBUX", "Starbucks", "Consumer"),
    ("NKE", "Nike", "Consumer"), ("TGT", "Target", "Consumer"), ("PM", "Philip Morris", "Consumer"),
    ("MDLZ", "Mondelez", "Consumer"), ("CL", "Colgate-Palmolive", "Consumer"), ("LULU", "Lululemon", "Consumer"),
    ("CMG", "Chipotle", "Consumer"),
    # energy
    ("XOM", "Exxon Mobil", "Energy"), ("CVX", "Chevron", "Energy"), ("COP", "ConocoPhillips", "Energy"),
    ("SLB", "Schlumberger", "Energy"), ("OXY", "Occidental Petroleum", "Energy"), ("EOG", "EOG Resources", "Energy"),
    # industrials and defence
    ("GE", "GE Aerospace", "Industrials"), ("CAT", "Caterpillar", "Industrials"), ("DE", "Deere", "Industrials"),
    ("BA", "Boeing", "Industrials"), ("RTX", "RTX", "Industrials"), ("HON", "Honeywell", "Industrials"),
    ("UNP", "Union Pacific", "Industrials"), ("UPS", "UPS", "Industrials"), ("LMT", "Lockheed Martin", "Industrials"),
    ("NOC", "Northrop Grumman", "Industrials"), ("GD", "General Dynamics", "Industrials"), ("MMM", "3M", "Industrials"),
    # telecom and utilities
    ("VZ", "Verizon", "Telecom"), ("T", "AT&T", "Telecom"), ("TMUS", "T-Mobile US", "Telecom"),
    ("NEE", "NextEra Energy", "Utilities"), ("DUK", "Duke Energy", "Utilities"), ("SO", "Southern Company", "Utilities"),
    # autos
    ("F", "Ford", "Autos"), ("GM", "General Motors", "Autos"), ("TM", "Toyota", "Autos"), ("RIVN", "Rivian", "Autos"),
    # international companies listed in the US
    ("TSM", "Taiwan Semiconductor", "Technology"), ("ASML", "ASML", "Technology"), ("SAP", "SAP", "Technology"),
    ("BABA", "Alibaba", "Consumer"), ("PDD", "PDD Holdings", "Consumer"), ("JD", "JD.com", "Consumer"),
    ("BIDU", "Baidu", "Technology"), ("NIO", "NIO", "Autos"), ("AZN", "AstraZeneca", "Healthcare"),
    ("SHEL", "Shell", "Energy"), ("BP", "BP", "Energy"), ("HSBC", "HSBC", "Financials"), ("UL", "Unilever", "Consumer"),
    ("TTE", "TotalEnergies", "Energy"), ("MSTR", "Strategy (MicroStrategy)", "Financials"),
]
# US-listed funds, priced the same way
ETFS = [
    ("SPY", "SPDR S&P 500 ETF"), ("QQQ", "Invesco QQQ (Nasdaq-100)"), ("DIA", "SPDR Dow Jones ETF"), ("IWM", "iShares Russell 2000"),
    ("GLD", "SPDR Gold Shares"), ("SLV", "iShares Silver Trust"), ("USO", "United States Oil Fund"), ("TLT", "iShares 20+ Year Treasury"),
]
# listed outside the US: Yahoo only, so delayed
INTL_STOCKS = [
    ("SHEL.L", "Shell", "UK"), ("AZN.L", "AstraZeneca", "UK"), ("HSBA.L", "HSBC", "UK"), ("BP.L", "BP", "UK"),
    ("ULVR.L", "Unilever", "UK"), ("GSK.L", "GSK", "UK"), ("RIO.L", "Rio Tinto", "UK"), ("BARC.L", "Barclays", "UK"),
    ("LLOY.L", "Lloyds Banking Group", "UK"), ("7203.T", "Toyota", "Japan"), ("6758.T", "Sony Group", "Japan"),
    ("7974.T", "Nintendo", "Japan"), ("9984.T", "SoftBank Group", "Japan"), ("SAP.DE", "SAP", "Germany"),
    ("SIE.DE", "Siemens", "Germany"), ("MC.PA", "LVMH", "France"), ("AIR.PA", "Airbus", "France"),
    ("ASML.AS", "ASML", "Netherlands"), ("0700.HK", "Tencent", "Hong Kong"), ("9988.HK", "Alibaba", "Hong Kong"),
    ("1211.HK", "BYD", "Hong Kong"), ("005930.KS", "Samsung Electronics", "South Korea"), ("NESN.SW", "Nestl\u00e9", "Switzerland"),
    ("RELIANCE.NS", "Reliance Industries", "India"), ("BHP.AX", "BHP Group", "Australia"), ("2222.SR", "Saudi Aramco", "Saudi Arabia"),
]
# (yahoo symbol, name, country)
INDICES = [
    ("^GSPC", "S&P 500", "United States"), ("^DJI", "Dow Jones", "United States"), ("^IXIC", "Nasdaq Composite", "United States"),
    ("^RUT", "Russell 2000", "United States"), ("^VIX", "VIX (volatility)", "United States"), ("^GSPTSE", "S&P/TSX", "Canada"),
    ("^MXX", "IPC Mexico", "Mexico"), ("^BVSP", "Bovespa", "Brazil"), ("^FTSE", "FTSE 100", "United Kingdom"),
    ("^GDAXI", "DAX", "Germany"), ("^FCHI", "CAC 40", "France"), ("^STOXX50E", "Euro Stoxx 50", "Europe"),
    ("^AEX", "AEX", "Netherlands"), ("^IBEX", "IBEX 35", "Spain"), ("FTSEMIB.MI", "FTSE MIB", "Italy"),
    ("^SSMI", "SMI", "Switzerland"), ("^TASI.SR", "Tadawul All Share", "Saudi Arabia"), ("^NSEI", "Nifty 50", "India"),
    ("^BSESN", "BSE Sensex", "India"), ("^STI", "Straits Times", "Singapore"), ("^HSI", "Hang Seng", "Hong Kong"),
    ("000001.SS", "Shanghai Composite", "China"), ("399001.SZ", "Shenzhen Component", "China"), ("^N225", "Nikkei 225", "Japan"),
    ("^KS11", "KOSPI", "South Korea"), ("^TWII", "Taiwan Weighted", "Taiwan"), ("^AXJO", "S&P/ASX 200", "Australia"),
]
# (yahoo symbol, name, unit, group)
COMMODITIES = [
    ("GC=F", "Gold", "USD per troy oz", "Metals"), ("SI=F", "Silver", "USD per troy oz", "Metals"),
    ("PL=F", "Platinum", "USD per troy oz", "Metals"), ("PA=F", "Palladium", "USD per troy oz", "Metals"),
    ("HG=F", "Copper", "USD per lb", "Metals"), ("ALI=F", "Aluminium", "USD per tonne", "Metals"),
    ("CL=F", "Crude oil (WTI)", "USD per barrel", "Energy"), ("BZ=F", "Crude oil (Brent)", "USD per barrel", "Energy"),
    ("NG=F", "Natural gas", "USD per MMBtu", "Energy"), ("RB=F", "Gasoline (RBOB)", "USD per gallon", "Energy"),
    ("HO=F", "Heating oil", "USD per gallon", "Energy"),
    ("ZW=F", "Wheat", "US cents per bushel", "Agriculture"), ("ZC=F", "Corn", "US cents per bushel", "Agriculture"),
    ("ZS=F", "Soybeans", "US cents per bushel", "Agriculture"), ("KC=F", "Coffee", "US cents per lb", "Agriculture"),
    ("SB=F", "Sugar", "US cents per lb", "Agriculture"), ("CC=F", "Cocoa", "USD per tonne", "Agriculture"),
    ("CT=F", "Cotton", "US cents per lb", "Agriculture"), ("LE=F", "Live cattle", "US cents per lb", "Agriculture"),
    ("HE=F", "Lean hogs", "US cents per lb", "Agriculture"), ("OJ=F", "Orange juice", "US cents per lb", "Agriculture"),
]
FX = [
    ("GBPUSD=X", "GBP / USD"), ("EURUSD=X", "EUR / USD"), ("USDJPY=X", "USD / JPY"), ("USDCHF=X", "USD / CHF"),
    ("AUDUSD=X", "AUD / USD"), ("USDCAD=X", "USD / CAD"), ("NZDUSD=X", "NZD / USD"), ("EURGBP=X", "EUR / GBP"),
    ("USDCNY=X", "USD / CNY"), ("USDINR=X", "USD / INR"), ("USDTRY=X", "USD / TRY"), ("USDBRL=X", "USD / BRL"),
    ("USDZAR=X", "USD / ZAR"), ("DX-Y.NYB", "US Dollar Index"),
]
# used if CoinGecko cannot be reached on the very first start
CRYPTO_FALLBACK = [
    ("bitcoin", "BTC", "Bitcoin"), ("ethereum", "ETH", "Ethereum"), ("binancecoin", "BNB", "BNB"), ("solana", "SOL", "Solana"),
    ("ripple", "XRP", "XRP"), ("dogecoin", "DOGE", "Dogecoin"), ("cardano", "ADA", "Cardano"), ("tron", "TRX", "TRON"),
    ("chainlink", "LINK", "Chainlink"), ("avalanche-2", "AVAX", "Avalanche"), ("litecoin", "LTC", "Litecoin"), ("polkadot", "DOT", "Polkadot"),
]
STABLECOINS = {"USDT", "USDC", "DAI", "USDE", "FDUSD", "TUSD", "USDS", "PYUSD", "USDD", "BUIDL", "USD1", "USDG"}

# stock exchanges on the globe. sessions are local (start hour, start minute, end hour, end minute); days: Monday = 0.
# Public holidays are not in this table; an exchange whose index has gone quiet during its session is shown as "quiet".
WEEK = (0, 1, 2, 3, 4)
EXCHANGES = [
    {"id": "nyse", "name": "NYSE", "city": "New York", "country": "United States", "lat": 40.7069, "lon": -74.0113, "tz": "America/New_York", "sessions": [(9, 30, 16, 0)], "days": WEEK, "index": "^GSPC", "index_name": "S&P 500"},
    {"id": "nasdaq", "name": "Nasdaq", "city": "New York", "country": "United States", "lat": 40.7567, "lon": -73.9862, "tz": "America/New_York", "sessions": [(9, 30, 16, 0)], "days": WEEK, "index": "^IXIC", "index_name": "Nasdaq Composite"},
    {"id": "tsx", "name": "TSX", "city": "Toronto", "country": "Canada", "lat": 43.6487, "lon": -79.3816, "tz": "America/Toronto", "sessions": [(9, 30, 16, 0)], "days": WEEK, "index": "^GSPTSE", "index_name": "S&P/TSX"},
    {"id": "bmv", "name": "Bolsa Mexicana", "city": "Mexico City", "country": "Mexico", "lat": 19.4326, "lon": -99.1332, "tz": "America/Mexico_City", "sessions": [(8, 30, 15, 0)], "days": WEEK, "index": "^MXX", "index_name": "IPC"},
    {"id": "b3", "name": "B3", "city": "S\u00e3o Paulo", "country": "Brazil", "lat": -23.5469, "lon": -46.6340, "tz": "America/Sao_Paulo", "sessions": [(10, 0, 17, 0)], "days": WEEK, "index": "^BVSP", "index_name": "Bovespa"},
    {"id": "lse", "name": "London Stock Exchange", "city": "London", "country": "United Kingdom", "lat": 51.5155, "lon": -0.0990, "tz": "Europe/London", "sessions": [(8, 0, 16, 30)], "days": WEEK, "index": "^FTSE", "index_name": "FTSE 100"},
    {"id": "euronext-paris", "name": "Euronext Paris", "city": "Paris", "country": "France", "lat": 48.8696, "lon": 2.3392, "tz": "Europe/Paris", "sessions": [(9, 0, 17, 30)], "days": WEEK, "index": "^FCHI", "index_name": "CAC 40"},
    {"id": "euronext-amsterdam", "name": "Euronext Amsterdam", "city": "Amsterdam", "country": "Netherlands", "lat": 52.3727, "lon": 4.8938, "tz": "Europe/Amsterdam", "sessions": [(9, 0, 17, 30)], "days": WEEK, "index": "^AEX", "index_name": "AEX"},
    {"id": "xetra", "name": "Deutsche B\u00f6rse", "city": "Frankfurt", "country": "Germany", "lat": 50.1153, "lon": 8.6794, "tz": "Europe/Berlin", "sessions": [(9, 0, 17, 30)], "days": WEEK, "index": "^GDAXI", "index_name": "DAX"},
    {"id": "six", "name": "SIX Swiss Exchange", "city": "Zurich", "country": "Switzerland", "lat": 47.3914, "lon": 8.5195, "tz": "Europe/Zurich", "sessions": [(9, 0, 17, 30)], "days": WEEK, "index": "^SSMI", "index_name": "SMI"},
    {"id": "bme", "name": "Bolsa de Madrid", "city": "Madrid", "country": "Spain", "lat": 40.4154, "lon": -3.6925, "tz": "Europe/Madrid", "sessions": [(9, 0, 17, 30)], "days": WEEK, "index": "^IBEX", "index_name": "IBEX 35"},
    {"id": "borsa-italiana", "name": "Borsa Italiana", "city": "Milan", "country": "Italy", "lat": 45.4655, "lon": 9.1888, "tz": "Europe/Rome", "sessions": [(9, 0, 17, 30)], "days": WEEK, "index": "FTSEMIB.MI", "index_name": "FTSE MIB"},
    {"id": "tadawul", "name": "Tadawul", "city": "Riyadh", "country": "Saudi Arabia", "lat": 24.7136, "lon": 46.6753, "tz": "Asia/Riyadh", "sessions": [(10, 0, 15, 0)], "days": (6, 0, 1, 2, 3), "index": "^TASI.SR", "index_name": "TASI"},
    {"id": "nse", "name": "NSE / BSE", "city": "Mumbai", "country": "India", "lat": 19.0657, "lon": 72.8654, "tz": "Asia/Kolkata", "sessions": [(9, 15, 15, 30)], "days": WEEK, "index": "^NSEI", "index_name": "Nifty 50"},
    {"id": "sgx", "name": "Singapore Exchange", "city": "Singapore", "country": "Singapore", "lat": 1.2840, "lon": 103.8492, "tz": "Asia/Singapore", "sessions": [(9, 0, 17, 0)], "days": WEEK, "index": "^STI", "index_name": "Straits Times"},
    {"id": "hkex", "name": "HKEX", "city": "Hong Kong", "country": "Hong Kong", "lat": 22.2845, "lon": 114.1575, "tz": "Asia/Hong_Kong", "sessions": [(9, 30, 12, 0), (13, 0, 16, 0)], "days": WEEK, "index": "^HSI", "index_name": "Hang Seng"},
    {"id": "sse", "name": "Shanghai Stock Exchange", "city": "Shanghai", "country": "China", "lat": 31.2347, "lon": 121.5050, "tz": "Asia/Shanghai", "sessions": [(9, 30, 11, 30), (13, 0, 15, 0)], "days": WEEK, "index": "000001.SS", "index_name": "SSE Composite"},
    {"id": "szse", "name": "Shenzhen Stock Exchange", "city": "Shenzhen", "country": "China", "lat": 22.5431, "lon": 114.0579, "tz": "Asia/Shanghai", "sessions": [(9, 30, 11, 30), (13, 0, 15, 0)], "days": WEEK, "index": "399001.SZ", "index_name": "SZSE Component"},
    {"id": "tse", "name": "Tokyo Stock Exchange", "city": "Tokyo", "country": "Japan", "lat": 35.6820, "lon": 139.7740, "tz": "Asia/Tokyo", "sessions": [(9, 0, 11, 30), (12, 30, 15, 30)], "days": WEEK, "index": "^N225", "index_name": "Nikkei 225"},
    {"id": "krx", "name": "Korea Exchange", "city": "Seoul", "country": "South Korea", "lat": 37.5183, "lon": 126.9262, "tz": "Asia/Seoul", "sessions": [(9, 0, 15, 30)], "days": WEEK, "index": "^KS11", "index_name": "KOSPI"},
    {"id": "twse", "name": "Taiwan Stock Exchange", "city": "Taipei", "country": "Taiwan", "lat": 25.0417, "lon": 121.5620, "tz": "Asia/Taipei", "sessions": [(9, 0, 13, 30)], "days": WEEK, "index": "^TWII", "index_name": "TAIEX"},
    {"id": "asx", "name": "ASX", "city": "Sydney", "country": "Australia", "lat": -33.8636, "lon": 151.2102, "tz": "Australia/Sydney", "sessions": [(10, 0, 16, 0)], "days": WEEK, "index": "^AXJO", "index_name": "S&P/ASX 200"},
]
# which exchange a Yahoo ticker suffix belongs to (for deciding how often to ask)
SUFFIX_EXCHANGE = {".L": "lse", ".T": "tse", ".DE": "xetra", ".PA": "euronext-paris", ".AS": "euronext-amsterdam", ".HK": "hkex",
                   ".KS": "krx", ".SW": "six", ".NS": "nse", ".AX": "asx", ".SR": "tadawul", ".MI": "borsa-italiana", ".MC": "bme", ".TO": "tsx"}
INDEX_EXCHANGE = {e["index"]: e["id"] for e in EXCHANGES}
# the symbols shown in the scrolling ticker at the bottom of the globe
TICKER = ["BTC", "ETH", "SOL", "^GSPC", "^IXIC", "^FTSE", "^N225", "GC=F", "SI=F", "CL=F", "GBPUSD=X", "TTWO", "NVDA", "AAPL"]
