from aiogram.fsm.state import State, StatesGroup


class TransactionStates(StatesGroup):
    waiting_for_category = State()
    waiting_for_confirm = State()
    waiting_for_date = State()


class DeleteDataStates(StatesGroup):
    waiting_for_confirm = State()


class FeedbackStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_choice = State()


class CategoryStates(StatesGroup):
    waiting_for_new_category_name = State()
    waiting_for_type = State()
    waiting_for_emoji = State()


class AccountStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_type = State()
    waiting_for_currency = State()


class TransferStates(StatesGroup):
    waiting_for_to_account = State()
    waiting_for_amount = State()
    waiting_for_accept = State()


class AccountEditStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_balance = State()
