from aiogram.fsm.state import State, StatesGroup


class TransactionStates(StatesGroup):
    waiting_for_type = State()
    waiting_for_category = State()


class CategoryStates(StatesGroup):
    waiting_for_new_category_name = State()
    waiting_for_type = State()
    waiting_for_emoji = State()


class AccountStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_type = State()
    waiting_for_currency = State()
