import logging
import os
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

# 📌 تنظیمات لاگ‌گیری
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s",
                    level=logging.INFO)

# 📌 توکن ربات
TOKEN = "7231221565:AAF7FffXcvVODTHu-mjuixRoa2j-4FAhzeU"

ZARINPAL_API = "YOUR_ZARINPAL_API"

# 📌 مسیر ذخیره اطلاعات کاربران
USER_DATA_FILE = "user_data.txt"
USER_LOG_FILE = "user_log.txt"

# 📌 آیدی عددی گروه پشتیبانی و ادمین
SUPPORT_GROUP_ID = -1002343002499  # جایگزین با آیدی گروه
ADMIN_ID = 8176330297  # جایگزین با آیدی خودت

# ذخیره کاربران مجاز برای ارسال پیام پشتیبانی در روز جاری
user_last_request = {}

# 📌 دیکشنری ذخیره کاربران در حال ارسال پیام به پشتیبانی
pending_support_users = {}

# 📌 دیکشنری برای ذخیره پیام کاربران قبل از ارسال
user_messages = {}

# 📌 ایجاد قفل برای همزمانی
lock = asyncio.Lock()

waiting_users = []  # صف کاربران در حال انتظار برای چت
active_chats = {}  # ذخیره چت‌های فعال


# 📌 تابع ذخیره لاگ کاربران
def log_user_activity(user_id, activity):
    with open(USER_LOG_FILE, "a") as file:
        file.write(f"{datetime.now()} | {user_id} | {activity}\n")


# 📌 تابع خواندن اطلاعات کاربران از فایل
def load_user_data():
    user_data = {}
    if os.path.exists(USER_DATA_FILE):
        with open(USER_DATA_FILE, "r") as file:
            for line in file.readlines():
                parts = line.strip().split("|")
                if len(parts) >= 3:
                    user_id = parts[0]
                    accepted = parts[1]
                    coins = int(parts[2]) if parts[2].isdigit() else 0
                    invited_count = int(parts[3]) if len(
                        parts) > 3 and parts[3].isdigit() else 0
                    chat_count = int(parts[4]) if len(
                        parts) > 4 and parts[4].isdigit() else 0
                    name = parts[5] if len(parts) > 5 else "Unknown"
                    username = parts[6] if len(parts) > 6 else "N/A"
                    last_request_date = parts[7] if len(
                        parts) > 7 else "نامشخص"

                    user_data[user_id] = {
                        "accepted": accepted,
                        "coins": coins,
                        "invited_count": invited_count,
                        "chat_count": chat_count,
                        "name": name,
                        "username": username,
                        "last_request_date": last_request_date
                    }
    return user_data


# 📌 تابع ذخیره اطلاعات کاربران در فایل
def save_user_data(user_data):
    with open(USER_DATA_FILE, "w") as file:
        for user_id, data in user_data.items():
            file.write(f"{user_id}|{data['accepted']}|{data['coins']}|"
                       f"{data['invited_count']}|{data['chat_count']}|"
                       f"{data['name']}|{data['username']}|"
                       f"{data.get('last_request_date', 'نامشخص')}\n")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بررسی تأیید قوانین و نمایش منوی مناسب"""
    logging.info(f"📩 دریافت /start از کاربر: {update.effective_user.id}")
    user = update.effective_user
    user_id = str(user.id)
    user_data = load_user_data()
    # بررسی وجود message و اینکه متنی برای split کردن وجود داشته باشد
    if update.message and update.message.text:
        args = update.message.text.split()
        inviter_id = args[1] if len(args) > 1 and args[1].isdigit() else None

    # اگر کاربر جدید است، اطلاعات او را ذخیره کن
    if user_id not in user_data:
        user_data[user_id] = {
            "accepted": "pending",
            "coins": 3,
            "invited_count": 0,
            "chat_count": 0,
            "name": user.full_name,
            "username": user.username if user.username else "N/A"
        }
        if inviter_id and inviter_id in user_data and inviter_id != user_id:
            user_data[inviter_id]["coins"] += 1
            user_data[inviter_id]["invited_count"] += 1
            log_user_activity(inviter_id, f"دعوت موفق {user_id}")

        save_user_data(user_data)

    # اگر کاربر قبلاً قوانین را تأیید کرده، منو را نمایش بده
    if user_data[user_id]["accepted"] == "accepted":
        await show_main_menu(update, context)
        return

    # دکمه تایید قوانین
    keyboard = [[
        InlineKeyboardButton("✅ قبول قوانین", callback_data="accept_rules")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    rules_text = (
        "📜 **قوانین و مقررات ربات چت ناشناس** 📜\n\n"
        "1️⃣ **مسئولیت پیام‌ها:** سازنده‌ی ربات هیچ‌گونه مسئولیتی در قبال پیام‌های رد و بدل شده بین کاربران ندارد.\n"
        "2️⃣ **محتوای غیرمجاز:** ارسال هرگونه محتوای غیرقانونی، سیاسی، توهین‌آمیز و غیراخلاقی اکیداً ممنوع است.\n"
        "3️⃣ **حریم خصوصی:** تمامی پیام‌های شما به‌صورت رمزگذاری‌شده ارسال می‌شوند و هیچ فردی (حتی ادمین های ربات) به آن‌ها دسترسی ندارد.\n"
        "4️⃣ **قطع سرویس:** در صورت بروز مشکلات فنی یا سایر موارد، سازنده این حق را دارد که دسترسی به ربات را متوقف کند.\n"
        "5️⃣ **پرداخت امن:** تمامی تراکنش‌های مالی از طریق درگاه امن **زرین پال** انجام می‌شوند.\n"
        "6️⃣ **پشتیبانی مالی:** مشکلات مربوط به پرداخت و خرید سکه فقط از طریق پشتیبانی رسمی ربات قابل پیگیری است.\n"
        "7️⃣ **کلاهبرداری:** سازندگان ربات **هیچ‌گاه** از شما اطلاعات خصوصی درخواست نمی‌کنند؛ مراقب افراد سودجو باشید.\n"
        "8️⃣ **بازگشت وجه:** مبلغ پرداختی به هیچ عنوان قابل بازگشت (ریفاند) نیست؛ لطفاً قبل از پرداخت دقت کنید.\n\n"
        "✅ با ادامه‌ی فعالیت در این ربات، شما تمامی قوانین فوق را پذیرفته‌اید."
    )

    await update.message.reply_text(rules_text,
                                    reply_markup=reply_markup,
                                    parse_mode="Markdown")


async def accept_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پس از قبول قوانین، ذخیره تأیید و نمایش منوی اصلی"""
    query = update.callback_query
    user_id = str(query.from_user.id)

    user_data = load_user_data()
    user_data[user_id]["accepted"] = "accepted"
    save_user_data(user_data)

    await query.answer()
    await show_main_menu(update, context, query)


async def show_main_menu(update: Update,
                         context: ContextTypes.DEFAULT_TYPE,
                         query=None):
    """نمایش منوی اصلی"""
    keyboard = [[
        InlineKeyboardButton("🗣️ شروع گفتگو", callback_data="start_chat")
    ],
                [
                    InlineKeyboardButton("💰 کیف پول", callback_data="wallet"),
                    InlineKeyboardButton("👥 دعوت از دوستان",
                                         callback_data="invite")
                ]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = "🎉 خوش آمدید! از گزینه‌های زیر استفاده کنید:"

    if update.callback_query:
        current_text = update.callback_query.message.text  # متن فعلی پیام
        if current_text != text:  # فقط اگر تغییر کرده باشه، ویرایش کن
            await update.callback_query.message.edit_text(
                text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)


async def cancel_search(update, context):
    print("🔴 در حال لغو جستجو")  # برای بررسی اجرا شدن تابع
    query = update.callback_query
    # حذف کاربر از لیست انتظار در صورت لغو
    user_id = update.callback_query.from_user.id
    if user_id in waiting_users:
        waiting_users.remove(user_id)
    await show_main_menu(update, context)


async def filter_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """فیلتر کردن پیام‌های نامناسب هنگام چت"""
    user_id = str(update.message.from_user.id)

    # بررسی اگر کاربر در حال چت است
    if user_id not in active_chats:
        return

    # محتوای ممنوعه
    if any(char in update.message.text
           for char in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        await update.message.delete()
        await update.message.reply_text(
            "🚫 ارسال پیام با حروف انگلیسی در چت مجاز نیست!")
        return

    # ارسال پیام برای کاربر دیگر
    partner_id = active_chats[user_id]
    await context.bot.send_message(chat_id=partner_id,
                                   text=update.message.text)


async def start_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت درخواست شروع مکالمه و اتصال تصادفی کاربران"""
    if update.callback_query:
        user_id = str(update.callback_query.from_user.id)
        query = update.callback_query  # ذخیره callback_query برای استفاده در ادامه
    else:
        user_id = str(update.message.from_user.id)
        query = None  # چون این پیام معمولی است، callback_query نداریم

    print(f"✅ دکمه 'شروع مکالمه' کلیک شد توسط: {user_id}"
          )  # لاگ برای بررسی اجرا شدن تابع

    user_data = load_user_data()

    if user_id not in user_data:
        if query:
            await query.answer("❌ خطا! کاربر در دیتابیس یافت نشد.",
                               show_alert=True)
        else:
            await update.message.reply_text("❌ خطا! کاربر در دیتابیس یافت نشد."
                                            )
        return

    if user_data[user_id]["coins"] <= 0:
        if query:
            await query.answer("❌ سکه کافی ندارید! لطفاً سکه بخرید.",
                               show_alert=True)
        else:
            await update.message.reply_text(
                "❌ سکه کافی ندارید! لطفاً سکه بخرید.")
        return

    if user_id in active_chats:
        if query:
            await query.answer("❗ شما در حال حاضر در یک مکالمه هستید!",
                               show_alert=True)
        else:
            await update.message.reply_text(
                "❗ شما در حال حاضر در یک مکالمه هستید!")
        return

    # اضافه کردن کاربر به لیست انتظار
    waiting_users.append(user_id)
    print(f"🔍 کاربر {user_id} به لیست انتظار اضافه شد.")

    query = update.callback_query  # بررسی اگر از دکمه شیشه‌ای فراخوانی شده باشد
    if query:
        await query.answer("🔍 در حال جستجوی کاربر...")

    text = "🔍 در حال جستجوی کاربر...\n اگر بعد از 2 دقیقه پاسخی دریافت نشد دوباره امتحان کنید\n /start"

    # حذف دکمه شیشه‌ای از پیام قبلی
    if query and query.message:
        await query.message.edit_text(text)  # حذف دکمه‌ها از پیام

    elif update.message:
        await update.message.reply_text(text)  # ارسال پیام جدید بدون دکمه

    print("✅ تابع start_search اجرا شد")
    await asyncio.sleep(2)  # کمی تأخیر برای طبیعی‌تر شدن جستجو

    if len(waiting_users) >= 2:
        user1 = waiting_users.pop(0)
        user2 = waiting_users.pop(0)

        if user1 == user2:

            async def start_chat(update, context):
                pass  # عمل مورد نظر برای زمانی که دو کاربر یکی هستند
        else:
            print(f"✅ دو کاربر {user1} و {user2} به هم متصل شدند!")

            active_chats[user1] = user2
            active_chats[user2] = user1

            # کم کردن سکه از کاربران
            user_data[user1]["coins"] -= 1
            user_data[user2]["coins"] -= 1
            save_user_data(user_data)

            keyboard = [[
                InlineKeyboardButton("❌ اتمام مکالمه",
                                     callback_data="end_chat")
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await context.bot.send_message(
                chat_id=user1,
                text="✅ شما به یک کاربر تصادفی متصل شدید. شروع به صحبت کنید!",
                reply_markup=reply_markup)

            await context.bot.send_message(
                chat_id=user2,
                text="✅ شما به یک کاربر تصادفی متصل شدید. شروع به صحبت کنید!",
                reply_markup=reply_markup)


async def end_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اتمام مکالمه و خروج کاربران از چت"""
    user_id = str(update.callback_query.from_user.id)

    if user_id not in active_chats:
        await update.callback_query.answer(
            "❗ شما در حال حاضر در هیچ مکالمه‌ای نیستید!", show_alert=True)
        return

    partner_id = active_chats[user_id]

    # حذف کاربران از چت فعال
    del active_chats[user_id]
    del active_chats[partner_id]

    # ارسال پیام خروج از چت
    await context.bot.send_message(chat_id=user_id,
                                   text="❌ مکالمه شما به پایان رسید.")
    await context.bot.send_message(chat_id=user_id, text="/start")
    await context.bot.send_message(chat_id=partner_id,
                                   text="❌ مکالمه شما به پایان رسید.")
    await context.bot.send_message(chat_id=partner_id, text="/start")

    # هدایت کاربر به منوی اصلی


async def invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش لینک دعوت و تعداد دعوت‌های موفق"""
    query = update.callback_query
    user_id = str(query.from_user.id)
    user_data = load_user_data()

    invite_link = f"https://t.me/eyjrbfhdbot?start={user_id}"
    invites = user_data.get(user_id, {}).get("invited_count", 0)

    # تعریف دکمه بازگشت
    keyboard = [[
        InlineKeyboardButton("🔙 بازگشت", callback_data="show_main_menu")
    ]]

    # ایجاد کیبورد
    reply_markup = InlineKeyboardMarkup(keyboard)

    # متن پیام با لینک دعوت و تعداد دعوت‌های موفق
    text = f"🔗 **لینک دعوت اختصاصی شما:**\n{invite_link}\n\n👥 تعداد دعوت‌های موفق: {invites}\n🎁 به ازای هر دعوت، ۱ سکه دریافت کنید!\nاز 50 دعوت خود اسکرین بگیرید و در قرعه کشی 100 میلیون ریال پول نقد شرکت کنید\n"

    # ارسال یا ویرایش پیام با کیبورد
    await query.edit_message_text(text=text,
                                  reply_markup=reply_markup,
                                  parse_mode=ParseMode.MARKDOWN)


async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش کیف پول کاربر"""
    query = update.callback_query
    user_id = str(query.from_user.id)
    user_data = load_user_data()
    coins = user_data.get(user_id, {}).get("coins", 0)
    calls_remaining = coins // 3

    log_user_activity(user_id, "مشاهده کیف پول")

    keyboard = [[
        InlineKeyboardButton("💳 خرید سکه", callback_data="buy_coins")
    ], [InlineKeyboardButton("🔙 بازگشت", callback_data="show_main_menu")]]

    reply_markup = InlineKeyboardMarkup(keyboard)

    text = f"💰 **کیف پول شما**\n\n🔹 سکه‌های شما: {coins} عدد\n"
    await query.edit_message_text(text=text,
                                  reply_markup=reply_markup,
                                  parse_mode=ParseMode.MARKDOWN)


async def buy_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی خرید سکه"""
    query = update.callback_query
    user_id = str(query.from_user.id)
    log_user_activity(user_id, "ورود به منوی خرید سکه")

    keyboard = [[
        InlineKeyboardButton("3 سکه - 9000 تومان", callback_data="purchase_3")
    ],
                [
                    InlineKeyboardButton("10 سکه - 25000 تومان",
                                         callback_data="purchase_10")
                ],
                [
                    InlineKeyboardButton("اشتراک 1 روزه - 50000 تومان",
                                         callback_data="purchase_1d")
                ],
                [
                    InlineKeyboardButton("اشتراک 3 روزه - 125000 تومان",
                                         callback_data="purchase_3d")
                ], [InlineKeyboardButton("🔙 بازگشت", callback_data="wallet")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "🛒 لطفاً یکی از گزینه‌های زیر را برای خرید انتخاب کنید:",
        reply_markup=reply_markup)


async def process_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش خرید سکه"""
    query = update.callback_query
    user_id = str(query.from_user.id)
    choice = query.data.split("_")[1]

    prices = {"3": 9000, "10": 25000, "1d": 50000, "3d": 125000}
    coins_given = {
        "3": 3,
        "10": 10,
        "1d": "unlimited_1d",
        "3d": "unlimited_3d"
    }

    if choice not in prices:
        await query.answer("❌ گزینه نامعتبر است.", show_alert=True)
        return

    log_user_activity(user_id, f"درخواست خرید {choice} سکه")
    amount = prices[choice]
    payment_url = f"https://www.zarinpal.com/pg/pay/{ZARINPAL_API}?amount={amount}&callback_url=YOUR_CALLBACK_URL&user_id={user_id}&choice={choice}"

    keyboard = [[InlineKeyboardButton("💳 پرداخت", url=payment_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "💳 برای تکمیل خرید روی دکمه پرداخت کلیک کنید:",
        reply_markup=reply_markup)


async def confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE,
                          user_id: str, choice: str):
    """تأیید پرداخت موفق و افزودن سکه به کاربر"""
    user_data = load_user_data()

    if choice in ["1d", "3d"]:
        user_data[user_id]["coins"] = choice  # فعال‌سازی اشتراک
    else:
        user_data[user_id]["coins"] += int(choice)

    save_user_data(user_data)
    log_user_activity(user_id, f"پرداخت موفق - دریافت {choice} سکه")
    await context.bot.send_message(chat_id=int(user_id),
                                   text="✅ پرداخت موفق! سکه‌های شما اضافه شد.")


async def forward_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال پیام‌های کاربران به طرف مقابل"""
    user_id = str(update.message.from_user.id)

    # بررسی اینکه کاربر در حال چت است
    if user_id not in active_chats:
        return

    partner_id = active_chats[user_id]

    # اگر پیام متنی است
    if update.message.text:
        await context.bot.send_message(chat_id=partner_id,
                                       text=update.message.text)

    # اگر پیام عکس است
    elif update.message.photo:
        await context.bot.send_photo(chat_id=partner_id,
                                     photo=update.message.photo[-1].file_id,
                                     caption=update.message.caption or "")

    # اگر پیام استیکر است
    elif update.message.sticker:
        await context.bot.send_sticker(chat_id=partner_id,
                                       sticker=update.message.sticker.file_id)

    # اگر پیام گیف (انیمیشن) است
    elif update.message.animation:
        await context.bot.send_animation(
            chat_id=partner_id,
            animation=update.message.animation.file_id,
            caption=update.message.caption or "")

    # اگر پیام ویدئو است
    elif update.message.video:
        await context.bot.send_video(chat_id=partner_id,
                                     video=update.message.video.file_id,
                                     caption=update.message.caption or "")

    # اگر پیام صوتی است
    elif update.message.voice:
        await context.bot.send_voice(chat_id=partner_id,
                                     voice=update.message.voice.file_id)

    # اگر پیام فایل است
    elif update.message.document:
        await context.bot.send_document(
            chat_id=partner_id,
            document=update.message.document.file_id,
            caption=update.message.caption or "")


async def send_secret_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال پیام‌های محرمانه که بعد از چند ثانیه حذف می‌شوند"""
    user_id = str(update.message.from_user.id)

    if user_id not in active_chats:
        return

    partner_id = active_chats[user_id]
    sent_message = await context.bot.send_message(chat_id=partner_id, text=update.message.text)

    await asyncio.sleep(10)  # پیام بعد از 10 ثانیه حذف شود
    await sent_message.delete()



# اجرای ربات
if __name__ == "__main__":
    application = Application.builder().token(TOKEN).build()

    # Handlers

    application.add_handler(CommandHandler("start", start))
    application.add_handler(
        CallbackQueryHandler(accept_rules, pattern="^accept_rules$"))
    application.add_handler(CallbackQueryHandler(invite, pattern="^invite$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, send_secret_message))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, filter_messages))
    application.add_handler(
        MessageHandler(filters.ALL & ~filters.COMMAND, forward_message))
    application.add_handler(CallbackQueryHandler(wallet, pattern="^wallet$"))
    application.add_handler(
        CallbackQueryHandler(show_main_menu, pattern="^show_main_menu$"))
    application.add_handler(
        CallbackQueryHandler(buy_coins, pattern="^buy_coins$"))
    application.add_handler(
        CallbackQueryHandler(process_payment, pattern="^purchase_"))
    application.add_handler(
        CallbackQueryHandler(start_chat, pattern="^start_chat$"))
    application.add_handler(
        CallbackQueryHandler(end_chat, pattern="^end_chat$"))

    # اجرا
    application.run_polling()
