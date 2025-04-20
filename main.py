import asyncio
import re
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
import random
import asyncpg
from datetime import datetime
from typing import Union
# در بخش imports موجود، موارد زیر را اضافه کنید:
from dataclasses import dataclass
from typing import Dict, List, Optional

from aiohttp import web
import aiohttp

app = web.Application()

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# تنظیمات ربات و دیتابیس
BOT_TOKEN = "7765200180:AAGA3sGieudM6AvlKLsvE3Q4oUJ6fu-TUoE"
REQUIRED_CHANNEL = {"@mrrobot_py": "❤ کد تخفیف و شماره های ویژه ❤"}
ADMIN_ID = '8176330297'
# تنظیمات زرین‌پال
ZARINPAL_MERCHANT_ID = "5337de10-5a71-4735-b735-2d6993ef2bee"
ZARINPAL_CALLBACK_URL = f"https://mrrobotpy.chbk.app/webhook"  # استفاده از همان آدرس وب‌هوک
ZARINPAL_REQUEST_URL = "https://payment.zarinpal.com/pg/v4/payment/request.json"
ZARINPAL_VERIFY_URL = "https://payment.zarinpal.com/pg/v4/payment/verify.json"
ZARINPAL_PAYMENT_URL = "https://payment.zarinpal.com/pg/StartPay/"


# بعد از DB_CONFIG، تنظیمات API نامبرلند را اضافه کنید:
NUMBERLAND_API_KEY = "your_api_key_here"
NUMBERLAND_BASE_URL = "https://api.numberland.ir/v2.php"


DB_CONFIG = {
    "host": "services.fin2.chabokan.net",
    "port": "7105",
    "database": "donald",
    "user": "postgres",
    "password": "LQh5uVVim52qO6fS"
}


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

user_last_banner_message = {}

class WithdrawalStates(StatesGroup):
    confirm_withdrawal = State()


class WalletStates(StatesGroup):
    show_wallet = State()
    select_amount = State()
    enter_custom_amount = State()
    process_payment = State()

class EditUserInfo(StatesGroup):
    waiting_for_first_name = State()
    waiting_for_last_name = State()
    waiting_for_father_name = State()
    waiting_for_national_code = State()
    waiting_for_credit_card = State()
    waiting_for_birth_date = State()
    waiting_for_address = State()
    waiting_for_email = State()
    waiting_for_postal_code = State()

# تعریف State برای دریافت شماره
class GetPhoneNumber(StatesGroup):
    waiting_for_number = State()

async def create_db_pool():
    return await asyncpg.create_pool(**DB_CONFIG)

async def init_db():
    pool = await create_db_pool()
    async with pool.acquire() as connection:
        await connection.execute('''
            CREATE TABLE IF NOT EXISTS user_info (
                phone_number VARCHAR(15) PRIMARY KEY,
                first_name TEXT DEFAULT '',
                last_name TEXT DEFAULT '',
                father_name TEXT DEFAULT '',
                birth_date TEXT,
                national_code TEXT DEFAULT '',
                credit_card TEXT DEFAULT '',
                address TEXT DEFAULT '',
                email TEXT,
                postal_code VARCHAR(10) DEFAULT '',
                services TEXT[] DEFAULT '{}'::TEXT[]
            )
        ''')
        
        await connection.execute('''
            CREATE TABLE IF NOT EXISTS user_number_mrrobot_info (
                phone_number VARCHAR(15) PRIMARY KEY,
                user_id BIGINT UNIQUE,
                profile_link TEXT,
                wallet_balance DECIMAL(15, 2) DEFAULT 0,
                invited_users_count INTEGER DEFAULT 0,
                invited_by BIGINT,
                referral_income DECIMAL(15, 2) DEFAULT 0,
                FOREIGN KEY (phone_number) REFERENCES user_info(phone_number)
            )
        ''')
                # اضافه کردن ایندکس‌ها
        await connection.execute('CREATE INDEX IF NOT EXISTS idx_user_info_phone_number ON user_info(phone_number)')
        await connection.execute('CREATE INDEX IF NOT EXISTS idx_user_number_mrrobot_info_phone_number ON user_number_mrrobot_info(phone_number)')
        await connection.execute('CREATE INDEX IF NOT EXISTS idx_user_number_mrrobot_info_user_id ON user_number_mrrobot_info(user_id)')
    
    return pool

async def check_membership(user_id: int) -> bool:
    """بررسی عضویت کاربر در کانال‌های اجباری"""
    try:
        for channel in REQUIRED_CHANNEL.keys():
            member = await bot.get_chat_member(channel, user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        return True
    except:
        return False
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, pool: asyncpg.Pool):
    # بررسی آرگومان start برای سیستم دعوت
    args = message.text.split()
    ref_id = None
    if len(args) > 1 and args[1].startswith("ref_"):
        ref_id = int(args[1][4:])  # استخراج user_id از لینک دعوت

    # بررسی عضویت در کانال‌های اجباری
    if not await check_membership(message.from_user.id):
        join_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{name}", url=f"https://t.me/{channel.lstrip('@')}")]
            for channel, name in REQUIRED_CHANNEL.items()
        ] + [[InlineKeyboardButton(text="✅ الان عضو شدم ✅", callback_data="verify_join")]])

        await message.answer(
            "برای دریافت کد تخفیف و اطلاع از شماره ها\n"
            "در کانال مستر ربات عضو شوید",
            reply_markup=join_keyboard
        )
        return

    async with pool.acquire() as connection:
        # بررسی وجود کاربر در سیستم
        user_exists = await connection.fetchval(
            'SELECT EXISTS(SELECT 1 FROM user_number_mrrobot_info WHERE user_id = $1)',
            message.from_user.id
        )

        if user_exists:
            await show_main_menu(message, state)
            
            # اگر کاربر از طریق لینک دعوت آمده و قبلاً دعوت‌کننده نداشته
            if ref_id and ref_id != message.from_user.id:
                current_ref = await connection.fetchval(
                    'SELECT invited_by FROM user_number_mrrobot_info WHERE user_id = $1',
                    message.from_user.id
                )
                if not current_ref:
                    await connection.execute('''
                        UPDATE user_number_mrrobot_info 
                        SET invited_by = $1 
                        WHERE user_id = $2
                    ''', ref_id, message.from_user.id)
                    
                    # افزایش تعداد دعوت‌های دعوت‌کننده
                    await connection.execute('''
                        UPDATE user_number_mrrobot_info 
                        SET invited_users_count = invited_users_count + 1 
                        WHERE user_id = $1
                    ''', ref_id)
            return

        # اگر کاربر جدید است و از طریق لینک دعوت آمده
        if ref_id and ref_id != message.from_user.id:
            # بررسی وجود دعوت‌کننده در سیستم
            inviter_exists = await connection.fetchval(
                'SELECT EXISTS(SELECT 1 FROM user_number_mrrobot_info WHERE user_id = $1)',
                ref_id
            )
            if not inviter_exists:
                ref_id = None

        # درخواست شماره تلفن از کاربر
        phone_keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="💎 ورود به پنل کاربری 💎", request_contact=True)]],
            resize_keyboard=True, one_time_keyboard=True
        )
        await message.answer("👇 جهت ورود به پنل کاربری از دکمه زیر استفاده کنید 👇", reply_markup=phone_keyboard)
        
        # ذخیره ref_id در state اگر وجود دارد
        if ref_id:
            await state.update_data(invited_by=ref_id)
        
        await state.set_state(GetPhoneNumber.waiting_for_number)
    

@dp.message(GetPhoneNumber.waiting_for_number, F.contact)
async def process_phone(message: Message, state: FSMContext, pool: asyncpg.Pool):
    if message.contact.user_id != message.from_user.id:
        await message.answer("👇 جهت ورود به پنل کاربری از دکمه زیر استفاده کنید 👇")
        return

    phone_number = message.contact.phone_number
    user_data = await state.get_data()
    invited_by = user_data.get('invited_by')

    async with pool.acquire() as connection:
        # ثبت کاربر در user_info
        await connection.execute('''
            INSERT INTO user_info (phone_number, first_name, last_name, services)
            VALUES ($1, $2, $3, ARRAY['number_mrrobot_service'])
            ON CONFLICT (phone_number) DO UPDATE
            SET services = array_append(user_info.services, 'number_mrrobot_service')
            WHERE NOT user_info.services @> ARRAY['number_mrrobot_service']
        ''', phone_number, message.from_user.first_name or "", message.from_user.last_name or "")

        # ثبت کاربر در user_number_mrrobot_info
        profile_link = f"tg://user?id={message.from_user.id}"
        await connection.execute('''
            INSERT INTO user_number_mrrobot_info (phone_number, user_id, profile_link, invited_by)
            VALUES ($1, $2, $3, $4)
        ''', phone_number, message.from_user.id, profile_link, invited_by)

        # اگر دعوت‌کننده وجود داشت، تعداد دعوت‌هایش را افزایش بده
        if invited_by:
            await connection.execute('''
                UPDATE user_number_mrrobot_info 
                SET invited_users_count = invited_users_count + 1 
                WHERE user_id = $1
            ''', invited_by)

    await state.clear()
    await message.answer("✅ با موفقیت وارد شدید ✅", reply_markup=types.ReplyKeyboardRemove())
    await show_main_menu(message, state)


@dp.callback_query(F.data == "verify_join")
async def verify_join(callback: CallbackQuery, state: FSMContext, pool: asyncpg.Pool):
    if await check_membership(callback.from_user.id):
        await callback.message.delete()
        await callback.message.answer("✅")
        await cmd_start(callback.message, state, pool)  # ✅ اینجا `state` را پاس می‌دهیم
    else:
        await callback.answer("😎 رفیق جوین کانال شو کد تخفیف توش میذاریم و شماره های با کیفیت رو از همه زودتر بهت اطلاع میدیم 😎", show_alert=True)



@dp.callback_query(F.data == "love")
async def love(callback: CallbackQuery):
    messages = [
        "هر شماره‌ای که بخوای همینجا برات آماده‌ست! 😉🔥",
        "با خیال راحت خرید کن، ما حواسمون بهت هست! ❤️",
        "شماره مجازی خاص؟ فقط با چند کلیک اینجاست! 🚀",
        "رفیق، بدون تو اینجا هیچ معنی نداره! ❤️",
        "یه شماره بگیر، یه دنیای جدیدو تجربه کن! 🌍",
        "اینجا همیشه سریع‌ترین و مطمئن‌ترین شماره‌ها رو داری! ✅",
        "هیچ سوالی نذار تو دلت، من اینجام برای جواب دادن! 😎",
        "تو انتخاب کن، من برات آماده می‌کنم! 🎯",
        "هر چی داریم از حمایتای خفن توعه! 😍",
        "خیالت تخت، شماره‌ها همه تست‌شده و تضمینیه! 🔥",
        "اینجا رفیقت کنارته، نه یه فروشنده خشک و بی‌روح! 💙",
        "کاربرای ما مثل خانواده‌مون هستن، همیشه کنارتیم! 💙",
        "تو فقط بگو چی می‌خوای، ما با عشق انجامش می‌دیم! 🔥",
        "قیمت‌ها رو ببین، عاشق رفاقتی بودنمون می‌شی! 🥰",
        "دلمون خوشه که همچین همراهای خفنی داریم! 🤩",
        "هر شماره‌ای که می‌خوای، همینجاس با چند تا کلیک ساده! 🏆",
        "دنبال شماره مجازی بی‌دردسر و سریع هستی؟ بزن بریم! 🚀",
        "این شماره‌ها جادو می‌کنن! سریع، امن، بدون دردسر! ✨",
        "عشق مایی! بدون تو اینجا هیچ معنایی نداره! 🥰",
        "رفیق، ما اینجاییم که سریع‌ترین و بهترینو بهت بدیم! 🔥",
        "تو یه مشتری نیستی، یه رفیق درجه‌یکی! 🤝",
        "یه شماره، یه فرصت جدید، یه تجربه تازه! 🌟",
        "اینجا مشتریامون، دوستای ما هستن! پس راحت باش! 🤗",
        "واسه ما ارزش تو بیشتر از هر چیزیه، همیشه هواتو داریم! 💯",
        "می‌خوای سریع ثبت‌نام کنی؟ شماره مجازی با یه کلیک اینجاست! 🏁",
        "هر روز که اینجایی، یه دلیل جدید واسه شادی ماست! 🎉",
        "هیچ وقت اینقدر راحت شماره نگرفته بودی، امتحان کن! 🎉",
        "با یه شماره، درهای جدید رو به روی خودت باز کن! 🚪",
        "ما برای تو اینجاییم، هر وقت نیاز داشتی، رو ما حساب کن! 💖",
        "پشتیبانی ما همیشه کنارتونه، هر سوالی داشتی بپرس! 💬",
    ]

    random_message = random.choice(messages)  # انتخاب تصادفی از لیست پیام‌ها
    await callback.answer(random_message, show_alert=True)



# بعد از کلاس WalletStates، کلاس‌های جدید را اضافه کنید:
class NumberStates(StatesGroup):
    select_api = State()
    select_service = State()
    select_country = State()
    view_numbers = State()
    confirm_purchase = State()
    waiting_for_code = State()

@dataclass
class Service:
    id: str
    name: str
    active: bool

@dataclass
class Country:
    id: str
    name: str
    active: bool

@dataclass
class NumberInfo:
    id: str
    number: str
    price: int
    repeat: bool
    time: str
    description: str

class NumberLandAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.active = True

    async def get_services(self) -> List[Service]:
        params = {"apikey": self.api_key, "method": "getservice"}
        async with aiohttp.ClientSession() as session:
            async with session.get(NUMBERLAND_BASE_URL, params=params) as resp:
                data = await resp.json()
                return [Service(id=s['id'], name=s['name'], active=bool(s['active'])) for s in data]

    async def get_countries(self) -> List[Country]:
        params = {"apikey": self.api_key, "method": "getcountry"}
        async with aiohttp.ClientSession() as session:
            async with session.get(NUMBERLAND_BASE_URL, params=params) as resp:
                data = await resp.json()
                return [Country(id=c['id'], name=c['name'], active=bool(c['active'])) for c in data]

    async def get_numbers(self, service_id: str, country_id: str) -> List[NumberInfo]:
        params = {
            "apikey": self.api_key,
            "method": "getinfo",
            "service": service_id,
            "country": country_id,
            "operator": "min"
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(NUMBERLAND_BASE_URL, params=params) as resp:
                data = await resp.json()
                return [NumberInfo(
                    id=f"{item['service']}_{item['country']}_{item['operator']}",
                    number="",
                    price=int(item['amount']),
                    repeat=bool(item['repeat']),
                    time=item['time'],
                    description=item.get('description', '')
                ) for item in data]

    async def buy_number(self, service_id: str, country_id: str) -> Optional[Dict]:
        params = {
            "apikey": self.api_key,
            "method": "getnum",
            "service": service_id,
            "country": country_id,
            "operator": "min"
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(NUMBERLAND_BASE_URL, params=params) as resp:
                data = await resp.json()
                if data.get('RESULT') == "1":
                    return data
                return None

    async def check_status(self, number_id: str) -> Optional[Dict]:
        params = {
            "apikey": self.api_key,
            "method": "checkstatus",
            "id": number_id
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(NUMBERLAND_BASE_URL, params=params) as resp:
                return await resp.json()

    async def cancel_number(self, number_id: str) -> bool:
        params = {
            "apikey": self.api_key,
            "method": "cancelnumber",
            "id": number_id
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(NUMBERLAND_BASE_URL, params=params) as resp:
                data = await resp.json()
                return data.get('RESULT') == "1"

class APIManager:
    def __init__(self):
        self.apis = {
            "numberland": NumberLandAPI(NUMBERLAND_API_KEY)
        }
    
    def add_api(self, name: str, api_instance, active: bool = True):
        api_instance.active = active
        self.apis[name] = api_instance
    
    def get_active_apis(self):
        return {name: api for name, api in self.apis.items() if api.active}

# بعد از تعریف bot و dp، API Manager را ایجاد کنید:
api_manager = APIManager()

# بعد از تمام handlerهای موجود، handlerهای جدید را اضافه کنید:
@dp.callback_query(F.data == "number_panel")
async def number_panel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    active_apis = api_manager.get_active_apis()
    
    if not active_apis:
        await callback.answer("در حال حاضر هیچ سرویس فعالی وجود ندارد.", show_alert=True)
        return
    
    if len(active_apis) == 1:
        api_name, api = next(iter(active_apis.items()))
        await state.update_data(current_api=api_name)
        await show_services_menu(callback.message, state)
        return
    
    keyboard_buttons = []
    for api_name, api in active_apis.items():
        keyboard_buttons.append([InlineKeyboardButton(
            text=f"{api_name.upper()} API",
            callback_data=f"select_api_{api_name}"
        )])
    
    keyboard_buttons.append([InlineKeyboardButton(text="🚀 بازگشت", callback_data="show_main_menu")])
    
    await callback.message.edit_text(
        "لطفاً سرویس مورد نظر را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    )
    await state.set_state(NumberStates.select_api)

@dp.callback_query(NumberStates.select_api, F.data.startswith("select_api_"))
async def select_api(callback: CallbackQuery, state: FSMContext):
    api_name = callback.data.split("_")[-1]
    active_apis = api_manager.get_active_apis()
    
    if api_name not in active_apis:
        await callback.answer("سرویس مورد نظر یافت نشد!", show_alert=True)
        return
    
    await state.update_data(current_api=api_name)
    await show_services_menu(callback.message, state)

async def show_services_menu(message: Union[Message, CallbackQuery], state: FSMContext, page: int = 0):
    data = await state.get_data()
    api = api_manager.apis.get(data['current_api'])
    
    services = await api.get_services()
    active_services = [s for s in services if s.active]
    
    chunks = [active_services[i:i+10] for i in range(0, len(active_services), 10)]
    current_page = chunks[page] if page < len(chunks) else []
    
    keyboard_buttons = []
    for i in range(0, len(current_page), 2):
        row = current_page[i:i+2]
        keyboard_buttons.append([
            InlineKeyboardButton(text=service.name, callback_data=f"service_{service.id}")
            for service in row
        ])
    
    navigation_buttons = []
    if page > 0:
        navigation_buttons.append(InlineKeyboardButton(text="⬅️ صفحه قبل", callback_data=f"services_page_{page-1}"))
    if page < len(chunks) - 1:
        navigation_buttons.append(InlineKeyboardButton(text="صفحه بعد ➡️", callback_data=f"services_page_{page+1}"))
    
    if navigation_buttons:
        keyboard_buttons.append(navigation_buttons)
    
    keyboard_buttons.append([InlineKeyboardButton(text="🚀 بازگشت", callback_data="number_panel")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    if isinstance(message, CallbackQuery):
        await message.message.edit_text(
            "🛒 لطفاً سرویس مورد نظر را انتخاب کنید:",
            reply_markup=keyboard
        )
    else:
        await message.answer(
            "🛒 لطفاً سرویس مورد نظر را انتخاب کنید:",
            reply_markup=keyboard
        )
    
    await state.set_state(NumberStates.select_service)
    await state.update_data(services_page=page)

@dp.callback_query(NumberStates.select_service, F.data.startswith("services_page_"))
async def change_services_page(callback: CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[-1])
    await show_services_menu(callback.message, state, page)

@dp.callback_query(NumberStates.select_service, F.data.startswith("service_"))
async def select_service(callback: CallbackQuery, state: FSMContext):
    service_id = callback.data.split("_")[-1]
    await state.update_data(selected_service_id=service_id)
    await show_countries_menu(callback.message, state)

async def show_countries_menu(message: Union[Message, CallbackQuery], state: FSMContext, page: int = 0):
    data = await state.get_data()
    api = api_manager.apis.get(data['current_api'])
    
    countries = await api.get_countries()
    active_countries = [c for c in countries if c.active]
    
    chunks = [active_countries[i:i+10] for i in range(0, len(active_countries), 10)]
    current_page = chunks[page] if page < len(chunks) else []
    
    keyboard_buttons = []
    for i in range(0, len(current_page), 2):
        row = current_page[i:i+2]
        keyboard_buttons.append([
            InlineKeyboardButton(text=country.name, callback_data=f"country_{country.id}")
            for country in row
        ])
    
    navigation_buttons = []
    if page > 0:
        navigation_buttons.append(InlineKeyboardButton(text="⬅️ صفحه قبل", callback_data=f"countries_page_{page-1}"))
    if page < len(chunks) - 1:
        navigation_buttons.append(InlineKeyboardButton(text="صفحه بعد ➡️", callback_data=f"countries_page_{page+1}"))
    
    if navigation_buttons:
        keyboard_buttons.append(navigation_buttons)
    
    keyboard_buttons.append([
        InlineKeyboardButton(text="🔙 بازگشت به سرویس‌ها", callback_data="back_to_services")
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    if isinstance(message, CallbackQuery):
        await message.message.edit_text(
            "🌍 لطفاً کشور مورد نظر را انتخاب کنید:",
            reply_markup=keyboard
        )
    else:
        await message.answer(
            "🌍 لطفاً کشور مورد نظر را انتخاب کنید:",
            reply_markup=keyboard
        )
    
    await state.set_state(NumberStates.select_country)
    await state.update_data(countries_page=page)

@dp.callback_query(NumberStates.select_country, F.data.startswith("countries_page_"))
async def change_countries_page(callback: CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[-1])
    await show_countries_menu(callback.message, state, page)

@dp.callback_query(NumberStates.select_country, F.data == "back_to_services")
async def back_to_services(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await show_services_menu(callback.message, state, data.get('services_page', 0))

@dp.callback_query(NumberStates.select_country, F.data.startswith("country_"))
async def select_country(callback: CallbackQuery, state: FSMContext):
    country_id = callback.data.split("_")[-1]
    data = await state.get_data()
    service_id = data['selected_service_id']
    
    await state.update_data(selected_country_id=country_id)
    await show_numbers_menu(callback.message, state, service_id, country_id)

async def show_numbers_menu(message: Union[Message, CallbackQuery], state: FSMContext, 
                          service_id: str, country_id: str, page: int = 0):
    data = await state.get_data()
    api = api_manager.apis.get(data['current_api'])
    
    numbers = await api.get_numbers(service_id, country_id)
    
    chunks = [numbers[i:i+5] for i in range(0, len(numbers), 5)]
    current_page = chunks[page] if page < len(chunks) else []
    
    keyboard_buttons = []
    for number in current_page:
        keyboard_buttons.append([
            InlineKeyboardButton(
                text=f"{number.price:,} تومان - {number.time} - {'🔁' if number.repeat else '❌'}",
                callback_data=f"number_{number.id}"
            )
        ])
    
    navigation_buttons = []
    if page > 0:
        navigation_buttons.append(InlineKeyboardButton(text="⬅️ صفحه قبل", callback_data=f"numbers_page_{page-1}"))
    if page < len(chunks) - 1:
        navigation_buttons.append(InlineKeyboardButton(text="صفحه بعد ➡️", callback_data=f"numbers_page_{page+1}"))
    
    if navigation_buttons:
        keyboard_buttons.append(navigation_buttons)
    
    keyboard_buttons.append([
        InlineKeyboardButton(text="🔙 بازگشت به کشورها", callback_data="back_to_countries")
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    if isinstance(message, CallbackQuery):
        await message.message.edit_text(
            "📱 لطفاً شماره مورد نظر را انتخاب کنید:",
            reply_markup=keyboard
        )
    else:
        await message.answer(
            "📱 لطفاً شماره مورد نظر را انتخاب کنید:",
            reply_markup=keyboard
        )
    
    await state.set_state(NumberStates.view_numbers)
    await state.update_data(numbers_page=page)

@dp.callback_query(NumberStates.view_numbers, F.data.startswith("numbers_page_"))
async def change_numbers_page(callback: CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[-1])
    data = await state.get_data()
    await show_numbers_menu(
        callback.message, state, 
        data['selected_service_id'], 
        data['selected_country_id'], 
        page
    )

@dp.callback_query(NumberStates.view_numbers, F.data == "back_to_countries")
async def back_to_countries(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await show_countries_menu(callback.message, state, data.get('countries_page', 0))

@dp.callback_query(NumberStates.view_numbers, F.data.startswith("number_"))
async def select_number(callback: CallbackQuery, state: FSMContext):
    number_id = callback.data.split("_")[-1]
    await state.update_data(selected_number_id=number_id)
    
    data = await state.get_data()
    api = api_manager.apis.get(data['current_api'])
    
    numbers = await api.get_numbers(data['selected_service_id'], data['selected_country_id'])
    selected_number = next((n for n in numbers if n.id == number_id), None)
    
    if not selected_number:
        await callback.answer("شماره مورد نظر یافت نشد!", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ خرید", callback_data="confirm_buy"),
            InlineKeyboardButton(text="🔙 بازگشت", callback_data="back_to_numbers")
        ]
    ])
    
    await callback.message.edit_text(
        f"📋 اطلاعات شماره:\n\n"
        f"💰 قیمت: {selected_number.price:,} تومان\n"
        f"⏳ مدت زمان: {selected_number.time}\n"
        f"🔁 دریافت مجدد کد: {'✅' if selected_number.repeat else '❌'}\n"
        f"📝 توضیحات: {selected_number.description}\n\n"
        f"آیا مایل به خرید این شماره هستید؟",
        reply_markup=keyboard
    )
    
    await state.set_state(NumberStates.confirm_purchase)

@dp.callback_query(NumberStates.confirm_purchase, F.data == "back_to_numbers")
async def back_to_numbers(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await show_numbers_menu(
        callback.message, state,
        data['selected_service_id'],
        data['selected_country_id'],
        data.get('numbers_page', 0)
    )

async def check_code_periodically(message: Message, state: FSMContext):
    data = await state.get_data()
    api = api_manager.apis.get(data.get('current_api'))
    
    if not api:
        return
    
    for _ in range(6):
        await asyncio.sleep(20)
        
        data = await state.get_data()
        if 'purchased_number_id' not in data:
            break
        
        status = await api.check_status(data['purchased_number_id'])
        if status and status.get('RESULT') == 2:
            await message.edit_text(
                f"✅ کد دریافت شد!\n\n"
                f"📞 شماره: {data['purchased_number']}\n"
                f"🔢 کد: {status['CODE']}\n\n"
                f"با تشکر از خرید شما!",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 بازگشت به منوی اصلی", callback_data="show_main_menu")]
                ])
            )
            await state.clear()
            return
    
    if await state.get_state() == NumberStates.waiting_for_code:
        await message.edit_text(
            f"⏳ زمان دریافت کد به پایان رسید!\n\n"
            f"📞 شماره: {data['purchased_number']}\n"
            f"🕒 زمان: {data['purchase_time']}\n\n"
            f"در صورتی که کدی دریافت نکرده‌اید، می‌توانید درخواست لغو دهید.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ لغو و بازگشت وجه", callback_data="cancel_purchase")],
                [InlineKeyboardButton(text="🏠 بازگشت به منوی اصلی", callback_data="show_main_menu")]
            ])
        )

@dp.callback_query(NumberStates.confirm_purchase, F.data == "confirm_buy")
async def confirm_buy_number(callback: CallbackQuery, state: FSMContext, pool: asyncpg.Pool):
    user_id = callback.from_user.id
    data = await state.get_data()
    api = api_manager.apis.get(data['current_api'])
    
    async with pool.acquire() as connection:
        balance = await connection.fetchval(
            'SELECT wallet_balance FROM user_number_mrrobot_info WHERE user_id = $1',
            user_id
        )
        
        numbers = await api.get_numbers(data['selected_service_id'], data['selected_country_id'])
        selected_number = next((n for n in numbers if n.id == data['selected_number_id']), None)
        
        if not selected_number:
            await callback.answer("شماره مورد نظر یافت نشد!", show_alert=True)
            return
        
        if balance < selected_number.price:
            await callback.message.edit_text(
                f"موجودی کیف پول شما کافی نیست!\n\n"
                f"💰 موجودی شما: {balance:,} تومان\n"
                f"💸 قیمت شماره: {selected_number.price:,} تومان\n\n"
                "لطفاً کیف پول خود را شارژ کنید.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💳 شارژ کیف پول", callback_data="wallet_panel")],
                    [InlineKeyboardButton(text="🔙 بازگشت", callback_data="back_to_numbers")]
                ])
            )
            return
    
    purchase_result = await api.buy_number(
        data['selected_service_id'],
        data['selected_country_id']
    )
    
    if not purchase_result:
        await callback.answer("خطا در خرید شماره! لطفاً مجدداً تلاش کنید.", show_alert=True)
        return
    
    async with pool.acquire() as connection:
        await connection.execute(
            '''UPDATE user_number_mrrobot_info 
               SET wallet_balance = wallet_balance - $1 
               WHERE user_id = $2''',
            selected_number.price,
            user_id
        )
    
    await state.update_data(
        purchased_number_id=purchase_result['ID'],
        purchased_number=purchase_result['NUMBER'],
        purchased_amount=selected_number.price,
        purchase_time=datetime.now().isoformat()
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 دریافت کد", callback_data="get_code")],
        [InlineKeyboardButton(text="❌ لغو و بازگشت وجه", callback_data="cancel_purchase")]
    ])
    
    await callback.message.edit_text(
        f"✅ شماره با موفقیت خریداری شد!\n\n"
        f"📞 شماره: {purchase_result['NUMBER']}\n"
        f"⏳ زمان باقی‌مانده: {purchase_result['TIME']}\n"
        f"🔁 دریافت مجدد کد: {'✅' if purchase_result['REPEAT'] == '1' else '❌'}\n\n"
        f"لطفاً در سرویس مورد نظر این شماره را وارد کنید و سپس روی دکمه دریافت کد کلیک کنید.",
        reply_markup=keyboard
    )
    
    asyncio.create_task(check_code_periodically(callback.message, state))
    await state.set_state(NumberStates.waiting_for_code)

@dp.callback_query(NumberStates.waiting_for_code, F.data == "get_code")
async def get_sms_code(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    api = api_manager.apis.get(data['current_api'])
    
    status = await api.check_status(data['purchased_number_id'])
    
    if not status or status.get('RESULT') not in [1, 2, 5]:
        await callback.answer("هنوز کدی دریافت نشده است. لطفاً کمی صبر کنید...", show_alert=True)
        return
    
    if status['RESULT'] == 2:
        await callback.message.edit_text(
            f"✅ کد دریافت شد!\n\n"
            f"📞 شماره: {data['purchased_number']}\n"
            f"🔢 کد: {status['CODE']}\n\n"
            f"با تشکر از خرید شما!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 بازگشت به منوی اصلی", callback_data="show_main_menu")]
            ])
        )
        await state.clear()
    elif status['RESULT'] in [1, 5]:
        await callback.answer("کد هنوز دریافت نشده است. لطفاً کمی صبر کنید...", show_alert=True)

@dp.callback_query(NumberStates.waiting_for_code, F.data == "cancel_purchase")
async def cancel_purchase(callback: CallbackQuery, state: FSMContext, pool: asyncpg.Pool):
    data = await state.get_data()
    user_id = callback.from_user.id
    api = api_manager.apis.get(data['current_api'])
    
    success = await api.cancel_number(data['purchased_number_id'])
    
    if success:
        async with pool.acquire() as connection:
            await connection.execute(
                '''UPDATE user_number_mrrobot_info 
                   SET wallet_balance = wallet_balance + $1 
                   WHERE user_id = $2''',
                data['purchased_amount'],
                user_id
            )
        
        await callback.message.edit_text(
            "✅ خرید شما لغو شد و مبلغ به کیف پول شما بازگشت داده شد.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 بازگشت به منوی اصلی", callback_data="show_main_menu")]
            ])
        )
    else:
        await callback.message.edit_text(
            "❌ خطا در لغو خرید! لطفاً با پشتیبانی تماس بگیرید.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 بازگشت به منوی اصلی", callback_data="show_main_menu")]
            ])
        )
    
    await state.clear()


@dp.callback_query(F.data == "pay_accept")
async def cannot_edit_phone(callback: CallbackQuery):
    await callback.answer("❗ بعد از تکمیل پرداخت بر روی گزینه ✅تکمیل پرداخت✅ کلیک کنید ❗", show_alert=True)

@dp.callback_query(F.data == "no_edit")
async def cannot_edit_phone(callback: CallbackQuery):
    await callback.answer("🚨 Error Code : 2 🚨         جهت تغییر شماره همراه با پشتیبانی در ارتباط باشید", show_alert=True)
    
@dp.callback_query(F.data == "user_panel")
async def user_panel(callback: CallbackQuery, state: FSMContext, pool: asyncpg.Pool):
    user_id = callback.from_user.id
        # حذف پیام‌های قبلی از state
    state_data = await state.get_data()
    messages_to_delete = state_data.get('messages_to_delete', [])

    for msg_id in messages_to_delete:
        try:
            await callback.bot.delete_message(chat_id=callback.message.chat.id, message_id=msg_id)
        except:
            pass

    # خواندن اطلاعات کاربر از دیتابیس به روش بهینه
    async with pool.acquire() as connection:
        # ابتدا شماره تلفن کاربر را بگیریم
        phone_number = await connection.fetchval(
            'SELECT phone_number FROM user_number_mrrobot_info WHERE user_id = $1',
            user_id
        )
        
        # اگر شماره تلفن وجود داشت، اطلاعات کاربر را بگیریم
        user_info = None
        if phone_number:
            user_info = await connection.fetchrow(
                'SELECT * FROM user_info WHERE phone_number = $1',
                phone_number
            )

    if not user_info:
        await callback.answer("🚨 Error code : 1 🚨         موضوع را به پشتیبانی اطلاع دهید")
        return

    # تابع کمکی برای نمایش مقادیر خالی
    def get_field(value, _):
        return value if value else "خالی"

    # ساخت دکمه‌های پویا
    fields = [
        ("نام", user_info['first_name'], "first_name"),
        ("نام خانوادگی", user_info['last_name'], "last_name"),
        ("نام پدر", user_info['father_name'], "father_name"),
        ("کد ملی", user_info['national_code'], "national_code"),
        ("شماره کارت", user_info['credit_card'], "credit_card"),
        ("تاریخ تولد", user_info['birth_date'], "birth_date"),
        ("شماره همراه", user_info['phone_number'], "phone_number"),
        ("آدرس", user_info['address'], "address"),
        ("ایمیل", user_info['email'], "email"),
        ("کد پستی", user_info['postal_code'], "postal_code")
    ]

    # ساخت کیبورد به صورت پویا
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{field}: {get_field(value, field)}", 
            callback_data="no_edit" if field == "شماره همراه" else f"edit_{field_name}"
        )]
        for field, value, field_name in fields
    ] + [
        [InlineKeyboardButton(text="🚀", callback_data="show_main_menu")]
    ])

    try:
        await callback.message.edit_text(
            "🧑‍🚀 پنل کاربری 🧑‍🚀\n\n👇 برای تکمیل و یا تغییر اطلاعات پروفایل خود از دکمه‌های زیر استفاده کنید 👇",
            reply_markup=keyboard
        )
    except TelegramBadRequest:
        pass



@dp.callback_query(F.data.startswith("edit_"))
async def edit_user_info(callback: CallbackQuery, state: FSMContext):
    field_to_edit = "_".join(callback.data.split("_")[1:])  # اصلاح اینجا
    
    state_mapping = {
        "first_name": EditUserInfo.waiting_for_first_name,
        "last_name": EditUserInfo.waiting_for_last_name,
        "father_name": EditUserInfo.waiting_for_father_name,
        "national_code": EditUserInfo.waiting_for_national_code,
        "credit_card": EditUserInfo.waiting_for_credit_card,
        "birth_date": EditUserInfo.waiting_for_birth_date,
        "address": EditUserInfo.waiting_for_address,
        "email": EditUserInfo.waiting_for_email,
        "postal_code": EditUserInfo.waiting_for_postal_code,
    }
    

    await state.set_state(state_mapping[field_to_edit])

    await state.update_data(messages_to_delete=[callback.message.message_id])


    
    # ارسال پیام جدید و ذخیره ID آن
    sent_msg = await callback.message.answer(
        "🍄 اطلاعات جدید را ارسال کنید 🍄",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 بازگشت", callback_data="user_panel")]
        ])
    )
    await state.update_data(messages_to_delete=[callback.message.message_id, sent_msg.message_id])



@dp.message(F.text)
async def update_user_info(message: Message, state: FSMContext, pool: asyncpg.Pool):
    current_state = await state.get_state()
    
    # اگر کاربر در حال ویرایش اطلاعات نیست، پیام را نادیده بگیر
    if not current_state or not current_state.startswith("EditUserInfo:"):
        return
    
        # دریافت message_id از state
    state_data = await state.get_data()
    messages_to_delete = state_data.get('messages_to_delete', [])
    edit_message_id = state_data.get('edit_message_id')

    # حذف پیام‌های قبلی
    for msg_id in messages_to_delete:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=msg_id)
        except:
            pass
    
    # حذف پیام کاربر
    try:
        await message.delete()
    except:
        pass


    # نگاشت فیلدها
    field_mapping = {
        "EditUserInfo:waiting_for_first_name": ("first_name", "نام"),
        "EditUserInfo:waiting_for_last_name": ("last_name", "نام خانوادگی"),
        "EditUserInfo:waiting_for_father_name": ("father_name", "نام پدر"),
        "EditUserInfo:waiting_for_national_code": ("national_code", "کد ملی"),
        "EditUserInfo:waiting_for_credit_card": ("credit_card", "کد ملی"),
        "EditUserInfo:waiting_for_birth_date": ("birth_date", "تاریخ تولد"),
        "EditUserInfo:waiting_for_address": ("address", "آدرس"),
        "EditUserInfo:waiting_for_email": ("email", "ایمیل"),
        "EditUserInfo:waiting_for_postal_code": ("postal_code", "کد پستی"),
    }
    
    db_field, field_name = field_mapping.get(current_state, (None, None))
    if not db_field:
        return
    
    # اعتبارسنجی داده‌ها
    validation_rules = {
        "national_code": (r'^\d{10}$', "کد ملی باید 10 رقم باشد."),
        "credit_card": (r'^\d{16}$', "شماره کارت باید 16 رقم باشد."),
        "email": (r'^[\w\.-]+@[\w\.-]+\.\w+$', "فرمت ایمیل نامعتبر است."),
        "birth_date": (r'^\d{4}-\d{2}-\d{2}$', "تاریخ تولد باید YYYY-MM-DD باشد."),
        "postal_code": (r'^\d{10}$', "کد پستی باید 10 رقم باشد."),
    }

    if db_field in validation_rules:
        regex, error_msg = validation_rules[db_field]
        if not re.match(regex, message.text):
            await message.answer(
                error_msg,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🚀 بازگشت به منوی کاربری", callback_data="user_panel")]]
                )
            )
            return
    # بهینه‌سازی: ابتدا شماره تلفن را بگیریم
    async with pool.acquire() as connection:
        phone_number = await connection.fetchval(
            'SELECT phone_number FROM user_number_mrrobot_info WHERE user_id = $1',
            message.from_user.id
        )
        
        if phone_number:
            # آپدیت اطلاعات با استفاده از شماره تلفن
            await connection.execute(
                f"UPDATE user_info SET {db_field} = $1 WHERE phone_number = $2",
                message.text, phone_number
            )
    
    # ارسال پیام تأیید
    confirm_msg = await message.answer(
        "✅ اطلاعات با موفقیت به‌روزرسانی شد ✅",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🧑‍🚀 بازگشت به پنل کاربری", callback_data="user_panel")]]
        ))
    
    # ذخیره ID پیام تأیید برای حذف بعدی
    await state.update_data(messages_to_delete=[confirm_msg.message_id])
    await state.clear()


@dp.callback_query(F.data == "show_main_menu")
async def show_main_menu(entity: Union[Message, CallbackQuery], state: FSMContext = None):
    if isinstance(entity, CallbackQuery):
        user_id = entity.from_user.id
    else:
        user_id = entity.from_user.id

    if state:
        await state.clear()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 پنل خرید شماره 🚀", callback_data="number_panel")],
        [InlineKeyboardButton(text="🛰️ کیف پول 🛰️", callback_data="wallet_panel"),
         InlineKeyboardButton(text="🛸 کسب درآمد 🛸", callback_data="income_panel")],
        [InlineKeyboardButton(text="🧑‍🚀 پنل کاربری 🧑‍🚀", callback_data="user_panel"),
         InlineKeyboardButton(text="☄️ مهم ☄️", callback_data="love")],
        [InlineKeyboardButton(text="🏪 سوالات متداول و پشتیبانی 🏪", callback_data="support_menu")],
    ])

    if isinstance(entity, Message):
        await entity.answer("🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀", reply_markup=keyboard)
    elif isinstance(entity, CallbackQuery):
        try:
            await entity.message.edit_text("🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀", reply_markup=keyboard)
        except TelegramBadRequest:
            pass

    # حذف پیام بنر اگر وجود دارد
    if user_id in user_last_banner_message:
        try:
            await bot.delete_message(chat_id=entity.message.chat.id, message_id=user_last_banner_message[user_id])
            del user_last_banner_message[user_id]
        except:
            pass



@dp.callback_query(F.data == "income_panel")
async def user_panel(callback: CallbackQuery, state: FSMContext, pool: asyncpg.Pool):
    user_id = callback.from_user.id

    async with pool.acquire() as connection:
        user_data = await connection.fetchrow(
            '''
            SELECT 
                ui.*,  
                umi.user_id AS mrrobot_user_id,
                umi.profile_link,
                umi.wallet_balance,
                umi.invited_users_count,
                umi.invited_by,
                umi.referral_income
            FROM 
                user_info ui
            JOIN 
                user_number_mrrobot_info umi ON ui.phone_number = umi.phone_number
            WHERE 
                umi.user_id = $1
            ''',
            user_id
        )

    if not user_data:
        await callback.answer("🚨 Error code : 1             🚨 موضوع را به پشتیبانی اطلاع دهید")
        return

    # اطلاعات کاربر
    user_id = callback.from_user.id
    invited_count = user_data['invited_users_count'] or 0
    income = user_data['referral_income'] or 0
    invited_by = user_data['invited_by']

    # ساخت کیبورد
    keyboard_buttons = [
        [InlineKeyboardButton(text=f"👥 تعداد دعوت‌ها: {invited_count}", callback_data="dummy")],
        [InlineKeyboardButton(text=f"🎯 درآمد شما: {income:,} تومان", callback_data="dummy")]
    ]

    if invited_by:
        try:
            inviter = await bot.get_chat(invited_by)
            inviter_name = inviter.first_name or "کاربر"
            keyboard_buttons.append(
                [InlineKeyboardButton(text=f"👤 دعوت‌شده توسط: {inviter_name}", callback_data="dummy")]
            )
        except:
            pass

    if income >= 10000:
        keyboard_buttons.append(
            [InlineKeyboardButton(text="💳 درخواست برداشت", callback_data="withdraw_request")]
        )
    else:
        keyboard_buttons.append(
            [InlineKeyboardButton(text="🚫 حداقل برداشت: 10,000 تومان", callback_data="dummy")]
        )

    # دکمه بازگشت به منو
    keyboard_buttons.append(
        [InlineKeyboardButton(text="🚀", callback_data="show_main_menu")]
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    # 1. ویرایش پیام فعلی به توضیحات سیستم همکاری
    await callback.message.edit_text(
        "🎉 اینجا پنل همکاری شماست!\n\n"
        "هرکس از لینک شخصی شما وارد ربات شود، مادام‌العمر به ازای هر بار شارژ کیف پول، "
        "۵٪ مبلغ به حساب شما واریز می‌شود.",
        reply_markup=keyboard
    )

    # 2. تاخیر ۲ ثانیه‌ای
    await asyncio.sleep(2)

    # 3. ارسال پیام جدید حاوی لینک اختصاصی
    referral_link = f"https://t.me/number_mrrobot?start=ref_{user_id}"
    banner_msg = await callback.message.answer(
        f"📱 شماره مجازی فوری برای همه برنامه‌ها\n"
        f"⚡ فعال‌سازی آنی + تضمین بازگشت وجه\n"
        f"🎁 تخفیف ۵۰٪ با کد: NEW\n\n"
        f"{referral_link}"
    )

    # ذخیره پیام آخر لینک برای حذف در آینده
    user_last_banner_message[user_id] = banner_msg.message_id


@dp.callback_query(F.data == "withdraw_request")
async def withdraw_request(callback: CallbackQuery, state: FSMContext, pool: asyncpg.Pool):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    
    # دیکشنری برای ذخیره پیام‌های بنر (در سطح ماژول تعریف شود)
    global user_last_banner_message
    
    async with pool.acquire() as connection:
        user_data = await connection.fetchrow(
            '''SELECT 
                ui.first_name, ui.last_name,
                ui.credit_card,
                umi.referral_income
            FROM user_info ui
            JOIN user_number_mrrobot_info umi ON ui.phone_number = umi.phone_number
            WHERE umi.user_id = $1''',
            user_id
        )

        if not user_data:
            await callback.answer("🚨 Error code : 1 🚨         موضوع را به پشتیبانی اطلاع دهید")
            return

        if not user_data['credit_card']:
            await callback.message.edit_text(
                "🔒 برای برداشت، ابتدا پروفایل‌ رو کامل کن (نام + کارت بانکی).",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🚀", callback_data="show_main_menu")]
                ])
            )
            return

        if user_data['referral_income'] < 10000:
            await callback.message.edit_text(
                f"💰 موجودی شما: {user_data['referral_income']:,} تومان\n"
                "حداقل برداشت: 10,000 تومان",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🚀", callback_data="show_main_menu")]
                ])
            )
            return

        await state.update_data(
            amount=user_data['referral_income'],
            bank_card=user_data['credit_card'],
            account_name=f"{user_data['first_name']} {user_data['last_name']}"
        )

        # حذف پیام بنر اگر وجود دارد
        if user_id in user_last_banner_message:
            try:
                await bot.delete_message(
                    chat_id=chat_id,
                    message_id=user_last_banner_message[user_id]
                )
                del user_last_banner_message[user_id]
            except Exception as e:
                print(f"Error deleting banner message: {e}")

        await callback.message.edit_text(
            f"⚠️ برداشت قطعی؟\n\n"
            f"💸 مبلغ: {user_data['referral_income']:,} تومان\n"
            f"💳 کارت: {user_data['credit_card']}\n"
            f"👤 به‌نام: {user_data['first_name']} {user_data['last_name']}\n\n"
            "❗درصورت عدم تطابق اطلاعات، مبلغ حذف می‌شود❗",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ بله", callback_data="confirm_withdraw")],
                [InlineKeyboardButton(text="❌ نه، برگشت", callback_data="show_main_menu")]
            ])
        )

        await state.set_state(WithdrawalStates.confirm_withdrawal)

@dp.callback_query(WithdrawalStates.confirm_withdrawal, F.data == "confirm_withdraw")
async def confirm_withdrawal(callback: CallbackQuery, state: FSMContext, pool: asyncpg.Pool):
    user_id = callback.from_user.id
    data = await state.get_data()

    async with pool.acquire() as connection:
        await connection.execute(
            '''UPDATE user_number_mrrobot_info 
               SET referral_income = referral_income - $1
               WHERE user_id = $2''',
            data['amount'], user_id
        )

        await bot.send_message(
            ADMIN_ID,
            f"📤 برداشت جدید:\n\n"
            f"👤 {callback.from_user.full_name}\n"
            f"🆔 {user_id}\n"
            f"💰 {data['amount']:,} تومان\n"
            f"💳 {data['bank_card']}\n"
            f"📛 {data['account_name']}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ تایید", callback_data=f"approve_{user_id}_{data['amount']}")],
                [InlineKeyboardButton(text="❌ رد", callback_data=f"reject_{user_id}")]
            ])
        )

        await callback.message.edit_text(
            "✅ درخواست ثبت شد.\nمنتظر تایید ادمین باش.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚀", callback_data="show_main_menu")]
            ])
        )

    await state.clear()

@dp.callback_query(F.data.startswith("approve_"))
async def approve_withdrawal(callback: CallbackQuery, pool: asyncpg.Pool):
    _, user_id, amount = callback.data.split("_")
    
    await bot.send_message(
        user_id,
        "✅ برداشت تایید شد.\nتا ۷ روز کاری مبلغ واریز می‌شه.\n❤️ ممنون که با مایی!"
    )

    await callback.message.delete()

@dp.callback_query(F.data.startswith("reject_"))
async def reject_withdrawal(callback: CallbackQuery, pool: asyncpg.Pool):
    _, user_id = callback.data.split("_")

    await bot.send_message(
        user_id,
        "❌ برداشت شما رد شد.\n\n"
        "📍ممکنه کارت نادرست یا نام تطابق نداشته باشه.\n"
        "⚠️ طبق قوانین، مبلغ حذف شد."
    )

    await callback.message.edit_text(
        callback.message.text + "\n\n❌ این درخواست رد شد.",
        reply_markup=None
    )




@dp.callback_query(F.data == "wallet_panel")
async def wallet_panel(callback: CallbackQuery, state: FSMContext, pool: asyncpg.Pool):
    """نمایش پنل کیف پول و موجودی کاربر"""
    user_id = callback.from_user.id
    
    async with pool.acquire() as connection:
        balance = await connection.fetchval(
            'SELECT wallet_balance FROM user_number_mrrobot_info WHERE user_id = $1',
            user_id
        )
    
    if balance is None:
        await callback.answer("🚨 Error code : 1 🚨 موضوع را به پشتیبانی اطلاع دهید", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 شارژ کیف پول", callback_data="charge_wallet")],
        [InlineKeyboardButton(text="🚀 بازگشت", callback_data="show_main_menu")]
    ])
    
    await callback.message.edit_text(
        f"💳 موجودی کیف پول شما: {balance:,} تومان\n"
        f"❗ بعد از تکمیل پرداخت بر روی گزینه ✅تکمیل پرداخت✅ کلیک کنید ❗",
        reply_markup=keyboard
    )
    await state.set_state(WalletStates.show_wallet)

@dp.callback_query(WalletStates.show_wallet, F.data == "charge_wallet")
async def charge_wallet(callback: CallbackQuery, state: FSMContext):
    """منوی انتخاب مبلغ برای شارژ"""
    amounts = [
        [1_00, 19_999, 29_999],
        [49_999, 79_999, 99_999],
        [199_999, 299_999, 499_999],
        [999_999]
    ]
    
    keyboard_buttons = []
    for row in amounts:
        keyboard_buttons.append([
            InlineKeyboardButton(text=f"{amount:,} تومان", callback_data=f"charge_{amount}")
            for amount in row
        ])
    
    keyboard_buttons.append([
        InlineKeyboardButton(
            text="❗ بعد از تکمیل پرداخت بر روی گزینه ✅تکمیل پرداخت✅ کلیک کنید ❗",
            callback_data="pay_accept"
        )
    ])
    
    keyboard_buttons.append([
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="wallet_panel")
    ])
    
    await callback.message.edit_text(
        "لطفاً مبلغ مورد نظر برای شارژ را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    )
    await state.set_state(WalletStates.select_amount)

@dp.callback_query(WalletStates.select_amount, F.data.startswith("charge_"))
async def process_preselected_amount(callback: CallbackQuery, state: FSMContext):
    """پردازش مبلغ از پیش تعیین شده"""
    try:
        amount = int(callback.data.split("_")[1])
        await state.update_data(amount=amount)
        await initiate_payment(callback.message, state)
    except Exception as e:
        logger.error(f"Error in process_preselected_amount: {e}")
        await callback.answer("خطا در پردازش مبلغ انتخاب شده", show_alert=True)

async def initiate_payment(message: Union[Message, CallbackQuery], state: FSMContext):
    """آغاز فرآیند پرداخت با زرین‌پال"""
    try:
        data = await state.get_data()
        amount_toman = data['amount']
        user_id = message.from_user.id

        # محاسبه مالیات 10% و مبلغ نهایی
        tax = int(amount_toman * 0.1)  # 10% مالیات
        final_amount = amount_toman + tax
        amount_rial = final_amount * 10  # تبدیل به ریال
        
        # ذخیره اطلاعات در state
        await state.update_data(
            original_amount=amount_toman,
            tax_amount=tax,
            final_amount=final_amount,
            amount_rial=amount_rial
        )
        
        # ایجاد درخواست پرداخت به زرین‌پال
        payload = {
            "merchant_id": ZARINPAL_MERCHANT_ID,
            "amount": amount_rial,  # استفاده از مبلغ ریال
            "callback_url": ZARINPAL_CALLBACK_URL,
            "description": f"شارژ کیف پول ربات شماره مجازی - کاربر {user_id}",
            "metadata": {
                "mobile": str(user_id),
                "email": f"user{user_id}@mrrobotpy.chbk.app"
            }
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ZARINPAL_REQUEST_URL,
                json=payload,
                headers={'accept': 'application/json', 'content-type': 'application/json'}
            ) as response:
                result = await response.json()
                
                if 'data' in result and result['data'].get('code') == 100:
                    authority = result['data']['authority']
                    payment_url = f"{ZARINPAL_PAYMENT_URL}{authority}"
                    
                    await state.update_data(
                        authority=authority,
                        payment_url=payment_url
                    )
                    
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="💳 پرداخت آنلاین", url=payment_url)],
                        [InlineKeyboardButton(text="✅ تکمیل پرداخت ✅", callback_data="check_payment")],
                        [InlineKeyboardButton(text="❌ انصراف", callback_data="wallet_panel")]
                    ])
                    
                    text = (
                        f"💳 مبلغ اصلی: {amount_toman:,} تومان\n"
                        f"💰 هزینه جانبی (10%): {tax:,} تومان\n"
                        f"💸 مبلغ کل: {final_amount:,} تومان\n\n"
                        "لطفاً برای پرداخت روی دکمه زیر کلیک کنید:"
                    )
                    
                    if isinstance(message, Message):
                        await message.answer(text, reply_markup=keyboard)
                    else:
                        await message.edit_text(text, reply_markup=keyboard)
                    
                    await state.set_state(WalletStates.process_payment)
                else:
                    error_msg = result.get('errors', {}).get('message', 'خطای نامشخص از زرین‌پال')
                    await message.answer(f"خطا در اتصال به درگاه پرداخت: {error_msg}")
    
    except Exception as e:
        logger.error(f"Error initiating payment: {e}")
        await message.answer("خطا در ارتباط با درگاه پرداخت. لطفاً مجدداً تلاش کنید.")

@dp.callback_query(WalletStates.process_payment, F.data == "check_payment")
async def verify_payment(callback: CallbackQuery, state: FSMContext, pool: asyncpg.Pool):
    """بررسی وضعیت پرداخت کاربر"""
    try:
        data = await state.get_data()
        original_amount = data['original_amount']  # مبلغ بدون مالیات
        tax_amount = data['tax_amount']  # مقدار مالیات
        final_amount = data['final_amount']  # مبلغ با مالیات
        amount_rial = data['amount_rial']
        authority = data['authority']
        user_id = callback.from_user.id
        
        # بررسی پرداخت با زرین‌پال
        payload = {
            "merchant_id": ZARINPAL_MERCHANT_ID,
            "amount": amount_rial,  # استفاده از مبلغ ریال
            "authority": authority
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ZARINPAL_VERIFY_URL,
                json=payload,
                headers={'accept': 'application/json', 'content-type': 'application/json'}
            ) as response:
                result = await response.json()
                
                if 'data' in result and result['data'].get('code') in (100, 101):
                    # پرداخت موفقیت‌آمیز بود
                    ref_id = result['data'].get('ref_id', 'نامشخص')
                    
                    async with pool.acquire() as connection:
                        # افزایش موجودی کیف پول کاربر (بدون مالیات)
                        await connection.execute(
                            '''UPDATE user_number_mrrobot_info 
                            SET wallet_balance = wallet_balance + $1 
                            WHERE user_id = $2''',
                            original_amount,
                            user_id
                        )
                        
                        # پیدا کردن کاربر دعوت کننده
                        invited_by = await connection.fetchval(
                            'SELECT invited_by FROM user_number_mrrobot_info WHERE user_id = $1',
                            user_id
                        )
                        
                        # اگر کاربر دعوت کننده وجود داشت، مالیات را به حسابش اضافه کن
                        if invited_by:
                            await connection.execute(
                                '''UPDATE user_number_mrrobot_info 
                                SET referral_income = referral_income + $1 
                                WHERE user_id = $2''',
                                tax_amount,
                                invited_by
                            )
                    
                    # نمایش پیام موفقیت
                    new_balance = await get_wallet_balance(pool, user_id)
                    success_text = (
                        f"✅ پرداخت شما با موفقیت انجام شد\n\n"
                        f"💳 مبلغ اصلی: {original_amount:,} تومان\n"
                        f"💰 هزینه جانبی (10%): {tax_amount:,} تومان\n"
                        f"💸 مبلغ کل پرداختی: {final_amount:,} تومان\n"
                        f"🆔 کد پیگیری: {ref_id}\n"
                        f"💎 موجودی جدید شما: {new_balance:,} تومان"
                    )
                    
                    await callback.message.edit_text(
                        success_text,
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="🏠 بازگشت به منوی اصلی", callback_data="show_main_menu")]
                        ])
                    )
                    
                    # اطلاع به ادمین
                    admin_text = (
                        f"💰 تراکنش موفق:\n"
                        f"👤 کاربر: {callback.from_user.full_name}\n"
                        f"🆔 آیدی: {user_id}\n"
                        f"💳 مبلغ اصلی: {original_amount:,} تومان\n"
                        f"🧾 هزینه جانبی: {tax_amount:,} تومان\n"
                        f"💸 مبلغ کل: {final_amount:,} تومان\n"
                        f"🆔 کد پیگیری: {ref_id}"
                    )
                    await bot.send_message(ADMIN_ID, admin_text)
                    
                    await state.clear()
                else:
                    error_code = result.get('data', {}).get('code', 'نامشخص')
                    error_message = {
                        101: "این تراکنش قبلاً ثبت شده است",
                        -9: "خطای اعتبار سنجی",
                        -10: "آی پی یا مرچنت کد پذیرنده صحیح نیست",
                        -11: "مرچنت کد فعال نیست",
                        -12: "تلاش بیش از حد در یک بازه زمانی کوتاه",
                        -15: "ترمینال شما به حالت تعلیق درآمده است",
                        -16: "سطح تایید پذیرنده پایین تر از سطح نقره ای است",
                        -30: "اجازه دسترسی به تسویه اشتراکی شناور ندارید",
                        -31: "حساب بانکی تسویه را به پنل اضافه کنید",
                        -32: "مبلغ تسویه بیشتر از حد مجاز است",
                        -33: "درخواست تسویه مبلغ کمتر از حداقل مجاز"
                    }.get(error_code, f"کد خطا: {error_code}")
                    
                    await callback.message.edit_text(
                        f"❌ پرداخت شما تایید نشد.\nدلیل: {error_message}\n\n"
                        "در صورت کسر وجه، طی 72 ساعت به حساب شما بازمی‌گردد.",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="🔁 تلاش مجدد", callback_data="charge_wallet")],
                            [InlineKeyboardButton(text="🏠 بازگشت", callback_data="show_main_menu")]
                        ])
                    )
    
    except Exception as e:
        logger.error(f"Error verifying payment: {e}")
        await callback.message.edit_text(
            "لطفا ابتدا پرداخت را انجام دهید سپس این دکمه را وارد کنید",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 بازگشت", callback_data="show_main_menu")]
            ])
        )

async def get_wallet_balance(pool: asyncpg.Pool, user_id: int) -> int:
    """دریافت موجودی کیف پول کاربر"""
    async with pool.acquire() as connection:
        return await connection.fetchval(
            'SELECT wallet_balance FROM user_number_mrrobot_info WHERE user_id = $1',
            user_id
        ) or 0


@dp.callback_query(F.data == "support_menu")
async def support_menu(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="| FAQ |", callback_data="faq"),
            InlineKeyboardButton(text="| SUPPORT |", callback_data="support"),
            InlineKeyboardButton(text="| RULES |", callback_data="rules")
        ],
        [InlineKeyboardButton(text="🚀", callback_data="show_main_menu")]
    ])

    await callback.message.edit_text("🏪 سوالات متداول و پشتیبانی 🏪\n\n ✅ استفاده از ربات به معنای تایید و پذیرش قوانین است ✅", reply_markup=keyboard)


from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

@dp.callback_query(F.data == "faq")
async def faq(callback: CallbackQuery):
    faq_text = (
        "❓ *سوالات متداول:*\n\n"
        
        "1️⃣ *چرا کد تأیید دریافت نمی‌شود؟*\n"
        "اگر نکات زیر را رعایت کنید معمولاً کد را دریافت می‌کنید:\n\n"
        "- اخیراً تلگرام برای نسخه ویندوز محدودیت‌های زیادی قرار داده است؛ سعی کنید برای اولین ورود، از تلگرام گوشی استفاده کنید.\n"
        "- از نسخه تلگرام ایکس (ترجیحا) یا نسخه رسمی تلگرام استفاده کنید. از نسخه‌های تلگرامی که فیلترشکن یا پراکسی سرخود دارند استفاده نکنید.\n"
        "- سعی کنید آی.‌پی شما از همان کشوری باشد که از آن شماره دریافت می‌کنید.\n"
        "- لوکیشن گوشی خود را خاموش کنید.\n"
        "- دو اکانت روی یک تلگرام نسازید.\n\n"

        "2️⃣ *مشکل دریافت کد در تلگرام*\n"
        "مشکل دریافت کد در تلگرام می‌تواند به دلایل مختلفی باشد:\n\n"
        "- از نسخه‌های تلگرام ایکس یا نسخه رسمی استفاده کنید.\n"
        "- از فیلترشکن با سرورهای کم‌تعداد استفاده نکنید.\n"
        "- از آی.‌پی‌های مربوط به همان کشور شماره دریافت کنید.\n\n"

        "3️⃣ *مشکل دریافت کد در واتساپ*\n"
        "در صورتی که نکات زیر را رعایت کنید معمولاً کد را دریافت می‌کنید:\n\n"
        "- سعی کنید آی.‌پی شما با کشوری که از آن شماره می‌گیرید یکسان باشد.\n"
        "- از واتساپ رسمی استفاده کنید نه بیزینس (تجاری).\n"
        "- در صورت عدم دریافت کد، واتساپ را حذف و دوباره نصب کنید.\n\n"

        "4️⃣ *مشکل دریافت کد در گوگل*\n"
        "اگر مشکل دریافت کد در سرویس‌های گوگل مثل جیمیل و یوتیوب دارید، این نکات را رعایت کنید:\n\n"
        "- لوکیشن خود را غیرفعال کنید.\n"
        "- آی.‌پی شما باید با کشور شماره شما هماهنگ باشد.\n"
        "- اگر مشکل حل نشد، حافظه پنهان مرورگر خود را پاک کنید.\n\n"

        "5️⃣ *مشکل دریافت کد در پی‌پال*\n"
        "اگر نکات زیر را رعایت کنید، معمولاً کد را دریافت می‌کنید:\n\n"
        "- از اپلیکیشن پی‌پال استفاده نکنید. از مرورگر ویندوز استفاده کنید.\n\n"

        "6️⃣ *مشکل دریافت کد در اپل آیدی*\n"
        "اگر مشکلی در دریافت کد در اپل آیدی دارید، این نکات را رعایت کنید:\n\n"
        "- از مرورگر ویندوز استفاده کنید.\n"
        "- از گوشی یا اپلیکیشن‌های اپل استفاده نکنید.\n\n"

        "7️⃣ *مشکل دریافت کد در اینستاگرام*\n"
        "در صورت رعایت نکات زیر، معمولاً کد تأیید از سوی اینستاگرام ارسال می‌شود:\n\n"
        "- لوکیشن گوشی را خاموش کنید.\n"
        "- از وی.‌پی.‌ان برای تغییر آی.‌پی استفاده کنید.\n"
        "- شماره مجازی را در اینستاگرامی وارد کنید که هیچ اکانت دیگری نداشته باشید.\n\n"

        "8️⃣ *مشکل دریافت کد در سایر سرویس‌ها*\n"
        "اگر از شماره مجازی برای سرویس‌های مختلف استفاده می‌کنید، معمولاً با رعایت نکات زیر مشکلی نخواهید داشت:\n\n"
        "- آی.‌پی شما باید با کشوری که از آن شماره می‌گیرید یکسان باشد.\n"
        "- از مرورگر وب برای دریافت کد استفاده کنید.\n\n"

        "9️⃣ *چرا قبل از دریافت کد، پیام بن شدن نمایش داده می‌شود؟*\n"
        "گاهی شماره‌ای که وارد می‌کنید به دلیل محدودیت‌های سرویس، مسدود می‌شود. در این صورت باید شماره را لغو کنید.\n\n"

        "🔟 *چرا با وجود موجودی، شماره‌ای برای خرید نیست؟*\n"
        "این مشکل به دلیل اختلالات در اپراتورهای مخابراتی خارجی است. اگر شماره‌ای فعال نمی‌شود، شماره دیگری را امتحان کنید.\n\n"

        "🔹 *آیا این شماره‌ها اختصاصی و همیشه برای ما هستند؟*\n"
        "شماره‌های دائمی کاملاً اختصاصی هستند و همیشه در اختیار شما خواهند بود. شماره‌های اجاره‌ای به مدت محدود فعال هستند و بعد از مدت زمان مشخص از شبکه خارج می‌شوند.\n\n"

        "🔹 *اعداد کنار نام کشور به چه معناست؟*\n"
        "این اعداد نشان‌دهنده اپراتورهای مختلف مخابراتی هستند که شماره‌های مجازی از آن‌ها ارائه می‌شود.\n\n"

        "🔹 *تفاوت قیمت شماره‌ها برای چیست؟*\n"
        "قیمت شماره‌ها بستگی به کیفیت و نوع آن‌ها دارد. شماره‌های دائمی کیفیت بالاتری دارند و قیمت آن‌ها بیشتر است.\n\n"

        "🔹 *از کدام کشور بهتر است شماره بگیریم؟*\n"
        "برای انتخاب کشور، بهتر است از شماره‌های با کیفیت و کمترین مشکلات استفاده کنید. معمولاً شماره‌های ابتدای لیست، کیفیت بالاتری دارند.\n\n"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀", callback_data="support_menu")]
        ]
    )

    await callback.message.edit_text(faq_text, reply_markup=keyboard, parse_mode="Markdown")

@dp.callback_query(F.data == "rules")
async def rules(callback: CallbackQuery):
    rules_text = (
        "📜 *قوانین ربات مستر ربات:*\n\n"
        
        "✅ *قانون ۱:* مستر ربات مطابق با قوانین کشور راه اندازی شده و قانونی می‌باشد. هرگونه استفاده غیر مجاز از شماره‌ها بر عهده مصرف‌کننده است.\n"
        "قبل از دریافت هرگونه خدمات، راهنما و شرایط استفاده آن را کامل مطالعه کنید، در صورت عدم مطالعه مشمول گارانتی و پشتیبانی محصول نخواهید بود.\n"
        "مستر ربات در هر زمان مجاز به بروزرسانی قوانین بوده و کاربران گرامی برای اطلاع از تغییرات ملزم به مطالعه می‌باشند.\n\n"
        
        "✅ *قانون ۲:* استفاده از شماره‌ها:\n"
        "مستر ربات به عنوان یک اپراتور مخابراتی فعالیت می‌کند و تنها وظیفه پنل، ارائه شماره مجازی و دریافت پیامک‌های ارسالی به آن است. توجه داشته باشید که در مواردی ممکن است بنا به قوانین نرم‌افزار و سرویس مورد نظر شما، پس از استفاده محدودیتی برای شماره به وجود آید یا مسدود شود. مستر ربات تعهدی نسبت به این مشکلات نمی‌پذیرد، اما تمامی نکات لازم جهت استفاده را در راهنما توضیح داده‌ایم.\n\n"
        
        "✅ *قانون ۳:* شماره‌های عادی:\n"
        "در صورتی که پس از دریافت شماره، کد پیامکی دریافت نشود، هیچ هزینه‌ای از حساب شما کسر نمی‌شود. شماره‌های مجازی عادی تنها بین ۱۰ الی ۲۰ دقیقه قابلیت دریافت پیامک دارند. پس از این زمان، امکان دریافت مجدد کد وجود ندارد.\n\n"
        
        "✅ *قانون ۴:* شماره‌های اجاره‌ای:\n"
        "شماره‌های اجاره‌ای از اپراتورهای مختلف ارائه می‌شود که هر اپراتور قوانین خاص خود را دارد. هنگام خرید شماره، شرایط مربوط به آن اعلام می‌شود.\n\n"
        
        "✅ *قانون ۵:* شماره‌های دائمی:\n"
        "شماره‌های دائمی از اپراتور معتبر و با کیفیت تهیه شده‌اند و تمامی نکات لازم پس از خرید در اختیار شما قرار می‌گیرد. مسئولیت مستر ربات تنها در صورت تعویض شماره یا عودت وجه است که فقط برای مدت تست شماره قابل اجراست.\n\n"
        
        "✅ *قانون ۶:* امور مالی:\n"
        "تمامی مبالغ مستر ربات به نرخ \"تومان\" درج شده است و قیمت شماره‌ها ممکن است به دلیل تغییر نرخ ارز و قوانین مخابراتی کشورهای مختلف تغییر کند.\n"
        "در صورت مشکل در پرداخت آنلاین و عدم شارژ حساب، مبلغ پرداختی ظرف ۲۴ تا ۷۲ ساعت به کارت شما برگشت می‌خورد.\n\n"
        
        "✅ *قانون ۷:* درخواست عودت وجه:\n"
        "مبالغ کمتر از 50000 تومان قابل عودت نیستند. در صورت درخواست عودت وجه، کارمزد درگاه از مبلغ دریافتی کسر خواهد شد.\n"
        "پس از درخواست شما، معمولاً مبلغ تا ۵ روز کاری به حساب شما واریز می‌شود. (در برخی موارد خاص ممکن است زمان بیشتری طول بکشد).\n\n"
        
        "✅ *قانون ۸:* برای ثبت درخواست عودت وجه، شماره کارتی که با آن پرداخت انجام داده‌اید به همراه شماره شبای آن در چت آنلاین سایت ارسال کنید.\n"
        "در صورتی که تراکنش شما مشکوک به فیشینگ شناسایی شود، ارائه تصویر کارت بانکی (و در برخی موارد کارت شناسایی) الزامی است.\n\n"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀", callback_data="support_menu")]
        ]
    )

    await callback.message.edit_text(rules_text, reply_markup=keyboard, parse_mode="Markdown")

@dp.callback_query(F.data == "support")
async def support(callback: CallbackQuery):
    support_message = (
        "<a href='https://t.me/mrrobotgroup_py'>پشتیبانی ربات</a>"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀", callback_data="support_menu")]
        ]
    )

    await callback.message.edit_text(support_message, reply_markup=keyboard, parse_mode="HTML")

class DatabaseMiddleware:
    def __init__(self, pool):
        self.pool = pool

    async def __call__(self, handler, event, data):
        data["pool"] = self.pool
        return await handler(event, data)

async def handle_webhook(request):
    try:
        # Get the update from Telegram
        update = types.Update(**await request.json())
        
        # Process the update using the dispatcher
        await dp.feed_webhook_update(bot, update)
        
        return web.Response()
    except Exception as e:
        logger.error(f"Error processing update: {e}")
        return web.Response(status=500)

async def webhook_main():
    # Initialize database pool
    pool = await init_db()
    
    # Register middleware
    dp.update.middleware.register(DatabaseMiddleware(pool))
    
    # Create web application
    app = web.Application()
    
    # Register webhook handler
    app.router.add_post(f'/webhook', handle_webhook)  # Use token in webhook path

    # Set webhook on startup
    async def on_startup(app):
        webhook_url = f"https://mrrobotpy.chbk.app/webhook"
        await bot.set_webhook(
            url=webhook_url,
            drop_pending_updates=True
        )
        logger.info(f"Webhook set to: {webhook_url}")
    
    app.on_startup.append(on_startup)
    
    # Add shutdown handler
    async def on_shutdown(app):
        await bot.delete_webhook()
        await pool.close()
        logger.info("Bot and database pool shut down gracefully")
    
    app.on_shutdown.append(on_shutdown)
    
    # Start the server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 3000)
    
    logger.info("Starting webhook server...")
    await site.start()
    
    # Keep the application running
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("✅")
    asyncio.run(webhook_main())
