from aiogram.fsm.state import State, StatesGroup


class ExpenseStates(StatesGroup):
    waiting_for_category = State()


class CategoryStates(StatesGroup):
    waiting_for_new_category_name = State()
    waiting_for_emoji = State()
