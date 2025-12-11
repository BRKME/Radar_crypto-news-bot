"""Парсер крипто новостей с умной фильтрацией"""

import feedparser
import requests
from datetime import datetime, timedelta
import json
import os
import re
import html
from html.parser import HTMLParser
from news_config import IMPORTANCE_RULES, EXCLUDE_KEYWORDS, MIN_IMPORTANCE_SCORE, RSS_SOURCES, SIMILARITY_THRESHOLD, SOURCE_PRIORITY


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


def titles_are_similar(title1, title2):
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
    
    return similarity >= SIMILARITY_THRESHOLD


def filter_duplicates(news_items):
    """Убираем дубликаты по схожести заголовков с учетом приоритета источников"""
    unique_news = []
    
    for item in news_items:
        duplicate_index = -1
        
        # Сравниваем с уже добавленными новостями
        for i, existing in enumerate(unique_news):
            if titles_are_similar(item['title'], existing['title']):
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


def load_published():
    """Загружаем уже опубликованные новости"""
    try:
        if os.path.exists('published_news.json'):
            with open('published_news.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Очищаем старые (>7 дней)
                week_ago = datetime.now() - timedelta(days=7)
                cleaned_data = {}
                for k, v in data.items():
                    try:
                        # Парсим ISO формат
                        published_date = datetime.fromisoformat(v.replace('Z', '+00:00'))
                        if published_date > week_ago:
                            cleaned_data[k] = v
                    except (ValueError, AttributeError):
                        # Если не можем распарсить, оставляем (лучше дубликат чем потеря)
                        cleaned_data[k] = v
                return cleaned_data
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"⚠ Warning loading published news: {e}")
    
    return {}


def save_published(published):
    """Сохраняем опубликованные новости"""
    try:
        with open('published_news.json', 'w', encoding='utf-8') as f:
            json.dump(published, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"✗ Error saving published news: {e}")


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
    message += f"<b>{safe_title}</b>\n\n"
    
    # Добавляем summary если есть
    if safe_summary:
        message += f"{safe_summary}\n\n"
    
    message += f"📊 Score: {news_item['score']} | 🏷 {', '.join(news_item['categories'])}\n"
    message += f"📅 {news_item['source'].upper()}"
    
    # Финальная проверка длины (для caption лимит 1024 символа)
    if len(message) > 1024:
        # Обрезаем по последнему пробелу чтобы не резать слово
        message = message[:1020]
        last_space = message.rfind(' ')
        if last_space > 950:  # Не обрезаем слишком много
            message = message[:last_space] + '...'
        else:
            message = message + '...'
    
    return message


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
        
        try:
            # Если есть картинка - отправляем через sendPhoto
            if image_url:
                url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
                payload = {
                    'chat_id': channel_id,
                    'photo': image_url,
                    'caption': caption,
                    'parse_mode': 'HTML'
                }
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
                # Повторная попытка
                response = requests.post(url, json=payload, timeout=10)
                if response.status_code == 200:
                    published_links.append(item['link'])
                    print(f"✓ Published (retry): {item['title'][:50]}...")
                else:
                    print(f"✗ Failed after retry: {response.text}")
            elif response.status_code == 400 and image_url:
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
    
    # 3. Фильтруем уже опубликованные
    new_news = [item for item in all_news if item['link'] not in published]
    print(f"New news items: {len(new_news)}")
    
    # 4. Рассчитываем важность
    print("\n🎯 Calculating importance scores...")
    scored_news = []
    for item in new_news:
        score, categories = calculate_importance(item)
        if score >= MIN_IMPORTANCE_SCORE:
            item['score'] = score
            item['categories'] = categories
            scored_news.append(item)
    
    print(f"News above threshold ({MIN_IMPORTANCE_SCORE}): {len(scored_news)}")
    
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
        
        # 8. Публикуем
        published_links = send_to_telegram(top_news)
        
        # 9. Сохраняем опубликованные ТОЛЬКО если что-то успешно опубликовалось
        if published_links:
            for link in published_links:
                published[link] = datetime.now().isoformat()
            save_published(published)
            print(f"\n✅ Successfully published {len(published_links)} news items")
        else:
            print(f"\n⚠ No news items were successfully published")
    else:
        print("\n💤 No important news found")
    
    print("=" * 60)


if __name__ == '__main__':
    main()
