from __future__ import annotations

import csv
import io
import re
import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.markdown import hbold

from db import Database
from keyboards import (
    admin_confirm_assign_keyboard, admin_menu, admin_tweet_select_keyboard,
    admin_user_select_keyboard, main_menu, tweet_keyboard,
)
from states import AdminStates, UserStates

router = Router()


def ts(value: int | None) -> str:
    if not value:
        return "—"
    return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def is_admin_user(user_id: int, admin_ids: set[int]) -> bool:
    return user_id in admin_ids


async def ensure_user(message: Message, db: Database, admin_ids: set[int]) -> None:
    u = message.from_user
    await db.upsert_user(
        telegram_id=u.id,
        username=u.username,
        first_name=u.first_name,
        last_name=u.last_name,
        force_allowed=True if u.id in admin_ids else None,
    )


@router.message(Command("start"))
async def start(message: Message, db: Database, admin_ids: set[int]):
    await ensure_user(message, db, admin_ids)
    await message.answer(
        "سلام 👋\nاز منوی زیر گزینه موردنظر را انتخاب کنید.",
        reply_markup=main_menu(is_admin_user(message.from_user.id, admin_ids)),
    )


@router.message(F.text == "📖 راهنما")
async def guide(message: Message, db: Database, admin_ids: set[int]):
    await ensure_user(message, db, admin_ids)
    text = (
        "راهنما\n\n"
        "1) از «📝 متن توییت» متن اختصاصی خودتان را دریافت کنید.\n"
        "2) تا وقتی آن متن را «استفاده کردم» نزنید، با درخواست بعدی همان متن به شما نمایش داده می‌شود.\n"
        "3) یک متن اختصاص‌داده‌شده به کاربر دیگر داده نمی‌شود.\n"
        "4) بعد از استفاده، «✅ استفاده کردم» را بزنید تا در درخواست بعدی متن آزاد بعدی تخصیص یابد."
    )
    await message.answer(text, reply_markup=main_menu(is_admin_user(message.from_user.id, admin_ids)))


@router.message(F.text == "📞 ارتباط با مدیر")
async def contact_admin(message: Message, db: Database, admin_ids: set[int], state: FSMContext):
    await ensure_user(message, db, admin_ids)
    await state.set_state(UserStates.contact_message)
    await message.answer("پیام خود را ارسال کنید. پیام شما برای مدیر/مدیران ربات ارسال می‌شود. برای لغو، /cancel را بزنید.")


@router.message(UserStates.contact_message)
async def contact_admin_finish(message: Message, state: FSMContext, admin_ids: set[int]):
    if message.from_user.id in admin_ids:
        await state.clear()
        await message.answer("عملیات ارتباط لغو شد.")
        return
    text = (message.text or message.caption or "").strip()
    if not text:
        await message.answer("لطفاً پیام متنی ارسال کنید.")
        return
    sender = message.from_user
    label = f"کاربر {sender.id}"
    if sender.username:
        label += f" (@{sender.username})"
    forwarded = f"📩 پیام جدید برای مدیر\n\n{label}\n\n{text}"
    for admin_id in admin_ids:
        try:
            await message.bot.send_message(admin_id, forwarded)
        except Exception:
            logging.exception("Failed to notify admin %s", admin_id)
    await state.clear()
    await message.answer("✅ پیام شما برای مدیر ارسال شد.")


@router.message(F.text == "📝 متن توییت")
async def get_tweet(message: Message, db: Database, admin_ids: set[int]):
    await ensure_user(message, db, admin_ids)
    user = await db.get_user_by_telegram_id(message.from_user.id)
    if not user or not user["is_allowed"]:
        await message.answer("⛔ دسترسی شما به دریافت متن فعال نشده است.")
        return

    assignment = await db.assign_for_user(message.from_user.id)
    if not assignment:
        await message.answer("در حال حاضر متن جدیدی برای شما موجود نیست. لطفاً بعداً دوباره مراجعه کنید.")
        return

    await message.answer(
        f"📝 متن اختصاص‌یافته شما (شماره {assignment['tweet_id']})\n\n{assignment['text']}",
        reply_markup=tweet_keyboard(assignment["text"]),
    )


@router.callback_query(F.data == "user:used")
async def mark_used(callback: CallbackQuery, db: Database):
    await callback.answer()
    result = await db.mark_current_used(callback.from_user.id)
    if not result:
        await callback.message.answer("متن فعال فعالی برای شما پیدا نشد.")
        return
    await callback.message.answer("✅ این متن در سابقه شما به‌عنوان «استفاده‌شده» ثبت شد.")


@router.message(F.text == "⚙️ پنل مدیریت")
async def admin_panel(message: Message, db: Database, admin_ids: set[int]):
    await ensure_user(message, db, admin_ids)
    if not is_admin_user(message.from_user.id, admin_ids):
        await message.answer("⛔ دسترسی غیرمجاز")
        return
    await message.answer("⚙️ پنل مدیریت", reply_markup=admin_menu())


@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery, db: Database, admin_ids: set[int]):
    await callback.answer()
    if not is_admin_user(callback.from_user.id, admin_ids):
        return
    s = await db.stats()
    text = (
        "📊 آمار سیستم\n\n"
        f"کل متن‌ها: {s['total']}\n"
        f"آزاد: {s['available']}\n"
        f"اختصاص‌یافته: {s['assigned']}\n"
        f"استفاده‌شده: {s['used']}\n\n"
        f"کل کاربران: {s['users']}\n"
        f"کاربران مجاز: {s['allowed_users']}"
    )
    await callback.message.answer(text)


@router.callback_query(F.data == "admin:tweets")
async def admin_tweets(callback: CallbackQuery, db: Database, admin_ids: set[int]):
    await callback.answer()
    if not is_admin_user(callback.from_user.id, admin_ids):
        return
    rows = await db.list_tweets(limit=30)
    if not rows:
        await callback.message.answer("هیچ متنی در بانک ثبت نشده است.")
        return
    chunks = []
    for r in rows:
        preview = r["text"].replace("\n", " ")
        if len(preview) > 90:
            preview = preview[:90] + "…"
        owner = ""
        if r["status"] == "assigned":
            owner = f" | کاربر: {r['telegram_id']}"
        assigned = f" | زمان تخصیص: {ts(r['assigned_at'])}" if r["assigned_at"] else ""
        chunks.append(f"#{r['id']} | {r['status']}{owner}{assigned}\n{preview}")
    await callback.message.answer("📝 آخرین متن‌ها:\n\n" + "\n\n".join(chunks))


@router.callback_query(F.data == "admin:users")
async def admin_users(callback: CallbackQuery, db: Database, admin_ids: set[int]):
    await callback.answer()
    if not is_admin_user(callback.from_user.id, admin_ids):
        return
    rows = await db.list_users(limit=30)
    if not rows:
        await callback.message.answer("هنوز کاربری ثبت نشده است.")
        return
    parts = []
    for r in rows:
        name = r["first_name"] or "بدون نام"
        username = f"@{r['username']}" if r["username"] else "بدون username"
        status = "✅ مجاز" if r["is_allowed"] else "🚫 غیرمجاز"
        parts.append(f"{r['telegram_id']} | {name} | {username} | {status}")
    await callback.message.answer("👥 کاربران:\n\n" + "\n".join(parts))


@router.callback_query(F.data == "admin:add")
async def admin_add_start(callback: CallbackQuery, state: FSMContext, admin_ids: set[int]):
    await callback.answer()
    if not is_admin_user(callback.from_user.id, admin_ids):
        return
    await state.set_state(AdminStates.add_text)
    await callback.message.answer("متن جدید را ارسال کنید. برای چند خط هم می‌توانید همان پیام را ارسال کنید.")


@router.message(AdminStates.add_text)
async def admin_add_finish(message: Message, state: FSMContext, db: Database, admin_ids: set[int]):
    if not is_admin_user(message.from_user.id, admin_ids):
        return
    if not message.text:
        await message.answer("لطفاً متن را به‌صورت پیام متنی ارسال کنید.")
        return
    tweet_id = await db.add_tweet(message.text)
    await state.clear()
    await message.answer(f"✅ متن با شماره #{tweet_id} اضافه شد.", reply_markup=admin_menu())


@router.callback_query(F.data == "admin:import")
async def admin_import_start(callback: CallbackQuery, state: FSMContext, admin_ids: set[int]):
    await callback.answer()
    if not is_admin_user(callback.from_user.id, admin_ids):
        return
    await state.set_state(AdminStates.import_file)
    await callback.message.answer(
        "فایل TXT یا CSV را ارسال کنید.\n\n"
        "TXT: هر متن با خط خالی از متن بعدی جدا شود، یا از قالب ## TEXT 1 استفاده کنید.\n"
        "CSV: یک ستون به نام text داشته باشد."
    )


def parse_txt(raw: str) -> list[str]:
    if re.search(r"^\s*##\s*TEXT\s*\d+\s*$", raw, flags=re.I | re.M):
        pieces = re.split(r"^\s*##\s*TEXT\s*\d+\s*$", raw, flags=re.I | re.M)
        return [p.strip() for p in pieces if p.strip()]
    pieces = re.split(r"\n\s*\n+", raw)
    return [p.strip() for p in pieces if p.strip()]


def parse_csv(raw: str) -> list[str]:
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames:
        return []
    field = next((f for f in reader.fieldnames if f.strip().lower() in {"text", "tweet", "tweet_text"}), None)
    if not field:
        return []
    return [row.get(field, "").strip() for row in reader if row.get(field, "").strip()]


@router.message(AdminStates.import_file, F.document)
async def admin_import_finish(message: Message, state: FSMContext, db: Database, admin_ids: set[int]):
    if not is_admin_user(message.from_user.id, admin_ids):
        return
    name = (message.document.file_name or "").lower()
    if not (name.endswith(".txt") or name.endswith(".csv")):
        await message.answer("❌ فقط فایل TXT یا CSV مجاز است.")
        return
    data = await message.bot.download(message.document)
    if not data:
        await message.answer("❌ دانلود فایل ناموفق بود.")
        return
    raw = data.read().decode("utf-8-sig", errors="replace")
    texts = parse_csv(raw) if name.endswith(".csv") else parse_txt(raw)
    if not texts:
        await message.answer("❌ متنی برای ورود پیدا نشد. قالب فایل را بررسی کنید.")
        return
    count = await db.add_tweets_bulk(texts)
    await state.clear()
    await message.answer(f"✅ {count} متن به‌صورت گروهی وارد شد.", reply_markup=admin_menu())


@router.callback_query(F.data == "admin:edit")
async def admin_edit_start(callback: CallbackQuery, state: FSMContext, admin_ids: set[int]):
    await callback.answer()
    if not is_admin_user(callback.from_user.id, admin_ids):
        return
    await state.set_state(AdminStates.edit_tweet_id)
    await callback.message.answer("شماره متن را بفرستید، مثلاً: 17")


@router.message(AdminStates.edit_tweet_id)
async def admin_edit_id(message: Message, state: FSMContext, db: Database, admin_ids: set[int]):
    if not is_admin_user(message.from_user.id, admin_ids):
        return
    try:
        tweet_id = int((message.text or "").strip())
    except ValueError:
        await message.answer("شماره متن باید عدد باشد.")
        return
    if not await db.get_tweet(tweet_id):
        await message.answer("چنین متنی وجود ندارد.")
        return
    await state.update_data(tweet_id=tweet_id)
    await state.set_state(AdminStates.edit_tweet_text)
    await message.answer("متن جدید را ارسال کنید.")


@router.message(AdminStates.edit_tweet_text)
async def admin_edit_finish(message: Message, state: FSMContext, db: Database, admin_ids: set[int]):
    if not is_admin_user(message.from_user.id, admin_ids):
        return
    data = await state.get_data()
    ok = await db.update_tweet(int(data["tweet_id"]), message.text or "")
    await state.clear()
    await message.answer("✅ ویرایش شد." if ok else "❌ ویرایش انجام نشد.", reply_markup=admin_menu())


@router.callback_query(F.data == "admin:delete")
async def admin_delete_start(callback: CallbackQuery, state: FSMContext, admin_ids: set[int]):
    await callback.answer()
    if not is_admin_user(callback.from_user.id, admin_ids):
        return
    await state.set_state(AdminStates.delete_tweet_id)
    await callback.message.answer("شماره متن آزاد را برای حذف ارسال کنید. متن‌های assigned/used مستقیم حذف نمی‌شوند.")


@router.message(AdminStates.delete_tweet_id)
async def admin_delete_finish(message: Message, state: FSMContext, db: Database, admin_ids: set[int]):
    if not is_admin_user(message.from_user.id, admin_ids):
        return
    try:
        tweet_id = int((message.text or "").strip())
    except ValueError:
        await message.answer("شماره متن باید عدد باشد.")
        return
    ok, reason = await db.delete_tweet(tweet_id)
    await state.clear()
    if ok:
        await message.answer(f"✅ متن #{tweet_id} حذف شد.", reply_markup=admin_menu())
    elif reason == "not_found":
        await message.answer("متن پیدا نشد.", reply_markup=admin_menu())
    else:
        await message.answer("این متن آزاد نیست؛ ابتدا در صورت نیاز آن را آزاد کنید یا بگذارید در سابقه بماند.", reply_markup=admin_menu())


@router.callback_query(F.data == "admin:release")
async def admin_release_start(callback: CallbackQuery, db: Database, admin_ids: set[int]):
    await callback.answer()
    if not is_admin_user(callback.from_user.id, admin_ids):
        return
    rows = await db.list_assigned_tweets(limit=50)
    if not rows:
        await callback.message.answer("هیچ متن اختصاص‌یافته‌ای برای آزاد کردن وجود ندارد.", reply_markup=admin_menu())
        return
    await callback.message.answer(
        "🔓 متن موردنظر برای آزاد کردن را انتخاب کنید:",
        reply_markup=admin_tweet_select_keyboard(rows, "release"),
    )


@router.callback_query(F.data.startswith("admin:release:tweet:"))
async def admin_release_selected(callback: CallbackQuery, db: Database, admin_ids: set[int]):
    await callback.answer()
    if not is_admin_user(callback.from_user.id, admin_ids):
        return
    try:
        tweet_id = int(callback.data.rsplit(":", 1)[1])
    except (ValueError, AttributeError):
        await callback.message.answer("شناسه متن نامعتبر است.")
        return
    ok, reason, _ = await db.release_tweet(tweet_id)
    if ok:
        await callback.message.answer(f"✅ متن #{tweet_id} آزاد شد و دوباره قابل تخصیص است.", reply_markup=admin_menu())
    else:
        await callback.message.answer(f"❌ عملیات انجام نشد: {reason}", reply_markup=admin_menu())


@router.message(AdminStates.release_tweet_id)
async def admin_release_finish(message: Message, state: FSMContext, db: Database, admin_ids: set[int]):
    if not is_admin_user(message.from_user.id, admin_ids):
        return
    try:
        tweet_id = int((message.text or "").strip())
    except ValueError:
        await message.answer("شماره متن باید عدد باشد.")
        return
    ok, reason, _ = await db.release_tweet(tweet_id)
    await state.clear()
    if ok:
        await message.answer(f"✅ متن #{tweet_id} آزاد شد و می‌تواند به کاربر دیگری تخصیص پیدا کند.", reply_markup=admin_menu())
    else:
        await message.answer(f"❌ عملیات انجام نشد: {reason}", reply_markup=admin_menu())


@router.callback_query(F.data == "admin:assign")
async def admin_assign_start(callback: CallbackQuery, db: Database, admin_ids: set[int]):
    await callback.answer()
    if not is_admin_user(callback.from_user.id, admin_ids):
        return
    rows = await db.list_available_tweets(limit=50)
    if not rows:
        await callback.message.answer("❌ هیچ متن آزادی برای تخصیص دستی وجود ندارد.", reply_markup=admin_menu())
        return
    await callback.message.answer(
        "🎯 ابتدا متن موردنظر را انتخاب کنید:",
        reply_markup=admin_tweet_select_keyboard(rows, "assign"),
    )


@router.callback_query(F.data.startswith("admin:assign:tweet:"))
async def admin_assign_tweet_selected(callback: CallbackQuery, db: Database, admin_ids: set[int]):
    await callback.answer()
    if not is_admin_user(callback.from_user.id, admin_ids):
        return
    try:
        tweet_id = int(callback.data.rsplit(":", 1)[1])
    except (ValueError, AttributeError):
        await callback.message.answer("شناسه متن نامعتبر است.")
        return
    tweet = await db.get_tweet(tweet_id)
    if not tweet or tweet["status"] != "available":
        await callback.message.answer("❌ این متن دیگر آزاد نیست. دوباره فهرست را باز کنید.", reply_markup=admin_menu())
        return
    users = await db.list_allowed_users(limit=50)
    if not users:
        await callback.message.answer("❌ هنوز هیچ کاربر مجازی ثبت نشده است.", reply_markup=admin_menu())
        return
    await callback.message.answer(
        f"👤 کاربر موردنظر برای متن #{tweet_id} را انتخاب کنید:",
        reply_markup=admin_user_select_keyboard(users, tweet_id),
    )


@router.callback_query(F.data.startswith("admin:assign:user:"))
async def admin_assign_user_selected(callback: CallbackQuery, db: Database, admin_ids: set[int]):
    await callback.answer()
    if not is_admin_user(callback.from_user.id, admin_ids):
        return
    try:
        _, _, _, tweet_id, telegram_id = callback.data.split(":")
        tweet_id, telegram_id = int(tweet_id), int(telegram_id)
    except (ValueError, AttributeError):
        await callback.message.answer("اطلاعات تخصیص نامعتبر است.")
        return
    tweet = await db.get_tweet(tweet_id)
    user = await db.get_user_by_telegram_id(telegram_id)
    if not tweet or tweet["status"] != "available":
        await callback.message.answer("❌ این متن دیگر آزاد نیست.", reply_markup=admin_menu())
        return
    if not user or not user["is_allowed"]:
        await callback.message.answer("❌ این کاربر مجاز نیست.", reply_markup=admin_menu())
        return
    name = user["first_name"] or "بدون نام"
    username = f"@{user['username']}" if user["username"] else "بدون username"
    await callback.message.answer(
        f"🎯 تأیید تخصیص\n\nمتن: #{tweet_id}\nکاربر: {name} ({username})\nآیدی: {telegram_id}\n\nآیا تخصیص انجام شود؟",
        reply_markup=admin_confirm_assign_keyboard(tweet_id, telegram_id),
    )


@router.callback_query(F.data.startswith("admin:assign:confirm:"))
async def admin_assign_confirm(callback: CallbackQuery, db: Database, admin_ids: set[int]):
    await callback.answer()
    if not is_admin_user(callback.from_user.id, admin_ids):
        return
    try:
        _, _, _, tweet_id, telegram_id = callback.data.split(":")
        tweet_id, telegram_id = int(tweet_id), int(telegram_id)
    except (ValueError, AttributeError):
        await callback.message.answer("اطلاعات تخصیص نامعتبر است.")
        return
    ok, reason = await db.manual_assign(tweet_id, telegram_id)
    if ok:
        await callback.message.answer(f"✅ متن #{tweet_id} با موفقیت به کاربر {telegram_id} تخصیص داده شد.", reply_markup=admin_menu())
    else:
        await callback.message.answer(f"❌ تخصیص انجام نشد: {reason}", reply_markup=admin_menu())


@router.callback_query(F.data == "admin:assign:back")
async def admin_assign_back(callback: CallbackQuery, db: Database, admin_ids: set[int]):
    await callback.answer()
    if not is_admin_user(callback.from_user.id, admin_ids):
        return
    rows = await db.list_available_tweets(limit=50)
    if not rows:
        await callback.message.answer("❌ هیچ متن آزادی وجود ندارد.", reply_markup=admin_menu())
        return
    await callback.message.answer("🎯 متن موردنظر را انتخاب کنید:", reply_markup=admin_tweet_select_keyboard(rows, "assign"))


@router.callback_query(F.data == "admin:back")
async def admin_back(callback: CallbackQuery, admin_ids: set[int]):
    await callback.answer()
    if not is_admin_user(callback.from_user.id, admin_ids):
        return
    await callback.message.answer("⚙️ پنل مدیریت", reply_markup=admin_menu())


@router.callback_query(F.data == "admin:allow")
async def admin_allow_start(callback: CallbackQuery, state: FSMContext, admin_ids: set[int]):
    await callback.answer()
    if not is_admin_user(callback.from_user.id, admin_ids):
        return
    await state.set_state(AdminStates.allow_user)
    await callback.message.answer("Telegram User ID کاربر را ارسال کنید.")


@router.message(AdminStates.allow_user)
async def admin_allow_finish(message: Message, state: FSMContext, db: Database, admin_ids: set[int]):
    if not is_admin_user(message.from_user.id, admin_ids):
        return
    try:
        telegram_id = int((message.text or "").strip())
    except ValueError:
        await message.answer("User ID باید عدد باشد.")
        return
    ok = await db.set_allowed(telegram_id, True)
    await state.clear()
    await message.answer(
        "✅ دسترسی فعال شد."
        if ok else "کاربر هنوز با ربات تعامل نکرده است؛ ابتدا کاربر باید /start بزند.",
        reply_markup=admin_menu(),
    )


@router.callback_query(F.data == "admin:deny")
async def admin_deny_start(callback: CallbackQuery, state: FSMContext, admin_ids: set[int]):
    await callback.answer()
    if not is_admin_user(callback.from_user.id, admin_ids):
        return
    await state.set_state(AdminStates.deny_user)
    await callback.message.answer("Telegram User ID کاربر را برای لغو دسترسی ارسال کنید.")


@router.message(AdminStates.deny_user)
async def admin_deny_finish(message: Message, state: FSMContext, db: Database, admin_ids: set[int]):
    if not is_admin_user(message.from_user.id, admin_ids):
        return
    try:
        telegram_id = int((message.text or "").strip())
    except ValueError:
        await message.answer("User ID باید عدد باشد.")
        return
    ok = await db.set_allowed(telegram_id, False)
    await state.clear()
    await message.answer(
        "✅ دسترسی لغو شد." if ok else "کاربر پیدا نشد.",
        reply_markup=admin_menu(),
    )


@router.callback_query(F.data == "admin:search")
async def admin_search_start(callback: CallbackQuery, state: FSMContext, admin_ids: set[int]):
    await callback.answer()
    if not is_admin_user(callback.from_user.id, admin_ids):
        return
    await state.set_state(AdminStates.search)
    await callback.message.answer("برای جست‌وجو عبارت خود را بفرستید. ربات هم کاربران و هم متن‌ها را جست‌وجو می‌کند.")


@router.message(AdminStates.search)
async def admin_search_finish(message: Message, state: FSMContext, db: Database, admin_ids: set[int]):
    if not is_admin_user(message.from_user.id, admin_ids):
        return
    query = (message.text or "").strip()
    users = await db.search_users(query, limit=10)
    tweets = await db.search_tweets(query, limit=10)
    await state.clear()

    out = [f"🔎 نتیجه جست‌وجو برای: {query}"]
    if users:
        out.append("\n👥 کاربران:")
        for u in users:
            out.append(
                f"- {u['telegram_id']} | {u['first_name'] or 'بدون نام'} | "
                f"@{u['username'] if u['username'] else '-'} | "
                f"{'مجاز' if u['is_allowed'] else 'غیرمجاز'}"
            )
            history = await db.assignment_history_for_user(u['telegram_id'], limit=5)
            if history:
                for h in history:
                    out.append(
                        f"  • متن #{h['tweet_id']} | {h['status']} | تخصیص: {ts(h['assigned_at'])}"
                    )
    if tweets:
        out.append("\n📝 متن‌ها:")
        for t in tweets:
            preview = t["text"].replace("\n", " ")[:100]
            out.append(f"- #{t['id']} | {t['status']} | {preview}")
    if not users and not tweets:
        out.append("\nچیزی پیدا نشد.")
    await message.answer("\n".join(out), reply_markup=admin_menu())


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext, admin_ids: set[int]):
    if not is_admin_user(message.from_user.id, admin_ids):
        return
    await state.clear()
    await message.answer("عملیات لغو شد.", reply_markup=admin_menu())


@router.message()
async def fallback(message: Message, db: Database, admin_ids: set[int]):
    await ensure_user(message, db, admin_ids)
    if message.from_user.id in admin_ids:
        await message.answer("از منو استفاده کنید.", reply_markup=main_menu(True))
    else:
        await message.answer("از منوی ربات استفاده کنید.", reply_markup=main_menu(False))
