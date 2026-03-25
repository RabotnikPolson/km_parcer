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

