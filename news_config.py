"""Конфигурация для фильтрации крипто новостей"""

# Категории важности с весами
IMPORTANCE_RULES = {
    'STOCK_CRITICAL': {
        'weight': 150,
        'keywords': [
            # Fed & Monetary Policy (ONLY)
            'fed raises', 'fed cuts', 'fed rate decision', 'fomc decision',
            'powell says', 'federal reserve announces',
            
            # Major Market Moves (ONLY broad indices)
            'dow plunges', 'dow surges', 'dow crashes',
            's&p plunges', 's&p surges', 's&p crashes', 
            'nasdaq plunges', 'nasdaq surges', 'nasdaq crashes',
            'market crash', 'circuit breaker', 'trading halted',
            'black monday', 'market meltdown',
            
            # Critical Economic Data (ONLY)
            'unemployment rate', 'jobs report shock',
            'inflation shock', 'cpi shock', 'gdp shock',
            'recession declared', 'recession confirmed',
            
            # Treasury/Bond Market (ONLY major events)
            'treasury yields surge', 'treasury yields plunge',
            'bond market crisis', 'bond market turmoil',
            
            # Global Crisis Events (ONLY)
            'financial crisis', 'banking crisis', 'debt crisis',
            'government shutdown', 'debt ceiling crisis'
        ]
    },
    'CRITICAL': {
        'weight': 100,
        'keywords': [
            'sec approves', 'sec denies', 'sec sues',
            'crypto banned', 'crypto ban', 'regulation passed',  # Более специфичные keywords
            'etf approved', 'etf rejected',
            'hard fork', 'network upgrade',
            'exchange hack', 'exploit', '$100m', '$500m', '$1b',
            'binance hack', 'coinbase halt'
        ]
    },
    'HIGH': {
        'weight': 50,
        'keywords': [
            'cftc', 'federal reserve', 'fed rate',
            'bitcoin etf', 'ethereum etf', 'crypto etf',
            'blackrock', 'fidelity', 'grayscale',
            'microstrategy', 'michael saylor',
            'el salvador', 'government adopts',
            'sec lawsuit', 'settles lawsuit', 'regulatory'
        ]
    },
    'MEDIUM': {
        'weight': 25,
        'keywords': [
            'listing', 'delisting',
            'partnership', 'integration',
            'funding round', 'raises $',
            'mainnet launch', 'testnet',
            'major upgrade', 'protocol update'
        ]
    },
    'MARKET_MOVE': {
        'weight': 40,
        'keywords': [
            'surges', 'plunges', 'crashes', 'rallies',
            'all-time high', 'ath', 'record high',
            'breaks $', 'hits $100', 'hits $50',
            '+10%', '+15%', '+20%',
            '-10%', '-15%', '-20%'
        ]
    }
}

# Исключения (шум)
EXCLUDE_KEYWORDS = [
    'opinion', 'analysis',
    'how to', 'guide', 'tutorial',
    'price prediction', 'forecast',
    'meme coin', 'shitcoin', 'dog coin',
    'airdrop', 'giveaway', 'sponsored',
    # Personal finance / lifestyle stories
    'my friend', 'retired with', 'secret to',
    'personal story', 'what i learned',
    'immigrant', 'walmart', 'minimum wage',
    'her secret', 'his secret', 'their secret',
    'my husband', 'my wife', 'we are in our',
    'where are we', 'should i', 'should we',
    'mortgage is paid', 'we have $', 'our home',
    'vulnerable', 'iras', 'downsizing',
    # Company-specific news (exclude for stock sources)
    'ceo says', 'cfo says', 'earnings beat', 'earnings miss',
    'quarterly results', 'stock buyback', 'dividend increase',
    'merger with', 'acquires', 'acquisition',
    'ipo', 'going public', 'stock split',
    'files for bankruptcy', 'chapter 11', 'bankruptcy protection',
    'goes private', 'going private', 'maker files'
]

# Минимальный порог для публикации
MIN_IMPORTANCE_SCORE = 60  # Только важные новости

# Более высокий порог для stock market источников
# Только супер критичные broad market события
STOCK_MARKET_THRESHOLD = 120  # CRITICAL events only (fed, crashes, major indices)

# Порог схожести для дедупликации (0.0-1.0)
# Используем разные пороги для разных проверок:

# Для проверки с уже опубликованными (строгий - ловим все похожие)
PUBLISHED_SIMILARITY_THRESHOLD = 0.3  # 30% общих слов = дубликат

# Для дедупликации внутри текущей партии (средний - убираем очевидные)
BATCH_SIMILARITY_THRESHOLD = 0.5  # 50% общих слов = дубликат

# Приоритет источников (1 = highest)
# При дубликатах выбирается источник с меньшим номером
SOURCE_PRIORITY = {
    'theblock': 1,      # Highest - has summary
    'coindesk': 2,
    'bloomberg': 3,     # Stock market
    'marketwatch': 4,   # Stock market
    'reuters': 5,       # Stock market
    'decrypt': 6
}

# Twitter Integration
TWITTER_ENABLED = True  # Set to False to disable Twitter posts

# Источники RSS
RSS_SOURCES = {
    'coindesk': {
        'url': 'https://www.coindesk.com/arc/outboundfeeds/rss/',
        'priority': 1,
        'weight_multiplier': 1.2  # Доверяем больше
    },
    'theblock': {
        'url': 'https://www.theblock.co/rss.xml',
        'priority': 1,
        'weight_multiplier': 1.2
    },
    'decrypt': {
        'url': 'https://decrypt.co/feed',
        'priority': 1,
        'weight_multiplier': 1.0
    },
    'marketwatch': {
        'url': 'https://www.marketwatch.com/rss/topstories',
        'priority': 2,
        'weight_multiplier': 1.3  # Major US market news
    },
    'bloomberg': {
        'url': 'https://www.bloomberg.com/feed/podcast/markets.xml',
        'priority': 2,
        'weight_multiplier': 1.3  # Major market moves
    },
    'reuters': {
        'url': 'https://www.reutersagency.com/feed/?taxonomy=best-topics&post_type=best',
        'priority': 2,
        'weight_multiplier': 1.2  # Breaking business news
    }
}
