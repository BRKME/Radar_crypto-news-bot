"""Тестовый скрипт для проверки парсера без публикации в Telegram"""

import feedparser
from datetime import datetime, timedelta
from news_config import IMPORTANCE_RULES, EXCLUDE_KEYWORDS, MIN_IMPORTANCE_SCORE, RSS_SOURCES
import re


def test_feed_parsing():
    """Тестируем парсинг одного источника"""
    print("🧪 Testing RSS feed parsing...\n")
    
    source_name = 'coindesk'
    config = RSS_SOURCES[source_name]
    
    try:
        feed = feedparser.parse(config['url'])
        print(f"✓ Successfully parsed {source_name}")
        print(f"  Total entries: {len(feed.entries)}")
        print(f"  Feed title: {feed.feed.get('title', 'N/A')}\n")
        
        if len(feed.entries) > 0:
            print("📰 Latest 3 entries:")
            for i, entry in enumerate(feed.entries[:3], 1):
                print(f"\n{i}. {entry.title}")
                print(f"   Link: {entry.link}")
                print(f"   Published: {entry.get('published', 'N/A')}")
        
        return True
    except Exception as e:
        print(f"✗ Error parsing {source_name}: {e}")
        return False


def test_scoring():
    """Тестируем систему скоринга"""
    print("\n\n🎯 Testing scoring system...\n")
    
    test_titles = [
        "SEC Approves Bitcoin ETF Applications from BlackRock",
        "Bitcoin Surges 15% After Fed Rate Cut Decision",
        "Ethereum Upgrade Scheduled for Next Month",
        "New Meme Coin Launches with Price Predictions",
        "How to Buy Bitcoin: A Complete Guide",
        "MicroStrategy Purchases Additional $500M in Bitcoin"
    ]
    
    for title in test_titles:
        news_item = {
            'title': title,
            'source_weight': 1.2
        }
        
        score = 0
        categories = []
        title_lower = title.lower()
        
        # Проверяем исключения
        excluded = False
        for exclude in EXCLUDE_KEYWORDS:
            if exclude in title_lower:
                excluded = True
                break
        
        if excluded:
            print(f"❌ [EXCLUDED] {title}")
            continue
        
        # Считаем баллы
        for category, rules in IMPORTANCE_RULES.items():
            for keyword in rules['keywords']:
                if keyword.lower() in title_lower:
                    score += rules['weight']
                    categories.append(category)
                    break
        
        # Бонусы
        if 'bitcoin' in title_lower or 'btc' in title_lower:
            score *= 1.3
        
        if re.search(r'\$[\d,]+[mbk]?|\d+%', title_lower):
            score *= 1.2
        
        score *= news_item['source_weight']
        score = round(score)
        
        status = "✅" if score >= MIN_IMPORTANCE_SCORE else "⚠️"
        print(f"{status} [{score:3d}] {title}")
        if categories:
            print(f"      Categories: {', '.join(categories)}")


def test_all_sources():
    """Тестируем все источники"""
    print("\n\n📡 Testing all RSS sources...\n")
    
    for source_name, config in RSS_SOURCES.items():
        try:
            feed = feedparser.parse(config['url'])
            status = "✓" if len(feed.entries) > 0 else "⚠"
            print(f"{status} {source_name:15s} - {len(feed.entries):2d} entries")
        except Exception as e:
            print(f"✗ {source_name:15s} - Error: {e}")


def main():
    print("=" * 70)
    print("🧪 CRYPTO NEWS BOT - TEST SUITE")
    print("=" * 70)
    
    # Тест 1: Парсинг RSS
    test_feed_parsing()
    
    # Тест 2: Система скоринга
    test_scoring()
    
    # Тест 3: Все источники
    test_all_sources()
    
    print("\n" + "=" * 70)
    print("✅ Testing complete!")
    print("=" * 70)


if __name__ == '__main__':
    main()
