"""Конфигурация для фильтрации крипто новостей"""

# Категории важности с весами
IMPORTANCE_RULES = {
    'CRITICAL': {
        'weight': 100,
        'keywords': [
            'sec approves', 'sec denies', 'sec sues',
            'banned', 'ban', 'regulation passed',
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
    'airdrop', 'giveaway', 'sponsored'
]

# Минимальный порог для публикации
MIN_IMPORTANCE_SCORE = 25

# Порог схожести для дедупликации (0.0-1.0)
# 0.6 = 60% общих слов → считается дубликатом
# Увеличь если слишком много дубликатов пропускается
# Уменьши если слишком агрессивная фильтрация
SIMILARITY_THRESHOLD = 0.6

# Приоритет источников (1 = highest)
# При дубликатах выбирается источник с меньшим номером
SOURCE_PRIORITY = {
    'theblock': 1,    # Highest - has summary
    'coindesk': 2,
    'decrypt': 3
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
    }
}
