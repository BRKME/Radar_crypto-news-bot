# news_parser.py - COMPLETE FILE v1.5.7 (FIXED)

"""
Крипто новостной бот с AI анализом
Парсит RSS, фильтрует важные новости, генерирует Alpha Take через OpenAI
Публикует в Telegram и Twitter
"""

import feedparser
import requests
import os
import json
from datetime import datetime, timedelta
import re
import html
import io

# OpenAI Integration
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print("⚠️ OpenAI not available - Alpha Take will be skipped")

from news_config import (
    RSS_SOURCES, 
    IMPORTANCE_RULES, 
    EXCLUDE_KEYWORDS, 
    MIN_IMPORTANCE_SCORE,
    STOCK_MARKET_THRESHOLD,
    SOURCE_PRIORITY,
    TWITTER_ENABLED,
    CLICKBAIT_PATTERNS,
    ALLOWED_HASHTAGS
)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.environ.get('TELEGRAM_CHANNEL_ID')

TWITTER_API_KEY = os.environ.get('TWITTER_API_KEY')
TWITTER_API_SECRET = os.environ.get('TWITTER_API_SECRET')
TWITTER_ACCESS_TOKEN = os.environ.get('TWITTER_ACCESS_TOKEN')
TWITTER_ACCESS_TOKEN_SECRET = os.environ.get('TWITTER_ACCESS_TOKEN_SECRET')

PUBLISHED_FILE = 'published_news.json'


def fetch_rss_feed(source_name, feed_config):
    """Парсим RSS feed"""
    try:
        feed = feedparser.parse(feed_config['url'])
        
        if not feed.entries:
            return []
        
        news_items = []
        for entry in feed.entries:
            title = entry.get('title', '').strip()
            link = entry.get('link', '')
            summary = entry.get('summary', entry.get('description', '')).strip()
            
            if summary:
                summary = re.sub('<.*?>', '', summary)
                summary = html.unescape(summary)
            
            published = entry.get('published_parsed') or entry.get('updated_parsed')
            published_date = datetime(*published[:6]) if published else datetime.now()
            
            image_url = None
            if 'media_content' in entry:
                image_url = entry.media_content[0].get('url')
            elif 'enclosures' in entry and entry.enclosures:
                image_url = entry.enclosures[0].get('href')
            
            news_items.append({
                'title': title,
                'link': link,
                'summary': summary[:300] if summary else '',
                'published_date': published_date,
                'source': source_name,
                'source_weight': feed_config['weight_multiplier'],
                'source_priority': feed_config['priority'],
                'image_url': image_url
            })
        
        return news_items
    
    except Exception as e:
        return []


def fetch_all_news():
    """Собираем новости из всех источников"""
    print("\n📡 Fetching news from sources...")
    all_news = []
    
    for source_name, feed_config in RSS_SOURCES.items():
        news = fetch_rss_feed(source_name, feed_config)
        if news:
            print(f"✓ Parsed {source_name}: {len(news)} entries")
            all_news.extend(news)
        else:
            print(f"✗ {source_name}: Invalid RSS feed")
    
    print(f"Total news fetched: {len(all_news)}")
    return all_news


def load_published_news():
    """Загружаем опубликованные новости"""
    try:
        with open(PUBLISHED_FILE, 'r', encoding='utf-8') as f:
            published = json.load(f)
            print(f"✓ Loaded {len(published)} items from {PUBLISHED_FILE}")
            return published
    except FileNotFoundError:
        print(f"⚠ {PUBLISHED_FILE} not found, creating new")
        return []
    except json.JSONDecodeError:
        print(f"⚠ {PUBLISHED_FILE} corrupted, starting fresh")
        return []


def save_published_news(published):
    """Сохраняем опубликованные новости"""
    with open(PUBLISHED_FILE, 'w', encoding='utf-8') as f:
        json.dump(published, f, ensure_ascii=False, indent=2)
    print(f"✓ Saved {len(published)} published items to {PUBLISHED_FILE}")


def cleanup_old_news(published, days=7):
    """Удаляем старые записи"""
    cutoff_date = datetime.now() - timedelta(days=days)
    
    cleaned = []
    for item in published:
        if isinstance(item, str):
            continue
        
        if not item.get('title'):
            continue
        
        try:
            pub_date = datetime.fromisoformat(item['published_date'])
            if pub_date >= cutoff_date:
                cleaned.append(item)
        except (ValueError, KeyError):
            cleaned.append(item)
    
    removed = len(published) - len(cleaned)
    if removed > 0:
        print(f"✓ After cleanup: {len(cleaned)} items (removed {removed} old, {len([x for x in published if not isinstance(x, dict) or not x.get('title')])} without titles)")
    else:
        print(f"✓ After cleanup: {len(cleaned)} items (removed 0 old, 0 without titles)")
    
    return cleaned


def calculate_similarity(title1, title2):
    """Jaccard similarity для заголовков"""
    def tokenize(text):
        text = text.lower()
        text = re.sub(r'[^\w\s]', '', text)
        return set(text.split())
    
    tokens1 = tokenize(title1)
    tokens2 = tokenize(title2)
    
    if not tokens1 or not tokens2:
        return 0.0
    
    intersection = len(tokens1.intersection(tokens2))
    union = len(tokens1.union(tokens2))
    
    return intersection / union if union > 0 else 0.0


def is_duplicate(news_item, published):
    """Проверяем дубликаты"""
    link = news_item.get('link', '')
    title = news_item.get('title', '')
    
    for pub_item in published:
        pub_link = pub_item.get('link', '')
        pub_title = pub_item.get('title', '')
        
        if link and pub_link and link == pub_link:
            return True
        
        if title and pub_title:
            similarity = calculate_similarity(title, pub_title)
            if similarity >= 0.5:
                return True
    
    return False


def calculate_importance(news_item):
    """Рассчитываем важность новости"""
    title = news_item['title'].lower()
    original_title = news_item['title']  # Для паттернов с учетом регистра
    score = 0
    matched_categories = []
    
    for exclude in EXCLUDE_KEYWORDS:
        if exclude in title:
            return 0, ['EXCLUDED']
    
    # Фильтруем кликбейт/неполные заголовки
    for pattern in CLICKBAIT_PATTERNS:
        if re.search(pattern, original_title):
            print(f"  ⚠️ Clickbait filtered: {original_title[:50]}...")
            return 0, ['CLICKBAIT']
    
    for category, rules in IMPORTANCE_RULES.items():
        category_matched = False
        for keyword in rules['keywords']:
            if keyword.lower() in title:
                score += rules['weight']
                if category not in matched_categories:
                    matched_categories.append(category)
                category_matched = True
                break
    
    if 'sec' in title and 'CRITICAL' not in matched_categories and 'HIGH' not in matched_categories:
        score += 50
        matched_categories.append('HIGH')
    
    if 'bitcoin' in title or re.search(r'\bbtc\b', title):
        score *= 1.3
    
    if re.search(r'\$\s*[\d,]+\.?\d*\s*[mbk]?|\$\s*[\d,]+|\d+\.?\d*%', title, re.IGNORECASE):
        score *= 1.2
    
    score *= news_item['source_weight']
    
    return round(score), matched_categories


def deduplicate_news(news_list):
    """Удаляем дубликаты по similarity"""
    if not news_list:
        return []
    
    sorted_news = sorted(news_list, key=lambda x: (x['source_priority'], -x['score']))
    
    unique_news = []
    for item in sorted_news:
        is_dup = False
        for unique_item in unique_news:
            similarity = calculate_similarity(item['title'], unique_item['title'])
            if similarity >= 0.3:
                is_dup = True
                break
        
        if not is_dup:
            unique_news.append(item)
    
    return unique_news


def process_image_for_telegram(image_url, source):
    """Обрабатываем картинку: обрезаем watermark для CoinDesk"""
    
    if source.lower() != 'coindesk':
        return image_url
    
    try:
        from PIL import Image
        
        response = requests.get(image_url, timeout=10)
        if response.status_code != 200:
            print(f"  ⚠️ Failed to download image for cropping")
            return image_url
        
        img = Image.open(io.BytesIO(response.content))
        width, height = img.size
        
        crop_pixels = 70
        if height > crop_pixels:
            img_cropped = img.crop((0, 0, width, height - crop_pixels))
            
            output = io.BytesIO()
            img_cropped.save(output, format='JPEG', quality=95)
            output.seek(0)
            
            print(f"  ✓ Cropped CoinDesk watermark (removed {crop_pixels}px)")
            return output
        else:
            print(f"  ⚠️ Image too small to crop")
            return image_url
            
    except ImportError:
        print(f"  ⚠️ Pillow not installed - skipping watermark removal")
        return image_url
    except Exception as e:
        print(f"  ⚠️ Error processing image: {e}")
        return image_url


def get_alpha_take(news_item):
    """Получаем Alpha Take от OpenAI для новости"""
    
    if not OPENAI_AVAILABLE:
        return None
    
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("  ⚠️ OPENAI_API_KEY not found - skipping Alpha Take")
        return None
    
    try:
        client = OpenAI(api_key=api_key)
        
        score = news_item.get('score', 0)
        if score >= 80:
            impact = "HIGH"
        elif score >= 60:
            impact = "MEDIUM"
        else:
            impact = "LOW"
        
        categories = ', '.join(news_item.get('categories', []))
        summary = news_item.get('summary', '')
        
        system_prompt = """You are a crypto market analyst writing for regular investors.

TASK: Analyze the news and provide VALUE-ADDED insight, NOT a summary of the headline.

OUTPUT FORMAT (MANDATORY):
ALPHA_TAKE: [One sentence with NEW INSIGHT not in the headline. Explain the IMPLICATION or CONSEQUENCE. What does this MEAN for investors? Don't repeat facts from the title.]

CONTEXT: [Strength] [Sentiment]
Sentiment options: Neutral | Negative | Positive
Strength options: Low | Medium | Strong
Example: "Strong positive" or "Medium negative"

HASHTAGS: [Exactly 2 short hashtags from this list ONLY: #Bitcoin #BTC #Ethereum #ETH #Crypto #SEC #ETF #DeFi #NFT #Regulation #BlackRock #Fidelity #Grayscale #Coinbase #Binance #Fed #Markets #Breaking #Bullish #Bearish #Altcoins #Trading #Institutional #Adoption]

CRITICAL RULES:
- Alpha Take must ADD VALUE, not summarize the headline
- Never repeat the company name or action from headline
- Focus on: WHY it matters, WHAT happens next, WHO benefits/loses
- Context must be exactly "[Strength] [Sentiment]" - nothing else
- Hashtags: EXACTLY 2 tags, short, from the allowed list only

GOOD Alpha Take examples:
Headline: "BlackRock files for Bitcoin ETF"
BAD: "BlackRock filing for Bitcoin ETF signals institutional interest" (just restates headline)
GOOD: "If approved, this opens the door for pension funds and 401k investments into crypto, potentially bringing billions in new capital."

Headline: "SEC delays ETF decision"
BAD: "The SEC delaying the ETF decision creates uncertainty" (restates)
GOOD: "Historically, delays lead to 5-10% dips as traders exit; buying opportunity often follows within 2 weeks."

Headline: "Bitcoin hits $70,000"
BAD: "Bitcoin reaching $70,000 shows strong momentum" (restates)
GOOD: "Last time BTC broke a major round number, it continued 15-20% higher before consolidating."
"""

        user_prompt = f"""News Title: {news_item['title']}

Summary: {summary if summary else 'No summary available'}

Score: {score} | Impact: {impact}
Categories: {categories}
Source: {news_item['source'].upper()}

Generate Alpha Take, Context, and Hashtags."""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=200,
            temperature=0.3,
            timeout=10.0
        )
        
        content = response.choices[0].message.content.strip()
        
        alpha_take = None
        context = None
        hashtags = None
        
        for line in content.split('\n'):
            line = line.strip()
            if line.startswith('ALPHA_TAKE:'):
                alpha_take = line.replace('ALPHA_TAKE:', '').strip()
            elif line.startswith('CONTEXT:'):
                context = line.replace('CONTEXT:', '').strip()
            elif line.startswith('HASHTAGS:'):
                hashtags = line.replace('HASHTAGS:', '').strip()
        
        if not alpha_take:
            alpha_take = content
        
        if alpha_take and len(alpha_take) > 10:
            print(f"  ✓ Generated Alpha Take: {alpha_take[:50]}...")
            if context:
                print(f"  ✓ Context: {context}")
            if hashtags:
                print(f"  ✓ Hashtags: {hashtags}")
            
            return {
                "alpha_take": alpha_take,
                "context": context,
                "hashtags": hashtags
            }
        else:
            print(f"  ⚠️ Empty Alpha Take received")
            return None
            
    except Exception as e:
        print(f"  ⚠️ OpenAI error: {e}")
        return None


def format_telegram_message(news_item):
    """Форматируем сообщение для Telegram"""
    
    # Единый заголовок для всех новостей
    header = '🚨 BREAKING NEWS'
    
    safe_title = html.escape(news_item['title'])
    safe_summary = html.escape(news_item.get('summary', ''))
    
    if len(safe_title) > 200:
        safe_title = safe_title[:197] + '...'
    
    # Собираем хэштеги (макс 2, только короткие из разрешенного списка)
    hashtags_str = ""
    alpha_take_data = news_item.get('alpha_take_data')
    if alpha_take_data:
        raw_hashtags = alpha_take_data.get('hashtags', '')
        if raw_hashtags:
            # Извлекаем хэштеги
            tags = re.findall(r'#\w+', raw_hashtags)
            # Фильтруем: только короткие (до 15 символов) и из разрешенного списка
            filtered_tags = []
            for tag in tags:
                if len(tag) <= 15 and tag in ALLOWED_HASHTAGS:
                    filtered_tags.append(tag)
                elif len(tag) <= 12:  # Короткие теги допускаем даже не из списка
                    filtered_tags.append(tag)
            # Берем максимум 2
            filtered_tags = filtered_tags[:2]
            if filtered_tags:
                hashtags_str = ' '.join(filtered_tags)
    
    # Формируем сообщение: хэштеги вверху
    message = ""
    if hashtags_str:
        message += f"{hashtags_str}\n\n"
    
    message += f"{header}\n\n"
    message += f"{safe_title}\n\n"
    
    if alpha_take_data:
        alpha_take = alpha_take_data.get('alpha_take')
        context = alpha_take_data.get('context')
        
        if alpha_take:
            message += f"◼️ <b>Alpha Take:</b>\n{html.escape(alpha_take)}\n\n"
        
        if context:
            # Нормализуем context
            context_clean = context.strip()
            # Убираем лишние слова, оставляем только Strength + Sentiment
            context_clean = re.sub(r'[Cc]ontext:?\s*', '', context_clean)
            message += f"<i>Context: {html.escape(context_clean)}</i>"
    
    if len(message) > 1024:
        message = message[:1020]
        last_space = message.rfind(' ')
        if last_space > 900:
            message = message[:last_space] + '...'
    
    return message


def format_twitter_message(news_item):
    """Форматируем tweet"""
    header = '🚨'  # Единый для всех
    
    title = news_item['title']
    
    # Получаем хэштеги
    hashtags_str = ""
    alpha_take_data = news_item.get('alpha_take_data')
    if alpha_take_data:
        raw_hashtags = alpha_take_data.get('hashtags', '')
        if raw_hashtags:
            tags = re.findall(r'#\w+', raw_hashtags)
            # Берем максимум 2 коротких хэштега
            filtered_tags = [tag for tag in tags if len(tag) <= 12][:2]
            if filtered_tags:
                hashtags_str = ' '.join(filtered_tags)
    
    alpha_text = ''
    if alpha_take_data and alpha_take_data.get('alpha_take'):
        alpha = alpha_take_data['alpha_take']
        if len(alpha) <= 100:
            alpha_text = f"\n\n💡 {alpha}"
    
    # Собираем tweet
    if hashtags_str:
        tweet = f"{hashtags_str}\n\n{header} {title}{alpha_text}"
    else:
        tweet = f"{header} {title}{alpha_text}"
    
    if len(tweet) > 280:
        available = 280 - len(header) - len(alpha_text) - len(hashtags_str) - 10
        title = title[:available] + '...'
        if hashtags_str:
            tweet = f"{hashtags_str}\n\n{header} {title}{alpha_text}"
        else:
            tweet = f"{header} {title}{alpha_text}"
    
    return tweet


def publish_to_telegram(news_item):
    """Публикуем в Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        return False
    
    try:
        message = format_telegram_message(news_item)
        image = news_item.get('image_url')
        
        processed_image = None
        if image and isinstance(image, str) and image.strip():
            processed_image = process_image_for_telegram(image, news_item['source'])
        
        # Inline keyboard с кнопкой Subscribe
        reply_markup = {
            "inline_keyboard": [[
                {
                    "text": "⭐ Subscribe",
                    "url": "https://t.me/frogfriends"
                }
            ]]
        }
        
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        
        is_file = isinstance(processed_image, io.BytesIO)
        
        if processed_image:
            if is_file:
                files = {'photo': ('image.jpg', processed_image, 'image/jpeg')}
                data = {
                    'chat_id': TELEGRAM_CHANNEL_ID,
                    'caption': message,
                    'parse_mode': 'HTML',
                    'reply_markup': json.dumps(reply_markup)
                }
                response = requests.post(url, data=data, files=files)
            else:
                payload = {
                    'chat_id': TELEGRAM_CHANNEL_ID,
                    'photo': processed_image,
                    'caption': message,
                    'parse_mode': 'HTML',
                    'reply_markup': reply_markup
                }
                response = requests.post(url, json=payload)
        else:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                'chat_id': TELEGRAM_CHANNEL_ID,
                'text': message,
                'parse_mode': 'HTML',
                'disable_web_page_preview': False,
                'reply_markup': reply_markup
            }
            response = requests.post(url, json=payload)
        
        if response.status_code == 200:
            print(f"✓ Published: {news_item['title'][:60]}...")
            return True
        else:
            print(f"✗ Telegram error: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"✗ Telegram error: {e}")
        return False


def publish_to_twitter(news_item):
    """Публикуем в Twitter"""
    if not all([TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET]):
        return False
    
    try:
        import tweepy
        
        client = tweepy.Client(
            consumer_key=TWITTER_API_KEY,
            consumer_secret=TWITTER_API_SECRET,
            access_token=TWITTER_ACCESS_TOKEN,
            access_token_secret=TWITTER_ACCESS_TOKEN_SECRET
        )
        
        tweet = format_twitter_message(news_item)
        
        response = client.create_tweet(text=tweet)
        
        if response.data:
            print(f"✓ Tweeted: {news_item['title'][:60]}...")
            return True
        else:
            print(f"✗ Twitter error: No response data")
            return False
            
    except ImportError:
        print("⚠️ Tweepy not installed - skipping Twitter")
        return False
    except Exception as e:
        print(f"✗ Twitter error: {e}")
        return False


def main():
    print("=" * 60)
    print("🤖 Crypto News Bot - Starting...")
    print("=" * 60)
    
    all_news = fetch_all_news()
    published = load_published_news()
    published = cleanup_old_news(published)
    
    print(f"Already published (last 7 days): {len(published)}")
    
    new_news = []
    for item in all_news:
        if not is_duplicate(item, published):
            new_news.append(item)
        else:
            print(f"  ⚠ Already published ({'similar title' if not item.get('link') else 'link'}): {item['title'][:60]}...")
    
    print(f"New news items: {len(new_news)}")
    
    print("\n🎯 Calculating importance scores...")
    scored_news = []
    stock_sources = ['marketwatch', 'yahoo_finance', 'reuters']
    
    for item in new_news:
        score, categories = calculate_importance(item)
        
        threshold = MIN_IMPORTANCE_SCORE
        if item['source'] in stock_sources:
            threshold = STOCK_MARKET_THRESHOLD
        
        if score >= threshold:
            item['score'] = score
            item['categories'] = categories
            scored_news.append(item)
    
    print(f"News above threshold: {len(scored_news)}")
    
    final_news = deduplicate_news(scored_news)
    print(f"After deduplication: {len(final_news)}")
    
    if not final_news:
        print("💤 No important news found")
        print("=" * 60)
        return
    
    final_news.sort(key=lambda x: x['score'], reverse=True)
    top_news = final_news[:5]
    
    print(f"\n📢 Publishing top {len(top_news)} news items:")
    for i, item in enumerate(top_news, 1):
        print(f"{i}. [{item['score']}] {item['title']}")
        if item.get('summary'):
            print(f"   Summary: {item['summary'][:50]}...")
    
    print("\n🤖 Generating Alpha Takes with OpenAI...")
    for item in top_news:
        alpha_take_data = get_alpha_take(item)
        if alpha_take_data:
            item['alpha_take_data'] = alpha_take_data
    
    telegram_count = 0
    twitter_count = 0
    
    for item in top_news:
        if publish_to_telegram(item):
            telegram_count += 1
        
        if TWITTER_ENABLED and publish_to_twitter(item):
            twitter_count += 1
        
        published.append({
            'title': item['title'],
            'link': item.get('link', ''),
            'published_date': datetime.now().isoformat()
        })
    
    save_published_news(published)
    
    print(f"\n✅ Published: {telegram_count} to Telegram, {twitter_count} to Twitter")
    print("=" * 60)


if __name__ == '__main__':
    main()
