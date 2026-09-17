from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="📝 متن توییت"), KeyboardButton(text="📖 راهنما")],
        [KeyboardButton(text="📞 ارتباط با مدیر")],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="⚙️ پنل مدیریت")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def tweet_keyboard(tweet_text: str) -> InlineKeyboardMarkup:
    buttons = []
    if len(tweet_text) <= 256:
        from aiogram.types import CopyTextButton
        buttons.append(InlineKeyboardButton(text="📋 کپی متن", copy_text=CopyTextButton(text=tweet_text)))
    buttons.append(InlineKeyboardButton(text="✅ استفاده کردم", callback_data="user:used"))
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def admin_tweet_select_keyboard(rows, action: str) -> InlineKeyboardMarkup:
    buttons = []
    for r in rows:
        preview = r["text"].replace("\n", " ")[:45]
        buttons.append([InlineKeyboardButton(text=f"#{r['id']} — {preview}", callback_data=f"admin:{action}:tweet:{r['id']}")])
    buttons.append([InlineKeyboardButton(text="🔙 برگشت", callback_data="admin:back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_user_select_keyboard(rows, tweet_id: int) -> InlineKeyboardMarkup:
    buttons = []
    for r in rows:
        name = r["first_name"] or "بدون نام"
        username = f" @{r['username']}" if r["username"] else ""
        buttons.append([InlineKeyboardButton(text=f"{name}{username} ({r['telegram_id']})", callback_data=f"admin:assign:user:{tweet_id}:{r['telegram_id']}")])
    buttons.append([InlineKeyboardButton(text="🔙 برگشت به متن‌ها", callback_data="admin:assign:back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_confirm_assign_keyboard(tweet_id: int, telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تأیید تخصیص", callback_data=f"admin:assign:confirm:{tweet_id}:{telegram_id}")],
        [InlineKeyboardButton(text="❌ لغو", callback_data="admin:back")],
    ])


def admin_menu() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="➕ افزودن متن", callback_data="admin:add"),
         InlineKeyboardButton(text="📥 ورود فایل", callback_data="admin:import")],
        [InlineKeyboardButton(text="📊 آمار", callback_data="admin:stats"),
         InlineKeyboardButton(text="📝 متن‌ها", callback_data="admin:tweets")],
        [InlineKeyboardButton(text="👥 کاربران", callback_data="admin:users"),
         InlineKeyboardButton(text="🔎 جست‌وجو", callback_data="admin:search")],
        [InlineKeyboardButton(text="✏️ ویرایش متن", callback_data="admin:edit"),
         InlineKeyboardButton(text="🗑 حذف متن", callback_data="admin:delete")],
        [InlineKeyboardButton(text="🔓 آزاد کردن متن", callback_data="admin:release"),
         InlineKeyboardButton(text="🎯 تخصیص دستی", callback_data="admin:assign")],
        [InlineKeyboardButton(text="✅ فعال‌سازی کاربر", callback_data="admin:allow"),
         InlineKeyboardButton(text="🚫 لغو دسترسی", callback_data="admin:deny")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
