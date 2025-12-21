"""Парсер крипто новостей с умной фильтрацией"""

import feedparser
import requests
from datetime import datetime, timedelta
import json
import os
import re
import html
import io
from html.parser import HTMLParser
from news_config import IMPORTANCE_RULES, EXCLUDE_KEYWORDS, MIN_IMPORTANCE_SCORE, RSS_SOURCES, SOURCE_PRIORITY, STOCK_MARKET_THRESHOLD, PUBLISHED_SIMILARITY_THRESHOLD, BATCH_SIMILARITY_THRESHOLD

# OpenAI Integration
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print("⚠️ OpenAI not available - Alpha Take will be skipped")


# HTML Stripper для очистки summary от тегов
class MLStripper(HTMLParser):
    """Удаляет HTML теги из текста"""
    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = []
    
    def handle_data(self, d):
        self.text.append(d)
    
    def get_data(self):
        return ''.join(self.text)
    
    def clear(self):
        self.text = []


def parse_all_feeds():
    """Парсим все RSS источники"""
    all_news = []
    
    for source_name, config in RSS_SOURCES.items():
        try:
            # Парсим RSS (feedparser не поддерживает timeout аргумент)
            feed = feedparser.parse(config['url'])
            
            # Проверяем что feed валидный
            if hasattr(feed, 'bozo') and feed.bozo and not feed.entries:
                print(f"✗ {source_name}: Invalid RSS feed")
                continue
                
            print(f"✓ Parsed {source_name}: {len(feed.entries)} entries")
            
            for entry in feed.entries[:10]:  # Последние 10 из каждого источника
                try:
                    # Парсим время с проверкой
                    if not hasattr(entry, 'published_parsed') or entry.published_parsed is None:
                        # Используем текущее время если нет метки времени
                        published = datetime.now()
                    else:
                        published = datetime(*entry.published_parsed[:6])
                    
                    # Пропускаем старые новости (>12 часов)
                    if datetime.now() - published > timedelta(hours=12):
                        continue
                    
                    # Проверяем обязательные поля
                    if not hasattr(entry, 'title') or not hasattr(entry, 'link'):
                        continue
                    
                    # Проверяем что title не пустой
                    if not entry.title or not entry.title.strip():
                        continue
                    
                    # Извлекаем summary (первый абзац)
                    summary = ''
                    
                    # Пробуем разные источники summary
                    if hasattr(entry, 'summary') and entry.summary:
                        summary = entry.summary
                    elif hasattr(entry, 'description') and entry.description:
                        summary = entry.description
                    elif hasattr(entry, 'content') and entry.content:
                        # Пробуем извлечь из content
                        if isinstance(entry.content, list) and entry.content:
                            if isinstance(entry.content[0], dict):
                                summary = entry.content[0].get('value', '')
                    elif hasattr(entry, 'subtitle') and entry.subtitle:
                        summary = entry.subtitle
                    
                    # Очищаем HTML теги из summary
                    if summary:
                        try:
                            # Используем глобальный stripper
                            stripper = MLStripper()
                            stripper.feed(summary)
                            summary = stripper.get_data().strip()
                        except Exception as e:
                            # Fallback - простое удаление тегов regex
                            summary = re.sub(r'<[^>]+>', '', summary).strip()
                        
                        # Нормализуем переносы строк
                        summary = re.sub(r'\n+', ' ', summary)
                        summary = re.sub(r'\s+', ' ', summary)
                        
                        # Обрезаем до первых предложений (убрали минимум 150 символов)
                        if '. ' in summary:
                            # Берем первые 2 предложения
                            sentences = summary.split('. ')
                            if len(sentences) >= 2:
                                summary = '. '.join(sentences[:2]) + '.'
                            elif sentences and sentences[0]:
                                summary = sentences[0]
                                if not summary.endswith('.'):
                                    summary += '...'
                        
                        # Ограничиваем длину
                        if len(summary) > 300:
                            summary = summary[:297] + '...'
                        
                        # Если summary слишком короткий (< 20 символов) - игнорируем
                        if len(summary) < 20:
                            summary = ''
                    
                    # Извлекаем URL картинки
                    image_url = None
                    
                    # Вариант 1: media_content (CoinDesk, The Block)
                    if (hasattr(entry, 'media_content') and 
                        isinstance(entry.media_content, list) and 
                        entry.media_content and
                        isinstance(entry.media_content[0], dict)):
                        image_url = entry.media_content[0].get('url')
                    
                    # Вариант 2: media_thumbnail
                    if (not image_url and 
                        hasattr(entry, 'media_thumbnail') and 
                        isinstance(entry.media_thumbnail, list) and
                        entry.media_thumbnail and
                        isinstance(entry.media_thumbnail[0], dict)):
                        image_url = entry.media_thumbnail[0].get('url')
                    
                    # Вариант 3: enclosure
                    if not image_url and hasattr(entry, 'enclosures') and isinstance(entry.enclosures, list):
                        for enclosure in entry.enclosures:
                            if isinstance(enclosure, dict) and enclosure.get('type', '').startswith('image/'):
                                image_url = enclosure.get('href')
                                break
                    
                    # Вариант 4: парсим из content/summary HTML
                    if not image_url and hasattr(entry, 'content') and isinstance(entry.content, list):
                        try:
                            content_html = entry.content[0].get('value', '') if isinstance(entry.content[0], dict) else ''
                            # Более гибкий regex - ловит single и double quotes
                            img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', content_html, re.IGNORECASE)
                            if img_match:
                                image_url = img_match.group(1)
                        except (IndexError, AttributeError, TypeError):
                            pass
                    
                    # Валидация URL - только http/https
                    if image_url:
                        image_url = image_url.strip()
                        if not (image_url.startswith('http://') or image_url.startswith('https://')):
                            image_url = None
                    
                    all_news.append({
                        'title': entry.title.strip(),
                        'link': entry.link,
                        'summary': summary,
                        'image_url': image_url,
                        'published': published.isoformat(),
                        'source': source_name,
                        'source_weight': config['weight_multiplier']
                    })
                except Exception as e:
                    print(f"  ⚠ Skipping entry from {source_name}: {e}")
                    continue
                    
        except Exception as e:
            print(f"✗ Error parsing {source_name}: {e}")
    
    return all_news


def calculate_importance(news_item):
    """Рассчитываем важность новости"""
    title = news_item['title'].lower()
    score = 0
    matched_categories = []
    
    # Проверяем исключения
    for exclude in EXCLUDE_KEYWORDS:
        if exclude in title:
            return 0, ['EXCLUDED']
    
    # Считаем баллы по категориям
    for category, rules in IMPORTANCE_RULES.items():
        category_matched = False
        for keyword in rules['keywords']:
            if keyword.lower() in title:
                score += rules['weight']
                if category not in matched_categories:
                    matched_categories.append(category)
                category_matched = True
                break  # Одно совпадение на категорию
    
    # Дополнительная проверка для SEC (может быть в разных формах)
    if 'sec' in title and 'CRITICAL' not in matched_categories and 'HIGH' not in matched_categories:
        score += 50
        matched_categories.append('HIGH')
    
    # Бонус за упоминание Bitcoin
    if 'bitcoin' in title or re.search(r'\bbtc\b', title):
        score *= 1.3
    
    # Бонус за цифры (конкретика) - улучшенный regex
    # Ловит: $100M, $1.5B, 50%, $100 million, $1,234,567
    if re.search(r'\$\s*[\d,]+\.?\d*\s*[mbk]?|\$\s*[\d,]+|\d+\.?\d*%', title, re.IGNORECASE):
        score *= 1.2
    
    # Применяем вес источника
    score *= news_item['source_weight']
    
    return round(score), matched_categories


def titles_are_similar(title1, title2, threshold=0.5):
    """Проверяем схожесть заголовков по перекрытию слов (Jaccard similarity)"""
    # Извлекаем слова
    words1 = set(re.sub(r'[^\w\s]', '', title1.lower()).split())
    words2 = set(re.sub(r'[^\w\s]', '', title2.lower()).split())
    
    # Убираем короткие и стоп-слова
    stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'as', 'is'}
    words1 = {w for w in words1 if len(w) > 2 and w not in stop_words}
    words2 = {w for w in words2 if len(w) > 2 and w not in stop_words}
    
    if not words1 or not words2:
        return False
    
    # Считаем перекрытие (Jaccard similarity)
    intersection = len(words1 & words2)
    union = len(words1 | words2)
    similarity = intersection / union if union > 0 else 0
    
    return similarity >= threshold


def filter_duplicates(news_items):
    """Убираем дубликаты по схожести заголовков с учетом приоритета источников"""
    unique_news = []
    
    for item in news_items:
        duplicate_index = -1
        
        # Сравниваем с уже добавленными новостями (средний порог)
        for i, existing in enumerate(unique_news):
            if titles_are_similar(item['title'], existing['title'], BATCH_SIMILARITY_THRESHOLD):
                duplicate_index = i
                break
        
        if duplicate_index >= 0:
            # Нашли дубликат - проверяем приоритет источника
            existing = unique_news[duplicate_index]
            item_priority = SOURCE_PRIORITY.get(item['source'], 999)
            existing_priority = SOURCE_PRIORITY.get(existing['source'], 999)
            
            if item_priority < existing_priority:
                # Новый источник приоритетнее - заменяем
                print(f"  ⚠ Duplicate: replacing {existing['source']} with {item['source']}: {item['title'][:50]}...")
                unique_news[duplicate_index] = item
            else:
                # Существующий приоритетнее - оставляем как есть
                print(f"  ⚠ Duplicate: keeping {existing['source']} over {item['source']}: {item['title'][:50]}...")
        else:
            # Не дубликат - добавляем
            unique_news.append(item)
    
    return unique_news


def filter_already_published(news_items, published):
    """Фильтруем новости похожие на уже опубликованные (по заголовкам)"""
    filtered_news = []
    
    # Извлекаем заголовки опубликованных новостей (только непустые)
    published_titles = []
    published_links = set(published.keys())  # Все ссылки (быстрая проверка)
    
    for link, data in published.items():
        if isinstance(data, dict) and data.get('title'):
            published_titles.append(data['title'])
    
    for item in news_items:
        # Проверка 1: По ссылке (быстро)
        if item['link'] in published_links:
            print(f"  ⚠ Already published (link): {item['title'][:50]}...")
            continue
        
        # Проверка 2: По заголовку (строгий порог - ловим все похожие)
        is_duplicate = False
        for pub_title in published_titles:
            if titles_are_similar(item['title'], pub_title, PUBLISHED_SIMILARITY_THRESHOLD):
                print(f"  ⚠ Already published (similar title): {item['title'][:50]}...")
                is_duplicate = True
                break
        
        if not is_duplicate:
            filtered_news.append(item)
    
    return filtered_news


def load_published():
    """Загружаем уже опубликованные новости с заголовками"""
    try:
        if os.path.exists('published_news.json'):
            with open('published_news.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                print(f"✓ Loaded {len(data)} items from published_news.json")
                
                # Очищаем старые (>7 дней) И записи с пустым title
                week_ago = datetime.now() - timedelta(days=7)
                cleaned_data = {}
                removed_empty_titles = 0
                
                for k, v in data.items():
                    try:
                        # Новый формат: {link: {timestamp, title}}
                        if isinstance(v, dict):
                            # Удаляем записи с пустым title (не можем проверить похожесть)
                            if not v.get('title') or not v.get('title').strip():
                                removed_empty_titles += 1
                                continue
                                
                            published_date = datetime.fromisoformat(v.get('timestamp', '').replace('Z', '+00:00'))
                            if published_date > week_ago:
                                cleaned_data[k] = v
                        # Старый формат: {link: timestamp} - удаляем (нет title)
                        else:
                            removed_empty_titles += 1
                            continue
                    except (ValueError, AttributeError) as e:
                        # Если не можем распарсить, пропускаем
                        continue
                
                print(f"✓ After cleanup: {len(cleaned_data)} items (removed {len(data) - len(cleaned_data)} old, {removed_empty_titles} without titles)")
                return cleaned_data
        else:
            print("ℹ️ published_news.json not found - starting fresh")
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"⚠ Warning loading published news: {e}")
    
    return {}


def save_published(published):
    """Сохраняем опубликованные новости"""
    try:
        with open('published_news.json', 'w', encoding='utf-8') as f:
            json.dump(published, f, indent=2, ensure_ascii=False)
        print(f"✓ Saved {len(published)} published items to published_news.json")
    except Exception as e:
        print(f"✗ Error saving published news: {e}")


def process_image_for_telegram(image_url, source):
    """Обрабатывает картинку: обрезает watermark для CoinDesk"""
    
    # Только для CoinDesk обрезаем watermark
    if source.lower() != 'coindesk':
        return image_url  # Возвращаем URL как есть
    
    try:
        from PIL import Image
        
        # Скачиваем картинку
        response = requests.get(image_url, timeout=10)
        if response.status_code != 200:
            print(f"  ⚠️ Failed to download image for cropping")
            return image_url
        
        # Открываем картинку
        img = Image.open(io.BytesIO(response.content))
        width, height = img.size
        
        # Обрезаем 70px снизу (watermark + немного больше чтобы полностью скрыть логотип)
        crop_pixels = 70
        if height > crop_pixels:
            img_cropped = img.crop((0, 0, width, height - crop_pixels))
            
            # Сохраняем в BytesIO
            output = io.BytesIO()
            img_cropped.save(output, format='JPEG', quality=95)
            output.seek(0)
            
            print(f"  ✓ Cropped CoinDesk watermark (removed {crop_pixels}px)")
            return output  # Возвращаем файл объект
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
        
        # Определяем Impact Label
        score = news_item.get('score', 0)
        if score >= 80:
            impact = "HIGH"
        elif score >= 60:
            impact = "MEDIUM"
        else:
            impact = "LOW"
        
        # Формируем промпт
        categories = ', '.join(news_item.get('categories', []))
        summary = news_item.get('summary', '')
        
        system_prompt = """🔥 MASTER PROMPT — MARKET ALERT (Breaking / Urgent News)

ROLE
You are a real-time crypto market alert system for professional investors.
Your task is to surface time-sensitive crypto news and extract high-signal, emotionally neutral market intelligence.
You prioritize speed, clarity, and relevance, not depth.
You do not:
* give trading advice
* issue price targets
* speculate beyond observable implications
Audience: US-based, market-literate crypto investors.

WHEN TO USE MARKET ALERT
Use this format only if at least ONE condition is met:
• Breaking or urgent news (regulation, ETFs, macro, major institutions)
• Unexpected deviation from market consensus
• Potential short-term impact on positioning, liquidity, volatility, or narratives
• Credible, widely cited source (CoinDesk, Bloomberg, WSJ, official filings)
If not urgent → use the standard Alpha Take format.

SCORING SYSTEM (FOR REFERENCE ONLY - DO NOT OUTPUT)
📊 Score (0–100) Represents potential market relevance, not price impact.
• 80–100 → Systemic / market-wide relevance
• 60–79 → Major narrative or positioning impact
• 40–59 → Sector-specific or temporary relevance
• <40 → Informational only (generally avoid alerts)

🏷 Impact Label (choose ONE):
• HIGH — broad attention, positioning sensitivity
• MEDIUM — narrative or sector impact
• LOW — informational, limited spillover

ALPHA TAKE — ALERT EDITION (OUTPUT THIS)
Use only if the implication is obvious and time-sensitive.

STRICT RULES
• Exactly ONE sentence
• MUST NOT repeat or paraphrase the headline
• MUST NOT restate facts already shown above
• MUST place the event in the broader market / news context
• Focus only on second-order effects:
  * positioning behavior
  * liquidity sensitivity
  * risk appetite shifts
  * narrative reinforcement or disruption

❌ No predictions
❌ No bullish / bearish language
❌ No calls to action
❌ No generic phrasing ("adds uncertainty", "could impact markets")

Good structural framing examples:
"This shifts positioning incentives toward…"
"Against the current macro/liquidity backdrop, this reinforces…"
"In a market already focused on X, this increases sensitivity to…"

STYLE RULES (STRICT)
❌ No emojis
❌ No hashtags in the output
❌ No opinionated language
❌ No price targets
❌ No speculation
❌ No strategy or execution language

QUALITY FILTER (BEFORE PUBLISHING)
Ask internally:
• Is this time-sensitive right now?
• Does this add context, not noise?
• Would a hedge fund analyst care immediately?
If yes → publish
If no → downgrade to standard post

Return ONLY the Alpha Take text (ONE sentence), nothing else."""

        user_prompt = f"""News Title: {news_item['title']}

Summary: {summary if summary else 'No summary available'}

Score: {score} | Impact: {impact}
Categories: {categories}
Source: {news_item['source'].upper()}

Generate a concise Alpha Take (EXACTLY ONE SENTENCE) explaining the broader market context and second-order effects."""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=150,  # Increased for institutional analysis
            temperature=0.3,
            timeout=10.0  # 10 second timeout
        )
        
        alpha_take = response.choices[0].message.content.strip()
        
        if alpha_take and len(alpha_take) > 10:
            print(f"  ✓ Generated Alpha Take: {alpha_take[:50]}...")
            return alpha_take
        else:
            print(f"  ⚠️ Empty Alpha Take received")
            return None
            
    except Exception as e:
        print(f"  ⚠️ OpenAI error: {e}")
        return None


def format_telegram_message(news_item):
    """Форматируем сообщение для Telegram"""
    
    # Динамические headers по категориям
    header_map = {
        'CRITICAL': '🚨 BREAKING NEWS',
        'HIGH': '🔥 MARKET ALERT',
        'MARKET_MOVE': '📈 PRICE ALERT',
        'MEDIUM': '📰 CRYPTO UPDATE'
    }
    
    # Выбираем header
    main_category = news_item['categories'][0] if news_item['categories'] else 'MEDIUM'
    header = header_map.get(main_category, '📰 CRYPTO UPDATE')
    
    # Экранируем HTML символы в заголовке и summary
    safe_title = html.escape(news_item['title'])
    safe_summary = html.escape(news_item.get('summary', ''))
    
    # Обрезаем длинный заголовок если нужно
    if len(safe_title) > 200:
        safe_title = safe_title[:197] + '...'
    
    # Формируем сообщение
    message = f"{header}\n\n"
    message += f"{safe_title}\n\n"
    
    # Добавляем summary если есть
    if safe_summary:
        message += f"{safe_summary}\n\n"
    
    # Убрали Score и Source - это внутренняя информация
    
    # Добавляем Alpha Take только если есть место
    alpha_take = news_item.get('alpha_take')
    if alpha_take:
        alpha_section = f"💡 <b>Alpha Take:</b>\n{html.escape(alpha_take)}"
        
        # Проверяем что Alpha Take полностью поместится
        if len(message) + len(alpha_section) <= 1024:
            message += alpha_section
        else:
            # Не хватает места - пропускаем Alpha Take
            print(f"  ⚠️ Alpha Take too long for Telegram (message would be {len(message) + len(alpha_section)} chars)")
    
    # Финальная проверка длины (для caption лимит 1024 символа)
    # Это на случай если summary слишком длинный
    if len(message) > 1024:
        # Обрезаем по последнему пробелу чтобы не резать слово
        message = message[:1020]
        last_space = message.rfind(' ')
        if last_space > 950:  # Не обрезаем слишком много
            message = message[:last_space] + '...'
        else:
            message = message + '...'
    
    return message


def format_twitter_message(news_item):
    """Форматируем сообщение для Twitter (280 char limit)"""
    
    # Динамические headers
    header_map = {
        'CRITICAL': '🚨 BREAKING',
        'HIGH': '🔥 ALERT',
        'MARKET_MOVE': '📈 MARKET',
        'MEDIUM': '📰 NEWS'
    }
    
    main_category = news_item['categories'][0] if news_item['categories'] else 'MEDIUM'
    header = header_map.get(main_category, '📰 NEWS')
    
    title = news_item['title']
    alpha_take = news_item.get('alpha_take')
    
    # Twitter limit: 280 chars (NO link in text, only image)
    base_length = len(header) + 5  # header + spacing
    
    # Try to fit: Header + Title + Alpha Take (NO link)
    if alpha_take:
        alpha_text = f"\n\n💡 {alpha_take}"
        available_for_title = 280 - base_length - len(alpha_text)
        
        if available_for_title > 50:  # Enough space for meaningful title
            if len(title) > available_for_title:
                title = title[:available_for_title-3] + '...'
            tweet = f"{header}\n\n{title}{alpha_text}"
        else:
            # Not enough space - skip Alpha Take
            available_for_title = 280 - base_length
            if len(title) > available_for_title:
                title = title[:available_for_title-3] + '...'
            tweet = f"{header}\n\n{title}"
    else:
        # No Alpha Take - just title
        available_for_title = 280 - base_length
        if len(title) > available_for_title:
            title = title[:available_for_title-3] + '...'
        tweet = f"{header}\n\n{title}"
    
    return tweet


def send_to_telegram(news_items):
    """Публикуем в Telegram"""
    import time
    
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    channel_id = os.getenv('TELEGRAM_CHANNEL_ID')
    
    if not bot_token or not channel_id:
        print("❌ Telegram credentials not found")
        return []
    
    published_links = []
    
    for i, item in enumerate(news_items):
        # Rate limiting: пауза между сообщениями
        if i > 0:
            time.sleep(1)  # 1 секунда между сообщениями
        
        caption = format_telegram_message(item)
        image_url = item.get('image_url')
        
        # Валидация image_url
        if image_url:
            image_url = image_url.strip()
            # Проверяем что это валидный URL
            if not image_url or not (image_url.startswith('http://') or image_url.startswith('https://')):
                image_url = None
        
        # Обрабатываем картинку (обрезаем watermark для CoinDesk)
        processed_image = None
        if image_url:
            processed_image = process_image_for_telegram(image_url, item['source'])
        
        try:
            # Определяем тип отправки
            is_file = isinstance(processed_image, io.BytesIO)
            
            # Если есть картинка - отправляем через sendPhoto
            if processed_image:
                url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
                
                if is_file:
                    # Отправляем как файл (обрезанная картинка CoinDesk)
                    files = {'photo': ('image.jpg', processed_image, 'image/jpeg')}
                    data = {
                        'chat_id': channel_id,
                        'caption': caption,
                        'parse_mode': 'HTML'
                    }
                    response = requests.post(url, data=data, files=files, timeout=30)
                else:
                    # Отправляем как URL (необработанная картинка)
                    payload = {
                        'chat_id': channel_id,
                        'photo': processed_image,
                        'caption': caption,
                        'parse_mode': 'HTML'
                    }
                    response = requests.post(url, json=payload, timeout=10)
            else:
                # Если нет картинки - обычное текстовое сообщение
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                payload = {
                    'chat_id': channel_id,
                    'text': caption,
                    'parse_mode': 'HTML',
                    'disable_web_page_preview': True
                }
                response = requests.post(url, json=payload, timeout=10)
            
            if response.status_code == 200:
                published_links.append(item['link'])
                print(f"✓ Published: {item['title'][:50]}...")
            elif response.status_code == 429:
                # Too Many Requests - ждем и пробуем еще раз
                try:
                    retry_after = int(response.json().get('parameters', {}).get('retry_after', 60))
                except (ValueError, json.JSONDecodeError):
                    retry_after = 60  # Fallback если не можем распарсить
                print(f"⚠ Rate limited, waiting {retry_after} seconds...")
                time.sleep(retry_after)
                
                # Повторная попытка с правильным методом
                if is_file:
                    # Сбрасываем позицию в файле для повторной отправки
                    processed_image.seek(0)
                    files = {'photo': ('image.jpg', processed_image, 'image/jpeg')}
                    response = requests.post(url, data=data, files=files, timeout=30)
                else:
                    response = requests.post(url, json=payload, timeout=10)
                
                if response.status_code == 200:
                    published_links.append(item['link'])
                    print(f"✓ Published (retry): {item['title'][:50]}...")
                else:
                    print(f"✗ Failed after retry: {response.text}")
            elif response.status_code == 400 and processed_image:
                # Проверяем что ошибка связана с картинкой
                error_text = response.text.lower()
                if any(word in error_text for word in ['photo', 'image', 'media', 'file']):
                    # Точно проблема с картинкой - пробуем без неё
                    print(f"⚠ Image failed, retrying without image...")
                    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                    payload = {
                        'chat_id': channel_id,
                        'text': caption,
                        'parse_mode': 'HTML',
                        'disable_web_page_preview': True
                    }
                    response = requests.post(url, json=payload, timeout=10)
                    if response.status_code == 200:
                        published_links.append(item['link'])
                        print(f"✓ Published (without image): {item['title'][:50]}...")
                    else:
                        print(f"✗ Failed: {response.text[:100]}")
                else:
                    # Ошибка не связана с картинкой
                    print(f"✗ Failed to publish (status 400): {response.text[:100]}")
            else:
                print(f"✗ Failed to publish (status {response.status_code}): {response.text[:100]}")
                
        except requests.exceptions.Timeout:
            print(f"✗ Timeout sending to Telegram: {item['title'][:50]}...")
        except requests.exceptions.RequestException as e:
            print(f"✗ Error sending to Telegram: {e}")
        except Exception as e:
            print(f"✗ Unexpected error: {e}")
    
    return published_links


def send_to_twitter(news_items):
    """Публикуем в Twitter"""
    import time
    from news_config import TWITTER_ENABLED
    
    if not TWITTER_ENABLED:
        print("ℹ️ Twitter disabled")
        return []
    
    # Получаем credentials
    api_key = os.getenv('TWITTER_API_KEY')
    api_secret = os.getenv('TWITTER_API_SECRET')
    access_token = os.getenv('TWITTER_ACCESS_TOKEN')
    access_token_secret = os.getenv('TWITTER_ACCESS_TOKEN_SECRET')
    
    if not all([api_key, api_secret, access_token, access_token_secret]):
        print("❌ Twitter credentials not found")
        return []
    
    try:
        import tweepy
        
        # Authenticate
        auth = tweepy.OAuth1UserHandler(
            api_key, api_secret,
            access_token, access_token_secret
        )
        api = tweepy.API(auth)
        client = tweepy.Client(
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_token_secret
        )
        
    except ImportError:
        print("❌ Tweepy not installed")
        return []
    except Exception as e:
        print(f"❌ Twitter auth failed: {e}")
        return []
    
    published_links = []
    
    for i, item in enumerate(news_items):
        # Rate limiting
        if i > 0:
            time.sleep(2)
        
        tweet_text = format_twitter_message(item)
        image_url = item.get('image_url')
        
        try:
            media_id = None
            
            # Upload image if available
            if image_url:
                try:
                    # Download image
                    img_response = requests.get(image_url, timeout=10)
                    if img_response.status_code == 200:
                        # Upload to Twitter
                        import tempfile
                        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
                            tmp.write(img_response.content)
                            tmp_path = tmp.name
                        
                        media = api.media_upload(tmp_path)
                        media_id = media.media_id
                        
                        # Cleanup
                        os.unlink(tmp_path)
                except Exception as e:
                    print(f"⚠ Twitter image upload failed: {e}")
            
            # Post tweet
            if media_id:
                response = client.create_tweet(text=tweet_text, media_ids=[media_id])
            else:
                response = client.create_tweet(text=tweet_text)
            
            if response.data:
                published_links.append(item['link'])
                print(f"✓ Tweeted: {item['title'][:50]}...")
            else:
                print(f"✗ Twitter post failed")
                
        except tweepy.TweepyException as e:
            print(f"✗ Twitter error: {e}")
        except Exception as e:
            print(f"✗ Unexpected Twitter error: {e}")
    
    return published_links


def main():
    print("=" * 60)
    print("🤖 Crypto News Bot - Starting...")
    print("=" * 60)
    
    # 1. Парсим источники
    print("\n📡 Fetching news from sources...")
    all_news = parse_all_feeds()
    print(f"Total news fetched: {len(all_news)}")
    
    # КРИТИЧНО: Если все источники упали - выходим с предупреждением
    if len(all_news) == 0:
        print("\n⚠️ WARNING: No news fetched from any source!")
        print("This could indicate:")
        print("  - All RSS sources are down")
        print("  - Network connectivity issues")
        print("  - All news are older than 12 hours")
        print("\nSkipping this run. Will try again on next schedule.")
        return  # Выходим без ошибки чтобы не ломать workflow
    
    # 2. Загружаем уже опубликованные
    published = load_published()
    print(f"Already published (last 7 days): {len(published)}")
    
    # 3. Фильтруем уже опубликованные (по ссылке И по заголовку)
    new_news = filter_already_published(all_news, published)
    print(f"New news items: {len(new_news)}")
    
    # 4. Рассчитываем важность
    print("\n🎯 Calculating importance scores...")
    scored_news = []
    stock_sources = ['marketwatch', 'yahoo_finance', 'reuters']
    
    for item in new_news:
        score, categories = calculate_importance(item)
        
        # Применяем разные пороги для разных источников
        threshold = MIN_IMPORTANCE_SCORE
        if item['source'] in stock_sources:
            threshold = STOCK_MARKET_THRESHOLD  # Выше порог для stock news
        
        if score >= threshold:
            item['score'] = score
            item['categories'] = categories
            scored_news.append(item)
    
    print(f"News above threshold: {len(scored_news)}")
    
    # 5. Убираем дубликаты
    unique_news = filter_duplicates(scored_news)
    print(f"After deduplication: {len(unique_news)}")
    
    # 6. Сортируем по важности
    unique_news.sort(key=lambda x: x['score'], reverse=True)
    
    # 7. Берем топ-3
    top_news = unique_news[:3]
    
    if top_news:
        print(f"\n📢 Publishing top {len(top_news)} news items:")
        for i, item in enumerate(top_news, 1):
            summary_preview = item.get('summary', '')[:50] if item.get('summary') else 'NO SUMMARY'
            print(f"{i}. [{item['score']}] {item['title']}")
            print(f"   Summary: {summary_preview}{'...' if len(item.get('summary', '')) > 50 else ''}")
        
        # 7.5 Генерируем Alpha Take для каждой новости
        print(f"\n🤖 Generating Alpha Takes with OpenAI...")
        for item in top_news:
            alpha_take = get_alpha_take(item)
            if alpha_take:
                item['alpha_take'] = alpha_take
        
        # 8. Публикуем в Telegram и Twitter
        telegram_links = send_to_telegram(top_news)
        twitter_links = send_to_twitter(top_news)
        
        # Объединяем успешно опубликованные ссылки
        published_links = list(set(telegram_links + twitter_links))
        
        # 9. Сохраняем опубликованные ТОЛЬКО если что-то успешно опубликовалось
        if published_links:
            for link in published_links:
                # Находим соответствующую новость для получения заголовка
                news_item = next((item for item in top_news if item['link'] == link), None)
                published[link] = {
                    'timestamp': datetime.now().isoformat(),
                    'title': news_item['title'] if news_item else ''
                }
            save_published(published)
            print(f"\n✅ Published: {len(telegram_links)} to Telegram, {len(twitter_links)} to Twitter")
        else:
            print(f"\n⚠ No news items were successfully published")
    else:
        print("\n💤 No important news found")
    
    print("=" * 60)


if __name__ == '__main__':
    main()
