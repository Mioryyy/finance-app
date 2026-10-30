CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "RUB": "₽",
    "BYN": "Br",
}

ACCOUNT_TYPES = {"card": "💳 Карта", "cash": "💵 Наличные", "crypto": "🪙 Криптовалюта"}
ACCOUNT_TYPES_EMOJI = {"card": "💳", "cash": "💵", "crypto": "🪙"}
# эти счета могут уйти в минус (овердрафт); остальные — нет.
# то же правило продублировано в CHECK-ограничении таблицы accounts
OVERDRAFT_ACCOUNT_TYPES = ("card",)
TX_TYPES = {"expense": "-", "income": "+"}
PAGE_SIZE = 10
# сколько дней дампы базы хранятся на сервере (cron-задача удаляет старше этого срока);
# об этом честно сообщаем пользователю при удалении данных
BACKUP_RETENTION_DAYS = 14
# отзыв: ограничения от спама и слишком длинных сообщений
FEEDBACK_MAX_LENGTH = 1000
FEEDBACK_COOLDOWN_SECONDS = 60
# быстрый ввод: трата сохраняется сразу, только если сумма не выглядит опечаткой.
# «Подозрительно» — больше обычной для категории в UNUSUAL_FACTOR раз (и не меньше
# UNUSUAL_MIN), а если истории по категории нет — больше MAX_WITHOUT_HISTORY
QUICK_UNUSUAL_FACTOR = 5
QUICK_UNUSUAL_MIN = 50
QUICK_MAX_WITHOUT_HISTORY = 300
# вечернее сообщение: в REMINDER_HOUR по Минску (UTC+3, без перехода на летнее время)
REMINDER_HOUR = 20
MINSK_UTC_OFFSET_HOURS = 3
# сколько трат максимум показываем в вечернем списке «проверь»
REVIEW_LIST_LIMIT = 10
# первый счёт при /start создаётся сам, без вопросов про название и тип
DEFAULT_ACCOUNT_NAME = "Карта"
# валюты на кнопках первого запуска: сначала самые вероятные для аудитории
ONBOARDING_CURRENCIES = ("BYN", "RUB", "USD", "EUR")
# после какой по счёту записи один раз предлагаем включить быстрый ввод
QUICK_ENTRY_OFFER_AFTER = 20
