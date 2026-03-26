## План: Мониторинг цены MacBook Air на Kaspi (упрощенный)

### 1) Упрощенный план файлов
- `main.py`
- `requirements.txt`
- `.github/workflows/price-monitor.yml`

### 2) Ответственность каждого файла
- `main.py` — весь код в одном месте: Playwright (headless) парсит `.item__price-once`, `re.sub` чистит цену до `int`, SQLite `prices.db` в корне (чтение последней цены + запись новой), Telegram-уведомление только при изменении, weekly-отчет по пятницам после 20:00 в `Asia/Almaty`.
- `requirements.txt` — минимальные зависимости: `playwright`, `requests`.
- `.github/workflows/price-monitor.yml` — запуск по расписанию 3 раза в день (Алматы 10/15/20 => UTC 05/10/15), установка зависимостей, запуск `main.py`, коммит и `push` обновленного `prices.db`.

### 3) Содержимое `.github/workflows/price-monitor.yml`
```yaml
name: Price Monitor

on:
  schedule:
	# Almaty (UTC+5): 10:00, 15:00, 20:00 -> UTC: 05:00, 10:00, 15:00
	- cron: "0 5,10,15 * * *"
  workflow_dispatch:

permissions:
  contents: write

jobs:
  monitor:
	runs-on: ubuntu-latest

	steps:
	  - name: Checkout repository
		uses: actions/checkout@v4
		with:
		  fetch-depth: 0

	  - name: Setup Python
		uses: actions/setup-python@v5
		with:
		  python-version: "3.12"

	  - name: Install dependencies
		run: |
		  python -m pip install --upgrade pip
		  pip install -r requirements.txt
		  python -m playwright install --with-deps chromium

	  - name: Run monitor script
		env:
		  PRODUCT_URL: https://kaspi.kz/shop/p/apple-macbook-air-13-2022-13-6-16-gb-ssd-256-gb-macos-mc7x4-133963854/?c=750000000
		  PRICE_SELECTOR: .item__price-once
		  TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
		  TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
		  TZ_NAME: Asia/Almaty
		run: python main.py

	  - name: Commit and push prices.db
		if: success()
		run: |
		  git config user.name "github-actions[bot]"
		  git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

		  if [ -f prices.db ]; then
			git add prices.db
			if ! git diff --cached --quiet; then
			  git commit -m "chore: update prices.db [skip ci]"
			  git push
			else
			  echo "No changes in prices.db"
			fi
		  else
			echo "prices.db not found, nothing to commit"
		  fi
```

---

## 🐛 ИСПРАВЛЕНИЕ: Диагностика ошибки 400 Telegram API (2026-03-26)

### Найденная проблема

GitHub Actions запустился успешно, скрипт получил цену (454055 тенге), но **не отправил сообщение в Telegram**:
```
[15:22] Успешно считана цена: 454055
Ошибка отправки в Telegram: 400 Client Error: Bad Request
```

### Корневая причина (по анализу Гемини)

Ошибка **не в формате отправки (JSON vs form-encoded)**, а в **валидации данных и содержимом**. Обнаружены 4 критических уязвимости в `send_telegram_message()`:

### 4 Критических исправления

#### 1️⃣ Валидация chat_id (преобразование в int)
```python
# ❌ ДО: может быть строка вместо числа
payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}

# ✅ ПОСЛЕ: явное преобразование с обработкой ошибок
try:
    chat_id_int = int(chat_id)
except ValueError:
    print(f"❌ chat_id некорректен: '{chat_id}'")
    return
payload = {"chat_id": chat_id_int, "text": text, "parse_mode": "HTML"}
```

#### 2️⃣ Проверка на пустое сообщение
```python
# ✅ ДОБАВИТЬ перед отправкой
if not text or not text.strip():
    print("⚠️ Текст сообщения пуст")
    return
```

#### 3️⃣ Полное логирование ошибок от Telegram API
```python
# ❌ ДО: только выводим исключение
except requests.RequestException as exc:
    print(f"Ошибка: {exc}")

# ✅ ПОСЛЕ: парсим response.json() с полем description
if not response.ok:
    try:
        error_data = response.json()
        print(f"❌ Telegram API ошибка {response.status_code}:")
        print(f"   • error_code: {error_data.get('error_code')}")
        print(f"   • description: {error_data.get('description')}")
    except ValueError:
        print(f"❌ Ошибка {response.status_code}: {response.text}")
    response.raise_for_status()
```

#### 4️⃣ Добавить логирование размера сообщения
```python
# ✅ ДОБАВИТЬ перед отправкой (лимит Telegram - 4096 символов)
print(f"🔵 Отправка в Telegram ({len(text)} символов, parse_mode=HTML)...")
```

### План применения

1. Заменить функцию `send_telegram_message()` в `main.py` (строки 104-118)
2. Добавить валидацию: `int(chat_id)`, `text.strip()`, логирование `response.json()`
3. Commit: `git add main.py && git commit -m "fix: улучшена валидация Telegram API"`
4. Push и дождаться следующего запуска GitHub Actions
5. Проверить логи Actions - теперь будет видна истинная причина ошибки 400

### Ожидаемые результаты

- ✅ Если chat_id валидный → сообщение отправится
- ✅ Если chat_id невалидный → логи покажут: `❌ chat_id некорректен: 'xxx'`
- ✅ Если другая ошибка → логи покажут точный `description` от Telegram API

---
