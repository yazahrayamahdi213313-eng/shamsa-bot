from aiogram.fsm.state import State, StatesGroup


class AdminStates(StatesGroup):
    add_text = State()
    import_file = State()
    edit_tweet_id = State()
    edit_tweet_text = State()
    delete_tweet_id = State()
    release_tweet_id = State()
    assign_data = State()
    allow_user = State()
    deny_user = State()
    search = State()


class UserStates(StatesGroup):
    contact_message = State()
