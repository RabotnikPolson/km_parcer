import os
import re
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

DB_PATH = "prices.db"
DEFAULT_URL = (
    "https://kaspi.kz/shop/p/apple-macbook-air-13-2022-13-6-16-gb-ssd-256-gb-macos-mc7x4-133963854/?c=750000000"
)
DEFAULT_SELECTOR = ".item__price-once"
DEFAULT_TZ = "Asia/Almaty"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

def init_db() -> None:
    """Создает базу данных и таблицу, если они еще не существуют."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS prices (
                                                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                                                  date_text TEXT NOT NULL,
                                                  price_int INTEGER NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()

def get_last_price() -> int | None:
    """Достает последнюю зафиксированную цену из БД."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("SELECT price_int FROM prices ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()

def insert_price(date_text: str, price_int: int) -> None:
    """Записывает новую цену и время проверки в БД."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO prices (date_text, price_int) VALUES (?, ?)",
            (date_text, price_int),
        )
        conn.commit()
    finally:
        conn.close()

def get_prices_for_last_7_days(current_time: datetime) -> list[tuple[str, int]]:
    """Делает выборку всех цен за последние 7 дней для отчета."""
    threshold = (current_time - timedelta(days=7)).isoformat(timespec="seconds")
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT date_text, price_int FROM prices WHERE date_text >= ? ORDER BY date_text ASC",
            (threshold,),
        )
        return cur.fetchall()
    finally:
        conn.close()

def fetch_price_int(url: str, selector: str, user_agent: str) -> int:
    """Парсит страницу Каспи через скрытый браузер и возвращает чистую цифру."""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"], # Маскировка от антибота
        )
        context = browser.new_context(user_agent=user_agent)
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector(selector, timeout=30000)
            text = page.locator(selector).first.inner_text(timeout=10000)
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(f"Таймаут Playwright: не удалось загрузить селектор. {exc}") from exc
        finally:
            context.close()
            browser.close()

    # Очистка от мусора (пробелы, &nbsp;, символы валюты)
    digits = re.sub(r"\D", "", text)
    if not digits:
        raise ValueError(f"Не удалось извлечь цифры из текста: '{text}'")
    return int(digits)

def send_telegram_message(bot_token: str, chat_id: str, text: str) -> None:
    """Отправляет HTTP POST запрос в API Телеграма."""
    if not bot_token or not chat_id:
        print("Отсутствуют ключи Telegram (bot_token или chat_id). Сообщение не отправлено.")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}

    try:
        response = requests.post(url, data=payload, timeout=20)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"Ошибка отправки в Telegram: {exc}")

def build_change_message(old_price: int, new_price: int) -> str:
    """Формирует понятное уведомление об изменении цены."""
    diff = new_price - old_price
    formatted_new_price = f"{new_price:,}".replace(",", " ")
    formatted_diff = f"{abs(diff):,}".replace(",", " ")

    if diff < 0:
        direction = "📉 <b>Подешевел</b>"
    else:
        direction = "📈 <b>Подорожал</b>"

    return (
        f"🚨 <b>Изменение цены на MacBook!</b>\n\n"
        f"💵 Текущая цена: <b>{formatted_new_price} ₸</b>\n"
        f"{direction} на {formatted_diff} ₸."
    )

def build_weekly_report(rows: list[tuple[str, int]]) -> str:
    """Формирует аналитический еженедельный отчет."""
    prices = [price for _, price in rows]
    min_price = min(prices)
    max_price = max(prices)
    avg_price = int(sum(prices) / len(prices))

    first_price = rows[0][1]
    last_price = rows[-1][1]

    if last_price < first_price:
        trend = "📉 Тренд на снижение"
    elif last_price > first_price:
        trend = "📈 Тренд на повышение"
    else:
        trend = "➖ Цена стабильна"

    lines = ["📊 <b>Еженедельный отчет по MacBook:</b>\n"]

    # Форматируем историю изменения цен
    for date_text, price in rows:
        try:
            dt = datetime.fromisoformat(date_text)
            clean_date = dt.strftime("%d.%m %H:%M")
        except ValueError:
            clean_date = date_text

        formatted_price = f"{price:,}".replace(",", " ")
        lines.append(f"• {clean_date} — {formatted_price} ₸")

    lines.append(f"\n🔹 Минимум: {f'{min_price:,}'.replace(',', ' ')} ₸")
    lines.append(f"🔺 Максимум: {f'{max_price:,}'.replace(',', ' ')} ₸")
    lines.append(f"🔸 Средняя: {f'{avg_price:,}'.replace(',', ' ')} ₸")
    lines.append(f"\n{trend}")

    return "\n".join(lines)

def should_send_weekly_report(current_time: datetime) -> bool:
    """Проверяет, наступило ли время пятничного отчета (Пятница = 4, время >= 20:00)."""
    return current_time.weekday() == 4 and current_time.hour >= 20

def main() -> None:
    # Загрузка конфигурации из окружения
    product_url = os.getenv("PRODUCT_URL", DEFAULT_URL)
    price_selector = os.getenv("PRICE_SELECTOR", DEFAULT_SELECTOR)
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    tz_name = os.getenv("TZ_NAME", DEFAULT_TZ)
    user_agent = os.getenv("USER_AGENT", DEFAULT_USER_AGENT)

    # Установка часового пояса
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        print(f"Ошибка таймзоны '{tz_name}', откат на {DEFAULT_TZ}")
        tz = ZoneInfo(DEFAULT_TZ)

    current_time = datetime.now(tz)
    now_text = current_time.isoformat(timespec="seconds")

    # 1. Инициализация БД
    try:
        init_db()
    except Exception as exc:
        print(f"Ошибка БД (init): {exc}")
        return

    # 2. Получение старой цены
    try:
        last_price = get_last_price()
    except Exception as exc:
        print(f"Ошибка БД (чтение): {exc}")
        return

    # 3. Парсинг новой цены
    try:
        new_price = fetch_price_int(product_url, price_selector, user_agent)
        print(f"[{current_time.strftime('%H:%M')}] Успешно считана цена: {new_price}")
    except Exception as exc:
        print(f"Ошибка парсера: {exc}")
        return

    # 4. Запись в БД
    try:
        insert_price(now_text, new_price)
    except Exception as exc:
        print(f"Ошибка БД (запись): {exc}")
        return

    # 5. Логика алерта (только при изменении цены)
    if last_price is not None and new_price != last_price:
        message = build_change_message(last_price, new_price)
        send_telegram_message(bot_token, chat_id, message)
        print("Цена изменилась, отправлен алерт.")
    else:
        print("Цена не изменилась. Алерт не отправлен.")

    # 6. Логика еженедельного отчета (Пятница, 20:00)
    if should_send_weekly_report(current_time):
        try:
            rows = get_prices_for_last_7_days(current_time)
            if rows:
                report = build_weekly_report(rows)
                send_telegram_message(bot_token, chat_id, report)
                print("Еженедельный отчет отправлен.")
            else:
                print("Нет данных для еженедельного отчета.")
        except Exception as exc:
            print(f"Ошибка отправки еженедельного отчета: {exc}")

if __name__ == "__main__":
    main()