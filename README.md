# Market Analyst — AI-аналитик глобального и российского рынков

Консольное приложение на Python. Оно собирает свежие финансовые новости (RSS ведущих изданий и,
если хотите, публичные Telegram-каналы), отбирает важное с помощью быстрой дешёвой модели,
подтягивает котировки и передаёт всё reasoning-модели DeepSeek. На выходе получается отчёт
с рекомендациями **ПОКУПАТЬ / ДЕРЖАТЬ / ПРОДАВАТЬ** отдельно по глобальному и российскому рынкам.

## Как это работает

```
RSS (25 лент) + Telegram ─► дедупликация, фильтр по свежести
        │
        ▼
FAST_MODEL: оценка заголовков, отбор top-N ссылок (поровну по регионам)
        │
        ▼
загрузка полных текстов (trafilatura) ─► FAST_MODEL: выжимка, тикеры, сентимент
        │
        ▼
котировки: Yahoo Finance (глобальные) + ISS Мосбиржи (РФ) — по списку наблюдения и упомянутым тикерам
        │
        ▼
REASONING_MODEL (DeepSeek R1): обзор, драйверы, рекомендации с горизонтом, уверенностью, рисками и ссылками
        │
        ▼
reports/report_YYYYMMDD_HHMM.md + .json
```

Все обращения к моделям идут через [OpenRouter](https://openrouter.ai).

**Источники по умолчанию** (`market_analyst/sources.py`):
- Глобальные: Bloomberg, FT, WSJ, MarketWatch, CNBC, Yahoo Finance, Investing.com, Seeking Alpha,
  Federal Reserve, OilPrice, CoinDesk.
- Российские: РБК, Интерфакс, Коммерсантъ, Ведомости, ТАСС, ПРАЙМ, Smart-Lab, Investing.com RU,
  Frank Media, Банк России.

Если лента недоступна, она просто пропускается, и это не прерывает работу.

## Установка

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # впишите OPENROUTER_API_KEY
cp config.example.yaml config.yaml  # список наблюдения, Telegram-каналы, свои ленты
```

## Запуск

```bash
python -m market_analyst                      # оба рынка, новости за 24 часа
python -m market_analyst -m russia            # только российский рынок
python -m market_analyst -m global --hours 12 -n 30
python -m market_analyst -t markettwits @russianmacro   # добавить Telegram-каналы
python -m market_analyst -q                   # только сохранить отчёт, без вывода в консоль
```

| Флаг | Назначение |
|---|---|
| `-c, --config` | путь к YAML-конфигу (по умолчанию `config.yaml`, если он есть) |
| `-m, --market` | `all` / `global` / `russia` |
| `--hours` | глубина новостей в часах |
| `-n, --max-articles` | сколько статей читать целиком (по умолчанию 25) |
| `-t, --telegram` | дополнительные Telegram-каналы |
| `-o, --out` | папка для отчётов (`reports/`) |
| `-v, --verbose` | подробный лог |

## Модели

Модели задаются в `.env`:

```env
REASONING_MODEL=deepseek/deepseek-r1          # итоговый анализ
FAST_MODEL=google/gemini-2.5-flash-lite       # отбор ссылок и выжимки
```

Подойдёт любая модель из каталога OpenRouter, например `deepseek/deepseek-r1-0528` или
`deepseek/deepseek-chat-v3.1`. В качестве быстрой модели можно взять `openai/gpt-4.1-nano`,
`qwen/qwen-turbo` и т. п. Один прогон обычно стоит несколько центов: быстрая модель обрабатывает
около 30 запросов, reasoning-модель вызывается один раз.

## Telegram

Каналы читаются через публичное веб-превью `https://t.me/s/<канал>`, поэтому API-ключи и
авторизация не нужны. Работает только с открытыми каналами, в которых включено превью
(так у большинства новостных и инвест-каналов). Каналы можно указать в `config.yaml`
(`telegram_channels`) или передать флагом `-t`.

## Регулярный запуск

Пример для cron: каждый будний день в 9:00 и в 19:00 по МСК.

```cron
0 9,19 * * 1-5 cd /path/to/repo && .venv/bin/python -m market_analyst -q
```

## Тесты

```bash
pip install pytest && pytest -q
```

---

> ⚠️ Отчёты генерируются языковыми моделями на основе открытых новостей и не являются
> индивидуальной инвестиционной рекомендацией. Модели ошибаются, а новости бывают
> неполными. Перед сделкой проверяйте данные самостоятельно.
