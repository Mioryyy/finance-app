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
