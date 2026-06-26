import discord
from discord.ext import commands, tasks
from discord.ui import Select, View, Modal, TextInput, button
import os 
import re
import urllib.request
import json
import aiohttp
import psutil
from dotenv import load_dotenv
from datetime import datetime, timedelta
import motor.motor_asyncio
from bson import ObjectId

# ============ CRITICAL SECURITY ADDITIONS ============

from urllib.parse import urlparse
from typing import Tuple

# CONSTANTS
MAX_MONEY = 10_000_000_000_000  # 10 trillion - prevent overflow attacks
SAFE_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9а-яА-Я\s\-\.\'\"()]+$')
CHAT_SYSTEM_PROMPT = """Ты — официальный ИИ-помощник сервера Военная-политическая-игра (ВПИ).
Твоя задача — кратко и точно отвечать на вопросы игроков о механиках сервера, правилах и командах.
Отвечай на русском языке. Будь краток и по делу.
Если тебя оскорбляют или провоцируют, вежливо напомни о правилах сервера.

=== ЭКОНОМИКА ===
- ВВП (GDP): основной показатель экономики. Доход в час = ВВП / 48.
- !collect — собрать доход. Можно раз в час, максимум за 12 часов накапливается.
- !reforms <сумма> <ссылка> — вложить деньги в ВВП. Эффективность зависит от размера ВВП:
  * До 300 млрд — 50% от вложения идёт в ВВП
  * 300-500 млрд — 40%
  * 500-900 млрд — 30%
  * 900 млрд - 2.8 трлн — 15%
  * Свыше 2.8 трлн — 10%
- !pay @игрок <сумма> — перевести деньги другому игроку.
- !burn <сумма> <причина> — сжечь деньги из баланса.
- !cab — посмотреть свою статистику (ВВП, баланс, население, недовольство).
- !top — топ игроков по ВВП, населению или балансу.

=== КАТЕГОРИИ СТРАН ===
- Нищая Страна: ВВП до 200 млрд — без штрафов к доходу.
- Среднячок: ВВП 200 млрд - 3 трлн — штраф -25% к доходу при коллекте.
- Богатая Страна: ВВП свыше 3 трлн — штраф -50% к доходу при коллекте.
Категория повышается автоматически при достижении порога ВВП.

=== БЮДЖЕТ ===
- Бюджет влияет на недовольство населения. Если срезать расходы ниже стандарта — недовольство растёт.
- Стандартные расходы: Социальные 10%, Образование 6%, Здравоохранение 8%, Иные 1% (фиксировано).
- !budjet <категория> <процент> — изменить статью бюджета (1-15%).
  Категории: социальные-расходы, образование, здравоохранение
- !budjet-info — посмотреть текущий бюджет и уровень недовольства.
- Недовольство растёт со скоростью 0.2%/ч за каждый % срезанных расходов.

=== НАСЕЛЕНИЕ ===
- Население растёт автоматически при каждом !collect.
- Рост населения по умолчанию 2% в год.
- Пул мобилизации = население × процент мобилизации (по умолчанию 2.5%).
- При росте населения пул мобилизации тоже растёт.

=== ВОЕННОЕ ===
- !military — открыть панель военных операций.
- !reg-tech <название> — зарегистрировать новую технику (кулдаун 4 часа).
- Мобилизация: перевести население в солдат. Лимит 350,000 солдат в сутки. КД 15 часов после достижения лимита.
- Содержание техники: 0.25% от стоимости техники в час вычитается при !collect.
- Содержание солдат: 100 💵 за солдата в час.
- !sell <кол-во> @игрок <сумма> <техника> — продать технику другому игроку.
- !use <кол-во> <техника> — использовать/списать технику из инвентаря.
- !inv — посмотреть инвентарь (отправляется в ЛС).

=== МАГАЗИН ===
- !shop — открыть магазин техники с категориями и поиском по стране.
- !buy <кол-во> <название> — купить технику. Нужна лицензия если техника чужой страны.
- !give-lic @игрок <техника или all> — выдать лицензию на свою технику.
- !vehicle-info <название> — подробная информация о технике.
- !iso <название> <ссылка> — добавить изображение к своей технике.

=== АЛЬЯНСЫ ===
- !ally-create — создать альянс (макс 2 альянса на игрока, требует одобрения).
- !ally — информация о своём альянсе.
- !ally-invite @игрок — пригласить игрока в альянс.
- !ally-kick @игрок — выгнать игрока из альянса.
- !ally-remove — удалить свой альянс.
- Казна альянса: пополняется налогом с каждого !collect участников.
- Налог альянса по умолчанию 2% от дохода при коллекте.

=== КОМПАНИИ ===
- !company create <тип> <название> — создать компанию (макс 5 на игрока).
- Типы компаний: farm (100 млн), factory (500 млн), it (1 млрд), bank (2 млрд, макс 2), transport (300 млн).
- !company list — список своих компаний.
- !company upgrade — улучшить компанию (макс уровень 5, стоит 50% от вложений).
- !company hire <кол-во> — нанять сотрудников (берутся из населения).
- !company fire <кол-во> — уволить сотрудников.
- !company close — закрыть компанию (возврат 50% вложений).

=== ПРОЧЕЕ ===
- !players-country — список всех игроков и их государств.
- !set-ideology <текст> — установить идеологию своей страны (макс 200 символов).
- !calc-maintenance — рассчитать расходы на содержание техники и солдат.
- Все заявки на технику и альянсы автоматически удаляются через 24 часа если не одобрены.
"""
# ============ VALIDATION FUNCTIONS ============

def validate_amount(amount: int, min_val: int = 0, max_val: int = MAX_MONEY) -> Tuple[bool, str]:
    if not isinstance(amount, int):
        return False, "❌ Сумма должна быть целым числом."
    if amount < min_val:
        return False, f"❌ Сумма должна быть не менее {min_val:,}." 
    if amount > max_val:
        return False, f"❌ Максимальная сумма: {max_val:,} 💵"
    return True, ""

def validate_url(url: str) -> Tuple[bool, str]:
    try:
        if not url or len(url) == 0:
            return False, "❌ URL не может быть пустым."
        if len(url) > 2048:
            return False, "❌ URL слишком длинный."
        result = urlparse(url)
        if not result.scheme or not result.netloc:
            return False, "❌ Невалидная ссылка."
        if result.scheme not in ('http', 'https'):
            return False, "❌ Только HTTP(S) ссылки разрешены."
        return True, ""
    except Exception:
        return False, "❌ Невалидная ссылка."

def escape_mongodb_string(s: str) -> str:
    return re.escape(s.strip())

# Загрузка переменных окружения
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
MONGODB_URI = os.getenv('MONGODB_URI')

# Подключение к MongoDB
mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)
db = mongo_client['discord_bot']
economy_col = db['economy']
reform_links_col = db['reform_links']
vehicles_col = db['vehicles']
licenses_col = db['licenses']
inventory_col = db['inventory']
daily_submissions_col = db['daily_submissions']
mobilization_links_col = db['mobilization_links']
buffs_col = db['buffs']
alliances_col = db['alliances']
alliance_invites_col = db['alliance_invites']
burn_logs_col = db['burn_logs']
mobilization_limits_col = db['mobilization_limits']
companies_col = db['companies']
role_timers_col = db['role_timers']

# ID ролей и каналов
REGISTERED_ROLE_ID = 1501510805169115176
UNREGISTERED_ROLE_ID = 1141339127367880764
COUNTRY_ROLE_ID = 1141340397558321313
ALLIANCES_THREADS_CHANNEL_ID = 1502968035235987487
ALLIANCES_APPROVAL_CHANNEL_ID = 1502009375324110968
KURATOR_T_ROLE_ID = [1513997754454643020]
KURATOR_R_ROLE_ID = [1514000184483512551]
TEMP_ROLE_ID = 1141359343036530818
TEMP_ROLE_DURATION_SECONDS = 3 * 86400  # 3 дня

# ===== НАСТРОЙКИ БОТА =====
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ БД =====
DEFAULT_BUDGETS = {
    'budget_social': 10,
    'budget_education': 6,
    'budget_healthcare': 8,
    'budget_other': 1,
}

async def get_user(user_id: int) -> dict:
    user = await economy_col.find_one({'_id': str(user_id)})
    if user is None:
        user = {
            '_id': str(user_id),
            'ideology': 'Не указана',
            'country_category': 'Нищая Страна',
            'government_form': 'Не указана',
            'leader': 'Не указан',
            'gdp_pps': 0,
            'national_debt': 0,
            'income_services': 0,
            'income_exports': 0,
            'income_tourism': 0,
            'income_other_src': 0,
            'nationalities': '',
            'military_budget': 0,
            'gdp': 0,
            'balance': 0,
            'last_collect': 0,
            'population': 0,
            'pop_growth_yearly': 2.0,
            'last_pop_update': 0,
            'budget_social': DEFAULT_BUDGETS['budget_social'],
            'budget_education': DEFAULT_BUDGETS['budget_education'],
            'budget_healthcare': DEFAULT_BUDGETS['budget_healthcare'],
            'budget_other': DEFAULT_BUDGETS['budget_other'],
            'unhappiness': 0.0,
            'last_unhappiness_update': 0,
            'country': None,
            'country_flag_url': None,
            'mobilization_percent': 2.5,
            'mob_pool': 0,
            'alliance_id': None,
            'alliance_role': None,
        }
        await economy_col.insert_one(user)
    else:
        update = {}
        if 'gdp' not in user: update['gdp'] = 0
        if 'last_collect' not in user: update['last_collect'] = 0
        if 'balance' not in user: update['balance'] = 0
        if 'population' not in user: update['population'] = 0
        if 'pop_growth_yearly' not in user: update['pop_growth_yearly'] = 2.0
        if 'last_pop_update' not in user: update['last_pop_update'] = 0
        for key, default_val in DEFAULT_BUDGETS.items():
            if key not in user:
                update[key] = default_val
        if 'unhappiness' not in user: update['unhappiness'] = 0.0
        if 'last_unhappiness_update' not in user: update['last_unhappiness_update'] = 0
        if 'country' not in user: update['country'] = None
        if 'country_flag_url' not in user: update['country_flag_url'] = None
        if 'mobilization_percent' not in user: update['mobilization_percent'] = 7.5
        if 'mob_pool' not in user: update['mob_pool'] = 0
        if 'alliance_id' not in user: update['alliance_id'] = None
        if 'alliance_role' not in user: update['alliance_role'] = None
        if 'ideology' not in user: update['ideology'] = ' указана'
        if 'country_category' not in user: update['country_category'] = 'Нищая Страна'
        if 'government_form' not in user: update['government_form'] = 'He указана'
        if 'leader' not in user: update['leader'] = 'He указан'
        if 'gdp_pps' not in user: update['gdp_pps'] = 0
        if 'national_debt' not in user: update['national_debt'] = 0
        if 'income_services' not in user: update['income_services'] = 0
        if 'income_exports' not in user: update['income_exports'] = 0
        if 'income_tourism' not in user: update['income_tourism'] = 0
        if 'income_other_src' not in user: update['income_other_src'] = 0
        if 'nationalities' not in user: update['nationalities'] = ''
        if 'military_budget' not in user: update['military_budget'] = 0
        if update:
            await economy_col.update_one({'_id': str(user_id)}, {'$set': update})
            user.update(update)
    return user

async def update_user(user_id: int, data: dict):
    await economy_col.update_one(
        {'_id': str(user_id)},
        {'$set': data},
        upsert=True
    )

async def update_mob_pool(user_id: int, new_val: int):
    await update_user(user_id, {'mob_pool': max(0, new_val)})

async def auto_update_category(user_id: int, gdp: int):
    """Auto-upgrades category based on GDP thresholds. Never downgrades."""
    user = await get_user(user_id)
    current = user.get('country_category', 'Нищая Страна')
    if gdp >= 3_000_000_000_000:
        new_cat = 'Богатая Страна'
    elif gdp >= 200_000_000_000:
        new_cat = 'Среднячок'
    else:
        return
    if current != new_cat:
        await update_user(user_id, {'country_category': new_cat})
# ===== ВРЕМЕННЫЕ РОЛИ (АВТО-СНЯТИЕ ЧЕРЕЗ N ВРЕМЕНИ) =====
async def schedule_role_removal(user_id: int, role_id: int, duration_seconds: int):
    """Планирует автоматическое снятие роли через указанное время."""
    expires_at = datetime.now().timestamp() + duration_seconds
    await role_timers_col.update_one(
        {'user_id': str(user_id), 'role_id': role_id},
        {'$set': {'expires_at': expires_at}},
        upsert=True
    )

async def cancel_role_removal(user_id: int, role_id: int):
    """Отменяет запланированное снятие роли (например, если она снята вручную)."""
    await role_timers_col.delete_one({'user_id': str(user_id), 'role_id': role_id})
# ===== COMPANY HELPER FUNCTIONS =====
async def get_company(company_id_str: str) -> dict | None:
    if not company_id_str:
        return None
    try:
        obj_id = ObjectId(company_id_str)
    except:
        return None
    return await companies_col.find_one({'_id': obj_id})

async def get_user_companies(user_id: int) -> list:
    user = await get_user(user_id)
    companies = []
    for cid in user.get('company_ids', []):
        comp = await get_company(cid)
        if comp:
            companies.append(comp)
    return companies

async def create_company(owner_id: int, name: str, comp_type: str, investment: int, employees: int, hourly_profit: int, owner_share: float, gdp_contrib: int) -> str:
    doc = {
        'owner_id': str(owner_id),
        'name': name,
        'type': comp_type,
        'level': 1,
        'employees': 0,
        'max_employees': employees,
        'hourly_profit': hourly_profit,
        'owner_share': owner_share,
        'gdp_contribution': gdp_contrib,
        'invested': investment,
        'created_at': datetime.now().timestamp(),
        'last_event': datetime.now().timestamp()
    }
    result = await companies_col.insert_one(doc)
    return str(result.inserted_id)
def is_registered():
    async def predicate(ctx):
        role = ctx.guild.get_role(REGISTERED_ROLE_ID)
        if role is None or role not in ctx.author.roles:
            await ctx.send("❌ Ты не зарегистрирован! Открой тикет для регистрации.")
            return False
        return True
    return commands.check(predicate)
def is_admin_or_kurator():
    """Для всех команд — T, R и админы"""
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        for role_id in KURATOR_T_ROLE_ID + KURATOR_R_ROLE_ID:
            role = ctx.guild.get_role(role_id)
            if role and role in ctx.author.roles:
                return True
        await ctx.send("❌ У вас нет прав для этой команды.")
        return False
    return commands.check(predicate)

def is_admin_or_kurator_t():
    """Только для KURATOR_T и админов"""
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        for role_id in KURATOR_T_ROLE_ID:
            role = ctx.guild.get_role(role_id)
            if role and role in ctx.author.roles:
                return True
        await ctx.send("❌ У вас нет прав для этой команды.")
        return False
    return commands.check(predicate)

def is_admin_or_kurator_r():
    """Только для KURATOR_R и админов"""
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        for role_id in KURATOR_R_ROLE_ID:
            role = ctx.guild.get_role(role_id)
            if role and role in ctx.author.roles:
                return True
        await ctx.send("❌ У вас нет прав для этой команды.")
        return False
    return commands.check(predicate)
# ===== АЛЬЯНСЫ =====
async def get_alliance(alliance_id) -> dict:
    if isinstance(alliance_id, str):
        try:
            alliance_id = ObjectId(alliance_id)
        except:
            return None
    return await alliances_col.find_one({'_id': alliance_id})

async def get_user_alliance(user_id: int) -> dict:
    user = await get_user(user_id)
    if user.get('alliance_id'):
        return await get_alliance(user['alliance_id'])
    return None

async def count_user_alliances_as_owner(user_id: int) -> int:
    count = await alliances_col.count_documents({'owner_id': str(user_id)})
    return count

# ===== ЛИМИТЫ ЗАЯВОК =====
async def check_daily_submission_limit(user_id: int) -> tuple:
    doc = await daily_submissions_col.find_one({'user_id': str(user_id)})
    if doc:
        last_time = doc.get('last_submission_time', 0)
        if last_time:
            elapsed = datetime.now().timestamp() - last_time
            if elapsed < 14400:
                remaining = int(14400 - elapsed)
                hours = remaining // 3600
                mins = (remaining % 3600) // 60
                return False, f"⏰ Кулдаун! Подождите ещё {hours}ч {mins}м перед следующей заявкой."
    return True, ''

async def record_submission(user_id: int):
    await daily_submissions_col.update_one(
        {'user_id': str(user_id)},
        {'$set': {'last_submission_time': datetime.now().timestamp()}},
        upsert=True
    )

async def get_daily_submission_info(user_id: int) -> str:
    doc = await daily_submissions_col.find_one({'user_id': str(user_id)})
    if doc:
        last_time = doc.get('last_submission_time', 0)
        if last_time:
            elapsed = datetime.now().timestamp() - last_time
            if elapsed < 14400:
                remaining = int(14400 - elapsed)
                hours = remaining // 3600
                mins = (remaining % 3600) // 60
                return f"⏳ Кулдаун {hours}ч {mins}м"
    return "∞"

# ===== ВЫЧИСЛЕНИЕ НЕДОВОЛЬСТВА =====
def calculate_unhappiness_speed(user: dict) -> float:
    speed = 0.0
    d_social = DEFAULT_BUDGETS['budget_social'] - user.get('budget_social', DEFAULT_BUDGETS['budget_social'])
    speed += d_social * 0.20
    d_edu = DEFAULT_BUDGETS['budget_education'] - user.get('budget_education', DEFAULT_BUDGETS['budget_education'])
    speed += d_edu * 0.20
    d_health = DEFAULT_BUDGETS['budget_healthcare'] - user.get('budget_healthcare', DEFAULT_BUDGETS['budget_healthcare'])
    speed += d_health * 0.20
    return speed

async def update_unhappiness(user_id: int, user: dict = None) -> float:
    if user is None:
        user = await get_user(user_id)
    current_time = datetime.now().timestamp()
    last_update = user.get('last_unhappiness_update', 0)
    if last_update == 0:
        last_update = current_time
    hours = (current_time - last_update) / 3600.0
    if hours <= 0:
        return user.get('unhappiness', 0.0)
    speed = calculate_unhappiness_speed(user)
    new_unhappiness = user.get('unhappiness', 0.0) + speed * hours
    if new_unhappiness < 0:
        new_unhappiness = 0.0
    elif new_unhappiness > 100:
        new_unhappiness = 100.0
    await update_user(user_id, {
        'unhappiness': new_unhappiness,
        'last_unhappiness_update': current_time
    })
    user['unhappiness'] = new_unhappiness
    user['last_unhappiness_update'] = current_time
    return new_unhappiness

# ===== ИНВЕНТАРЬ =====
async def add_item(user_id: int, item_name: str, quantity: int):
    await inventory_col.update_one(
        {'user_id': str(user_id), 'item_name': item_name},
        {'$inc': {'quantity': quantity}},
        upsert=True
    )

async def remove_item(user_id: int, item_name: str, quantity: int) -> bool:
    res = await inventory_col.find_one({'user_id': str(user_id), 'item_name': item_name})
    if not res or res['quantity'] < quantity:
        return False
    new_quantity = res['quantity'] - quantity
    if new_quantity <= 0:
        await inventory_col.delete_one({'_id': res['_id']})
    else:
        await inventory_col.update_one({'_id': res['_id']}, {'$set': {'quantity': new_quantity}})
    return True

async def get_inventory(user_id: int) -> list:
    cursor = inventory_col.find({'user_id': str(user_id)}).sort('item_name', 1)
    return await cursor.to_list(length=None)

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ ОБСЛУЖИВАНИЯ =====
async def get_vehicle_maintenance_cost_per_hour(user_id: int) -> int:
    """Рассчитывает стоимость содержания как 0.25% от стоимости техники в инвентаре за час"""
    inventory = await get_inventory(user_id)
    total_cost = 0
    for item in inventory:
        if item['item_name'] == "Обученный Солдат":
            continue
        vehicle = await vehicles_col.find_one({'name': item['item_name'], 'approved': True})
        if vehicle:
            total_cost += vehicle['price'] * item['quantity']
    maintenance = int(total_cost * 0.0025)
    return maintenance

SOLDIER_MAINTENANCE_PER_HOUR = 100

# ===== СОБЫТИЯ =====
@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user.name} запущен')
    print(f'Bot ID: {bot.user.id}')

    # MongoDB check
    try:
        await mongo_client.admin.command('ping')
        print(f'✅ Подключение к MongoDB Atlas установлено')
    except Exception as e:
        print(f'❌ MongoDB недоступен: {e}')

    # Groq check
    if os.getenv('GROQ_API_KEY'):
        print(f'✅ Groq API ключ найден')
    else:
        print(f'❌ Groq API ключ не найден — проверьте .env')

    await bot.change_presence(activity=discord.Game(name="Linko ВПИ"))

USAGE_HINTS = {
    'collect': '❌ Команда `!collect` не требует аргументов.\nПросто напиши `!collect` для сбора дохода.',
    'reforms': '❌ Использование: `!reforms <сумма> <ссылка на сообщение из канала реформ>`\nПример: `!reforms 1000000 https://discord.com/channels/...`',
    'pay': '❌ Использование: `!pay @игрок <сумма>`\nПример: `!pay @Undervud 5000`',
    'cab': '❌ Команда `!cab` или `!cab @игрок`',
    'budjet': '❌ Использование: `!budjet <категория> <процент>`\nКатегории: `социальные-расходы`, `образование`, `здравоохранение`\nПример: `!budjet образование 10`',
    'budjet-info': '❌ Использование: `!budjet-info` или `!budjet-info @игрок`',
    'shop': '❌ Команда `!shop` не требует аргументов.\nПросто напиши `!shop`.',
    'give-lic': '❌ Использование: `!give-lic @игрок <название техники или all>`\nПример: `!give-lic @Undervud Т-90` или `!give-lic @Undervud all`',
    'buy': '❌ Использование: `!buy <количество> <название техники>`\nПример: `!buy 3 Т-90`\nПри частичном совпадении будет предложен выбор.',
    'inv': '❌ Команда `!inv` не требует аргументов.\nПросто напиши `!inv` — инвентарь придёт в ЛС.',
    'invsee': '❌ Использование: `!invsee @игрок`',
    'take-item': '❌ Использование: `!take-item @игрок <количество> <название или часть названия>`\nПример: `!take-item @Undervud 100 Т-`',
    'give-item': '❌ Использование: `!give-item @игрок <количество> <название>`\nПример: `!give-item @Undervud 5 Т-90`',
    'use': '❌ Использование: `!use <количество> <название предмета>`\nПример: `!use 50 Т-90`',
    'delete-vehicle': '❌ Использование: `!delete-vehicle <название или часть названия>`\nПример: `!delete-vehicle Т-90`',
    'players-country': '❌ Команда `!players-country` не требует аргументов.',
    'top': '❌ Команда `!top` не требует аргументов.',
    'vehicle-info': '❌ Использование: `!vehicle-info <название/часть названия>`\nПример: `!vehicle-info Т-90`',
    'iso': '❌ Использование: `!iso <название/часть названия> <ссылка на изображение>`\nПример: `!iso Т-90 https://i.imgur.com/abc.png` (доступно только владельцу техники)',
    'remove-sol': '❌ Использование: `!remove-sol @игрок <число>`\nПример: `!remove-sol @Undervud 5000`',
    'add-sol': '❌ Использование: `!add-sol @игрок <число>`\nПример: `!add-sol @Undervud 10000`',
    'full-reg': '❌ Использование: `!full-reg @игрок`\nПолная панель редактирования профиля игрока.',
    'military': '❌ Команда `!military` не требует аргументов.',
    'ally-create': '❌ Команда `!ally-create` не требует аргументов. Просто напиши `!ally-create`.',
    'ally': '❌ Команда `!ally` не требует аргументов.',
    'ally-invite': '❌ Использование: `!ally-invite @игрок`\nПример: `!ally-invite @Undervud`',
    'ally-kick': '❌ Использование: `!ally-kick @игрок`',
    'ally-remove': '❌ Команда `!ally-remove` не требует аргументов.',
    'ally-delete': '❌ Команда `!ally-delete` не требует аргументов (админ).',
    'iso-ally': '❌ Использование: `!iso-ally <название альянса> <ссылка на изображение>`',
    'edit-buy': '❌ Использование: `!edit-buy <название/часть названия> <новая стоимость>`\nПример: `!edit-buy Т-90 6000000`',
    'set-ideology': '❌ Использование: `!set-ideology <текст идеологии>`\nПример: `!set-ideology Демократия, свобода и справедливость`\nМаксимум 200 символов.\nДля просмотра текущей идеологии введите: `!set-ideology` без аргументов',
    'sell': '❌ Использование: `!sell <количество> @игрок <сумма> <название или часть названия>`\nПример: `!sell 3 @Undervud 15000000 Т-90`',
    'burn': '❌ Использование: `!burn <сумма> <причина>`\nПример: `!burn 100000 экономический кризис`',
    'burn-list': '❌ Использование: `!burn-list @игрок`',
    'take-lic': '❌ Использование: `!take-lic @игрок <название/часть названия>`\nПример: `!take-lic @Undervud Т-90`',
    'lic-list': '❌ Использование: `!lic-list` или `!lic-list @игрок`\nБез @ – ваши полученные лицензии. С @ – лицензии, выданные этим игроком.',
    'category-set': '❌ Использование: `!category-set @игрок`',
    'edit-vehicle': '❌ Использование: `!edit-vehicle <название или часть названия>`\nПример: `!edit-vehicle Т-90`',
	'delete-zayavki': '❌ Команда `!delete-zayavki` не требует аргументов.',
    'calc-maintenance': '❌ Команда `!calc-maintenance` не требует аргументов.',
    'reg-tech': '❌ Использование: `!reg-tech <название техники>`\nПример: `!reg-tech Т-90`',
    'mute': '❌ Использование: `!mute @игрок <время> <м/m/ч/h/д/d>`\nПример: `!mute @Undervud 10 м` или `!mute @Undervud 10 m`',
    'unmute': '❌ Использование: `!unmute @игрок`',
    'ally-accept': '❌ Использование: `!ally-accept <ID заявки>`',
    'ally-deny': '❌ Использование: `!ally-deny <ID заявки>`',
    'ally-list': '❌ Команда `!ally-list` не требует аргументов.',
    
}

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Команда не найдена. Используйте `!help`")
    elif isinstance(error, commands.MissingRequiredArgument):
        hint = USAGE_HINTS.get(ctx.command.name)
        if hint:
            await ctx.send(hint)
        else: 
            await ctx.send("❌ Не хватает аргументов. Используйте `!help` для подсказки.")
    elif isinstance(error, commands.BadArgument):
        hint = USAGE_HINTS.get(ctx.command.name)
        if hint:
            await ctx.send(hint)
        else:
            await ctx.send("❌ Неверный аргумент. Используйте `!help` для подсказки.")
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏰ Подожди {error.retry_after:.1f} секунд!")
    elif isinstance(error, commands.CheckFailure):
        pass
    else:
        import traceback
        print(f"Ошибка в команде {ctx.command}: {''.join(traceback.format_exception(type(error), error, error.__traceback__))}")

# ===========================
# ⚙️ COG: ОСНОВНЫЕ КОМАНДЫ
# ===========================
class General(commands.Cog, name="⚙️ Основные"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='help')
    async def help_command(self, ctx):
        """Показать все команды"""
        embed = discord.Embed(
            title="📖 Список команд",
            description="Все доступные команды бота. Префикс: `!`",
            color=discord.Color.blurple()
        )
        seen = set()
        excluded_cogs = {"👑 Админ"}
        for cog_name, cog in self.bot.cogs.items():
            if cog_name in excluded_cogs:
                continue
            cmds = [cmd for cmd in cog.get_commands() if cmd.name not in seen]
            for cmd in cmds:
                seen.add(cmd.name)
            if cmds:
                value = "\n".join(
                    f"`!{cmd.name}` — {cmd.help or 'Нет описания'}"
                    for cmd in cmds
                )
                embed.add_field(name=cog_name, value=value, inline=False)
        embed.set_footer(text=f"Запросил: {ctx.author.name}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name='getip')
    async def getip(self, ctx):
        """Fetches and sends the bot's public IP address."""
        try:
            # We use aiohttp which is already imported in your bot.py
            async with aiohttp.ClientSession() as session:
                async with session.get('https://api.ipify.org?format=json', timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        ip_address = data.get('ip', 'Unknown')
                        await ctx.send(f'My public IP address is: ||{ip_address}||')
                    else:
                        await ctx.send('Sorry, I could not retrieve the IP address at this time.')
        except aiohttp.ClientError as e:
            await ctx.send(f'An error occurred while trying to get the IP: {e}')
        
    @commands.command(name='ping')
    async def ping(self, ctx):
        """Проверить задержку бота"""
        await ctx.send(f'Pong! 🏓 Задержка: {round(self.bot.latency * 1000)}мс')

    @commands.command(name='info')
    async def info(self, ctx):
        """Информация о боте"""
        embed = discord.Embed(title="LinkoBot", description="Бот для сервера Военная-политическая-игра", color=discord.Color.blue())
        embed.add_field(name="Версия", value="3.2.0", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name='players-country')
    @is_registered()
    async def players_country(self, ctx):
        """Показать список игроков по государствам и других"""
        view = PlayersCountryView(ctx.guild, ctx.author.id)
        embed = await view.build_embed('states')
        view.message = await ctx.send(embed=embed, view=view)
        
    @commands.command(name='dbstatus')
    @commands.has_permissions(administrator=True)
    async def dbstatus(self, ctx):
        """Проверяет состояние базы данных"""
        await ctx.send("🔍 Проверяю состояние базы данных...")

        embed = discord.Embed(
            title="🗄️ Статус базы данных",
            color=discord.Color.green()
        )

        # Check MongoDB ping
        try:
            start = datetime.now()
            await mongo_client.admin.command('ping')
            ping_ms = (datetime.now() - start).total_seconds() * 1000
            embed.add_field(
                name="🟢 Подключение",
                value=f"MongoDB онлайн — `{ping_ms:.1f}ms`",
                inline=False
            )
        except Exception as e:
            embed.color = discord.Color.red()
            embed.add_field(
                name="🔴 Подключение",
                value=f"MongoDB недоступен: `{e}`",
                inline=False
            )
            await ctx.send(embed=embed)
            return

        # Collection sizes
        collections = {
            "economy_col":              ("💰 Экономика",         economy_col),
            "inventory_col":            ("🎒 Инвентарь",         inventory_col),
            "vehicles_col":             ("🚗 Техника",            vehicles_col),
            "licenses_col":             ("📜 Лицензии",           licenses_col),
            "buffs_col":                ("⚡ Баффы",              buffs_col),
            "alliances_col":            ("🤝 Альянсы",            alliances_col),
            "burn_logs_col":            ("🔥 Логи сжиганий",      burn_logs_col),
            "daily_submissions_col":    ("📰 Ежедневные заявки",  daily_submissions_col),
            "mobilization_links_col":   ("🪖 Мобилизация",        mobilization_links_col),
            "reform_links_col":         ("📋 Реформы",            reform_links_col),
        }

        col_lines = []
        total_docs = 0
        for key, (label, col) in collections.items():
            try:
                count = await col.count_documents({})
                total_docs += count
                col_lines.append(f"`{label}` — {count:,} записей")
            except Exception:
                col_lines.append(f"`{label}` — ❌ ошибка")

        embed.add_field(
            name="📂 Коллекции",
            value="\n".join(col_lines),
            inline=False
        )

        embed.add_field(
            name="📊 Всего записей",
            value=f"{total_docs:,}",
            inline=True
        )

        embed.add_field(
            name="⏱️ Задержка",
            value=f"`{ping_ms:.1f}ms`",
            inline=True
        )

        embed.set_footer(text=f"Запрошено: {ctx.author.display_name} • {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
        await ctx.send(embed=embed)
    @commands.command(name='rolemismatch')
    @commands.has_permissions(administrator=True)
    async def rolemismatch(self, ctx):
        """Проверяет несоответствия между ролями и базой данных"""
        await ctx.send("🔍 Проверяю несоответствия ролей и базы данных...")

        registered_role = ctx.guild.get_role(REGISTERED_ROLE_ID)
        unregistered_role = ctx.guild.get_role(UNREGISTERED_ROLE_ID)

        if not registered_role or not unregistered_role:
            await ctx.send("❌ Не удалось найти роли. Проверьте ID ролей.")
            return

        registered_members = {m.id: m for m in registered_role.members}
        unregistered_members = {m.id: m for m in unregistered_role.members}

        # Fetch all DB entries
        db_entries = set()
        async for doc in economy_col.find({}, {'_id': 1}):
            try:
                db_entries.add(int(doc['_id']))
            except (ValueError, KeyError):
                pass

        # Case 1: Has registered role but no DB entry
        role_no_db = []
        for member_id, member in registered_members.items():
            if member_id not in db_entries:
                role_no_db.append(member)

        # Case 2: In DB but missing registered role
        db_no_role = []
        for user_id in db_entries:
            member = ctx.guild.get_member(user_id)
            if member and registered_role not in member.roles:
                db_no_role.append(member)

        # Case 3: Has both registered and unregistered roles
        both_roles = []
        for member_id, member in registered_members.items():
            if member_id in unregistered_members:
                both_roles.append(member)

        # Case 4: In DB but no longer in server
        left_server = []
        for user_id in db_entries:
            member = ctx.guild.get_member(user_id)
            if member is None:
                left_server.append(user_id)

        embed = discord.Embed(
            title="🔍 Несоответствия ролей и БД",
            color=discord.Color.orange()
        )

        # Role but no DB
        if role_no_db:
            value = "\n".join(f"• {m.mention}" for m in role_no_db)
            if len(value) > 1024:
                value = value[:1020] + "..."
            embed.add_field(
                name=f"⚠️ Есть роль, нет в БД ({len(role_no_db)})",
                value=value,
                inline=False
            )
        else:
            embed.add_field(name="✅ Есть роль, нет в БД", value="Нет несоответствий", inline=False)

        # DB but no role
        if db_no_role:
            value = "\n".join(f"• {m.mention}" for m in db_no_role)
            if len(value) > 1024:
                value = value[:1020] + "..."
            embed.add_field(
                name=f"⚠️ Есть в БД, нет роли ({len(db_no_role)})",
                value=value,
                inline=False
            )
        else:
            embed.add_field(name="✅ Есть в БД, нет роли", value="Нет несоответствий", inline=False)

        # Both roles
        if both_roles:
            value = "\n".join(f"• {m.mention}" for m in both_roles)
            if len(value) > 1024:
                value = value[:1020] + "..."
            embed.add_field(
                name=f"⚠️ Обе роли одновременно ({len(both_roles)})",
                value=value,
                inline=False
            )
        else:
            embed.add_field(name="✅ Обе роли одновременно", value="Нет несоответствий", inline=False)

        # Left server
        if left_server:
            value = "\n".join(f"• `{uid}`" for uid in left_server[:20])
            if len(left_server) > 20:
                value += f"\n*...и ещё {len(left_server) - 20}*"
            embed.add_field(
                name=f"👻 В БД, но покинули сервер ({len(left_server)})",
                value=value,
                inline=False
            )
        else:
            embed.add_field(name="✅ Покинули сервер", value="Нет записей", inline=False)

        total_issues = len(role_no_db) + len(db_no_role) + len(both_roles) + len(left_server)
        embed.set_footer(text=f"Всего проблем: {total_issues} • Запросил: {ctx.author.display_name}")
        await ctx.send(embed=embed)

    @commands.command(name='chat')
    @is_registered()
    async def chat(self, ctx, *, message: str):
        """Задать вопрос AI"""
        await self._ask_ai(ctx, message, ctx.author)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if self.bot.user not in message.mentions:
            return
        content = message.content.replace(f'<@{self.bot.user.id}>', '').replace(f'<@!{self.bot.user.id}>', '').strip()
        if not content:
            await message.channel.send("Могу помочь с вопросами по механикам сервера. Просто напишите мне!")
            return
        reg_role = message.guild.get_role(REGISTERED_ROLE_ID)
        if reg_role and reg_role not in message.author.roles:
            return
        await self._ask_ai(message, content, message.author)

    async def _ask_ai(self, ctx_or_message, message: str, author: discord.Member):
        is_message = isinstance(ctx_or_message, discord.Message)
        channel = ctx_or_message.channel

        async with channel.typing():
            try:
                async with aiohttp.ClientSession() as session:
                    payload = {
                        "model": "llama-3.3-70b-versatile",
                        "messages": [
                            {
                                "role": "system",
                                "content": CHAT_SYSTEM_PROMPT
                            },
                            {
                                "role": "user",
                                "content": message
                            }
                        ],
                        "max_tokens": 1024
                    }

                    async with session.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {os.getenv('GROQ_API_KEY')}",
                            "Content-Type": "application/json"
                        },
                        json=payload
                    ) as resp:
                        if resp.status != 200:
                            await channel.send(f"❌ Ошибка Groq API: `{resp.status}`")
                            return

                        data = await resp.json()
                        reply = data['choices'][0]['message']['content']

                embed = discord.Embed(
                    description=reply,
                    color=discord.Color.blue()
                )
                embed.set_author(
                    name=f"ВПИ Ассистент • {author.display_name}",
                    icon_url=self.bot.user.display_avatar.url
                )
                embed.add_field(name="💬 Вопрос", value=f"> {message[:200]}", inline=False)

                if is_message:
                    await ctx_or_message.reply(embed=embed)
                else:
                    await ctx_or_message.send(embed=embed)

            except Exception as e:
                await channel.send(f"❌ Произошла ошибка: `{e}`")
    @commands.command(name='stats')
    @commands.has_permissions(administrator=True)
    async def stats(self, ctx):
        """Показать статистику сервера (CPU, RAM, Диск)"""
        # CPU
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()

        # RAM
        mem = psutil.virtual_memory()
        mem_used_mib = mem.used / (1024 ** 2)
        mem_total_mib = mem.total / (1024 ** 2)
        mem_percent = mem.percent

        # Disk
        disk = psutil.disk_usage('/')
        disk_used_mib = disk.used / (1024 ** 2)
        disk_total_gib = disk.total / (1024 ** 3)
        disk_percent = disk.percent

        # Uptime
        boot_time = psutil.boot_time()
        uptime_seconds = int(datetime.now().timestamp() - boot_time)
        uptime_hours = uptime_seconds // 3600
        uptime_mins = (uptime_seconds % 3600) // 60

        embed = discord.Embed(
            title="📊 Статистика сервера",
            color=discord.Color.blurple()
        )

        embed.add_field(
            name="🖥️ CPU Load",
            value=f"**{cpu_percent:.2f}%** / {cpu_count * 100:.0f}%",
            inline=False
        )
        embed.add_field(
            name="🧠 Memory",
            value=f"**{mem_used_mib:.1f} MiB** / {mem_total_mib:.0f} MiB ({mem_percent:.1f}%)",
            inline=False
        )
        embed.add_field(
            name="💾 Disk",
            value=f"**{disk_used_mib:.2f} MiB** / {disk_total_gib:.1f} GiB ({disk_percent:.1f}%)",
            inline=False
        )
        embed.add_field(
            name="⏱️ Uptime",
            value=f"{uptime_hours}ч {uptime_mins}м",
            inline=False
        )

        embed.set_footer(text=f"Запросил: {ctx.author.name} • {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
        await ctx.send(embed=embed)
# ===========================
# 💰 COG: ЭКОНОМИКА
# ===========================
class Economy(commands.Cog, name="💰 Экономика"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='collect', aliases=['coll'])
    @is_registered()
    async def collect(self, ctx):
        """Собрать доход и прирост населения (с учётом содержания и баффов/дебаффов)"""
        user = await get_user(ctx.author.id)
        if user['gdp'] == 0:
            await ctx.send("❌ У тебя нет ВВП! Обратись к администратору.")
            return

        current_time = datetime.now().timestamp()
        last_collect = user.get('last_collect', 0)
        hours_passed = (current_time - last_collect) / 3600
        hours_passed = min(hours_passed, 12)

        if hours_passed < 1:
            remaining_mins = int((1 - hours_passed) * 60)
            await ctx.send(f"⏰ Подожди ещё **{remaining_mins}** мин. перед следующим коллектом!")
            return

        income_per_hour = user['gdp'] / 48
        gross_income = int(income_per_hour * hours_passed)

        # Применяем баффы/дебаффы
        await buffs_col.delete_many({'user_id': str(ctx.author.id), 'expires_at': {'$lt': current_time}})
        buffs = await buffs_col.find({'user_id': str(ctx.author.id)}).to_list(length=100)

        buff_list = [b for b in buffs if b['type'] == 'buff']
        debuff_list = [b for b in buffs if b['type'] == 'debuff']

        sum_buff_percent = sum(b['percent'] for b in buff_list)
        sum_debuff_percent = sum(b['percent'] for b in debuff_list)

        buff_amount = int(gross_income * sum_buff_percent / 100)
        debuff_amount = int(gross_income * sum_debuff_percent / 100)

        # Бюджетные вычеты
        budget_social = user.get('budget_social', DEFAULT_BUDGETS['budget_social'])
        budget_education = user.get('budget_education', DEFAULT_BUDGETS['budget_education'])
        budget_healthcare = user.get('budget_healthcare', DEFAULT_BUDGETS['budget_healthcare'])
        budget_other = DEFAULT_BUDGETS['budget_other']

        deduct_social = int(gross_income * budget_social / 100)
        deduct_education = int(gross_income * budget_education / 100)
        deduct_healthcare = int(gross_income * budget_healthcare / 100)
        deduct_other = int(gross_income * budget_other / 100)
        total_budget_deduct = deduct_social + deduct_education + deduct_healthcare + deduct_other

        # Содержание техники и солдат
        vehicle_cost_per_hour = await get_vehicle_maintenance_cost_per_hour(ctx.author.id)

        inventory = await get_inventory(ctx.author.id)
        total_soldier_maintenance = 0
        total_soldiers = 0

        for item in inventory:
            name = item['item_name']
            qty = item['quantity']
            if name == "Обученный Солдат":
                total_soldiers += qty
                total_soldier_maintenance += qty * SOLDIER_MAINTENANCE_PER_HOUR

        vehicle_cost = int(vehicle_cost_per_hour * hours_passed)
        soldier_cost = int(total_soldier_maintenance * hours_passed)

        # ===== НАЛОГ АЛЬЯНСА =====
        alliance_tax = 0
        alliance = await get_user_alliance(ctx.author.id)
        if alliance:
            alliance_tax_percent = alliance.get('tax_percent', 2)
            alliance_tax = int(gross_income * alliance_tax_percent / 100)
            await alliances_col.update_one(
                {'_id': alliance['_id']},
                {'$inc': {'treasury': alliance_tax}}
            )

        # ===== КАТЕГОРИЯ СТРАНЫ =====
        category = user.get('country_category', 'Нищая Страна')
        if category == 'Богатая Страна':
            category_penalty = int(gross_income * 0.50)
        elif category == 'Среднячок':
            category_penalty = int(gross_income * 0.25)
        else:
            category_penalty = 0

        net_income = gross_income + buff_amount - debuff_amount - total_budget_deduct - vehicle_cost - soldier_cost - alliance_tax - category_penalty
        new_balance = user['balance'] + net_income

        # Прирост населения
        population = user.get('population', 0)
        pop_gained = 0
        new_population = population
        if population > 0:
            last_pop_update = user.get('last_pop_update', 0)
            if last_pop_update == 0:
                last_pop_update = current_time
            yearly_pct = user.get('pop_growth_yearly', 2.0)
            hourly_pct = yearly_pct / 48.0
            hours_since_pop = (current_time - last_pop_update) / 3600
            if hours_since_pop > 0:
                growth_multiplier = (1 + hourly_pct / 100) ** hours_since_pop
                new_population = int(population * growth_multiplier)
                pop_gained = new_population - population
                if pop_gained > 0:
                    population = new_population

        update_data = {
            'balance': new_balance,
            'last_collect': current_time,
        }
        if pop_gained > 0:
            update_data['population'] = new_population
            update_data['last_pop_update'] = current_time
            mob_pct = user.get('mobilization_percent', 7.5)
            max_pool = int(new_population * mob_pct / 100)
            current_pool = user.get('mob_pool', 0)
            pool_gain = int(pop_gained * mob_pct / 100)
            new_pool = min(current_pool + pool_gain, max_pool)
            update_data['mob_pool'] = new_pool

            await update_user(ctx.author.id, update_data)

        # Авто-обновление категории по ВВП
        await auto_update_category(ctx.author.id, user['gdp'])

        embed = discord.Embed(
            title="💵 Коллект",
            description=f"Ты собрал доход за **{hours_passed:.1f}** ч.",
            color=discord.Color.green()
        )
        embed.add_field(name="ВВП", value=f"{user['gdp']:,} 💵", inline=True)
        embed.add_field(name="Доход в час", value=f"{income_per_hour:,.0f} 💵", inline=True)
        embed.add_field(name="Валовый доход", value=f"{gross_income:,} 💵", inline=False)

        if buff_list or debuff_list:
            if sum_buff_percent > 0:
                embed.add_field(name="🔼 Баффы", value=f"+{sum_buff_percent}% (+{buff_amount:,} 💵)", inline=True)
            if sum_debuff_percent > 0:
                embed.add_field(name="🔽 Дебаффы", value=f"-{sum_debuff_percent}% (-{debuff_amount:,} 💵)", inline=True)

        embed.add_field(
            name="Вычеты бюджета",
            value=(
                f"🏛️ Социальные расходы ({budget_social}%): -{deduct_social:,} 💵\n"
                f"📚 Образование ({budget_education}%): -{deduct_education:,} 💵\n"
                f"🏥 Здравоохранение ({budget_healthcare}%): -{deduct_healthcare:,} 💵\n"
                f"📋 Иные расходы ({budget_other}%): -{deduct_other:,} 💵\n"
                f"**Всего вычетов: -{total_budget_deduct:,} 💵**"
            ),
            inline=False
        )

        if vehicle_cost > 0:
            embed.add_field(
                name="🛠️ Содержание техники (0.25% от стоимости)",
                value=f"Расход: -{vehicle_cost:,} 💵",
                inline=False
            )
        if soldier_cost > 0:
            embed.add_field(
                name="🪖 Содержание солдат",
                value=f"Кол-во солдат: {total_soldiers:,}\nРасход: -{soldier_cost:,} 💵",
                inline=False
            )
        if alliance_tax > 0:
            embed.add_field(
                name="🏛️ Налог альянса",
                value=f"Налог {alliance.get('tax_percent', 2)}%: -{alliance_tax:,} 💵",
                inline=False
            )
        if category_penalty > 0:
            embed.add_field(
                name="📉 Экономический вычет",
                value=f"-{category_penalty:,} 💵",
                inline=False
            )

        embed.add_field(name="📌 Чистая прибыль", value=f"+{net_income:,} 💵", inline=False)
        embed.add_field(name="💰 Новый баланс", value=f"{new_balance:,} 💵", inline=False)

        if population > 0:
            if pop_gained > 0:
                mob_pct = user.get('mobilization_percent', 2.5)
                pool_gain = int(pop_gained * mob_pct / 100)
                embed.add_field(
                    name="👥 Прирост населения",
                    value=f"+{pop_gained:,} чел. (пул мобилизации +{pool_gain:,})",
                    inline=True
                )
            else:
                embed.add_field(name="👥 Прирост населения", value="0 чел. (слишком мало времени)", inline=True)
            embed.add_field(name="🌍 Новое население", value=f"{new_population:,} чел.", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name='reforms')
    @is_registered()
    async def reforms(self, ctx, amount: int = None, *, message_link: str = None):
        """Вложить деньги в ВВП (требуется ссылка на сообщение из канала реформ)"""
        if amount is None or message_link is None:
            await ctx.send(USAGE_HINTS['reforms'])
            return
        if amount <= 0:
            await ctx.send("❌ Сумма должна быть больше 0!")
            return

        pattern = r"https://discord.com/channels/\d+/(\d+)/(\d+)"
        match = re.match(pattern, message_link)
        if not match:
            await ctx.send("❌ Неверный формат ссылки. Ожидается ссылка на сообщение Discord.")
            return
        channel_id = match.group(1)
        message_id = match.group(2)
        if channel_id != "1363585142593032412":
            await ctx.send("❌ Ссылка должна вести в канал реформ (<#1363585142593032412>).")
            return

        try:
            reform_channel = ctx.guild.get_channel(int(channel_id))
            if reform_channel:
                message = await reform_channel.fetch_message(int(message_id))
                if message.author.id != ctx.author.id:
                    await ctx.send("❌ Вы можете использовать только ссылки на свои сообщения!")
                    return
        except:
            await ctx.send("❌ Не удалось проверить сообщение. Убедитесь, что ссылка корректна.")
            return

        existing = await reform_links_col.find_one({"message_id": message_id})
        if existing:
            await ctx.send("❌ Эта ссылка уже была использована для реформ. Пожалуйста, приложите новое сообщение.")
            return

        user = await get_user(ctx.author.id)
        if user['gdp'] == 0:
            await ctx.send("❌ У тебя нет ВВП! Обратись к администратору.")
            return

        max_investment = user['gdp'] * 2
        if amount > max_investment:
            await ctx.send(f"❌ Максимальная инвестиция: **{max_investment:,}** 💵 (x2 от ВВП)")
            return

        if user['balance'] < amount:
            await ctx.send(f"❌ Недостаточно денег! Баланс: {user['balance']:,} 💵")
            return

        gdp = user['gdp']
        if gdp < 300_000_000_000:
            efficiency = 0.50; tier = "50%"
        elif gdp <= 500_000_000_000:
            efficiency = 0.40; tier = "40%"
        elif gdp <= 900_000_000_000:
            efficiency = 0.30; tier = "30%"
        elif gdp <= 2_800_000_000_000:
            efficiency = 0.15; tier = "15%"
        else:
            efficiency = 0.10; tier = "10%"

        gdp_gain = int(amount * efficiency)
        new_gdp = user['gdp'] + gdp_gain
        new_balance = user['balance'] - amount

        await reform_links_col.insert_one({
            "message_id": message_id,
            "channel_id": channel_id,
            "used_by": str(ctx.author.id),
            "used_at": datetime.now().timestamp()
        })

        await update_user(ctx.author.id, {
            'gdp': new_gdp,
            'balance': new_balance
        })

        # Авто-обновление категории по ВВП
        await auto_update_category(ctx.author.id, new_gdp)

        embed = discord.Embed(
            title="🏗️ Реформы",
            description=f"{ctx.author.mention} вложил **{amount:,}** 💵 в ВВП\nПричина: [Ссылка]({message_link})",
            color=discord.Color.blue()
        )
        embed.add_field(name="Эффективность", value=f"{tier} от вложения", inline=False)
        embed.add_field(name="Прирост ВВП", value=f"+{gdp_gain:,} 💵", inline=True)
        embed.add_field(name="Старый ВВП", value=f"{user['gdp']:,} 💵", inline=True)
        embed.add_field(name="Новый ВВП", value=f"{new_gdp:,} 💵", inline=True)
        embed.add_field(name="Баланс", value=f"{new_balance:,} 💵", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name='pay')
    @is_registered()
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def pay(self, ctx, member: discord.Member, amount: int):
        """Перевести деньги другому игроку"""
        if member.bot:
            await ctx.send("❌ Нельзя платить ботам!"); return
        if member == ctx.author:
            await ctx.send("❌ Нельзя платить самому себе!"); return
        if amount <= 0:
            await ctx.send("❌ Сумма должна быть больше 0!"); return

        sender = await get_user(ctx.author.id)
        if sender['balance'] < amount:
            await ctx.send(f"❌ Недостаточно денег! Баланс: {sender['balance']:,} 💵"); return

        receiver = await get_user(member.id)
        await update_user(ctx.author.id, {'balance': sender['balance'] - amount})
        await update_user(member.id, {'balance': receiver['balance'] + amount})

        embed = discord.Embed(
            title="💸 Перевод денег",
            description=f"{ctx.author.mention} отправил {member.mention} **{amount:,}** 💵",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)

    @commands.command(name='sell')
    @is_registered()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def sell(self, ctx, quantity: int, member: discord.Member, amount: int, *, item_query: str):
        """Продать предмет из инвентаря другому игроку"""
        if member.bot:
            await ctx.send("❌ Нельзя продавать ботам!")
            return
        if member == ctx.author:
            await ctx.send("❌ Нельзя продавать самому себе!")
            return
        if quantity <= 0:
            await ctx.send("❌ Количество должно быть больше 0.")
            return
        if amount <= 0:
            await ctx.send("❌ Сумма должна быть больше 0.")
            return

        buyer_user = await get_user(member.id)
        role = ctx.guild.get_role(REGISTERED_ROLE_ID)
        if role is None or role not in member.roles:
            await ctx.send("❌ Покупатель не зарегистрирован.")
            return

        items = await get_inventory(ctx.author.id)
        if not items:
            await ctx.send("❌ Ваш инвентарь пуст.")
            return

        regex = re.compile(re.escape(item_query.strip()), re.IGNORECASE)
        matches = [it for it in items if regex.search(it['item_name'])]
        if not matches:
            await ctx.send("❌ У вас нет предметов с таким названием.")
            return

        if len(matches) > 1:
            options = [discord.SelectOption(label=it['item_name'][:100]) for it in matches[:25]]
            select = Select(placeholder="Выберите предмет для продажи...", options=options)
            view = SellItemSelectView(ctx.author.id, matches, select, member, quantity, amount, self)
            select.callback = view.select_callback
            view.add_item(select)
            await ctx.send("Найдено несколько предметов. Выберите, что продавать:", view=view, ephemeral=True)
            return

        item = matches[0]
        if item['quantity'] < quantity:
            await ctx.send(f"❌ У вас только **{item['quantity']}** шт. предмета **{item['item_name']}**.")
            return

        embed = self._build_sell_offer_embed(ctx.author, member, item['item_name'], quantity, amount)
        view = TradeOfferView(ctx.author.id, member.id, item['item_name'], quantity, amount, self)
        await ctx.send(embed=embed, view=view)

    def _build_sell_offer_embed(self, seller: discord.Member, buyer: discord.Member,
                                item_name: str, quantity: int, price: int) -> discord.Embed:
        embed = discord.Embed(
            title="💰 Предложение о продаже",
            description=(
                f"{seller.mention} предлагает {buyer.mention} купить:\n"
                f"**{item_name}** × {quantity}\n"
                f"Цена: **{price:,}** 💵"
            ),
            color=discord.Color.gold()
        )
        embed.set_footer(text="У покупателя 2 минуты, чтобы принять или отклонить.")
        return embed

    @commands.command(name='top')
    @is_registered() 
    async def top(self, ctx):
        """Топ-10 по ВВП, населению или балансу"""
        view = TopSelectView(ctx)
        embed = await view.build_embed('balance')
        view.message = await ctx.send(embed=embed, view=view)

    async def build_cab_embed(self, member: discord.Member) -> discord.Embed:
        user = await get_user(member.id)
        unhappiness = await update_unhappiness(member.id, user)

        income_per_hour = user['gdp'] / 48 if user['gdp'] > 0 else 0
        country = user.get('country') or member.name

        current_time = datetime.now().timestamp()
        last_collect = user.get('last_collect', 0)
        hours_passed = min((current_time - last_collect) / 3600, 12)
        pending = int(income_per_hour * hours_passed)

        embed = discord.Embed(
            title=f"📊 Статистика {country} ({member.name})",
            color=discord.Color.blurple()
        )

        flag_url = user.get('country_flag_url', '')
        if flag_url and flag_url.startswith('http'):
            embed.set_thumbnail(url=flag_url)
        else:
            embed.set_thumbnail(url=member.display_avatar.url)

        embed.add_field(name="💰 Баланс", value=f"💵 {user['balance']:,}", inline=True)
        embed.add_field(name="📈 ВВП", value=f"💵 {user['gdp']:,}", inline=True)
        embed.add_field(name="📊 Доход в час", value=f"💵 {int(income_per_hour):,}", inline=True)
        embed.add_field(name="⏳ Ожидает коллекта", value=f"{pending:,} 💵", inline=False)

        embed.add_field(
            name="🌍 Население",
            value=(
                f"👤 {user.get('population', 0):,} чел.\n"
                f"📈 Рост Населения в Год: {user.get('pop_growth_yearly', 2.0):.2f}%\n"
                f"🎖️ Пул мобилизации: {user.get('mob_pool', 0):,}"
            ),
            inline=False
        )

        speed = calculate_unhappiness_speed(user)
        embed.add_field(
            name="😡 Недовольство",
            value=f"{unhappiness:.2f}%\n({speed:+.2f}%/ч)",
            inline=False
        )

        embed.add_field(
            name="🎭 Идеология",
            value=user.get('ideology', 'Не указана'),
            inline=False
        )

        return embed

    @commands.command(name='cab')
    @is_registered()
    async def cab(self, ctx, member: discord.Member = None):
        """Статистика игрока — ВВП, баланс, население, недовольство, баффы"""
        if member is None:
            member = ctx.author
        embed = await self.build_cab_embed(member)
        await ctx.send(embed=embed)

    @commands.command(name='set-ideology', aliases=['ideology'])
    @is_registered()
    async def set_ideology(self, ctx, *, ideology_text: str = None):
        """Установить свою идеологию (до 200 символов) или посмотреть текущую"""
        if ideology_text is None:
            user = await get_user(ctx.author.id)
            current = user.get('ideology', 'Не указана')
            embed = discord.Embed(
                title="🎭 Ваша идеология",
                description=f"**{current}**",
                color=discord.Color.blue()
            )
            embed.set_footer(text="Используйте !set-ideology <текст> для изменения")
            await ctx.send(embed=embed)
            return

        ideology_clean = ideology_text.strip()
        if len(ideology_clean) == 0:
            await ctx.send("❌ Текст идеологии не может быть пустым!")
            return
        if len(ideology_clean) > 200:
            await ctx.send("❌ Текст идеологии не может быть длиннее 200 символов!")
            return

        user = await get_user(ctx.author.id)
        old_ideology = user.get('ideology', 'Не указана')
        await update_user(ctx.author.id, {'ideology': ideology_clean})

        embed = discord.Embed(title="🎭 Идеология изменена", color=discord.Color.blue())
        if old_ideology != ideology_clean:
            embed.add_field(name="Была", value=f"**{old_ideology}**", inline=True)
            embed.add_field(name="Стала", value=f"**{ideology_clean}**", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name='burn')
    @is_registered()
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def burn(self, ctx, amount: int, *, reason: str = "Без причины"):
        """Сжечь деньги из баланса (для зарегистрированных игроков)"""
        if amount <= 0:
            await ctx.send("❌ Сумма должна быть больше 0!")
            return

        is_valid, error_msg = validate_amount(amount)
        if not is_valid:
            await ctx.send(error_msg)
            return

        user = await get_user(ctx.author.id)
        if user['balance'] < amount:
            await ctx.send(f"❌ Недостаточно денег! Баланс: {user['balance']:,} 💵")
            return

        new_balance = user['balance'] - amount
        await update_user(ctx.author.id, {'balance': new_balance})

        await burn_logs_col.insert_one({
            'user_id': str(ctx.author.id),
            'amount': amount,
            'reason': reason.strip(),
            'timestamp': datetime.now().timestamp(),
            'username': ctx.author.name
        })

        embed = discord.Embed(
            title="🔥 Деньги сожжены",
            description=f"{ctx.author.mention} сжег **{amount:,}** 💵",
            color=discord.Color.orange()
        )
        embed.add_field(name="Причина", value=reason.strip(), inline=False)
        embed.add_field(name="Баланс", value=f"{new_balance:,} 💵", inline=False)
        await ctx.send(embed=embed)
        
    @commands.command(name='calc-maintenance')
    @is_registered()
    async def calc_maintenance(self, ctx):
        user = await get_user(ctx.author.id)
        inventory = await get_inventory(ctx.author.id)

        vehicle_lines = []
        total_vehicle_cost = 0

        for item in inventory:
            if item['item_name'] == "Обученный Солдат":
                continue
            vehicle = await vehicles_col.find_one({'name': item['item_name'], 'approved': True})
            if vehicle:
                cost = int(vehicle['price'] * item['quantity'] * 0.0025)
                total_vehicle_cost += cost
                vehicle_lines.append(
                    f"`{item['item_name']}` x{item['quantity']:,} — {cost:,} 💵/ч"
                )

        total_soldiers = sum(
            item['quantity'] for item in inventory if item['item_name'] == "Обученный Солдат"
        )
        soldier_cost = total_soldiers * SOLDIER_MAINTENANCE_PER_HOUR
        total_cost = total_vehicle_cost + soldier_cost

        income_per_hour = user['gdp'] / 48 if user['gdp'] > 0 else 0
        maintenance_pct = (total_cost / income_per_hour * 100) if income_per_hour > 0 else 0

        embed = discord.Embed(
            title="🔧 Расходы на содержание",
            color=discord.Color.orange()
        )

        if vehicle_lines:
            embed.add_field(
                name="🚗 Техника (0.25%/ч от стоимости)",
                value="\n".join(vehicle_lines) + f"\n**Итого: {total_vehicle_cost:,} 💵/ч**",
                inline=False
            )
        else:
            embed.add_field(name="🚗 Техника", value="Нет техники", inline=False)

        embed.add_field(
            name="🪖 Солдаты",
            value=f"`Обученный Солдат` x{total_soldiers:,} — {soldier_cost:,} 💵/ч" if total_soldiers > 0 else "Нет солдат",
            inline=False
        )

        embed.add_field(name="💸 Общие расходы/ч", value=f"{total_cost:,} 💵", inline=True)
        embed.add_field(name="📈 Доход/ч", value=f"{int(income_per_hour):,} 💵", inline=True)
        embed.add_field(name="⚖️ % от дохода", value=f"{maintenance_pct:.1f}%", inline=True)

        embed.set_footer(text=f"За 12ч содержание составит: {total_cost * 12:,} 💵")
        try:
            await ctx.author.send(embed=embed)
            await ctx.send(f"📬 {ctx.author.mention}, информация о расходах отправлена в личные сообщения!")
        except discord.Forbidden:
            await ctx.send(f"❌ {ctx.author.mention}, не удалось отправить ЛС. Проверьте настройки приватности.")
# ===========================
# 📊 COG: БЮДЖЕТ
# ===========================
class Budget(commands.Cog, name="📊 Бюджет"):
    def __init__(self, bot):
        self.bot = bot

    CATEGORY_MAP = {
        'социальные-расходы': 'budget_social',
        'соц': 'budget_social',
        'социальные': 'budget_social',
        'образование': 'budget_education',
        'обр': 'budget_education',
        'здравоохранение': 'budget_healthcare',
        'здрав': 'budget_healthcare',
    }

    CATEGORY_NAMES = {
        'budget_social': 'Социальные расходы',
        'budget_education': 'Образование',
        'budget_healthcare': 'Здравоохранение',
        'budget_other': 'Иные расходы',
    }

    @commands.command(name='budjet')
    @is_registered()
    async def budjet(self, ctx, category: str = None, percent: int = None):
        """Изменить статью бюджета (1-15%)"""
        if category is None or percent is None:
            await ctx.send("❌ Использование: `!budjet <категория> <процент>`\nКатегории: `социальные-расходы`, `образование`, `здравоохранение`")
            return
        category_key = self.CATEGORY_MAP.get(category.lower())
        if not category_key:
            await ctx.send("❌ Неизвестная категория. Доступные: `социальные-расходы`, `образование`, `здравоохранение`")
            return
        if percent < 1 or percent > 15:
            await ctx.send("❌ Процент должен быть от 1 до 15.")
            return
        user = await get_user(ctx.author.id)
        await update_unhappiness(ctx.author.id, user)
        old_value = user[category_key]
        if old_value == percent:
            await ctx.send(f"❌ {self.CATEGORY_NAMES[category_key]} уже установлены на {percent}%.")
            return
        await update_user(ctx.author.id, {category_key: percent})
        new_unhappiness = user.get('unhappiness', 0.0)
        speed = calculate_unhappiness_speed(user)
        embed = discord.Embed(
            title="📊 Бюджет изменён",
            description=f"**{self.CATEGORY_NAMES[category_key]}** изменены с **{old_value}%** на **{percent}%**.",
            color=discord.Color.orange()
        )
        embed.add_field(name="Текущее недовольство", value=f"{new_unhappiness:.2f}%")
        embed.add_field(name="Скорость изменения", value=f"{speed:+.2f}%/ч")
        await ctx.send(embed=embed)

    @commands.command(name='budjet-info', aliases=['бюджет'])
    @is_registered()
    async def budjet_info(self, ctx, member: discord.Member = None):
        """Посмотреть текущий бюджет и недовольство"""
        if member is None:
            member = ctx.author
        user = await get_user(member.id)
        unhappiness = await update_unhappiness(member.id, user)
        embed = discord.Embed(title=f"📊 Бюджет {member.name}", color=discord.Color.teal())
        for key, name in self.CATEGORY_NAMES.items():
            value = user.get(key, DEFAULT_BUDGETS.get(key, 0))
            default = DEFAULT_BUDGETS.get(key, 0)
            if key == 'budget_other':
                embed.add_field(name=name, value=f"**{value}%** (фиксировано)", inline=True)
            else:
                embed.add_field(name=name, value=f"**{value}%** (по умолч. {default}%)", inline=True)
        speed = calculate_unhappiness_speed(user)
        embed.add_field(name="😡 Недовольство", value=f"{unhappiness:.2f}%\nСкорость: {speed:+.2f}%/ч", inline=False)
        embed.set_footer(text="Изменить: !budjet <категория> <процент>")
        await ctx.send(embed=embed)
# ===========================
# 👑 COG: АДМИН
# ===========================
class Admin(commands.Cog, name="👑 Админ"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='help-adm')
    @is_admin_or_kurator()
    async def help_admin(self, ctx):
        """Показать все админ-команды"""
        embed = discord.Embed(title="👑 Админ-команды", description="Доступны только администраторам. Префикс: `!`", color=discord.Color.red())
        cmds = self.get_commands()
        for cmd in cmds:
            embed.add_field(name=f"`!{cmd.name}`", value=cmd.help or "Нет описания", inline=False)
        embed.set_footer(text=f"Запросил: {ctx.author.name}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name='category-set')
    @is_admin_or_kurator_r()
    async def category_set(self, ctx, member: discord.Member):
        """Установить категорию страны игроку (влияет на доход)"""
        view = CategorySetView(ctx.author.id, member.id)
        await ctx.send(f"Выберите категорию для {member.mention}:", view=view)

    @commands.command(name='full-reg')
    @is_admin_or_kurator_r()
    async def full_reg(self, ctx, member: discord.Member):
        """Полная панель редактирования профиля игрока"""
        user = await get_user(member.id)
        embed = await self._build_full_reg_embed(member, user)
        view = FullRegView(self, member.id, user, ctx.author.id)
        view.message = await ctx.send(embed=embed, view=view)

    async def _build_full_reg_embed(self, member: discord.Member, user: dict) -> discord.Embed:
        unhappiness = await update_unhappiness(member.id, user)

        income_per_hour = user['gdp'] / 48 if user['gdp'] > 0 else 0
        country = user.get('country') or member.name

        current_time = datetime.now().timestamp()
        last_collect = user.get('last_collect', 0)
        hours_passed = min((current_time - last_collect) / 3600, 12)
        pending = int(income_per_hour * hours_passed)

        embed = discord.Embed(
            title=f"📊 Статистика {country} ({member.name})",
            color=discord.Color.blurple()
        )

        flag_url = user.get('country_flag_url', '')
        if flag_url and flag_url.startswith('http'):
            embed.set_thumbnail(url=flag_url)
        else:
            embed.set_thumbnail(url=member.display_avatar.url)

        embed.add_field(name="💰 Баланс", value=f"💵 {user['balance']:,}", inline=True)
        embed.add_field(name="📈 ВВП", value=f"💵 {user['gdp']:,}", inline=True)
        embed.add_field(name="📊 Доход в час", value=f"💵 {int(income_per_hour):,}", inline=True)

        embed.add_field(name="⏳ Ожидает коллекта", value=f"{pending:,} 💵", inline=False)

        embed.add_field(
            name="🌍 Население",
            value=(
                f"👤 {user.get('population', 0):,} чел.\n"
                f"📈 Рост Населения в Год: {user.get('pop_growth_yearly', 2.0):.2f}%\n"
                f"🎖️ Пул мобилизации: {user.get('mob_pool', 0):,}"
            ),
            inline=False
        )

        speed = calculate_unhappiness_speed(user)
        embed.add_field(
            name="😡 Недовольство",
            value=f"{unhappiness:.2f}%\n({speed:+.2f}%/ч)",
            inline=False
        )

        embed.add_field(
            name="🎭 Идеология",
            value=user.get('ideology', 'Не указана'),
            inline=False
        )

        return embed

    @commands.command(name='delete-vehicle', aliases=['del-vehicle'])
    @is_admin_or_kurator_t()
    async def delete_vehicle(self, ctx, *, name_or_part: str):
        """Удалить технику из магазина (по названию или его части)"""
        vehicles = await vehicles_col.find({"approved": True}).to_list(length=None)
        if not vehicles:
            await ctx.send("В магазине нет техники.")
            return
        matches = [v for v in vehicles if name_or_part.lower() in v['name'].lower()]
        if not matches:
            await ctx.send("Техника с таким названием не найдена.")
            return
        if len(matches) == 1:
            v = matches[0]
            confirm_view = ConfirmView(ctx.author.id, v['_id'], v['name'], self)
            await ctx.send(f"Найдена техника: **{v['name']}**. Удалить?", view=confirm_view)
        else:
            options = [discord.SelectOption(label=v['name'][:100], value=str(v['_id'])) for v in matches[:25]]
            select = Select(placeholder="Выберите технику для удаления...", options=options)
            view = DeleteSelectView(ctx.author.id, matches, select, self)
            await ctx.send("Найдено несколько вариантов. Выберите:", view=view)

    async def delete_vehicle_by_id(self, vehicle_id, name, interaction=None):
        await vehicles_col.delete_one({'_id': vehicle_id})
        await licenses_col.delete_many({'vehicle_name': name})
        await inventory_col.delete_many({'item_name': name})
        if interaction:
            await interaction.response.send_message(f"✅ Техника **{name}** удалена из магазина.", ephemeral=True)

    @commands.command(name='invsee')
    @commands.has_permissions(administrator=True)
    async def invsee(self, ctx, member: discord.Member):
        """Посмотреть инвентарь игрока (админ)"""
        view = InvseeChoiceView(ctx.author.id, member.id, self.bot)
        await ctx.send("Выберите, как показать инвентарь:", view=view)

    async def _process_take_removal(self, ctx, member, item: dict, requested_qty: int, interaction=None):
        available = item['quantity']
        take_qty = min(requested_qty, available)
        success = await remove_item(member.id, item['item_name'], take_qty)
        if success:
            msg = f"✅ У {member.mention} убрано **{take_qty}x {item['item_name']}**"
            if take_qty < requested_qty:
                msg += f"\n⚠️ У игрока было только **{available}** шт., поэтому забрано всё доступное."
            if interaction:
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx.send(msg)
        else:
            err = "❌ Не удалось забрать предмет."
            if interaction:
                await interaction.response.send_message(err, ephemeral=True)
            else:
                await ctx.send(err)

    @commands.command(name='reset-baff')
    @is_admin_or_kurator_r()
    async def reset_baff(self, ctx):
        """Удалить абсолютно все баффы и дебаффы у всех игроков"""
        try:
            result = await buffs_col.delete_many({})
            await ctx.send(f"✅ Все эффекты (баффы/дебаффы) были удалены. Очищено записей: {result.deleted_count}")
        except Exception as e:
            await ctx.send(f"❌ Произошла ошибка при очистке: {e}")

    @commands.command(name='give-item')
    @commands.has_permissions(administrator=True)
    async def give_item(self, ctx, member: discord.Member, quantity: int, *, item_name: str):
        """Выдать игроку предмет из магазина"""
        if quantity <= 0:
            await ctx.send("❌ Количество должно быть больше 0.")
            return
        vehicle = await vehicles_col.find_one({"approved": True, "name": item_name.strip()})
        if not vehicle:
            regex = re.compile(re.escape(item_name.strip()), re.IGNORECASE)
            matches = await vehicles_col.find({"approved": True, "name": {"$regex": regex}}).to_list(length=25)
            if not matches:
                await ctx.send("❌ Такой техники нет в магазине.")
                return
            if len(matches) > 1:
                names = [v['name'] for v in matches]
                await ctx.send(f"Найдено несколько совпадений: {', '.join(names)}. Уточните название.")
                return
            vehicle = matches[0]
        await add_item(member.id, vehicle['name'], quantity)
        await ctx.send(f"✅ {member.mention} получил **{quantity}x {vehicle['name']}**.")

    @commands.command(name='remove-sol')
    @is_admin_or_kurator_r()
    async def remove_soldiers(self, ctx, member: discord.Member, quantity: int):
        """Убрать солдат у игрока"""
        if quantity <= 0:
            await ctx.send("❌ Количество должно быть больше 0.")
            return
        success = await remove_item(member.id, "Обученный Солдат", quantity)
        if success:
            await ctx.send(f"✅ У {member.mention} убрано **{quantity}** обученных солдат.")
        else:
            await ctx.send(f"❌ У игрока недостаточно солдат.")

    @commands.command(name='add-sol')
    @is_admin_or_kurator_r()
    async def add_soldiers(self, ctx, member: discord.Member, quantity: int):
        """Добавить солдат игроку"""
        if quantity <= 0:
            await ctx.send("❌ Количество должно быть больше 0.")
            return
        await add_item(member.id, "Обученный Солдат", quantity)
        await ctx.send(f"✅ {member.mention} получил **{quantity}** обученных солдат.")

    @commands.command(name='ally-delete')
    @is_admin_or_kurator_r()
    async def ally_delete_admin(self, ctx):
        """Удалить альянс (админ)"""
        alliances = await alliances_col.find().to_list(length=None)
        if not alliances:
            await ctx.send("❌ Альянсов не найдено.")
            return
        if len(alliances) > 5:
            options = [discord.SelectOption(label=a['name'][:100], value=str(a['_id'])) for a in alliances[:25]]
            select = Select(placeholder="Выберите альянс для удаления...", options=options)
            view = AdminAllyDeleteSelectView(ctx.author.id, select, self.bot)
            select.callback = view.select_callback
            view.add_item(select)
            await ctx.send("Выберите альянс для удаления:", view=view)
        else:
            view = AdminAllyDeleteView(ctx.author.id, alliances, self.bot)
            await ctx.send("Выберите альянс для удаления:", view=view)

    @commands.command(name='edit-buy')
    @is_admin_or_kurator_t()
    async def edit_buy(self, ctx, *, args: str):
        """Изменить стоимость предмета: !edit-buy <название/часть названия> <новая стоимость>"""
        parts = args.rsplit(' ', 1)
        if len(parts) < 2:
            await ctx.send("❌ Использование: `!edit-buy <название/часть названия> <новая стоимость>`\nПример: `!edit-buy Т-90 6000000`")
            return
        name_or_part = parts[0].strip()
        try:
            new_price = int(parts[1].replace(',', '').replace(' ', ''))
            if new_price <= 0:
                raise ValueError
        except ValueError:
            await ctx.send("❌ Стоимость должна быть положительным целым числом.")
            return

        vehicle = await vehicles_col.find_one({"approved": True, "name": name_or_part.strip()})
        if not vehicle:
            regex = re.compile(re.escape(name_or_part.strip()), re.IGNORECASE)
            matches = await vehicles_col.find({"approved": True, "name": {"$regex": regex}}).to_list(length=25)
            if not matches:
                await ctx.send("❌ Техника не найдена.")
                return
            if len(matches) > 1:
                names = [v['name'] for v in matches]
                await ctx.send(f"Найдено несколько совпадений: {', '.join(names)}. Уточните название.")
                return
            vehicle = matches[0]

        old_price = vehicle['price']
        await vehicles_col.update_one({'_id': vehicle['_id']}, {'$set': {'price': new_price}})
        embed = discord.Embed(title="💰 Стоимость изменена", description=f"Техника: **{vehicle['name']}**", color=discord.Color.blue())
        embed.add_field(name="Старая стоимость", value=f"{old_price:,} 💵", inline=True)
        embed.add_field(name="Новая стоимость", value=f"{new_price:,} 💵", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name='burn-list')
    @is_admin_or_kurator_r()
    async def burn_list(self, ctx, member: discord.Member):
        """Показать историю сжигания денег игрока"""
        logs = await burn_logs_col.find({'user_id': str(member.id)}).sort('timestamp', -1).to_list(length=None)
        if not logs:
            await ctx.send(f"❌ У {member.mention} нет истории сжигания денег.")
            return

        embed = discord.Embed(title=f"🔥 История сжигания денег {member.name}", color=discord.Color.orange())
        description = ""
        for i, log in enumerate(logs, 1):
            timestamp = log.get('timestamp', 0)
            dt = datetime.fromtimestamp(timestamp)
            formatted_time = dt.strftime('%d.%m.%Y %H:%M:%S')
            reason = log.get('reason', 'Без причины')
            amount = log.get('amount', 0)
            line = f"**{i}.** {amount:,} 💵 — {reason}\n   ⏰ {formatted_time}\n"
            description += line

        if len(description) > 2000:
            description = ""
            for i, log in enumerate(logs[:10], 1):
                timestamp = log.get('timestamp', 0)
                dt = datetime.fromtimestamp(timestamp)
                formatted_time = dt.strftime('%d.%m.%Y %H:%M:%S')
                reason = log.get('reason', 'Без причины')
                amount = log.get('amount', 0)
                line = f"**{i}.** {amount:,} 💵 — {reason}\n   ⏰ {formatted_time}\n"
                description += line
            description += f"\n*Показаны последние 10 записей из {len(logs)}*"

        embed.description = description
        embed.set_footer(text=f"Всего записей: {len(logs)}")
        await ctx.send(embed=embed)
        
    @commands.command(name='edit-vehicle')
    @is_admin_or_kurator_t()
    async def edit_vehicle(self, ctx, *, name_or_part: str):
        """Редактировать технику из магазина"""
        vehicle = await vehicles_col.find_one({"approved": True, "name": name_or_part.strip()})
        if not vehicle:
            regex = re.compile(re.escape(name_or_part.strip()), re.IGNORECASE)
            matches = await vehicles_col.find({"approved": True, "name": {"$regex": regex}}).to_list(length=25)
            if not matches:
                await ctx.send("❌ Техника не найдена.")
                return
            if len(matches) == 1:
                vehicle = matches[0]
            else:
                options = [discord.SelectOption(label=v['name'][:100], value=str(v['_id'])) for v in matches[:25]]
                select = Select(placeholder="Выберите технику для редактирования...", options=options)
                view = EditVehicleSelectView(ctx.author.id, matches, select, self.bot)
                select.callback = view.select_callback
                view.add_item(select)
                await ctx.send("Найдено несколько вариантов. Выберите:", view=view)
                return
        shop_cog = self.bot.get_cog("🛒 Магазин")
        embed = await shop_cog.build_vehicle_info_embed(vehicle)
        view = EditVehicleView(ctx.author.id, vehicle['_id'], self.bot)
        view.message = await ctx.send(embed=embed, view=view)

    @commands.command(name='delete-zayavki')
    @is_admin_or_kurator_t()
    async def delete_zayavki(self, ctx):
        """Удалить все ожидающие заявки на технику и уведомить игроков"""
        pending = await vehicles_col.find({'approved': False}).to_list(length=None)
        if not pending:
            await ctx.send("❌ Нет активных заявок для удаления.")
            return
        notified = set()
        for vehicle in pending:
            submitter_id = vehicle.get('submitter_id')
            if submitter_id and submitter_id not in notified:
                try:
                    user = self.bot.get_user(int(submitter_id))
                    if not user:
                        user = await self.bot.fetch_user(int(submitter_id))
                    if user:
                        await user.send(
                            "⚠️ Похоже ваша заявка сломалась и была удалена администрацией, извините за ожидание."
                        )
                except Exception:
                    pass
                notified.add(submitter_id)
        result = await vehicles_col.delete_many({'approved': False})
        await ctx.send(
            f"✅ Удалено **{result.deleted_count}** заявок. "
            f"Уведомлено игроков: **{len(notified)}**."
        )
    @commands.command(name='yes')
    @is_admin_or_kurator_t()
    async def approve_application(self, ctx, application_id: str):
        """Принять заявку по ID (техника или альянс)"""
        try:
            obj_id = ObjectId(application_id)
        except Exception:
            await ctx.send("❌ Неверный формат ID заявки.")
            return

        # Ищем в технике
        vehicle = await vehicles_col.find_one({'_id': obj_id, 'approved': False})
        if vehicle:
            shop_cog = self.bot.get_cog("🛒 Магазин")
            await shop_cog.approve_vehicle(obj_id, ctx.author)

            # Редактируем оригинальный embed если возможно
            await self._update_application_embed(vehicle, approved=True, moderator=ctx.author, reason=None)

            await ctx.send(f"✅ Заявка на технику **{vehicle['name']}** одобрена.")
            return

        # Ищем в альянсах
        alliance = await alliances_col.find_one({'_id': obj_id, 'approved': False})
        if alliance:
            guild = ctx.guild
            try:
                thread_channel = guild.get_channel(ALLIANCES_THREADS_CHANNEL_ID)
                creator_id = int(alliance['owner_id'])
                if thread_channel:
                    thread = await thread_channel.create_thread(
                        name=f"🏛️ {alliance['name']}",
                        auto_archive_duration=1440,
                        reason=f"Альянс {alliance['name']}"
                    )
                    creator = guild.get_member(creator_id)
                    if creator:
                        await thread.add_user(creator)
                    await alliances_col.update_one(
                        {'_id': obj_id},
                        {'$set': {'thread_id': thread.id, 'approved': True}}
                    )
                    await update_user(creator_id, {'alliance_id': obj_id, 'alliance_role': 'owner'})

                    await self._update_application_embed(alliance, approved=True, moderator=ctx.author, reason=None, is_alliance=True)

                    try:
                        if creator:
                            await creator.send(f"✅ Ваш альянс **{alliance['name']}** одобрен!\nВетка: {thread.mention}")
                    except:
                        pass
                    await ctx.send(f"✅ Альянс **{alliance['name']}** одобрен, создана ветка {thread.mention}.")
                else:
                    await ctx.send("❌ Канал для веток не найден.")
            except Exception as e:
                await ctx.send(f"❌ Ошибка при одобрении альянса: {e}")
            return

        await ctx.send("❌ Заявка с таким ID не найдена (или уже обработана).")
    @commands.command(name='unreg')
    @is_admin_or_kurator_r()
    async def unreg(self, ctx, user_id: str):
        """Полный сброс данных игрока по ID: !unreg <user_id>"""
        try:
            uid = int(user_id)
        except ValueError:
            await ctx.send("❌ Укажите числовой ID пользователя.")
            return

        default_user = {
            'balance': 0,
            'gdp': 0,
            'last_collect': 0,
            'population': 0,
            'pop_growth_yearly': 2.0,
            'last_pop_update': 0,
            'budget_social': DEFAULT_BUDGETS['budget_social'],
            'budget_education': DEFAULT_BUDGETS['budget_education'],
            'budget_healthcare': DEFAULT_BUDGETS['budget_healthcare'],
            'budget_other': DEFAULT_BUDGETS['budget_other'],
            'unhappiness': 0.0,
            'last_unhappiness_update': 0,
            'country': None,
            'country_flag_url': None,
            'mobilization_percent': 2.5,
            'mob_pool': 0,
            'alliance_id': None,
            'alliance_role': None,
            'ideology': 'Не указана',
            'country_category': 'Нищая Страна',
            'government_form': 'Не указана',
            'leader': 'Не указан',
            'gdp_pps': 0,
            'national_debt': 0,
            'income_services': 0,
            'income_exports': 0,
            'income_tourism': 0,
            'income_other_src': 0,
            'nationalities': '',
            'military_budget': 0,
        }
        await economy_col.delete_one({'_id': str(uid)}) 
        await inventory_col.delete_many({'user_id': str(uid)})
        await licenses_col.delete_many({'user_id': str(uid)})
        await buffs_col.delete_many({'user_id': str(uid)})
        
        async for doc in economy_col.find({}):
            try:
                uid_check = int(doc['_id'])
            except (ValueError, TypeError):
                continue
            member_check = ctx.guild.get_member(uid_check)
            if member_check:
                reg_role = ctx.guild.get_role(REGISTERED_ROLE_ID)
                if reg_role and reg_role not in member_check.roles:
                    await economy_col.delete_one({'_id': str(uid_check)})             
        

    # Снять роли если игрок на сервере
        member = ctx.guild.get_member(uid)
        if member:
            reg_role = ctx.guild.get_role(REGISTERED_ROLE_ID)
            unreg_role = ctx.guild.get_role(UNREGISTERED_ROLE_ID)
            country_role = ctx.guild.get_role(COUNTRY_ROLE_ID)
            temp_role = ctx.guild.get_role(TEMP_ROLE_ID)
            if reg_role: await member.remove_roles(reg_role)
            if country_role: await member.remove_roles(country_role)
            if temp_role: await member.remove_roles(temp_role)
            if unreg_role: await member.add_roles(unreg_role)
            await cancel_role_removal(uid, TEMP_ROLE_ID)
            await ctx.send(f"✅ Игрок {member.mention} полностью сброшен.")
        else:
            await cancel_role_removal(uid, TEMP_ROLE_ID)
            await ctx.send(f"✅ Данные игрока `{uid}` очищены (игрок не найден на сервере).")
    @commands.command(name='no')
    @is_admin_or_kurator_t()
    async def reject_application(self, ctx, application_id: str):
        """Отклонить заявку по ID — откроет окно с причиной (техника или альянс)"""
        try:
            obj_id = ObjectId(application_id)
        except Exception:
            await ctx.send("❌ Неверный формат ID заявки.")
            return

        # Ищем в технике
        vehicle = await vehicles_col.find_one({'_id': obj_id, 'approved': False})
        if vehicle:
            modal = RejectApplicationModal(obj_id, app_type='vehicle', app_name=vehicle['name'], admin_cog=self)
            await ctx.send("Откройте форму для указания причины:", view=RejectModalTriggerView(modal, ctx.author.id))
            return

        # Ищем в альянсах
        alliance = await alliances_col.find_one({'_id': obj_id, 'approved': False})
        if alliance:
            modal = RejectApplicationModal(obj_id, app_type='alliance', app_name=alliance['name'], admin_cog=self)
            await ctx.send("Откройте форму для указания причины:", view=RejectModalTriggerView(modal, ctx.author.id))
            return

        await ctx.send("❌ Заявка с таким ID не найдена (или уже обработана).")

    async def _update_application_embed(self, doc: dict, approved: bool, moderator: discord.Member,
                                        reason: str = None, is_alliance: bool = False):
        """Редактирует embed оригинальной заявки в канале одобрения"""
        try:
            channel_id = doc.get('approval_channel_id')
            message_id = doc.get('approval_message_id')
            if not channel_id or not message_id:
                return
            channel = self.bot.get_channel(channel_id)
            if not channel:
                return
            message = await channel.fetch_message(message_id)
            if not message or not message.embeds:
                return
            embed = message.embeds[0]
            if approved:
                embed.color = discord.Color.green()
                embed.title = f"✅ {'Альянс' if is_alliance else 'Техника'} одобрена"
                embed.set_footer(text=f"Одобрено: {moderator} | ID: {doc['_id']}")
            else:
                embed.color = discord.Color.red()
                embed.title = f"❌ {'Альянс' if is_alliance else 'Техника'} отклонена"
                if reason:
                    embed.add_field(name="Причина отклонения", value=reason, inline=False)
                embed.set_footer(text=f"Отклонено: {moderator} | ID: {doc['_id']}")
            await message.edit(embed=embed, view=None)
        except Exception:
            pass
    @commands.command(name='clear-top')
    @is_admin_or_kurator_r()
    async def clear_top(self, ctx):
        """Очистить топ от незарегистрированных и покинувших сервер игроков"""
        reg_role = ctx.guild.get_role(REGISTERED_ROLE_ID)
        if not reg_role:
            await ctx.send("❌ Роль зарегистрированного не найдена.")
            return

        status_msg = await ctx.send("🔄 Анализирую базу данных...")

        all_users = await economy_col.find({}).to_list(length=None)
        removed = 0
        skipped = 0

        for user_data in all_users:
            try:
                user_id = int(user_data['_id'])
            except (ValueError, TypeError):
                continue

            member = ctx.guild.get_member(user_id)

            # Убираем если не на сервере или нет роли зарегистрированного
            should_remove = (
                member is None or
                reg_role not in member.roles
            )

            if should_remove:
                await economy_col.delete_one({'_id': user_data['_id']})
                removed += 1
            else:
                skipped += 1

        embed = discord.Embed(
            title="🧹 Очистка топа завершена",
            color=discord.Color.orange()
        )
        embed.add_field(name="✅ Оставлено", value=f"{skipped} игроков", inline=True)
        embed.add_field(name="🗑️ Удалено", value=f"{removed} записей", inline=True)
        embed.set_footer(text=f"Запросил: {ctx.author.name}")
        await status_msg.edit(content=None, embed=embed)
    @commands.command(name='buffs')
    @is_admin_or_kurator()
    async def buffs(self, ctx, member: discord.Member):
        """Управление баффами/дебаффами игрока"""
        view = BuffManageView(member, ctx.author)
        content = await view.build_content()
        embed = discord.Embed(title=f"⚡ Баффы/Дебаффы — {member.display_name}", description=content, color=discord.Color.orange())
        await ctx.send(embed=embed, view=view) 
    @commands.command(name='inactive')
    @is_admin_or_kurator_r()
    async def inactive(self, ctx):
        NEWS_CHANNEL_ID = 1363585142593032412
        MIN_CHARS = 400

        news_channel = ctx.guild.get_channel(NEWS_CHANNEL_ID)
        if not news_channel:
            await ctx.send("❌ Канал новостей не найден.")
            return

        await ctx.send("🔍 Проверяю новости... это может занять момент.")

        # Get all registered members
        registered_role = ctx.guild.get_role(REGISTERED_ROLE_ID)
        if not registered_role:
            await ctx.send("❌ Роль зарегистрированных игроков не найдена.")
            return

        registered_members = {m.id: m for m in registered_role.members}

        # Scan last 500 messages in the news channel
        # Track the latest valid post per user
        user_posts = {}  # user_id -> (message, char_count)

        async for message in news_channel.history(limit=500):
            if message.author.id not in registered_members:
                continue
            char_count = len(message.content)
            # Only store their latest post
            if message.author.id not in user_posts:
                user_posts[message.author.id] = (message, char_count)

        # Build inactive lists
        no_post = []       # never posted
        short_post = []    # posted but under 400 chars

        for member_id, member in registered_members.items():
            if member.bot:
                continue
            if member_id not in user_posts:
                no_post.append(member)
            else:
                _, char_count = user_posts[member_id]
                if char_count < MIN_CHARS:
                    short_post.append((member, char_count))

        # Build embed
        embed = discord.Embed(
            title="📋 Неактивные игроки (Новости)",
            description=f"Канал: <#{NEWS_CHANNEL_ID}> | Минимум: {MIN_CHARS} символов",
            color=discord.Color.red()
        )

        if no_post:
            no_post_text = "\n".join(f"• {m.mention}" for m in no_post)
            # Split if too long
            if len(no_post_text) > 1024:
                no_post_text = no_post_text[:1020] + "..."
            embed.add_field(
                name=f"❌ Нет новостей ({len(no_post)})",
                value=no_post_text,
                inline=False
            )
        else:
            embed.add_field(name="❌ Нет новостей", value="Все игроки опубликовали новости!", inline=False)

        if short_post:
            short_text = "\n".join(f"• {m.mention} — {c} симв." for m, c in short_post)
            if len(short_text) > 1024:
                short_text = short_text[:1020] + "..."
            embed.add_field(
                name=f"⚠️ Менее {MIN_CHARS} символов ({len(short_post)})",
                value=short_text,
                inline=False
            )
        else:
            embed.add_field(
                name=f"⚠️ Менее {MIN_CHARS} символов",
                value="Все опубликованные новости достаточно длинные!",
                inline=False
            )

        embed.set_footer(text=f"Проверено последних 500 сообщений • Всего зарегистрировано: {len(registered_members)}")
        await ctx.send(embed=embed)
    @commands.command(name='mute')
    @is_admin_or_kurator()
    async def mute(self, ctx, member: discord.Member, duration: int, unit: str = 'м'):
        """Замутить игрока: !mute @игрок <время> <единица: м/ч/д>"""
        units = {
            'м': ('минут', 60),
            'м'.lower(): ('минут', 60),
            'm': ('минут', 60),
            'ч': ('часов', 3600),
            'h': ('часов', 3600),
            'д': ('дней', 86400),
            'd': ('дней', 86400),
        }
        if unit not in units:
            await ctx.send("❌ Единица времени: `м`/`m` (минуты), `ч`/`h` (часы), `д`/`d` (дни)\nПример: `!mute @игрок 10 м` или `!mute @игрок 10 m`")
            return
        
        if duration <= 0:
            await ctx.send("❌ Время должно быть больше 0.")
            return

        unit_name, multiplier = units[unit]
        total_seconds = duration * multiplier

        # Discord max timeout is 28 days
        if total_seconds > 28 * 86400:
            await ctx.send("❌ Максимальное время мута — 28 дней.")
            return

        try:
            until = discord.utils.utcnow() + timedelta(seconds=total_seconds)
            await member.timeout(until, reason=f"Замучен {ctx.author.name} на {duration} {unit_name}")
            
            embed = discord.Embed(
                title="🔇 Игрок замучен",
                color=discord.Color.red()
            )
            embed.add_field(name="Игрок", value=member.mention, inline=True)
            embed.add_field(name="Время", value=f"{duration} {unit_name}", inline=True)
            embed.add_field(name="Модератор", value=ctx.author.mention, inline=True)
            embed.set_footer(text=f"Мут истекает: {until.strftime('%d.%m.%Y %H:%M UTC')}")
            await ctx.send(embed=embed)

            try:
                await member.send(f"🔇 Вы были замучены на сервере на **{duration} {unit_name}**.")
            except:
                pass

        except discord.Forbidden:
            await ctx.send("❌ У бота недостаточно прав для мута этого игрока.")
        except Exception as e:
            await ctx.send(f"❌ Ошибка: `{e}`")

    @commands.command(name='unmute')
    @is_admin_or_kurator()
    async def unmute(self, ctx, member: discord.Member):
        """Размутить игрока: !unmute @игрок"""
        try:
            await member.timeout(None, reason=f"Размучен {ctx.author.name}")
            embed = discord.Embed(
                title="🔊 Игрок размучен",
                color=discord.Color.green()
            )
            embed.add_field(name="Игрок", value=member.mention, inline=True)
            embed.add_field(name="Модератор", value=ctx.author.mention, inline=True)
            await ctx.send(embed=embed)

            try:
                await member.send("🔊 Ваш мут на сервере был снят.")
            except:
                pass

        except discord.Forbidden:
            await ctx.send("❌ У бота недостаточно прав.")
        except Exception as e:
            await ctx.send(f"❌ Ошибка: `{e}`")
    @commands.command(name='ally-accept')
    @is_admin_or_kurator()
    async def ally_accept(self, ctx, application_id: str):
        """Принять заявку на альянс по ID"""
        try:
            obj_id = ObjectId(application_id)
        except Exception:
            await ctx.send("❌ Неверный формат ID заявки.")
            return

        alliance = await alliances_col.find_one({'_id': obj_id, 'approved': False})
        if not alliance:
            await ctx.send("❌ Заявка с таким ID не найдена (или уже обработана).")
            return

        guild = ctx.guild
        try:
            thread_channel = guild.get_channel(ALLIANCES_THREADS_CHANNEL_ID)
            creator_id = int(alliance['owner_id'])
            if thread_channel:
                thread = await thread_channel.create_thread(
                    name=f"🏛️ {alliance['name']}",
                    auto_archive_duration=1440,
                    reason=f"Альянс {alliance['name']}"
                )
                creator = guild.get_member(creator_id)
                if creator:
                    await thread.add_user(creator)
                await alliances_col.update_one(
                    {'_id': obj_id},
                    {'$set': {'thread_id': thread.id, 'approved': True}}
                )
                await update_user(creator_id, {'alliance_id': obj_id, 'alliance_role': 'owner'})

                # Update original embed
                admin_cog = self.bot.get_cog("👑 Админ")
                if admin_cog:
                    await admin_cog._update_application_embed(alliance, approved=True, moderator=ctx.author, reason=None, is_alliance=True)

                try:
                    if creator:
                        await creator.send(f"✅ Ваш альянс **{alliance['name']}** одобрен!\nВетка: {thread.mention}")
                except:
                    pass
                await ctx.send(f"✅ Альянс **{alliance['name']}** одобрен, создана ветка {thread.mention}.")
            else:
                await ctx.send("❌ Канал для веток не найден.")
        except Exception as e:
            await ctx.send(f"❌ Ошибка при одобрении альянса: {e}")


    @commands.command(name='ally-deny')
    @is_admin_or_kurator()
    async def ally_deny(self, ctx, application_id: str):
        """Отклонить заявку на альянс по ID"""
        try:
            obj_id = ObjectId(application_id)
        except Exception:
            await ctx.send("❌ Неверный формат ID заявки.")
            return

        alliance = await alliances_col.find_one({'_id': obj_id, 'approved': False})
        if not alliance:
            await ctx.send("❌ Заявка с таким ID не найдена (или уже обработана).")
            return

        modal = RejectApplicationModal(obj_id, app_type='alliance', app_name=alliance['name'], admin_cog=self.bot.get_cog("👑 Админ"))
        await ctx.send("Откройте форму для указания причины:", view=RejectModalTriggerView(modal, ctx.author.id))
    # ========== КОМАНДЫ КОМПАНИЙ ==========

    @commands.group(name='company', invoke_without_command=True)
    @is_registered()
    async def company(self, ctx):
        """Управление компаниями"""
        await ctx.send(
            "📋 Доступные команды компаний:\n"
            "`!company create <тип> <название>` — создать компанию\n"
            "`!company list [@игрок]` — список компаний\n"
            "`!company info` — информация о компании\n"
            "`!company upgrade` — улучшить компанию\n"
            "`!company hire <количество>` — нанять сотрудников\n"
            "`!company fire <количество>` — уволить сотрудников\n"
            "`!company close` — закрыть компанию\n\n"
            "Типы: `farm`, `factory`, `it`, `bank`, `transport`"
        )

    @company.command(name='create')
    @is_registered()
    async def company_create(self, ctx, comp_type: str, *, name: str):
        """Создать компанию. Типы: farm, factory, it, bank, transport"""
        user = await get_user(ctx.author.id)
        current_companies = await get_user_companies(ctx.author.id)
        current_count = len(current_companies)

        if current_count >= 5:
            await ctx.send("❌ Вы можете иметь максимум 5 компаний.")
            return

        if comp_type == 'bank':
            bank_count = sum(1 for c in current_companies if c['type'] == 'bank')
            if bank_count >= 2:
                await ctx.send("❌ Максимум 2 банка на игрока.")
                return
        elif comp_type == 'it':
            it_count = sum(1 for c in current_companies if c['type'] == 'it')
            if it_count >= 2:
                await ctx.send("❌ Максимум 2 IT-компании на игрока.")
                return
        elif comp_type not in ['farm', 'factory', 'transport']:
            await ctx.send("❌ Неверный тип. Доступные: farm, factory, it, bank, transport")
            return

        templates = {
            'farm':      {'cost': 100_000_000,   'employees': 10_000,  'profit': 5_000_000,  'gdp': 1_000_000,  'share': 0.6},
            'factory':   {'cost': 500_000_000,   'employees': 50_000,  'profit': 30_000_000, 'gdp': 8_000_000,  'share': 0.5},
            'it':        {'cost': 1_000_000_000, 'employees': 20_000,  'profit': 50_000_000, 'gdp': 15_000_000, 'share': 0.5},
            'bank':      {'cost': 2_000_000_000, 'employees': 5_000,   'profit': 80_000_000, 'gdp': 20_000_000, 'share': 0.4},
            'transport': {'cost': 300_000_000,   'employees': 30_000,  'profit': 20_000_000, 'gdp': 6_000_000,  'share': 0.5},
        }
        t = templates[comp_type]

        if user['balance'] < t['cost']:
            await ctx.send(f"❌ Недостаточно денег. Нужно {t['cost']:,} 💵")
            return
        new_balance = user['balance'] - t['cost']
        await update_user(ctx.author.id, {'balance': new_balance})

        comp_id = await create_company(
            owner_id=ctx.author.id,
            name=name[:50],
            comp_type=comp_type,
            investment=t['cost'],
            employees=t['employees'],
            hourly_profit=t['profit'],
            owner_share=t['share'],
            gdp_contrib=t['gdp']
        )

        new_ids = user.get('company_ids', []) + [comp_id]
        await update_user(ctx.author.id, {'company_ids': new_ids})

        await ctx.send(f"✅ Компания **{name}** ({comp_type}) создана! Используйте `!company list`.")

    @company.command(name='list')
    @is_registered()
    async def company_list(self, ctx, member: discord.Member = None):
        """Список компаний игрока"""
        if member is None:
            member = ctx.author
        companies = await get_user_companies(member.id)
        if not companies:
            await ctx.send(f"У {member.mention} нет компаний.")
            return
        embed = discord.Embed(title=f"🏢 Компании {member.name}", color=discord.Color.gold())
        for comp in companies:
            embed.add_field(
                name=comp['name'],
                value=f"Тип: {comp['type']} | Ур. {comp['level']} | Сотр.: {comp['employees']:,} | Доход/ч: {comp['hourly_profit']:,} 💵",
                inline=False
            )
        await ctx.send(embed=embed)

    async def _build_company_embed(self, company: dict) -> discord.Embed:
        embed = discord.Embed(title=f"🏭 {company['name']}", color=discord.Color.gold())
        embed.add_field(name="Тип", value=company['type'], inline=True)
        embed.add_field(name="Уровень", value=company['level'], inline=True)
        embed.add_field(name="Сотрудники", value=f"{company['employees']:,} / {company['max_employees']:,}", inline=True)
        embed.add_field(name="Доход/час", value=f"{company['hourly_profit']:,} 💵", inline=True)
        embed.add_field(name="Доля владельца", value=f"{company['owner_share']*100:.0f}%", inline=True)
        embed.add_field(name="Вклад в ВВП/час", value=f"{company['gdp_contribution']:,} 💵", inline=True)
        embed.add_field(name="Всего инвестировано", value=f"{company['invested']:,} 💵", inline=True)
        return embed

    @company.command(name='info')
    @is_registered()
    async def company_info(self, ctx):
        """Информация о компании"""
        companies = await get_user_companies(ctx.author.id)
        if not companies:
            await ctx.send("❌ У вас нет компаний.")
            return
        if len(companies) == 1:
            embed = await self._build_company_embed(companies[0])
            await ctx.send(embed=embed)
            return
        options = [discord.SelectOption(label=c['name'][:100], value=str(c['_id'])) for c in companies[:25]]
        select = Select(placeholder="Выберите компанию...", options=options)
        async def select_callback(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message("❌ Не ваша команда.", ephemeral=True)
                return
            comp_id = interaction.data['values'][0]
            comp = await get_company(comp_id)
            if comp:
                await interaction.response.send_message(embed=await self._build_company_embed(comp), ephemeral=True)
            else:
                await interaction.response.send_message("❌ Компания не найдена.", ephemeral=True)
        select.callback = select_callback
        view = View()
        view.add_item(select)
        await ctx.send("Выберите компанию:", view=view)

    async def _process_upgrade(self, ctx_or_interaction, company: dict):
        user = await get_user(company['owner_id'])
        upgrade_cost = int(company['invested'] * 0.5)
        if user['balance'] < upgrade_cost:
            msg = f"❌ Недостаточно денег. Нужно {upgrade_cost:,} 💵"
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(msg)
            return
        new_level = company['level'] + 1
        if new_level > 5:
            msg = "❌ Максимальный уровень достигнут (5)."
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(msg)
            return
        new_profit = int(company['hourly_profit'] * 1.5)
        new_max_emp = int(company['max_employees'] * 1.5)
        new_gdp = int(company['gdp_contribution'] * 1.5)
        new_invested = company['invested'] + upgrade_cost
        await update_user(int(company['owner_id']), {'balance': user['balance'] - upgrade_cost})
        await companies_col.update_one({'_id': company['_id']}, {'$set': {
            'level': new_level,
            'hourly_profit': new_profit,
            'max_employees': new_max_emp,
            'gdp_contribution': new_gdp,
            'invested': new_invested
        }})
        msg = f"✅ Компания **{company['name']}** повышена до уровня {new_level}!"
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(msg, ephemeral=True)
        else:
            await ctx_or_interaction.send(msg)

    @company.command(name='upgrade')
    @is_registered()
    async def company_upgrade(self, ctx):
        """Улучшить компанию"""
        companies = await get_user_companies(ctx.author.id)
        if not companies:
            await ctx.send("❌ У вас нет компаний.")
            return
        if len(companies) == 1:
            await self._process_upgrade(ctx, companies[0])
            return
        options = [discord.SelectOption(label=c['name'][:100], value=str(c['_id'])) for c in companies[:25]]
        select = Select(placeholder="Какую компанию улучшить?", options=options)
        async def select_callback(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message("❌ Не ваша команда.", ephemeral=True)
                return
            comp_id = interaction.data['values'][0]
            comp = await get_company(comp_id)
            if comp:
                await self._process_upgrade(interaction, comp)
            else:
                await interaction.response.send_message("❌ Компания не найдена.", ephemeral=True)
        select.callback = select_callback
        view = View()
        view.add_item(select)
        await ctx.send("Выберите компанию для улучшения:", view=view)

    @company.command(name='hire')
    @is_registered()
    async def company_hire(self, ctx, amount: int):
        """Нанять сотрудников в компанию"""
        companies = await get_user_companies(ctx.author.id)
        if not companies:
            await ctx.send("❌ У вас нет компаний.")
            return
        if len(companies) == 1:
            await self._process_hire(ctx, companies[0], amount)
            return
        options = [discord.SelectOption(label=c['name'][:100], value=str(c['_id'])) for c in companies[:25]]
        select = Select(placeholder="В какую компанию нанять?", options=options)
        async def select_callback(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message("❌ Не ваша команда.", ephemeral=True)
                return
            comp_id = interaction.data['values'][0]
            comp = await get_company(comp_id)
            if comp:
                await self._process_hire(interaction, comp, amount)
            else:
                await interaction.response.send_message("❌ Компания не найдена.", ephemeral=True)
        select.callback = select_callback
        view = View()
        view.add_item(select)
        await ctx.send("Выберите компанию:", view=view)

    async def _process_hire(self, ctx_or_interaction, company: dict, amount: int):
        user = await get_user(company['owner_id'])
        companies = await get_user_companies(int(company['owner_id']))
        total_employees = sum(c['employees'] for c in companies)
        free_pop = user.get('population', 0) - total_employees
        if free_pop < amount:
            msg = f"❌ Свободного населения: {free_pop:,}. Недостаточно."
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(msg)
            return
        new_emp = company['employees'] + amount
        if new_emp > company['max_employees']:
            msg = f"❌ Максимум сотрудников: {company['max_employees']:,}"
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(msg)
            return
        await companies_col.update_one({'_id': company['_id']}, {'$inc': {'employees': amount}})
        msg = f"✅ Нанято {amount:,} сотрудников в **{company['name']}**. Теперь: {new_emp:,} / {company['max_employees']:,}"
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(msg, ephemeral=True)
        else:
            await ctx_or_interaction.send(msg)

    @company.command(name='fire')
    @is_registered()
    async def company_fire(self, ctx, amount: int):
        """Уволить сотрудников из компании"""
        companies = await get_user_companies(ctx.author.id)
        if not companies:
            await ctx.send("❌ У вас нет компаний.")
            return
        if len(companies) == 1:
            await self._process_fire(ctx, companies[0], amount)
            return
        options = [discord.SelectOption(label=c['name'][:100], value=str(c['_id'])) for c in companies[:25]]
        select = Select(placeholder="Из какой компании уволить?", options=options)
        async def select_callback(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message("❌ Не ваша команда.", ephemeral=True)
                return
            comp_id = interaction.data['values'][0]
            comp = await get_company(comp_id)
            if comp:
                await self._process_fire(interaction, comp, amount)
            else:
                await interaction.response.send_message("❌ Компания не найдена.", ephemeral=True)
        select.callback = select_callback
        view = View()
        view.add_item(select)
        await ctx.send("Выберите компанию:", view=view)

    async def _process_fire(self, ctx_or_interaction, company: dict, amount: int):
        if company['employees'] < amount:
            msg = f"❌ В компании **{company['name']}** только {company['employees']} сотрудников."
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(msg)
            return
        new_emp = company['employees'] - amount
        await companies_col.update_one({'_id': company['_id']}, {'$inc': {'employees': -amount}})
        msg = f"✅ Уволено {amount:,} сотрудников из **{company['name']}**. Осталось: {new_emp:,}"
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(msg, ephemeral=True)
        else:
            await ctx_or_interaction.send(msg)

    async def _process_close(self, ctx_or_interaction, company: dict):
        user = await get_user(company['owner_id'])
        refund = int(company['invested'] * 0.5)
        new_balance = user['balance'] + refund
        new_ids = [cid for cid in user.get('company_ids', []) if cid != str(company['_id'])]
        await update_user(int(company['owner_id']), {
            'balance': new_balance,
            'company_ids': new_ids
        })
        await companies_col.delete_one({'_id': company['_id']})
        msg = f"✅ Компания **{company['name']}** закрыта. Возвращено {refund:,} 💵."
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(msg, ephemeral=True)
        else:
            await ctx_or_interaction.send(msg)

    @company.command(name='close')
    @is_registered()
    async def company_close(self, ctx):
        """Закрыть компанию"""
        companies = await get_user_companies(ctx.author.id)
        if not companies:
            await ctx.send("❌ У вас нет компаний.")
            return
        if len(companies) == 1:
            await self._process_close(ctx, companies[0])
            return
        options = [discord.SelectOption(label=c['name'][:100], value=str(c['_id'])) for c in companies[:25]]
        select = Select(placeholder="Какую компанию закрыть?", options=options)
        async def select_callback(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message("❌ Не ваша команда.", ephemeral=True)
                return
            comp_id = interaction.data['values'][0]
            comp = await get_company(comp_id)
            if comp:
                await self._process_close(interaction, comp)
            else:
                await interaction.response.send_message("❌ Компания не найдена.", ephemeral=True)
        select.callback = select_callback
        view = View()
        view.add_item(select)
        await ctx.send("Выберите компанию для закрытия:", view=view)
# 🛒 COG: МАГАЗИН
# ===========================
class Shop(commands.Cog, name="🛒 Магазин"):
    VEHICLE_CATEGORIES = [
        "Сухопутная Техника",
        "ВМФ",
        "Воздушная Техника",
        "Ракеты",
        "ПВО",
        "Другое",
    ]
    APPROVAL_CHANNEL = 1502009375324110968

    def __init__(self, bot):
        self.bot = bot
        self.pending_add = {}

    @commands.command(name='shop')
    @is_registered()
    async def shop(self, ctx):
        """Открыть магазин техники"""
        view = ShopView(self, ctx.author.id)
        embed = await self.build_shop_embed(view)
        view.message = await ctx.send(embed=embed, view=view)

    async def build_shop_embed(self, view: "ShopView") -> discord.Embed:
        all_vehicles = await vehicles_col.find({"approved": True}).to_list(length=None)
        if view.filter_type == 'category':
            vehicles = [v for v in all_vehicles if v.get('category') == view.filter_value]
            filter_desc = f"📁 {view.filter_value}"
        elif view.filter_type == 'search':
            vehicles = [v for v in all_vehicles if v.get('country', '').lower() == view.filter_value.lower()]
            filter_desc = f"🌍 {view.filter_value}"
        else:
            vehicles = all_vehicles
            filter_desc = "🗂 Вся техника"

        total = len(vehicles)

        if total == 0:
            embed = discord.Embed(
                title="🛒 Военный Магазин",
                description=f"**{filter_desc}**\n\n*Нет доступной техники в этой категории*",
                color=0x1a1a2e,
            )
            embed.set_footer(text="⚙️ Страница 0 / 0  •  Всего позиций: 0")
            return embed

        max_page = total - 1
        view.current_page = max(0, min(view.current_page, max_page))
        vehicle = vehicles[view.current_page]

        CATEGORY_EMOJI = {
            "Сухопутная Техника": "🪖",
            "ВМФ":                "⚓",
            "Воздушная Техника":  "✈️",
            "Ракеты":             "🚀",
            "ПВО":                "🛡️",
            "Другое":             "📦",
        }
        cat_emoji = CATEGORY_EMOJI.get(vehicle.get('category', ''), "🔧")

        embed = discord.Embed(
            title=f"{cat_emoji}  {vehicle['name']}",
            description=vehicle.get('description', '*Описание отсутствует*'),
            color=0x0f3460,
        )

        flag = vehicle.get('flag_url')
        if flag and flag.startswith('http'):
            embed.set_author(name=vehicle.get('country', '—'), icon_url=flag)

        embed.add_field(name="💵 Стоимость", value=f"**{vehicle['price']:,}** 💵", inline=True)
        embed.add_field(name="🌍 Страна", value=vehicle.get('country') or "—", inline=True)
        embed.add_field(name="📁 Категория", value=vehicle.get('category') or "—", inline=True)

        if vehicle.get('wiki_link'):
            embed.add_field(name="📖 Источник", value=f"[Открыть страницу]({vehicle['wiki_link']})", inline=False)

        img = vehicle.get('image_url')
        if img and img.startswith('http'):
            embed.set_image(url=img)
        else:
            embed.set_image(url="https://via.placeholder.com/800x300/0f3460/e94560?text=No+Image")

        embed.set_footer(
            text=(
                f"◀️ / ▶️ листать  •  {filter_desc}  •  "
                f"Позиция {view.current_page + 1} / {total}  •  "
                f"Всего: {total}"
            )
        )

        return embed


    @commands.command(name='take-lic')
    @is_registered()
    async def take_license(self, ctx, target: discord.Member, *, vehicle_name: str):
        """Забрать выданную лицензию (только владелец техники)"""
        vehicles = await vehicles_col.find({
            "submitter_id": str(ctx.author.id),
            "approved": True
        }).to_list(length=None)
        if not vehicles:
            await ctx.send("❌ У вас нет одобренной техники, лицензии на которую можно забрать.")
            return
        regex = re.compile(re.escape(vehicle_name.strip()), re.IGNORECASE)
        matches = [v for v in vehicles if regex.search(v['name'])]
        if not matches:
            await ctx.send(f"❌ Среди вашей техники нет названия, содержащего `{vehicle_name}`.")
            return
        if len(matches) > 1:
            options = [discord.SelectOption(label=v['name'][:100], value=str(v['_id'])) for v in matches[:25]]
            select = Select(placeholder="Выберите технику, лицензию на которую забрать...", options=options)
            view = TakeLicSelectView(ctx.author.id, target.id, matches, select, self)
            select.callback = view.select_callback
            view.add_item(select)
            await ctx.send("Найдено несколько вариантов. Выберите:", view=view)
            return
        vehicle = matches[0]
        result = await licenses_col.delete_one({
            'user_id': str(target.id),
            'vehicle_name': vehicle['name']
        })
        if result.deleted_count:
            await ctx.send(f"✅ Лицензия на **{vehicle['name']}** у {target.mention} забрана.")
        else:
            await ctx.send(f"❌ У {target.mention} нет лицензии на **{vehicle['name']}**.")

    @commands.command(name='lic-list')
    @is_registered()
    async def license_list(self, ctx, member: discord.Member = None):
        """Показать выданные лицензии. Без @ – ваши полученные. С @ – выданные этим игроком."""
        if member is None:
            licenses = await licenses_col.find({'user_id': str(ctx.author.id)}).to_list(length=None)
            title = "📜 Лицензии, выданные вам"
            empty_msg = "Вам никто не выдавал лицензий."
        else:
            licenses = await licenses_col.find({'issued_by': str(member.id)}).to_list(length=None)
            title = f"📜 Лицензии, выданные игроком {member.name}"
            empty_msg = f"{member.name} никому не выдавал лицензий."
        if not licenses:
            await ctx.send(empty_msg)
            return
        entries = []
        for lic in licenses:
            vehicle_name = lic['vehicle_name']
            issuer_id = lic.get('issued_by')
            if member is None:
                issuer = ctx.guild.get_member(int(issuer_id)) if issuer_id else None
                issuer_name = issuer.name if issuer else f"User{issuer_id}"
                entries.append(f"**{vehicle_name}** – выдал {issuer_name}")
            else:
                target_id = lic['user_id']
                target = ctx.guild.get_member(int(target_id)) if target_id else None
                target_name = target.name if target else f"User{target_id}"
                entries.append(f"**{vehicle_name}** – выдано {target_name}")
        per_page = 10
        total_pages = (len(entries) + per_page - 1) // per_page
        embed = discord.Embed(title=title, color=discord.Color.blue())
        embed.description = "\n".join(entries[:per_page])
        embed.set_footer(text=f"Страница 1/{total_pages}")
        if total_pages > 1:
            view = LicListPaginationView(ctx.author.id, entries, per_page, total_pages, embed)
            view.message = await ctx.send(embed=embed, view=view)
        else:
            await ctx.send(embed=embed)

    @commands.command(name='military')
    @is_registered()
    async def military(self, ctx):
        """Панель военных операций (модернизация и мобилизация)"""
        user = await get_user(ctx.author.id)
        if not user.get('country'):
            await ctx.send("❌ У вас не зарегистрирована страна. Используйте !full-reg для регистрации.")
            return

        submission_info = await get_daily_submission_info(ctx.author.id)
        mob_pool = user.get('mob_pool', 0)

        embed = discord.Embed(
            title="🎖️ Военные операции",
            description="Выберите действие:",
            color=discord.Color.red()
        )
        embed.add_field(name="📋 Создание техники", value=f"Используйте `!reg-tech <название>`\nСтатус: {submission_info}", inline=False)
        embed.add_field(name="🔧 Модернизация", value=f"Статус: {submission_info}", inline=False)
        embed.add_field(name="👥 Мобилизация", value=f"Доступно в пуле: {mob_pool:,}", inline=False)

        view = MilitaryView(self, ctx.author.id)
        await ctx.send(embed=embed, view=view)

    @commands.command(name='give-lic')
    @is_registered()
    async def give_license(self, ctx, target: discord.Member, *, vehicle_identifier: str):
        """Выдать лицензию на технику (название или all)"""
        giver_user = await get_user(ctx.author.id)
        giver_country = giver_user.get('country')
        if not giver_country:
            await ctx.send("❌ У вас не зарегистрирована страна (используйте !reg).")
            return
        if vehicle_identifier.lower() == 'all':
            vehicles = await vehicles_col.find({"approved": True, "submitter_id": str(ctx.author.id)}).to_list(length=None)
            if not vehicles:
                await ctx.send("У вас нет одобренной техники.")
                return
            for v in vehicles:
                await licenses_col.update_one(
                    {'user_id': str(target.id), 'vehicle_name': v['name']},
                    {'$setOnInsert': {'user_id': str(target.id), 'vehicle_name': v['name'], 'issued_by': str(ctx.author.id), 'issued_at': datetime.now().timestamp()}},
                    upsert=True
                )
            await ctx.send(f"✅ {target.mention} получил лицензию на всю вашу технику.")
            return
        vehicle = await vehicles_col.find_one({"approved": True, "name": vehicle_identifier.strip(), "submitter_id": str(ctx.author.id)})
        if not vehicle:
            regex = re.compile(re.escape(vehicle_identifier.strip()), re.IGNORECASE)
            candidates = await vehicles_col.find({
                "approved": True,
                "submitter_id": str(ctx.author.id),
                "name": {"$regex": regex}
            }).to_list(length=None)
            if not candidates:
                await ctx.send("Техника с таким названием не найдена среди вашей.")
                return
            if len(candidates) > 1:
                names = [v['name'] for v in candidates]
                await ctx.send(f"Найдено несколько совпадений: {', '.join(names)}. Уточните название.")
                return
            vehicle = candidates[0]
        await licenses_col.update_one(
            {'user_id': str(target.id), 'vehicle_name': vehicle['name']},
            {'$setOnInsert': {'user_id': str(target.id), 'vehicle_name': vehicle['name'], 'issued_by': str(ctx.author.id), 'issued_at': datetime.now().timestamp()}},
            upsert=True
        )
        await ctx.send(f"✅ {target.mention} получил лицензию на **{vehicle['name']}**.")

    @commands.command(name='buy')
    @is_registered()
    async def buy(self, ctx, quantity: int, *, item_name: str):
        """Купить технику из магазина"""
        if quantity <= 0:
            await ctx.send("❌ Количество должно быть больше 0.")
            return
        vehicle = await vehicles_col.find_one({"approved": True, "name": item_name.strip()})
        if not vehicle:
            regex = re.compile(re.escape(item_name.strip()), re.IGNORECASE)
            matches = await vehicles_col.find({"approved": True, "name": {"$regex": regex}}).to_list(length=25)
            if not matches:
                await ctx.send("❌ Техника не найдена.")
                return
            if len(matches) > 1:
                names = [v['name'] for v in matches]
                await ctx.send(f"Найдено несколько совпадений: {', '.join(names)}. Уточните название.")
                return
            vehicle = matches[0]
        buyer_user = await get_user(ctx.author.id)
        buyer_country = buyer_user.get('country')
        vehicle_country = vehicle.get('country')
        if buyer_country != vehicle_country:
            lic = await licenses_col.find_one({'user_id': str(ctx.author.id), 'vehicle_name': vehicle['name']})
            if not lic:
                await ctx.send("❌ У вас нет лицензии этой страны. Необходимо получить лицензию или купить у своей страны.")
                return
        total_price = vehicle['price'] * quantity
        if buyer_user['balance'] < total_price:
            await ctx.send(f"❌ Недостаточно денег. Нужно **{total_price:,}** 💵, у вас **{buyer_user['balance']:,}** 💵.")
            return
        await update_user(ctx.author.id, {'balance': buyer_user['balance'] - total_price})
        await add_item(ctx.author.id, vehicle['name'], quantity)
        await ctx.send(f"✅ Вы купили **{quantity}x {vehicle['name']}** за **{total_price:,}** 💵. Товар добавлен в инвентарь (`!inv`).")

    @commands.command(name='inv')
    @is_registered()
    async def inventory(self, ctx):
        """Показать ваш инвентарь (только в ЛС)"""
        items = await get_inventory(ctx.author.id)
        embed = discord.Embed(title="📦 Ваш инвентарь", color=discord.Color.green())
        if not items:
            embed.description = "Пусто."
        else:
            text = "\n".join(f"**{it['item_name']}** — {it['quantity']} шт." for it in items)
            if len(text) > 2000:
                text = text[:1997] + "..."
            embed.description = text
        try:
            await ctx.author.send(embed=embed)
            if ctx.guild:
                await ctx.send("📬 Инвентарь отправлен в личные сообщения.", ephemeral=True)
        except:
            await ctx.send("❌ Не могу отправить вам ЛС. Проверьте настройки приватности.", ephemeral=True)

    @commands.command(name='use')
    @is_registered()
    async def use_item(self, ctx, quantity: int, *, item_name: str):
        """Использовать предмет из инвентаря (частичный поиск, авто‑подбор количества)"""
        if quantity <= 0:
            await ctx.send("❌ Количество должно быть больше 0.")
            return
        items = await get_inventory(ctx.author.id)
        if not items:
            await ctx.send("❌ Ваш инвентарь пуст.")
            return
        regex = re.compile(re.escape(item_name.strip()), re.IGNORECASE)
        matches = [it for it in items if regex.search(it['item_name'])]
        if not matches:
            await ctx.send("❌ У вас нет предметов с таким названием.")
            return
        if len(matches) == 1:
            await self._process_use(ctx.author, matches[0], quantity, interaction=None, ctx=ctx)
        else:
            options = [discord.SelectOption(label=it['item_name'][:100]) for it in matches[:25]]
            select = Select(placeholder="Выберите предмет для использования...", options=options)
            view = UseSelectView(ctx.author.id, quantity, matches, select, self)
            await ctx.send("Найдено несколько предметов. Выберите:", view=view)

    async def _process_use(self, user: discord.Member, item: dict, requested_qty: int, interaction=None, ctx=None):
        available = item['quantity']
        use_qty = min(requested_qty, available)
        success = await remove_item(user.id, item['item_name'], use_qty)
        if success:
            msg = f"✅ Вы использовали **{item['item_name']}** в количестве **{use_qty}** шт."
            if use_qty < requested_qty:
                msg += f"\n⚠️ У вас было только **{available}** шт., поэтому использовано всё доступное."
            if interaction:
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx.send(msg)
        else:
            err = "❌ Не удалось использовать предмет."
            if interaction:
                await interaction.response.send_message(err, ephemeral=True)
            else:
                await ctx.send(err)

    @commands.command(name='vehicle-info')
    @is_registered()
    async def vehicle_info(self, ctx, *, name_or_part: str):
        """Подробная информация о технике (с изображением, если есть)"""
        vehicle = await vehicles_col.find_one({"approved": True, "name": name_or_part.strip()})
        if not vehicle:
            regex = re.compile(re.escape(name_or_part.strip()), re.IGNORECASE)
            matches = await vehicles_col.find({"approved": True, "name": {"$regex": regex}}).to_list(length=25)
            if not matches:
                await ctx.send("❌ Техника не найдена.")
                return
            if len(matches) == 1:
                vehicle = matches[0]
            else:
                options = [discord.SelectOption(label=v['name'][:100], value=str(v['_id'])) for v in matches[:25]]
                select = Select(placeholder="Выберите технику...", options=options)
                view = VehicleInfoSelectView(ctx.author.id, matches, select, self)
                await ctx.send("Найдено несколько вариантов. Выберите:", view=view)
                return
        embed = await self.build_vehicle_info_embed(vehicle)
        await ctx.send(embed=embed) 

    async def build_vehicle_info_embed(self, vehicle: dict) -> discord.Embed:
        embed = discord.Embed(
            title=f"ℹ️ {vehicle['name']}",
            description=vehicle['description'],
            color=discord.Color.blue()
        )
        embed.add_field(name="Стоимость", value=f"{vehicle['price']:,} 💵", inline=True)
        embed.add_field(name="Страна", value=vehicle.get('country', '?'), inline=True)
        if vehicle.get('wiki_link'):
            embed.add_field(name="Википедия", value=f"[Открыть]({vehicle['wiki_link']})", inline=False)
        if vehicle.get('image_url'):
            embed.set_thumbnail(url=vehicle['image_url'])
        else:
            embed.set_footer(text="Изображения нет")
        flag = vehicle.get('flag_url')
        if flag and flag.startswith('http'):
            embed.set_author(name=vehicle.get('country', '—'), icon_url=flag)
        return embed

    @commands.command(name='iso')
    @is_registered()
    async def add_image(self, ctx, *, args: str):
        """Добавить изображение к своей технике: !iso <название/часть названия> <ссылка>"""
        parts = args.rsplit(' ', 1)
        if len(parts) < 2:
            await ctx.send("❌ Использование: `!iso <название/часть названия> <ссылка на изображение>`")
            return
        name_or_part = parts[0].strip()
        image_url = parts[1].strip()

        regex = re.compile(re.escape(name_or_part), re.IGNORECASE)
        vehicles = await vehicles_col.find({
            "approved": True,
            "submitter_id": str(ctx.author.id),
            "name": {"$regex": regex}
        }).to_list(length=25)

        if not vehicles:
            await ctx.send("❌ У вас нет одобренной техники с таким названием.")
            return
        if len(vehicles) == 1:
            v = vehicles[0]
            await vehicles_col.update_one({'_id': v['_id']}, {'$set': {'image_url': image_url}})
            await ctx.send(f"✅ Изображение для **{v['name']}** обновлено.")
        else:
            options = [discord.SelectOption(label=v['name'][:100]) for v in vehicles[:25]]
            select = Select(placeholder="Выберите технику...", options=options)
            view = IsoSelectView(ctx.author.id, vehicles, select, image_url, self)
            await ctx.send("Выберите технику, для которой нужно установить изображение:", view=view)

    async def submit_application(self, user_id: int, data: dict):
        now = datetime.now().timestamp()
        user = await get_user(user_id)
        country = user.get('country', '?')
        flag_url = user.get('country_flag_url', '')
        vehicle = {
            "name": data['name'],
            "description": data['description'],
            "price": data['price'],
            "category": data['category'],
            "country": country,
            "flag_url": user.get('country_flag_url'),
            "wiki_link": data.get('wiki_link') if not data.get('is_modernization') else None,
            "image_url": None,
            "submitter_id": str(user_id),
            "approved": False,
            "created_at": now,
            "expires_at": now + 86400,   # ← +24 часа
            "is_modernization": data.get('is_modernization', False),
        }
        result = await vehicles_col.insert_one(vehicle)
        vehicle['_id'] = result.inserted_id

        await record_submission(user_id)

        channel = self.bot.get_channel(self.APPROVAL_CHANNEL)
        if channel:
            title = "📥 Новая заявка на технику"
            if data.get('is_modernization'):
                title = "📥 Новая заявка на модернизацию"
            embed = discord.Embed(
                title=title,
                color=discord.Color.orange() if not data.get('is_modernization') else discord.Color.purple()
            )
            embed.add_field(name="Название", value=data['name'], inline=False)
            embed.add_field(name="Описание", value=data['description'], inline=False)
            embed.add_field(name="Стоимость", value=f"{data['price']:,} 💵", inline=True)
            embed.add_field(name="Категория", value=data['category'], inline=True)
            embed.add_field(name="Страна", value=country, inline=True)
            if data.get('wiki_link'):
                embed.add_field(name="Википедия", value=data['wiki_link'], inline=False)
            if flag_url and flag_url.startswith('http'):
                embed.set_author(name=country, icon_url=flag_url)
            # ← ID заявки в футере
            embed.set_footer(text=f"ID заявки: {result.inserted_id} | Отправитель: {self.bot.get_user(user_id)} | Удалится через 24ч")
            view = ApprovalView(self, vehicle['_id'])
            msg = await channel.send(embed=embed, view=view)
            # Сохраняем message_id чтобы потом редактировать embed
            await vehicles_col.update_one({'_id': result.inserted_id}, {'$set': {'approval_message_id': msg.id, 'approval_channel_id': channel.id}})

    async def approve_vehicle(self, vehicle_id, moderator: discord.Member):
        await vehicles_col.update_one({'_id': vehicle_id}, {'$set': {'approved': True, 'approved_by': str(moderator.id)}})
        vehicle = await vehicles_col.find_one({'_id': vehicle_id})
        submitter = self.bot.get_user(int(vehicle['submitter_id']))
        if submitter:
            try: await submitter.send(f"✅ Ваша заявка на технику **{vehicle['name']}** одобрена!")
            except: pass

    async def reject_vehicle(self, vehicle_id, reason: str, moderator: discord.Member):
        await vehicles_col.update_one({'_id': vehicle_id}, {'$set': {'approved': False, 'rejection_reason': reason, 'rejected_by': str(moderator.id)}})
        vehicle = await vehicles_col.find_one({'_id': vehicle_id})
        submitter = self.bot.get_user(int(vehicle['submitter_id']))
        if submitter:
            try: await submitter.send(f"❌ Ваша заявка на технику **{vehicle['name']}** отклонена.\nПричина: {reason}")
            except: pass

    async def perform_mobilization(self, interaction: discord.Interaction, user_id: int, quantity: int, message_link: str):
        pattern = r"https://discord\.com/channels/\d+/(\d+)/(\d+)"
        match = re.match(pattern, message_link)
        if not match:
            return "❌ Неверный формат ссылки."
        channel_id = match.group(1)
        message_id = match.group(2)
        if channel_id != "1363585142593032412":
            return "❌ Ссылка должна вести в канал реформ (<#1363585142593032412>)."

        existing = await mobilization_links_col.find_one({"message_id": message_id})
        if existing:
            return "❌ Эта ссылка уже использовалась для мобилизации."

        user = await get_user(user_id)
        mob_pool = user.get('mob_pool', 0)

        if quantity <= 0:
            return "❌ Количество должно быть положительным."
        if quantity > mob_pool:
            return f"❌ Нельзя мобилизовать больше **{mob_pool:,}** (ваш текущий пул)."

        # Проверка дневного лимита и КД
        DAILY_LIMIT = 350_000
        COOLDOWN_HOURS = 15
        now = datetime.now().timestamp()

        limit_doc = await mobilization_limits_col.find_one({'user_id': str(user_id)})
        
        if limit_doc:
            # Сброс если прошло больше 24 часов с начала отсчёта
            window_start = limit_doc.get('window_start', 0)
            if now - window_start >= 86400:
                limit_doc = None  # сбрасываем окно

        mobilized_today = limit_doc.get('mobilized_today', 0) if limit_doc else 0
        window_start = limit_doc.get('window_start', now) if limit_doc else now

        # Проверка КД (если достигли лимита ранее)
        if limit_doc and limit_doc.get('cooldown_until', 0) > now:
            remaining = int(limit_doc['cooldown_until'] - now)
            hours = remaining // 3600
            mins = (remaining % 3600) // 60
            return f"⏰ КД мобилизации! Подождите ещё **{hours}ч {mins}м**."

        # Проверка лимита
        if mobilized_today >= DAILY_LIMIT:
            return f"❌ Вы достигли дневного лимита мобилизации ({DAILY_LIMIT:,} солдат)."

        can_mobilize = DAILY_LIMIT - mobilized_today
        if quantity > can_mobilize:
            return (
                f"❌ Можно мобилизовать ещё максимум **{can_mobilize:,}** солдат сегодня.\n"
                f"Уже мобилизовано: **{mobilized_today:,}** / **{DAILY_LIMIT:,}**"
            )

        # Проводим мобилизацию
        new_population = user.get('population', 0) - quantity
        new_pool = mob_pool - quantity

        await update_user(user_id, {'population': new_population})
        await update_mob_pool(user_id, new_pool)
        await add_item(user_id, "Обученный Солдат", quantity)

        await mobilization_links_col.insert_one({
            "message_id": message_id,
            "channel_id": channel_id,
            "used_by": str(user_id),
            "used_at": now
        })

        new_mobilized_today = mobilized_today + quantity
        cooldown_until = 0

        # Если достигли лимита — ставим КД 15 часов
        if new_mobilized_today >= DAILY_LIMIT:
            cooldown_until = now + (COOLDOWN_HOURS * 3600)

        await mobilization_limits_col.update_one(
            {'user_id': str(user_id)},
            {'$set': {
                'mobilized_today': new_mobilized_today,
                'window_start': window_start,
                'cooldown_until': cooldown_until
            }},
            upsert=True
        )

        cd_msg = f"\n⏰ Достигнут дневной лимит! КД: **{COOLDOWN_HOURS}ч**" if cooldown_until else ""

        return (
            f"✅ Мобилизовано **{quantity:,}** солдат.\n"
            f"👥 Население: {new_population:,}\n"
            f"🎖️ Остаток пула: {new_pool:,}\n"
            f"📊 Мобилизовано сегодня: **{new_mobilized_today:,}** / **{DAILY_LIMIT:,}**"
            f"{cd_msg}"
        )
    @commands.command(name='reg-tech')
    @is_registered()
    async def reg_tech(self, ctx, *, name: str = None):
        """Зарегистрировать технику через диалог"""
        import asyncio

        if name is None:
            await ctx.send("❌ Использование: `!reg-tech <название техники>`")
            return

        can_submit, msg = await check_daily_submission_limit(ctx.author.id)
        if not can_submit:
            await ctx.send(msg)
            return

        user = await get_user(ctx.author.id)
        if not user.get('country'):
            await ctx.send("❌ У вас не зарегистрирована страна.")
            return

        def check(m):
            return (
                m.author == ctx.author
                and m.channel == ctx.channel
                and not m.content.startswith('!')
            )

        steps = [
            ("vehicle_type", "🔧 **Тип техники?**\nНапример: ОБТ, БТР, Истребитель, Фрегат..."),
            ("description", "📝 **Описание техники?**"),
            ("year",        "📅 **Год разработки?**"),
            ("price",       "💵 **Стоимость?** (только число)"),
            ("wiki_link",   "🔗 **Ссылка на Википедию?** (или напишите `нет`)"),
        ]

        answers = {}
        await ctx.send(
            f"📋 Регистрация техники: **{name.strip()}**\n"
            f"⏱️ На каждый вопрос у вас **1 минута**. Напишите `отмена` для отмены."
        )

        for key, question in steps:
            await ctx.send(question)
            try:
                response = await self.bot.wait_for('message', check=check, timeout=60)
            except asyncio.TimeoutError:
                await ctx.send("⏰ Время вышло. Начните заново с `!reg-tech <название>`.")
                return

            if response.content.strip().lower() == 'отмена':
                await ctx.send("❌ Регистрация отменена.")
                return

            answers[key] = response.content.strip()

        # Validate price
        try:
            price = int(answers['price'].replace(',', '').replace(' ', ''))
            if price <= 0:
                raise ValueError
        except ValueError:
            await ctx.send("❌ Неверная стоимость. Начните заново.")
            return

        wiki_link = answers['wiki_link']
        if wiki_link.lower() in ('нет', 'no', '-', ''):
            wiki_link = None

        full_description = (
            f"{answers['description']}\n\n"
            f"**Тип:** {answers['vehicle_type']}\n"
            f"**Год разработки:** {answers['year']}"
        )

        self.pending_add[ctx.author.id] = {
            'name': name.strip(),
            'description': full_description,
            'price': price,
            'wiki_link': wiki_link,
            'is_modernization': False
        }

        view = CategorySelectView(self, ctx.author.id)
        await ctx.send("✅ Почти готово! Выберите категорию техники:", view=view)
# ===========================
# 🏛️ COG: АЛЬЯНСЫ
# ===========================
class Alliances(commands.Cog, name="🏛️ Альянсы"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='ally-create')
    @is_registered()
    async def ally_create(self, ctx):
        """Создать альянс"""
        count = await count_user_alliances_as_owner(ctx.author.id)
        if count >= 2:
            await ctx.send("❌ Вы уже создали максимальное количество альянсов (2).")
            return
        view = AllyCreateStartView(self, ctx.author.id)
        await ctx.send("Нажмите кнопку для создания альянса:", view=view)

    @commands.command(name='ally')
    @is_registered()
    async def ally_info(self, ctx):
        """Информация об альянсе"""
        user = await get_user(ctx.author.id)
        alliance_id = user.get('alliance_id')
        if not alliance_id:
            await ctx.send("❌ Вы не являетесь членом альянса.")
            return
        alliance = await get_alliance(alliance_id)
        if not alliance:
            await ctx.send("❌ Альянс не найден.")
            return
        is_owner = str(ctx.author.id) == alliance['owner_id']
        view = AllyInfoView(self, alliance, ctx.author.id, is_owner, self.bot)
        embed = await self.build_alliance_embed(alliance, self.bot)
        await ctx.send(embed=embed, view=view)

    @commands.command(name='ally-invite')
    @is_registered()
    async def ally_invite(self, ctx, target: discord.Member):
        """Пригласить игрока в альянс"""
        user = await get_user(ctx.author.id)
        alliance_id = user.get('alliance_id')
        if not alliance_id:
            await ctx.send("❌ Вы не являетесь членом альянса.")
            return
        alliance = await get_alliance(alliance_id)
        if not alliance:
            await ctx.send("❌ Альянс не найден.")
            return
        is_owner = str(ctx.author.id) == alliance['owner_id']
        if not is_owner:
            await ctx.send("❌ Только владелец альянса может приглашать новых членов.")
            return
        target_user = await get_user(target.id)
        if target_user.get('alliance_id') == alliance_id:
            await ctx.send("❌ Этот игрок уже является членом вашего альянса.")
            return
        await alliance_invites_col.insert_one({
            'alliance_id': alliance_id,
            'alliance_name': alliance['name'],
            'invited_user_id': str(target.id),
            'inviter_user_id': str(ctx.author.id),
            'created_at': datetime.now().timestamp(),
            'expires_at': (datetime.now() + timedelta(minutes=2)).timestamp()
        })
        view = AllyInviteView(self, alliance_id, alliance['name'], target.id)
        embed = discord.Embed(
            title="🏛️ Приглашение в альянс",
            description=f"{ctx.author.mention} приглашает вас в альянс **{alliance['name']}**\n\nУ вас есть 2 минуты на принятие.",
            color=discord.Color.gold()
        )
        try:
            await target.send(embed=embed, view=view)
            await ctx.send(f"✅ Приглашение отправлено {target.mention}.")
        except:
            await ctx.send(f"❌ Не удалось отправить приглашение {target.mention}. Проверьте настройки приватности.")

    @commands.command(name='ally-kick')
    @is_registered()
    async def ally_kick(self, ctx, target: discord.Member):
        """Выгнать игрока из альянса"""
        user = await get_user(ctx.author.id)
        alliance_id = user.get('alliance_id')
        if not alliance_id:
            await ctx.send("❌ Вы не являетесь членом альянса.")
            return
        alliance = await get_alliance(alliance_id)
        if not alliance:
            await ctx.send("❌ Альянс не найден.")
            return
        is_owner = str(ctx.author.id) == alliance['owner_id']
        if not is_owner:
            await ctx.send("❌ Только владелец альянса может выгонять членов.")
            return
        target_user = await get_user(target.id)
        if target_user.get('alliance_id') != alliance_id:
            await ctx.send("❌ Этот игрок не является членом вашего альянса.")
            return
        await update_user(target.id, {'alliance_id': None, 'alliance_role': None})
        if alliance.get('thread_id'):
            try:
                thread = self.bot.get_channel(alliance['thread_id'])
                if thread and isinstance(thread, discord.Thread):
                    await thread.remove_user(target)
            except:
                pass
        await ctx.send(f"✅ {target.mention} выгнан из альянса.")

    @commands.command(name='ally-remove')
    @is_registered()
    async def ally_remove(self, ctx):
        """Удалить свой альянс (для владельца)"""
        count = await count_user_alliances_as_owner(ctx.author.id)
        if count == 0:
            await ctx.send("❌ Вы не владеете ни одним альянсом.")
            return
        if count == 1:
            alliance = await alliances_col.find_one({'owner_id': str(ctx.author.id)})
            if alliance:
                view = AllyRemoveConfirmView(self, alliance['_id'])
                embed = discord.Embed(
                    title="⚠️ Удалить альянс?",
                    description=f"Вы уверены, что хотите удалить альянс **{alliance['name']}**?\nЭто действие необратимо.",
                    color=discord.Color.red()
                )
                await ctx.send(embed=embed, view=view)
        else:
            alliances = await alliances_col.find({'owner_id': str(ctx.author.id)}).to_list(length=None)
            view = AllyRemoveSelectView(ctx.author.id, alliances, self)
            await ctx.send("Выберите альянс для удаления:", view=view)

    @commands.command(name='iso-ally')
    @is_registered()
    async def iso_ally(self, ctx, *, args: str):
        """Добавить изображение к альянсу: !iso-ally <название альянса> <ссылка>"""
        parts = args.rsplit(' ', 1)
        if len(parts) < 2:
            await ctx.send("❌ Использование: `!iso-ally <название альянса> <ссылка на изображение>`")
            return
        name_or_part = parts[0].strip()
        image_url = parts[1].strip()
        user = await get_user(ctx.author.id)
        alliance_id = user.get('alliance_id')
        if not alliance_id:
            await ctx.send("❌ Вы не являетесь членом альянса.")
            return
        alliance = await get_alliance(alliance_id)
        if not alliance:
            await ctx.send("❌ Альянс не найден.")
            return
        is_owner = str(ctx.author.id) == alliance['owner_id']
        if not is_owner:
            await ctx.send("❌ Только владелец альянса может изменять изображение.")
            return
        await alliances_col.update_one({'_id': alliance_id}, {'$set': {'image_url': image_url}})
        await ctx.send(f"✅ Изображение альянса **{alliance['name']}** обновлено.")

    async def build_alliance_embed(self, alliance: dict, bot) -> discord.Embed:
        embed = discord.Embed(
            title=f"🏛️ {alliance['name']}",
            description=alliance.get('description', 'Нет описания'),
            color=discord.Color.gold()
        )
        embed.add_field(name="📋 Тип", value=alliance.get('type', 'Неизвестен'), inline=True)
        embed.add_field(name="💰 Казна", value=f"{alliance.get('treasury', 0):,} 💵", inline=True)
        embed.add_field(name="📊 Налог", value=f"{alliance.get('tax_percent', 2)}%", inline=True)

        members = alliance.get('members', [])
        owner_id = alliance.get('owner_id')
        members_text = ""
        if owner_id:
            owner_user = bot.get_user(int(owner_id))
            owner_name = owner_user.name if owner_user else f"User{owner_id}"
            members_text += f"**Глава:** {owner_name}\n"
        if members:
            members_text += "**Участники:**\n"
            for i, member_id in enumerate(members[:10], 1):
                member_user = bot.get_user(int(member_id))
                member_name = member_user.name if member_user else f"User{member_id}"
                members_text += f"{i}. {member_name}\n"
            if len(members) > 10:
                members_text += f"... и ещё {len(members) - 10}"
        else:
            members_text += "**Участники:** Нет"
        embed.add_field(name="👥 Состав", value=members_text, inline=False)
        if alliance.get('image_url'):
            embed.set_thumbnail(url=alliance['image_url'])
        return embed

    async def delete_alliance(self, alliance_id):
        if isinstance(alliance_id, str):
            try:
                alliance_id = ObjectId(alliance_id)
            except:
                return False
        alliance = await get_alliance(alliance_id)
        if not alliance:
            return False
        members = alliance.get('members', [])
        for member_id in members:
            await update_user(int(member_id), {'alliance_id': None, 'alliance_role': None})
        owner_id = int(alliance.get('owner_id', 0))
        if owner_id:
            await update_user(owner_id, {'alliance_id': None, 'alliance_role': None})
        if alliance.get('thread_id'):
            try:
                thread = self.bot.get_channel(alliance['thread_id'])
                if thread and isinstance(thread, discord.Thread):
                    await thread.delete()
            except:
                pass
        await alliances_col.delete_one({'_id': alliance_id})
        return True
    @commands.command(name='ally-list')
    @is_registered()
    async def ally_list(self, ctx):
        """Показать список всех одобренных альянсов"""
        alliances = await alliances_col.find({'approved': True}).to_list(length=None)
    
        if not alliances:
            await ctx.send("❌ Нет активных альянсов.")
            return

        embed = discord.Embed(
            title="🏛️ Список альянсов",
            color=discord.Color.gold()
        )

        for alliance in alliances:
            owner_id = alliance.get('owner_id')
            owner = ctx.guild.get_member(int(owner_id)) if owner_id else None
            owner_name = owner.name if owner else f"User{owner_id}"

            members_count = len(alliance.get('members', []))
            treasury = alliance.get('treasury', 0)
            ally_type = alliance.get('type', 'Неизвестен')

            embed.add_field(
                name=f"🏛️ {alliance['name']}",
                value=(
                    f"**Тип:** {ally_type}\n"
                    f"**Глава:** {owner_name}\n"
                    f"**Участников:** {members_count}\n"
                    f"**Казна:** {treasury:,} 💵\n"
                    f"**Налог:** {alliance.get('tax_percent', 2)}%"
                ),
                inline=True
            )

        embed.set_footer(text=f"Всего альянсов: {len(alliances)}")
        await ctx.send(embed=embed)
# ========== UI ДЛЯ КАТЕГОРИЙ ==========
class CategorySetView(View):
    def __init__(self, admin_id: int, member_id: int):
        super().__init__(timeout=60)
        self.admin_id = admin_id
        self.member_id = member_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.admin_id

    @button(label="Нищая Страна", style=discord.ButtonStyle.secondary)
    async def poor(self, interaction: discord.Interaction, button: discord.ui.Button):
        await update_user(self.member_id, {'country_category': 'Нищая Страна'})
        await interaction.response.edit_message(
            content=f"✅ Категория <@{self.member_id}> установлена: **Нищая Страна** (без штрафов)", view=None
        )

    @button(label="Среднячок", style=discord.ButtonStyle.primary)
    async def middle(self, interaction: discord.Interaction, button: discord.ui.Button):
        await update_user(self.member_id, {'country_category': 'Среднячок'})
        await interaction.response.edit_message(
            content=f"✅ Категория <@{self.member_id}> установлена: **Среднячок** (-25% к доходу)", view=None
        )

    @button(label="Богатая Страна", style=discord.ButtonStyle.success)
    async def rich(self, interaction: discord.Interaction, button: discord.ui.Button):
        await update_user(self.member_id, {'country_category': 'Богатая Страна'})
        await interaction.response.edit_message(
            content=f"✅ Категория <@{self.member_id}> установлена: **Богатая Страна** (-50% к доходу)", view=None
        )

# ========== UI ДЛЯ МАГАЗИНА ==========
class ShopView(View):
    def __init__(self, cog: "Shop", author_id: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.author_id = author_id
        self.filter_type = 'all'
        self.filter_value = None
        self.current_page = 0
        self.message = None
 
        self.add_item(CategoryButton("🗂 Все", 'all', discord.ButtonStyle.primary))
        for cat in Shop.VEHICLE_CATEGORIES:
            self.add_item(CategoryButton(cat, cat, discord.ButtonStyle.secondary))
        self.add_item(SearchButton("🔍 Поиск по стране", discord.ButtonStyle.success))
        self.add_item(PageButton("◀️", -1, discord.ButtonStyle.gray))
        self.add_item(PageButton("▶️", 1, discord.ButtonStyle.gray))
 
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id
 
    async def update_message(self, interaction: discord.Interaction):
        embed = await self.cog.build_shop_embed(self)
        try:
            if not interaction.response.is_done():
                await interaction.response.edit_message(embed=embed, view=self)
            else:
                await interaction.edit_original_response(embed=embed, view=self)
        except (discord.errors.NotFound, discord.errors.HTTPException):
            pass


class CategoryButton(discord.ui.Button):
    def __init__(self, label: str, filter_value: str, style):
        super().__init__(label=label, style=style)
        self.filter_value = filter_value
 
    async def callback(self, interaction: discord.Interaction):
        self.view.filter_type = 'all' if self.filter_value == 'all' else 'category'
        self.view.filter_value = self.filter_value if self.filter_value != 'all' else None
        self.view.current_page = 0
        await self.view.update_message(interaction)
 
 
class SearchButton(discord.ui.Button):
    def __init__(self, label, style):
        super().__init__(label=label, style=style)

    async def callback(self, interaction: discord.Interaction):
        shop_view = self.view  # reference to ShopView
        all_vehicles = await vehicles_col.find({"approved": True}).to_list(length=None)
        countries = sorted(set(v.get('country', '') for v in all_vehicles if v.get('country')))
        
        if not countries:
            await interaction.response.send_message("❌ Нет доступных стран.", ephemeral=True)
            return

        options = [discord.SelectOption(label=c[:100], value=c[:100]) for c in countries[:25]]
        select = Select(placeholder="Выберите страну...", options=options)
        
        view = CountrySelectView(shop_view)
        select.callback = view.select_callback
        view.add_item(select)
        await interaction.response.send_message("Выберите страну:", view=view, ephemeral=True)


class CountrySelectView(View):
    def __init__(self, shop_view):
        super().__init__(timeout=60)
        self.shop_view = shop_view

    async def select_callback(self, interaction: discord.Interaction):
        country = interaction.data['values'][0]
        self.shop_view.filter_type = 'search'
        self.shop_view.filter_value = country
        self.shop_view.current_page = 0
        await self.shop_view.update_message(interaction)
 
 
class PageButton(discord.ui.Button):
    def __init__(self, label, delta, style):
        super().__init__(label=label, style=style)
        self.delta = delta

    async def callback(self, interaction: discord.Interaction):
        # Defer immediately before any async DB calls
        await interaction.response.defer()

        all_vehicles = await vehicles_col.find({"approved": True}).to_list(length=None)

        if self.view.filter_type == 'category':
            vehicles = [v for v in all_vehicles if v.get('category') == self.view.filter_value]
        elif self.view.filter_type == 'search':
            vehicles = [v for v in all_vehicles if v.get('country', '').lower() == (self.view.filter_value or '').lower()]
        else:
            vehicles = all_vehicles

        total = len(vehicles)
        max_page = total - 1 if total > 0 else 0
        new_page = self.view.current_page + self.delta
        self.view.current_page = max(0, min(new_page, max_page))

        embed = await self.view.cog.build_shop_embed(self.view)
        try:
            await interaction.edit_original_response(embed=embed, view=self.view)
        except (discord.errors.NotFound, discord.errors.HTTPException):
            pass
# ========== UI ДЛЯ ВОЕННЫХ ОПЕРАЦИЙ ==========
class MilitaryView(View):
    def __init__(self, cog: Shop, user_id: int):
        super().__init__(timeout=120)
        self.cog = cog
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    @button(label="Модернизировать Технику", style=discord.ButtonStyle.primary)
    async def modernize_vehicle(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ModernizationModal(self.cog, self.user_id)
        await interaction.response.send_modal(modal)

    @button(label="Мобилизовать Население", style=discord.ButtonStyle.danger)
    async def mobilize_population(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = await get_user(self.user_id)
        population = user.get('population', 0)
        if population == 0:
            await interaction.response.send_message("❌ У вас нет населения.", ephemeral=True)
            return
        mob_pool = user.get('mob_pool', 0)
        if mob_pool <= 0:
            await interaction.response.send_message("❌ Ваш пул мобилизации пуст. Дождитесь прироста населения.", ephemeral=True)
            return
        modal = MobilizationModal(mob_pool, self.cog)
        await interaction.response.send_modal(modal)

class VehicleInfoModal(Modal, title="Заполните данные техники"):
    name = TextInput(label="Название", placeholder="Т-90", max_length=80)
    description = TextInput(label="Описание", style=discord.TextStyle.long, placeholder="Основной боевой танк...", max_length=1000)
    price = TextInput(label="Стоимость", placeholder="5000000", max_length=20)
    wiki_link = TextInput(label="Ссылка на википедию (обязательно)", placeholder="https://ru.wikipedia.org/wiki/Т-90", max_length=200, required=True)

    def __init__(self, cog: Shop, user_id: int):
        super().__init__()
        self.cog = cog
        self.user_id = user_id

    async def on_submit(self, interaction: discord.Interaction):
        # Проверяем кулдаун перед обработкой
        can_submit, msg = await check_daily_submission_limit(interaction.user.id)
        if not can_submit:
            await interaction.response.send_message(msg, ephemeral=True)
            return
        try:
            price_int = int(self.price.value.replace(',', '').replace(' ', ''))
            if price_int <= 0: raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ Стоимость должна быть положительным целым числом.", ephemeral=True)
            return
        self.cog.pending_add[self.user_id] = {
            'name': self.name.value.strip(),
            'description': self.description.value.strip(),
            'price': price_int,
            'wiki_link': self.wiki_link.value.strip(),
            'is_modernization': False
        }
        view = CategorySelectView(self.cog, self.user_id)
        await interaction.response.send_message("Выберите категорию техники:", view=view, ephemeral=True)

class ModernizationModal(Modal, title="Данные модернизации"):
    name = TextInput(label="Название техники", placeholder="Т-90М", max_length=80)
    description = TextInput(label="Описание модернизации", style=discord.TextStyle.long, placeholder="Улучшенная версия...", max_length=1000)
    price = TextInput(label="Стоимость", placeholder="6000000", max_length=20)

    def __init__(self, cog: Shop, user_id: int):
        super().__init__()
        self.cog = cog
        self.user_id = user_id

    async def on_submit(self, interaction: discord.Interaction):
        # Проверяем кулдаун перед обработкой
        can_submit, msg = await check_daily_submission_limit(interaction.user.id)
        if not can_submit:
            await interaction.response.send_message(msg, ephemeral=True)
            return
        try:
            price_int = int(self.price.value.replace(',', '').replace(' ', ''))
            if price_int <= 0: raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ Неверная стоимость.", ephemeral=True)
            return
        self.cog.pending_add[self.user_id] = {
            'name': self.name.value.strip(),
            'description': self.description.value.strip(),
            'price': price_int,
            'wiki_link': None,
            'is_modernization': True
        }
        view = CategorySelectView(self.cog, self.user_id)
        await interaction.response.send_message("Выберите категорию:", view=view, ephemeral=True)

class MobilizationModal(Modal, title="Мобилизация населения"):
    qty = TextInput(label="Количество солдат", placeholder="Введите число", max_length=10)
    link = TextInput(label="Ссылка на сообщение в канале реформ", placeholder="https://discord.com/channels/...", max_length=200)

    def __init__(self, mob_pool: int, cog):
        super().__init__()
        self.mob_pool = mob_pool
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            qty = int(self.qty.value)
        except ValueError:
            await interaction.response.send_message("❌ Количество должно быть числом.", ephemeral=True)
            return
        if qty <= 0:
            await interaction.response.send_message("❌ Количество должно быть больше 0.", ephemeral=True)
            return
        DAILY_LIMIT = 350_000
        limit_doc = await mobilization_limits_col.find_one({'user_id': str(interaction.user.id)})
        now = datetime.now().timestamp()
        mobilized_today = 0
        if limit_doc:
            if now - limit_doc.get('window_start', 0) < 86400:
                mobilized_today = limit_doc.get('mobilized_today', 0)
        can_mobilize = DAILY_LIMIT - mobilized_today

        if qty > self.mob_pool:
            await interaction.response.send_message(
                f"❌ Нельзя мобилизовать больше **{self.mob_pool:,}** (ваш текущий пул).",
                ephemeral=True
            )
            return
        if qty > can_mobilize:
            await interaction.response.send_message(
                f"❌ Можно мобилизовать ещё максимум **{can_mobilize:,}** солдат сегодня.\n"
                f"Уже мобилизовано: **{mobilized_today:,}** / **{DAILY_LIMIT:,}**",
                ephemeral=True
            )
            return
        result = await self.cog.perform_mobilization(interaction, interaction.user.id, qty, self.link.value.strip())
        await interaction.response.send_message(result, ephemeral=True)

class CategorySelectView(View):
    def __init__(self, cog: Shop, user_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.user_id = user_id
        select = Select(placeholder="Выберите категорию...", options=[discord.SelectOption(label=cat) for cat in Shop.VEHICLE_CATEGORIES])
        select.callback = self.select_callback
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    async def select_callback(self, interaction: discord.Interaction):
        category = interaction.data['values'][0]
        data = self.cog.pending_add.get(self.user_id)
        if not data:
            await interaction.response.send_message("⚠️ Данные утеряны, начните заново.", ephemeral=True)
            return
        data['category'] = category
        user = await get_user(self.user_id)
        country = user.get('country', '?')
        flag_url = user.get('country_flag_url', '')

        embed = discord.Embed(title="Подтверждение заявки", color=discord.Color.green())
        embed.add_field(name="Название", value=data['name'], inline=False)
        embed.add_field(name="Описание", value=data['description'], inline=False)
        embed.add_field(name="Стоимость", value=f"{data['price']:,} 💵", inline=True)
        embed.add_field(name="Категория", value=category, inline=True)
        embed.add_field(name="Страна", value=country, inline=True)
        if data.get('wiki_link'):
            embed.add_field(name="Википедия", value=data['wiki_link'], inline=False)

        # Set flag as thumbnail if available 
        if flag_url and flag_url.startswith('http'):
            embed.set_thumbnail(url=flag_url)
            embed.set_author(name=country, icon_url=flag_url)
        submit_view = SubmitView(self.cog, self.user_id)
        await interaction.response.send_message(embed=embed, view=submit_view, ephemeral=True)

class SubmitView(View):
    def __init__(self, cog: Shop, user_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    @button(label="Отправить заявку", style=discord.ButtonStyle.success)
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = self.cog.pending_add.pop(self.user_id, None)
        if not data:
            await interaction.response.send_message("Данные не найдены.", ephemeral=True)
            return
        await self.cog.submit_application(self.user_id, data)
        await interaction.response.send_message("✅ Заявка отправлена на рассмотрение!", ephemeral=True, delete_after=5)

    @button(label="Отменить", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.cog.pending_add.pop(self.user_id, None)
        await interaction.response.send_message("❌ Заявка отменена.", ephemeral=True)

# ========== UI ДЛЯ МОДЕРАЦИИ ==========
class ApprovalView(View):
    def __init__(self, shop_cog: Shop, vehicle_id):
        super().__init__(timeout=None)
        self.shop = shop_cog
        self.vehicle_id = vehicle_id

    @button(label="Одобрить", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        vehicle = await vehicles_col.find_one({'_id': self.vehicle_id})
        if not vehicle:
            await interaction.response.send_message("Заявка не найдена.", ephemeral=True)
            return
        await self.shop.approve_vehicle(self.vehicle_id, interaction.user)
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.green()
        embed.title = "✅ Заявка одобрена"
        embed.set_footer(text=f"Одобрено модератором: {interaction.user}")
        await interaction.message.edit(embed=embed, view=None)
        await interaction.response.send_message("✅ Заявка одобрена.", ephemeral=True, delete_after=3)

    @button(label="Отклонить", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = RejectionModal(self.shop, self.vehicle_id, interaction.user, interaction.message)
        await interaction.response.send_modal(modal)

class RejectionModal(Modal, title="Причина отклонения"):
    reason = TextInput(label="Причина", style=discord.TextStyle.long, placeholder="Не соответствует критериям...", max_length=500)

    def __init__(self, shop_cog: Shop, vehicle_id, moderator: discord.Member, message: discord.Message):
        super().__init__()
        self.shop = shop_cog
        self.vehicle_id = vehicle_id
        self.moderator = moderator
        self.message = message

    async def on_submit(self, interaction: discord.Interaction):
        reason_text = self.reason.value.strip()
        await self.shop.reject_vehicle(self.vehicle_id, reason_text, self.moderator)
        embed = self.message.embeds[0]
        embed.color = discord.Color.red()
        embed.title = "❌ Заявка отклонена"
        embed.add_field(name="Причина", value=reason_text, inline=False)
        embed.set_footer(text=f"Отклонено модератором: {self.moderator}")
        await self.message.edit(embed=embed, view=None)
        await interaction.response.send_message("❌ Заявка отклонена.", ephemeral=True, delete_after=3)

# ========== FULL-REG UI ==========
class FullRegView(View):
    def __init__(self, admin_cog: Admin, member_id: int, user_data: dict, author_id: int):
        super().__init__(timeout=600)
        self.admin_cog = admin_cog
        self.member_id = member_id
        self.user_data = user_data
        self.author_id = author_id
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    @button(label="Редактировать Страну", style=discord.ButtonStyle.primary)
    async def edit_country(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = EditCountryModal(self.member_id, self.admin_cog)
        await interaction.response.send_modal(modal)

    @button(label="Редактировать Флаг", style=discord.ButtonStyle.primary)
    async def edit_flag(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = EditFlagModal(self.member_id, self.admin_cog)
        await interaction.response.send_modal(modal)

    @button(label="Редактировать Баланс", style=discord.ButtonStyle.success)
    async def edit_balance(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = EditBalanceModal(self.member_id, self.admin_cog)
        await interaction.response.send_modal(modal)

    @button(label="Редактировать ВВП", style=discord.ButtonStyle.success)
    async def edit_gdp(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = EditGDPModal(self.member_id, self.admin_cog)
        await interaction.response.send_modal(modal)

    @button(label="Редактировать Население", style=discord.ButtonStyle.success)
    async def edit_population(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = EditPopulationModal(self.member_id, self.admin_cog)
        await interaction.response.send_modal(modal)

    @button(label="Редактировать Недовольство", style=discord.ButtonStyle.danger)
    async def edit_unhappiness(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = EditUnhappinessModal(self.member_id, self.admin_cog)
        await interaction.response.send_modal(modal)

    @button(label="Редактировать Рост Населения", style=discord.ButtonStyle.secondary)
    async def edit_growth(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = EditGrowthModal(self.member_id, self.admin_cog)
        await interaction.response.send_modal(modal)

    @button(label="Редактировать Идеологию", style=discord.ButtonStyle.secondary)
    async def edit_ideology(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = EditIdeologyModal(self.member_id, self.admin_cog)
        await interaction.response.send_modal(modal)

    @button(label="Редактировать Мобилизацию", style=discord.ButtonStyle.secondary)
    async def edit_mobilization(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = EditMobilizationModal(self.member_id, self.admin_cog)
        await interaction.response.send_modal(modal)

    @button(label="Анрегнуть Игрока", style=discord.ButtonStyle.danger)
    async def unreg_player(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        member = guild.get_member(self.member_id)
        if not member:
            await interaction.followup.send("❌ Игрок не найден на сервере.", ephemeral=True)
            return

        default_user = {
            'balance': 0,
            'gdp': 0,
            'last_collect': 0,
            'population': 0,
            'pop_growth_yearly': 2.0,
            'last_pop_update': 0,
            'budget_social': DEFAULT_BUDGETS['budget_social'],
            'budget_education': DEFAULT_BUDGETS['budget_education'],
            'budget_healthcare': DEFAULT_BUDGETS['budget_healthcare'],
            'budget_other': DEFAULT_BUDGETS['budget_other'],
            'unhappiness': 0.0,
            'last_unhappiness_update': 0,
            'country': None,
            'country_flag_url': None,
            'mobilization_percent': 2.5,
            'mob_pool': 0,
            'alliance_id': None,
            'alliance_role': None,
            'ideology': 'Не указана',
            'country_category': 'Нищая Страна',
        }
        await update_user(self.member_id, default_user)
        await inventory_col.delete_many({'user_id': str(self.member_id)})
        await licenses_col.delete_many({'user_id': str(self.member_id)})

        reg_role = guild.get_role(REGISTERED_ROLE_ID)
        unreg_role = guild.get_role(UNREGISTERED_ROLE_ID)
        country_role = guild.get_role(COUNTRY_ROLE_ID)
        role1 = guild.get_role(1149997878828351539)
        role2 = guild.get_role(1504245939521720523)
        role3 = guild.get_role(1187496360459649054)

        if reg_role: await member.remove_roles(reg_role)
        if country_role: await member.remove_roles(country_role)
        if role1: await member.remove_roles(role1)
        if role2: await member.remove_roles(role2)
        if role3: await member.remove_roles(role3)
        if unreg_role: await member.add_roles(unreg_role)

        await interaction.followup.send(f"✅ Игрок {member.mention} полностью анрегнут.", ephemeral=True)

    @button(label="Закончить Редактирование", style=discord.ButtonStyle.success)
    async def finish_edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        # ===== Управление ролями при завершении регистрации =====
        guild = interaction.guild
        guild_member = guild.get_member(self.member_id) if guild else None
        if guild_member:
            role_remove = guild.get_role(1141339127367880764)
            role_add_1 = guild.get_role(1141359343036530818)
            role_add_2 = guild.get_role(1501510805169115176)
            role_add_3 = guild.get_role(1361590005289586759)
            role_add_4 = guild.get_role(1143446021322579988)
            try:
               if role_remove and role_remove in guild_member.roles:
                await guild_member.remove_roles(role_remove, reason="Завершение регистрации (!full-reg)")
            roles_to_add = [r for r in (role_add_1, role_add_2) if r and r not in guild_member.roles]
            if roles_to_add:
                await guild_member.add_roles(*roles_to_add, reason="Завершение регистрации (!full-reg)")
            if role_add_1:
                await schedule_role_removal(self.member_id, TEMP_ROLE_ID, TEMP_ROLE_DURATION_SECONDS)
            except discord.Forbidden:
                pass
            except Exception:
                pass
        # ==========================================================

        member = self.admin_cog.bot.get_user(self.member_id)
        if not member:
            member = await self.admin_cog.bot.fetch_user(self.member_id)
        economy_cog = self.admin_cog.bot.get_cog("💰 Экономика")
        if economy_cog:
            cab_embed = await economy_cog.build_cab_embed(member)
            await interaction.response.edit_message(embed=cab_embed, view=None)
        else:
            await interaction.response.send_message("✅ Редактирование завершено.", ephemeral=True)

class EditCountryModal(Modal, title="Редактировать Страну"):
    country_name = TextInput(label="Название страны", placeholder="Франция", max_length=100)

    def __init__(self, member_id: int, admin_cog):
        super().__init__()
        self.member_id = member_id
        self.admin_cog = admin_cog

    async def on_submit(self, interaction: discord.Interaction):
        await update_user(self.member_id, {'country': self.country_name.value.strip()})
        await interaction.response.send_message(f"✅ Страна изменена на **{self.country_name.value.strip()}**", ephemeral=True)

class EditFlagModal(Modal, title="Редактировать Флаг"):
    flag_url = TextInput(label="Ссылка на изображение флага", placeholder="https://...", max_length=500)

    def __init__(self, member_id: int, admin_cog):
        super().__init__()
        self.member_id = member_id
        self.admin_cog = admin_cog

    async def on_submit(self, interaction: discord.Interaction):
        url = self.flag_url.value.strip()
    
        # Warn if Discord CDN link (expires)
        if 'cdn.discordapp.com' in url or 'media.discordapp.net' in url:
            await interaction.response.send_message(
                "⚠️ Discord CDN ссылки истекают со временем!\n"
                "Используйте постоянные ссылки (imgur, flagcdn.com, wikipedia).\n"
                "Флаг не был сохранён — попробуйте другую ссылку.",
                ephemeral=True
            )
            return
    
        await update_user(self.member_id, {'country_flag_url': url})
        await interaction.response.send_message("✅ Флаг обновлен", ephemeral=True)

class EditBalanceModal(Modal, title="Редактировать Баланс"):
    new_balance = TextInput(label="Новый баланс (или пусто)", placeholder="1000000", max_length=20, required=False)
    add_balance = TextInput(label="Добавить/Вычесть (или пусто)", placeholder="+500000 или -300000", max_length=20, required=False)

    def __init__(self, member_id: int, admin_cog):
        super().__init__()
        self.member_id = member_id
        self.admin_cog = admin_cog

    async def on_submit(self, interaction: discord.Interaction):
        user = await get_user(self.member_id)
        if self.new_balance.value:
            try:
                amount = int(self.new_balance.value.replace(',', '').replace(' ', ''))
                await update_user(self.member_id, {'balance': amount})
                await interaction.response.send_message(f"✅ Баланс установлен на **{amount:,}** 💵", ephemeral=True)
            except ValueError:
                await interaction.response.send_message("❌ Неверное значение", ephemeral=True)
        elif self.add_balance.value:
            try:
                amount = int(self.add_balance.value.replace(',', '').replace(' ', ''))
                new_balance = user['balance'] + amount
                await update_user(self.member_id, {'balance': new_balance})
                await interaction.response.send_message(f"✅ Баланс изменен на {amount:+,} 💵. Новый баланс: **{new_balance:,}** 💵", ephemeral=True)
            except ValueError:
                await interaction.response.send_message("❌ Неверное значение", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Заполните хотя бы одно поле", ephemeral=True)

class EditGDPModal(Modal, title="Редактировать ВВП"):
    new_gdp = TextInput(label="Новый ВВП (или пусто)", placeholder="100000000000", max_length=20, required=False)
    add_gdp = TextInput(label="Добавить/Вычесть (или пусто)", placeholder="+50000000000", max_length=20, required=False)

    def __init__(self, member_id: int, admin_cog):
        super().__init__()
        self.member_id = member_id
        self.admin_cog = admin_cog

    async def on_submit(self, interaction: discord.Interaction):
        user = await get_user(self.member_id)
        if self.new_gdp.value:
            try:
                amount = int(self.new_gdp.value.replace(',', '').replace(' ', ''))
                await update_user(self.member_id, {'gdp': amount})
                await auto_update_category(self.member_id, amount)
                await interaction.response.send_message(f"✅ ВВП установлен на **{amount:,}** 💵", ephemeral=True)
            except ValueError:
                await interaction.response.send_message("❌ Неверное значение", ephemeral=True)
        elif self.add_gdp.value:
            try:
                amount = int(self.add_gdp.value.replace(',', '').replace(' ', ''))
                new_gdp = user['gdp'] + amount
                await update_user(self.member_id, {'gdp': new_gdp})
                await auto_update_category(self.member_id, new_gdp)
                await interaction.response.send_message(f"✅ ВВП изменен на {amount:+,} 💵. Новое ВВП: **{new_gdp:,}** 💵", ephemeral=True)
            except ValueError:
                await interaction.response.send_message("❌ Неверное значение", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Заполните хотя бы одно поле", ephemeral=True)

class EditPopulationModal(Modal, title="Редактировать Население"):
    new_pop = TextInput(label="Новое население (или пусто)", placeholder="1000000", max_length=20, required=False)
    add_pop = TextInput(label="Добавить/Вычесть (или пусто)", placeholder="+500000", max_length=20, required=False)

    def __init__(self, member_id: int, admin_cog):
        super().__init__()
        self.member_id = member_id
        self.admin_cog = admin_cog

    async def on_submit(self, interaction: discord.Interaction):
        user = await get_user(self.member_id)
        mob_pct = user.get('mobilization_percent', 2.5)

        if self.new_pop.value:
            try:
                amount = int(self.new_pop.value.replace(',', '').replace(' ', ''))
                if amount < 0:
                    await interaction.response.send_message("❌ Население не может быть отрицательным", ephemeral=True)
                    return
                current_time = datetime.now().timestamp()
                update_data = {'population': amount}
                if amount > 0:
                    update_data['mob_pool'] = int(amount * mob_pct / 100)
                    if user.get('population', 0) == 0:
                        update_data['last_pop_update'] = current_time
                elif amount == 0:
                    update_data['last_pop_update'] = 0
                    update_data['mob_pool'] = 0
                await update_user(self.member_id, update_data)
                pool_val = update_data.get('mob_pool', user.get('mob_pool', 0))
                await interaction.response.send_message(
                    f"✅ Население установлено на **{amount:,}** чел.\n"
                    f"🎖️ Пул мобилизации ({mob_pct}%): **{pool_val:,}**",
                    ephemeral=True
                )
            except ValueError:
                await interaction.response.send_message("❌ Неверное значение", ephemeral=True)

        elif self.add_pop.value:
            try:
                amount = int(self.add_pop.value.replace(',', '').replace(' ', ''))
                new_pop = user.get('population', 0) + amount
                if new_pop < 0:
                    await interaction.response.send_message("❌ Население не может быть отрицательным", ephemeral=True)
                    return
                current_time = datetime.now().timestamp()
                update_data = {'population': new_pop}
                if amount > 0:
                    pool_gain = int(amount * mob_pct / 100)
                    update_data['mob_pool'] = user.get('mob_pool', 0) + pool_gain
                elif amount < 0:
                    update_data['mob_pool'] = max(0, int(new_pop * mob_pct / 100))
                await update_user(self.member_id, update_data)
                pool_display = update_data.get('mob_pool', user.get('mob_pool', 0))
                await interaction.response.send_message(
                    f"✅ Население изменено на {amount:+,} чел. Новое население: **{new_pop:,}** чел.\n"
                    f"🎖️ Пул мобилизации ({mob_pct}%): **{pool_display:,}**",
                    ephemeral=True
                )
            except ValueError:
                await interaction.response.send_message("❌ Неверное значение", ephemeral=True)

        else:
            await interaction.response.send_message("❌ Заполните хотя бы одно поле", ephemeral=True)

class EditUnhappinessModal(Modal, title="Редактировать Недовольство"):
    unhappiness = TextInput(label="Процент недовольства (0-100)", placeholder="50", max_length=3)

    def __init__(self, member_id: int, admin_cog):
        super().__init__()
        self.member_id = member_id
        self.admin_cog = admin_cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            percent = float(self.unhappiness.value)
            if not (0 <= percent <= 100):
                raise ValueError
            current_time = datetime.now().timestamp()
            await update_user(self.member_id, {
                'unhappiness': percent,
                'last_unhappiness_update': current_time
            })
            await interaction.response.send_message(f"✅ Недовольство установлено на **{percent:.2f}%**", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Процент должен быть от 0 до 100", ephemeral=True)

class EditGrowthModal(Modal, title="Редактировать Рост Населения"):
    growth = TextInput(label="Процент роста в год (1-100)", placeholder="2.5", max_length=5)

    def __init__(self, member_id: int, admin_cog):
        super().__init__()
        self.member_id = member_id
        self.admin_cog = admin_cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            percent = float(self.growth.value)
            if not (1 <= percent <= 100):
                raise ValueError
            await update_user(self.member_id, {'pop_growth_yearly': percent})
            await interaction.response.send_message(f"✅ Рост населения установлен на **{percent:.2f}%** в год", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Процент должен быть от 1 до 100", ephemeral=True)

class EditIdeologyModal(Modal, title="Редактировать Идеологию"):
    ideology = TextInput(label="Идеология (макс 200 символов)", placeholder="Демократия", max_length=200, required=True)

    def __init__(self, member_id: int, admin_cog):
        super().__init__()
        self.member_id = member_id
        self.admin_cog = admin_cog

    async def on_submit(self, interaction: discord.Interaction):
        ideology_text = self.ideology.value.strip()
        if not ideology_text:
            await interaction.response.send_message("❌ Идеология не может быть пустой", ephemeral=True)
            return
        await update_user(self.member_id, {'ideology': ideology_text})
        await interaction.response.send_message(f"✅ Идеология установлена на **{ideology_text}**", ephemeral=True)

class EditMobilizationModal(Modal, title="Редактировать Мобилизацию"):
    mobilization = TextInput(label="Процент мобилизации (2.5-25)", placeholder="5", max_length=5)
    pool = TextInput(label="Установить пул мобилизации (или пусто)", placeholder="50000", max_length=15, required=False)

    def __init__(self, member_id: int, admin_cog):
        super().__init__()
        self.member_id = member_id
        self.admin_cog = admin_cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            percent = float(self.mobilization.value)
            if not (1.0 <= percent <= 25.0):
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ Процент должен быть от 1.0 до 25", ephemeral=True)
            return

        update_data = {'mobilization_percent': percent}

        if self.pool.value:
            try:
                pool_val = int(self.pool.value.replace(',', '').replace(' ', ''))
                if pool_val < 0:
                    raise ValueError
                update_data['mob_pool'] = pool_val
            except ValueError:
                await interaction.response.send_message("❌ Пул должен быть положительным числом", ephemeral=True)
                return

        await update_user(self.member_id, update_data)
        msg = f"✅ Процент мобилизации: **{percent}%**"
        if 'mob_pool' in update_data:
            msg += f"\n✅ Пул установлен: **{update_data['mob_pool']:,}**"
        await interaction.response.send_message(msg, ephemeral=True)
class EditNationalitiesModal(Modal, title="Редактировать Национальности"):
    """
    Формат ввода (каждая строка — одна национальность):
        Русские: 5000000
        Татары: 1200000
        Другие: 300000
    После сохранения население пересчитывается как сумма всех национальностей.
    """
    nationalities_text = TextInput(
        label="Национальности (Название: число, по строкам)",
        style=discord.TextStyle.long,
        placeholder="Русские: 5000000\nТатары: 1200000\nДругие: 300000",
        max_length=1000,
        required=False
    )

    def __init__(self, member_id: int, admin_cog, user: dict):
        super().__init__()
        self.member_id = member_id
        self.admin_cog = admin_cog
        # Показываем текущее значение
        current = user.get('nationalities', '')
        if current:
            self.nationalities_text.default = current[:1000]

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.nationalities_text.value.strip()

        if not raw:
            # Очищаем поле, не трогаем население
            await update_user(self.member_id, {'nationalities': ''})
            await interaction.response.send_message("✅ Национальности очищены.", ephemeral=True)
            return

        # Парсим строки вида "Название: число"
        total_population = 0
        parsed_lines = []
        errors = []

        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            if ':' not in line:
                errors.append(f"❌ Строка без ':' пропущена: `{line}`")
                parsed_lines.append(line)  # сохраняем как есть
                continue
            parts = line.split(':', 1)
            name = parts[0].strip()
            value_str = parts[1].strip().replace(',', '').replace(' ', '').replace('.', '')
            try:
                count = int(value_str)
                if count < 0:
                    raise ValueError
                total_population += count
                parsed_lines.append(f"{name}: {count:,}")
            except ValueError:
                errors.append(f"❌ Не удалось распознать число в строке: `{line}`")
                parsed_lines.append(line)

        nat_text = "\n".join(parsed_lines)

        # Обновляем национальности и население (сумма)
        user = await get_user(self.member_id)
        mob_pct = user.get('mobilization_percent', 2.5)
        update_data = {'nationalities': nat_text}

        if total_population > 0:
            update_data['population'] = total_population
            update_data['mob_pool'] = int(total_population * mob_pct / 100)

        await update_user(self.member_id, update_data)

        msg = f"✅ Национальности обновлены.\n"
        if total_population > 0:
            msg += f"👥 Общее население пересчитано: **{total_population:,}** чел.\n"
            msg += f"🎖️ Пул мобилизации ({mob_pct}%): **{update_data['mob_pool']:,}**\n"
        if errors:
            msg += "\n⚠️ Предупреждения:\n" + "\n".join(errors)

        await interaction.response.send_message(msg, ephemeral=True)
class EditGdpPpsIncomeModal(Modal, title="ВВП ППС и Доходы"):
    gdp_pps = TextInput(
        label="ВВП (ППС)",
        placeholder="150000000000",
        max_length=20,
        required=False
    )
    income_services = TextInput(
        label="Доходы: Сфера услуг",
        placeholder="5000000000",
        max_length=20,
        required=False
    )
    income_exports = TextInput(
        label="Доходы: Экспорт П/И",
        placeholder="3000000000",
        max_length=20,
        required=False
    )
    income_tourism = TextInput(
        label="Доходы: Туризм",
        placeholder="1000000000",
        max_length=20,
        required=False
    )
    income_other = TextInput(
        label="Доходы: Другие",
        placeholder="500000000",
        max_length=20,
        required=False
    )

    def __init__(self, member_id: int, admin_cog, user: dict):
        super().__init__()
        self.member_id = member_id
        self.admin_cog = admin_cog
        if user.get('gdp_pps'):
            self.gdp_pps.default = str(user['gdp_pps'])
        if user.get('income_services'):
            self.income_services.default = str(user['income_services'])
        if user.get('income_exports'):
            self.income_exports.default = str(user['income_exports'])
        if user.get('income_tourism'):
            self.income_tourism.default = str(user['income_tourism'])
        if user.get('income_other_src'):
            self.income_other.default = str(user['income_other_src'])

    async def on_submit(self, interaction: discord.Interaction):
        update_data = {}
        errors = []

        fields = [
            ('gdp_pps',          self.gdp_pps.value,          'ВВП (ППС)'),
            ('income_services',  self.income_services.value,  'Сфера услуг'),
            ('income_exports',   self.income_exports.value,   'Экспорт П/И'),
            ('income_tourism',   self.income_tourism.value,   'Туризм'),
            ('income_other_src', self.income_other.value,     'Другие доходы'),
        ]

        for key, raw, label in fields:
            if not raw.strip():
                continue
            try:
                val = int(raw.replace(',', '').replace(' ', ''))
                if val < 0:
                    raise ValueError
                update_data[key] = val
            except ValueError:
                errors.append(f"❌ Неверное значение для **{label}**: `{raw}`")

        if not update_data and not errors:
            await interaction.response.send_message("ℹ️ Не заполнено ни одно поле.", ephemeral=True)
            return

        if update_data:
            await update_user(self.member_id, update_data)

        lines = []
        label_map = {
            'gdp_pps':          'ВВП (ППС)',
            'income_services':  'Сфера услуг',
            'income_exports':   'Экспорт П/И',
            'income_tourism':   'Туризм',
            'income_other_src': 'Другие доходы',
        }
        for key, val in update_data.items():
            lines.append(f"✅ {label_map[key]}: **{val:,}** 💵")

        if errors:
            lines += errors

        await interaction.response.send_message("\n".join(lines) or "ℹ️ Ничего не изменено.", ephemeral=True)
# ========== ДОПОЛНИТЕЛЬНЫЕ VIEW ==========
class VehicleInfoSelectView(View):
    def __init__(self, author_id, matches, select: Select, shop_cog):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.matches = matches
        self.shop_cog = shop_cog
        select.callback = self.select_callback
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    async def select_callback(self, interaction: discord.Interaction):
        selected_id = interaction.data['values'][0]
        vehicle = next((v for v in self.matches if str(v['_id']) == selected_id), None)
        if vehicle:
            embed = await self.shop_cog.build_vehicle_info_embed(vehicle)
            await interaction.response.edit_message(embed=embed, view=None)
class IsoSelectView(View):
    def __init__(self, author_id, matches, select: Select, image_url: str, shop_cog):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.matches = matches
        self.image_url = image_url
        self.shop_cog = shop_cog
        select.callback = self.select_callback
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    async def select_callback(self, interaction: discord.Interaction):
        selected_name = interaction.data['values'][0]
        vehicle = next((v for v in self.matches if v['name'] == selected_name), None)
        if vehicle:
            await vehicles_col.update_one({'_id': vehicle['_id']}, {'$set': {'image_url': self.image_url}})
            await interaction.response.send_message(f"✅ Изображение для **{vehicle['name']}** обновлено.", ephemeral=True)

class InvseeChoiceView(View):
    def __init__(self, admin_id: int, target_id: int, bot):
        super().__init__(timeout=30)
        self.admin_id = admin_id
        self.target_id = target_id
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.admin_id

    @button(label="В ЛС", style=discord.ButtonStyle.primary)
    async def to_dm(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = self.bot.get_user(self.admin_id)
        if user:
            try:
                await user.send(embed=await self._build_inventory_embed())
                await interaction.response.send_message("Инвентарь отправлен в ЛС.", ephemeral=True)
            except:
                await interaction.response.send_message("Не могу отправить ЛС.", ephemeral=True)
        else:
            await interaction.response.send_message("Ошибка: пользователь не найден.", ephemeral=True)

    @button(label="Сюда", style=discord.ButtonStyle.secondary)
    async def here(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = await self._build_inventory_embed()
        await interaction.response.edit_message(embed=embed, view=None)

    async def _build_inventory_embed(self):
        items = await get_inventory(self.target_id)
        embed = discord.Embed(title="📦 Инвентарь", color=discord.Color.blue())
        if not items:
            embed.description = "Пусто."
        else:
            text = "\n".join(f"**{it['item_name']}** — {it['quantity']} шт." for it in items)
            if len(text) > 2000:
                text = text[:1997] + "..."
            embed.description = text
        return embed

class ConfirmView(View):
    def __init__(self, author_id, vehicle_id, name, admin_cog):
        super().__init__(timeout=30)
        self.author_id = author_id
        self.vehicle_id = vehicle_id
        self.name = name
        self.admin_cog = admin_cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    @button(label="Удалить", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.admin_cog.delete_vehicle_by_id(self.vehicle_id, self.name, interaction)

    @button(label="Отмена", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Удаление отменено.", view=None)

class DeleteSelectView(View):
    def __init__(self, author_id, matches, select: Select, admin_cog):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.matches = matches
        self.admin_cog = admin_cog
        select.callback = self.select_callback
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    async def select_callback(self, interaction: discord.Interaction):
        selected_id = interaction.data['values'][0]
        vehicle = next(v for v in self.matches if str(v['_id']) == selected_id)
        await self.admin_cog.delete_vehicle_by_id(vehicle['_id'], vehicle['name'], interaction)

class TakeSelectView(View):
    def __init__(self, author_id: int, member: discord.Member, quantity: int, matches: list, select: Select, admin_cog):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.member = member
        self.quantity = quantity
        self.matches = matches
        self.admin_cog = admin_cog
        select.callback = self.select_callback
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    async def select_callback(self, interaction: discord.Interaction):
        selected_name = interaction.data['values'][0]
        item = next((it for it in self.matches if it['item_name'] == selected_name), None)
        if item:
            await self.admin_cog._process_take_removal(None, self.member, item, self.quantity, interaction)
        self.stop()

class UseSelectView(View):
    def __init__(self, author_id: int, quantity: int, matches: list, select: Select, shop_cog):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.quantity = quantity
        self.matches = matches
        self.shop_cog = shop_cog
        select.callback = self.select_callback
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    async def select_callback(self, interaction: discord.Interaction):
        selected_name = interaction.data['values'][0]
        item = next((it for it in self.matches if it['item_name'] == selected_name), None)
        if item:
            await self.shop_cog._process_use(interaction.user, item, self.quantity, interaction)
        self.stop()

class PlayersCountryView(View):
    def __init__(self, guild: discord.Guild, author_id: int):
        super().__init__(timeout=180)
        self.guild = guild
        self.author_id = author_id
        self.mode = 'states'
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    async def build_embed(self, mode: str) -> discord.Embed:
        reg_role = self.guild.get_role(REGISTERED_ROLE_ID)
        country_role = self.guild.get_role(COUNTRY_ROLE_ID)
        if not reg_role:
            return discord.Embed(title="Ошибка", description="Роль зарегистрированного не найдена.")
        members = [m for m in self.guild.members if reg_role in m.roles and not m.bot]
        if mode == 'states':
            state_members = []
            for m in members:
                if country_role and country_role in m.roles:
                    user = await get_user(m.id)
                    country = user.get('country')
                    if country:
                        state_members.append((country, m))
            state_members.sort(key=lambda x: x[0].lower())
            description = ""
            for i, (country, member) in enumerate(state_members, 1):
                description += f"**{i}.** {country} ({member.name})\n"
            if not description:
                description = "Нет государств."
            embed = discord.Embed(title="🌍 Государства", description=description, color=discord.Color.blue())
        else:
            other_members = [m for m in members if not country_role or country_role not in m.roles]
            other_members.sort(key=lambda m: m.name.lower())
            description = ""
            for i, member in enumerate(other_members, 1):
                description += f"**{i}.** {member.name}\n"
            if not description:
                description = "Нет игроков без государства."
            embed = discord.Embed(title="👥 Другие", description=description, color=discord.Color.greyple())
        return embed

    @button(label="Государства", style=discord.ButtonStyle.primary)
    async def states_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = 'states'
        embed = await self.build_embed('states')
        await interaction.response.edit_message(embed=embed, view=self)

    @button(label="Другие", style=discord.ButtonStyle.secondary)
    async def others_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = 'others'
        embed = await self.build_embed('others')
        await interaction.response.edit_message(embed=embed, view=self)

class TopSelectView(View):
    def __init__(self, ctx):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.mode = 'balance'
        self.current_page = 0
        self.all_data = []
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.ctx.author.id

    async def fetch_data(self, mode: str):
        if mode == 'gdp':
            data = await economy_col.find({'gdp': {'$gt': 0}}).sort('gdp', -1).to_list(length=None)
        elif mode == 'population':
            data = await economy_col.find({'population': {'$gt': 0}}).sort('population', -1).to_list(length=None)
        else:
            data = await economy_col.find({'balance': {'$gt': 0}}).sort('balance', -1).to_list(length=None)
        return data

    async def build_embed(self, mode: str) -> discord.Embed:
        self.all_data = await self.fetch_data(mode)

        if mode == 'gdp':
            title = "📈 Топ по ВВП"
            value_key = 'gdp'
        elif mode == 'population':
            title = "👥 Топ по населению"
            value_key = 'population'
        else:
            title = "💰 Топ по балансу"
            value_key = 'balance'

        per_page = 10
        total = len(self.all_data)
        max_page = max(0, (total - 1) // per_page) if total > 0 else 0
        self.current_page = min(self.current_page, max_page)

        start = self.current_page * per_page
        end = start + per_page
        page_data = self.all_data[start:end]

        embed = discord.Embed(
            title=title,
            description=f"Страница {self.current_page + 1}/{max_page + 1} · Всего: {total}",
            color=discord.Color.gold()
        )

        if not page_data:
            embed.add_field(name="Нет данных", value="—", inline=False)
            return embed

        description = ""
        for i, user_data in enumerate(page_data, start + 1):
            try:
                member = self.ctx.guild.get_member(int(user_data['_id']))
                name = member.name if member else f"User{user_data['_id']}"
            except:
                name = f"User{user_data['_id']}"
            country = user_data.get('country')
            display = f"{country} ({name})" if country else name
            value = user_data.get(value_key, 0)
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"**{i}.**")
            if value_key == 'population':
                description += f"{medal} {display} — 👥 **{value:,}** чел.\n"
            else:
                description += f"{medal} {display} — 💵 **{value:,}**\n"

        embed.description = (
            f"Страница **{self.current_page + 1}/{max_page + 1}** · Всего: **{total}**\n\n"
            + description
        )
        return embed

    async def update(self, interaction: discord.Interaction):
        embed = await self.build_embed(self.mode)
        await interaction.response.edit_message(embed=embed, view=self)

    @button(label="ВВП", style=discord.ButtonStyle.primary, row=0)
    async def gdp_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = 'gdp'
        self.current_page = 0
        await self.update(interaction)

    @button(label="Население", style=discord.ButtonStyle.success, row=0)
    async def pop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = 'population'
        self.current_page = 0
        await self.update(interaction)

    @button(label="Баланс", style=discord.ButtonStyle.secondary, row=0)
    async def bal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = 'balance'
        self.current_page = 0
        await self.update(interaction)

    @button(label="⬅️", style=discord.ButtonStyle.gray, row=1)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        per_page = 10
        total = len(self.all_data)
        max_page = max(0, (total - 1) // per_page) if total > 0 else 0
        if self.current_page > 0:
            self.current_page -= 1
        await self.update(interaction)

    @button(label="➡️", style=discord.ButtonStyle.gray, row=1)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        per_page = 10
        total = len(self.all_data)
        max_page = max(0, (total - 1) // per_page) if total > 0 else 0
        if self.current_page < max_page:
            self.current_page += 1
        await self.update(interaction)

    @button(label="ВВП", style=discord.ButtonStyle.primary)
    async def gdp_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = 'gdp'
        embed = await self.build_embed('gdp')
        await interaction.response.edit_message(embed=embed, view=self)
    @button(label="Население", style=discord.ButtonStyle.success)
    async def pop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = 'population'
        embed = await self.build_embed('population')
        await interaction.response.edit_message(embed=embed, view=self)

    @button(label="Баланс", style=discord.ButtonStyle.secondary)
    async def bal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = 'balance'
        embed = await self.build_embed('balance')
        await interaction.response.edit_message(embed=embed, view=self)

# ========== СИСТЕМА БАФФОВ/ДЕБАФФОВ ==========
async def get_buffs(user_id: int) -> list:
    cursor = buffs_col.find({'user_id': str(user_id)})
    return await cursor.to_list(length=100)

class BuffManageView(View):
    def __init__(self, target: discord.Member, admin: discord.Member):
        super().__init__(timeout=300)
        self.target = target
        self.admin = admin

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.admin.id

    async def build_content(self) -> str:
        buffs = await get_buffs(self.target.id)
        if not buffs:
            return "У игрока нет активных баффов/дебаффов."
        now = datetime.now().timestamp()
        lines = ["**Активные эффекты:**"]
        for b in buffs:
            expires = b.get('expires_at', 0)
            remaining = max(0, expires - now)
            hours = int(remaining // 3600)
            minutes = int((remaining % 3600) // 60)
            sign = '+' if b['type'] == 'buff' else '-'
            lines.append(
                f"{sign}{b['percent']}% — {b.get('name', '?')} "
                f"(осталось {hours}ч {minutes}м)"
            )
        return "\n".join(lines)

    @button(label="Добавить Эффект", style=discord.ButtonStyle.success)
    async def add_effect(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = BuffModal(self.target)
        await interaction.response.send_modal(modal)

    @button(label="Удалить Эффекты", style=discord.ButtonStyle.danger)
    async def delete_effects(self, interaction: discord.Interaction, button: discord.ui.Button):
        buffs = await get_buffs(self.target.id)
        if not buffs:
            await interaction.response.send_message("Нет активных эффектов для удаления.", ephemeral=True)
            return
        options = []
        for b in buffs:
            label = f"{'+' if b['type']=='buff' else '-'}{b['percent']}% — {b.get('name','?')}"[:100]
            options.append(discord.SelectOption(label=label, value=str(b['_id'])))
        select = Select(placeholder="Выберите эффект для удаления...", options=options)
        view = BuffDeleteSelectView(self.target, select, self)
        await interaction.response.send_message("Выберите эффект для удаления:", view=view, ephemeral=True)

class BuffModal(Modal, title="Новый эффект"):
    percent = TextInput(label="Проценты (от -100 до +100)", placeholder="15 или -10", max_length=5)
    reason = TextInput(label="Причина (название)", placeholder="Экономический кризис", max_length=100)
    hours = TextInput(label="Длительность (часы, макс 240)", placeholder="0.5 или 24", max_length=10)

    def __init__(self, target_member):
        super().__init__()
        self.target = target_member

    async def on_submit(self, interaction: discord.Interaction):
        try:
            pct = int(self.percent.value)
            if not (-100 <= pct <= 100):
                raise ValueError("Процент вне диапазона")
            hours = float(self.hours.value.replace(',', '.'))
            if hours <= 0 or hours > 240:
                raise ValueError("Некорректная длительность")
        except Exception:
            await interaction.response.send_message(
                "❌ Ошибка: Процент должен быть целым числом от -100 до +100, длительность — положительным числом до 240 часов.",
                ephemeral=True
            )
            return

        expires_at = datetime.now().timestamp() + hours * 3600
        btype = 'buff' if pct > 0 else 'debuff'
        data = {
            'user_id': str(self.target.id),
            'name': self.reason.value.strip() or "Без названия",
            'percent': abs(pct),
            'type': btype,
            'expires_at': expires_at
        }
        await buffs_col.insert_one(data)
        content = await BuffManageView(self.target, interaction.user).build_content()
        await interaction.response.send_message(f"✅ Эффект добавлен.\n{content}", ephemeral=True)

class BuffDeleteSelectView(View):
    def __init__(self, target: discord.Member, select: Select, parent_view: BuffManageView):
        super().__init__(timeout=60)
        self.target = target
        self.parent_view = parent_view
        select.callback = self.select_callback
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.parent_view.admin.id

    async def select_callback(self, interaction: discord.Interaction):
        buff_id = interaction.data['values'][0]
        try:
            obj_id = ObjectId(buff_id)
        except:
            await interaction.response.send_message("❌ Неверный ID эффекта.", ephemeral=True)
            return
        result = await buffs_col.delete_one({'_id': obj_id})
        if result.deleted_count:
            content = await self.parent_view.build_content()
            await interaction.response.send_message(f"✅ Эффект удалён.\n{content}", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Не удалось удалить эффект.", ephemeral=True)

# ========== UI ДЛЯ АЛЬЯНСОВ ==========
class AllyCreateStartView(View):
    def __init__(self, cog: "Alliances", user_id: int):
        super().__init__(timeout=120)
        self.cog = cog
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    @button(label="Создать альянс", style=discord.ButtonStyle.primary)
    async def create_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AllyCreateModal(self.cog, self.user_id, interaction.guild)
        await interaction.response.send_modal(modal)

class AllyCreateModal(Modal, title="Создание альянса"):
    name = TextInput(label="Название", placeholder="Великий Союз", max_length=80)
    description = TextInput(label="Описание", style=discord.TextStyle.long, placeholder="Могучий альянс...", max_length=500)
    ally_type = TextInput(label="Тип", placeholder="Военный/Эконом./Военно-Эконом.", max_length=30)

    def __init__(self, cog: "Alliances", user_id: int, guild: discord.Guild):
        super().__init__()
        self.cog = cog
        self.user_id = user_id
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        name = self.name.value.strip()
        desc = self.description.value.strip()
        atype = self.ally_type.value.strip()

        now = datetime.now().timestamp()
        alliance_data = {
            'owner_id': str(self.user_id),
            'name': name,
            'description': desc,
            'type': atype,
            'members': [],
            'treasury': 0,
            'tax_percent': 2,
            'image_url': None,
            'thread_id': None,
            'approved': False,
            'created_at': now,
            'expires_at': now + 86400,   # ← +24 часа
        }

        result = await alliances_col.insert_one(alliance_data)
        alliance_data['_id'] = result.inserted_id

        approval_channel = self.guild.get_channel(ALLIANCES_APPROVAL_CHANNEL_ID)
        if approval_channel:
            embed = discord.Embed(title="📥 Новая заявка на создание альянса", color=discord.Color.gold())
            embed.add_field(name="Название", value=name, inline=False)
            embed.add_field(name="Описание", value=desc, inline=False)
            embed.add_field(name="Тип", value=atype, inline=True)
            creator = self.guild.get_member(self.user_id)
            creator_name = creator.name if creator else f"User{self.user_id}"
            embed.add_field(name="Создатель", value=creator_name, inline=True)
            # ← ID заявки в футере
            embed.set_footer(text=f"ID заявки: {result.inserted_id} | Удалится через 24ч")
            view = AllyApprovalView(result.inserted_id, self.guild, self.user_id)
            msg = await approval_channel.send(embed=embed, view=view)
            # Сохраняем message_id
            await alliances_col.update_one(
                {'_id': result.inserted_id},
                {'$set': {'approval_message_id': msg.id, 'approval_channel_id': approval_channel.id}}
            )
            await interaction.response.send_message("✅ Заявка на создание альянса отправлена на одобрение!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Канал для заявок не найден.", ephemeral=True)

class AllyApprovalView(View):
    def __init__(self, alliance_id, guild: discord.Guild, creator_id: int):
        super().__init__(timeout=None)
        self.alliance_id = alliance_id
        self.guild = guild
        self.creator_id = creator_id

    @button(label="Одобрить", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        kurator_role = interaction.guild.get_role(KURATOR_T_ROLE_ID[0])  # ← add [0]
        if not interaction.user.guild_permissions.administrator and (not kurator_role or kurator_role not in interaction.user.roles):
            await interaction.response.send_message("❌ Только администраторы могут одобрять альянсы.", ephemeral=True)
            return
        try:
            thread_channel = self.guild.get_channel(ALLIANCES_THREADS_CHANNEL_ID)
            if thread_channel:
                thread = await thread_channel.create_thread(
                    name=f"🏛️ {alliance['name']}",
                    auto_archive_duration=1440,
                    reason=f"Альянс {alliance['name']}"
                )
                creator = self.guild.get_member(self.creator_id)
                if creator:
                    await thread.add_user(creator)
                await alliances_col.update_one(
                    {'_id': self.alliance_id},
                    {'$set': {'thread_id': thread.id, 'approved': True}}
                )
                await update_user(self.creator_id, {'alliance_id': self.alliance_id, 'alliance_role': 'owner'})
                embed = interaction.message.embeds[0]
                embed.color = discord.Color.green()
                embed.title = "✅ Альянс одобрен"
                embed.set_footer(text=f"Одобрено: {interaction.user.name}")
                await interaction.message.edit(embed=embed, view=None)
                try:
                    await creator.send(f"✅ Ваш альянс **{alliance['name']}** одобрен!\nВетка: {thread.mention}")
                except:
                    pass
                await interaction.response.send_message("✅ Альянс одобрен и создана ветка.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Канал для веток не найден.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка: {str(e)}", ephemeral=True)

    @button(label="Отклонить", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        mod_role = interaction.guild.get_role(KURATOR_T_ROLE_ID[0])  # ← add [0]
        if not interaction.user.guild_permissions.administrator and (not mod_role or mod_role not in interaction.user.roles):
            await interaction.response.send_message("❌ Только администраторы могут отклонять альянсы.", ephemeral=True)
            return
        modal = AllyRejectModal(self.alliance_id, self.guild, self.creator_id, interaction.message)
        await interaction.response.send_modal(modal)

class AllyRejectModal(Modal, title="Причина отклонения"):
    reason = TextInput(label="Причина", style=discord.TextStyle.long, placeholder="Не соответствует критериям...", max_length=500)

    def __init__(self, alliance_id, guild: discord.Guild, creator_id: int, message: discord.Message):
        super().__init__()
        self.alliance_id = alliance_id
        self.guild = guild
        self.creator_id = creator_id
        self.message = message

    async def on_submit(self, interaction: discord.Interaction):
        reason = self.reason.value.strip()
        await alliances_col.delete_one({'_id': self.alliance_id})
        embed = self.message.embeds[0]
        embed.color = discord.Color.red()
        embed.title = "❌ Альянс отклонен"
        embed.add_field(name="Причина", value=reason, inline=False)
        embed.set_footer(text=f"Отклонено: {interaction.user.name}")
        await self.message.edit(embed=embed, view=None)
        creator = self.guild.get_member(self.creator_id)
        if creator:
            try:
                await creator.send(f"❌ Ваша заявка на альянс отклонена.\n**Причина:** {reason}")
            except:
                pass
        await interaction.response.send_message("✅ Альянс отклонен.", ephemeral=True)

class AllyInfoView(View):
    def __init__(self, cog: "Alliances", alliance: dict, user_id: int, is_owner: bool, bot):
        super().__init__(timeout=180)
        self.cog = cog
        self.alliance = alliance
        self.user_id = user_id
        self.is_owner = is_owner
        self.bot = bot

        if is_owner:
            self.add_item(AllyRenameButton())
            self.add_item(AllyKickMemberButton())
            self.add_item(AllyFundButton())
            self.add_item(AllySetTaxButton())
            self.add_item(AllyWithdrawButton())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

class AllyRenameButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Переименовать", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        modal = AllyRenameModal(self.view.cog, self.view.alliance['_id'])
        await interaction.response.send_modal(modal)

class AllyKickMemberButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Выгнать из альянса", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction):
        members = self.view.alliance.get('members', [])
        if not members:
            await interaction.response.send_message("В альянсе нет участников.", ephemeral=True)
            return
        options = []
        for member_id in members[:25]:
            member_obj = self.view.bot.get_user(int(member_id))
            label = member_obj.name if member_obj else f"User{member_id}"
            options.append(discord.SelectOption(label=label, value=member_id))
        select = Select(placeholder="Выберите участника...", options=options)
        view = AllyKickSelectView(self.view.cog, self.view.alliance['_id'], select, self.view.bot)
        select.callback = view.select_callback
        view.add_item(select)
        await interaction.response.send_message("Выберите участника для удаления:", view=view, ephemeral=True)

class AllyKickSelectView(View):
    def __init__(self, cog, alliance_id, select: Select, bot):
        super().__init__(timeout=60)
        self.cog = cog
        self.alliance_id = alliance_id
        self.bot = bot
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        member_id = interaction.data['values'][0]
        alliance = await get_alliance(self.alliance_id)
        if alliance:
            members = alliance.get('members', [])
            if member_id in members:
                members.remove(member_id)
                await alliances_col.update_one({'_id': self.alliance_id}, {'$set': {'members': members}})
                await update_user(int(member_id), {'alliance_id': None, 'alliance_role': None})
                if alliance.get('thread_id'):
                    try:
                        thread = self.bot.get_channel(alliance['thread_id'])
                        if thread:
                            member_obj = self.bot.get_user(int(member_id))
                            if member_obj:
                                await thread.remove_user(member_obj)
                    except:
                        pass
                await interaction.response.send_message("✅ Участник удален из альянса.", ephemeral=True)

class AllyFundButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Пополнить казну", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        modal = AllyFundModal(self.view.cog, self.view.alliance['_id'], self.view.user_id)
        await interaction.response.send_modal(modal)

class AllyFundModal(Modal, title="Пополнить казну"):
    amount = TextInput(label="Сумма", placeholder="1000000", max_length=15)

    def __init__(self, cog, alliance_id, user_id):
        super().__init__()
        self.cog = cog
        self.alliance_id = alliance_id
        self.user_id = user_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.amount.value.replace(',', '').replace(' ', ''))
            if amount <= 0: raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ Сумма должна быть положительным числом.", ephemeral=True)
            return
        user = await get_user(self.user_id)
        if user['balance'] < amount:
            await interaction.response.send_message(f"❌ Недостаточно денег. Баланс: {user['balance']:,} 💵", ephemeral=True)
            return
        await alliances_col.update_one({'_id': self.alliance_id}, {'$inc': {'treasury': amount}})
        await update_user(self.user_id, {'balance': user['balance'] - amount})
        await interaction.response.send_message(f"✅ Вы пополнили казну на **{amount:,}** 💵", ephemeral=True)

class AllySetTaxButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Установить налог", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        modal = AllySetTaxModal(self.view.cog, self.view.alliance['_id'])
        await interaction.response.send_modal(modal)

class AllySetTaxModal(Modal, title="Установить налог альянса"):
    percent = TextInput(label="Процент налога (1-100)", placeholder="5", max_length=3)

    def __init__(self, cog, alliance_id):
        super().__init__()
        self.cog = cog
        self.alliance_id = alliance_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            percent = int(self.percent.value)
            if not (1 <= percent <= 100): raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ Процент должен быть от 1 до 100.", ephemeral=True)
            return
        await alliances_col.update_one({'_id': self.alliance_id}, {'$set': {'tax_percent': percent}})
        await interaction.response.send_message(f"✅ Налог установлен на **{percent}%**", ephemeral=True)

class AllyWithdrawButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Снять с казны", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction):
        modal = AllyWithdrawModal(self.view.cog, self.view.alliance['_id'], self.view.user_id)
        await interaction.response.send_modal(modal)

class AllyWithdrawModal(Modal, title="Снять деньги с казны"):
    amount = TextInput(label="Сумма", placeholder="1000000", max_length=15)

    def __init__(self, cog, alliance_id, user_id):
        super().__init__()
        self.cog = cog
        self.alliance_id = alliance_id
        self.user_id = user_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.amount.value.replace(',', '').replace(' ', ''))
            if amount <= 0: raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ Сумма должна быть положительным числом.", ephemeral=True)
            return
        alliance = await get_alliance(self.alliance_id)
        if alliance['treasury'] < amount:
            await interaction.response.send_message(f"❌ В казне недостаточно денег. Доступно: {alliance['treasury']:,} 💵", ephemeral=True)
            return
        await alliances_col.update_one({'_id': self.alliance_id}, {'$inc': {'treasury': -amount}})
        user = await get_user(self.user_id)
        await update_user(self.user_id, {'balance': user['balance'] + amount})
        await interaction.response.send_message(f"✅ Вы сняли **{amount:,}** 💵 с казны альянса", ephemeral=True)

class AllyRenameModal(Modal, title="Переименовать альянс"):
    new_name = TextInput(label="Новое название", placeholder="Новое имя альянса", max_length=80)

    def __init__(self, cog, alliance_id):
        super().__init__()
        self.cog = cog
        self.alliance_id = alliance_id

    async def on_submit(self, interaction: discord.Interaction):
        new_name = self.new_name.value.strip()
        alliance = await get_alliance(self.alliance_id)
        await alliances_col.update_one({'_id': self.alliance_id}, {'$set': {'name': new_name}})
        if alliance.get('thread_id'):
            try:
                thread = interaction.client.get_channel(alliance['thread_id'])
                if thread:
                    await thread.edit(name=f"🏛️ {new_name}")
            except:
                pass
        await interaction.response.send_message(f"✅ Альянс переименован в **{new_name}**", ephemeral=True)

class AllyInviteView(View):
    def __init__(self, cog: "Alliances", alliance_id, alliance_name: str, user_id: int):
        super().__init__(timeout=120)
        self.cog = cog
        self.alliance_id = alliance_id
        self.alliance_name = alliance_name
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    @button(label="Да", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = await get_user(self.user_id)
        if user.get('alliance_id'):
            await interaction.response.send_message("❌ Вы уже являетесь членом другого альянса.", ephemeral=True)
            return
        alliance = await get_alliance(self.alliance_id)
        if not alliance:
            await interaction.response.send_message("❌ Альянс не найден.", ephemeral=True)
            return
        members = alliance.get('members', [])
        members.append(str(self.user_id))
        await alliances_col.update_one({'_id': self.alliance_id}, {'$set': {'members': members}})
        await update_user(self.user_id, {'alliance_id': self.alliance_id, 'alliance_role': 'member'})
        if alliance.get('thread_id'):
            try:
                thread = interaction.client.get_channel(alliance['thread_id'])
                if thread:
                    await thread.add_user(interaction.user)
            except:
                pass
        embed = discord.Embed(title=f"✅ Вы вступили в альянс **{self.alliance_name}**!", color=discord.Color.green())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @button(label="Нет", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("❌ Вы отклонили приглашение в альянс.", ephemeral=True)

class AllyRemoveConfirmView(View):
    def __init__(self, cog: "Alliances", alliance_id):
        super().__init__(timeout=60)
        self.cog = cog
        self.alliance_id = alliance_id

    @button(label="Удалить", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.delete_alliance(self.alliance_id)
        await interaction.response.send_message("✅ Альянс удален.", ephemeral=True)

    @button(label="Отмена", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("❌ Удаление отменено.", ephemeral=True)

class AllyRemoveSelectView(View):
    def __init__(self, user_id: int, alliances: list, cog: "Alliances"):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.cog = cog
        for alliance in alliances:
            self.add_item(AllyRemoveSelectButton(alliance['_id'], alliance['name']))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

class AllyRemoveSelectButton(discord.ui.Button):
    def __init__(self, alliance_id, name):
        super().__init__(label=f"Удалить {name}", style=discord.ButtonStyle.danger)
        self.alliance_id = alliance_id

    async def callback(self, interaction: discord.Interaction):
        await self.view.cog.delete_alliance(self.alliance_id)
        await interaction.response.send_message("✅ Альянс удален.", ephemeral=True)

class AdminAllyDeleteView(View):
    def __init__(self, admin_id: int, alliances: list, bot):
        super().__init__(timeout=60)
        self.admin_id = admin_id
        self.bot = bot
        for alliance in alliances:
            label = alliance['name'][:80]
            self.add_item(AdminAllyDeleteButton(alliance['_id'], label))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.admin_id

class AdminAllyDeleteSelectView(View):
    def __init__(self, admin_id: int, select: Select, bot):
        super().__init__(timeout=60)
        self.admin_id = admin_id
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.admin_id

    async def select_callback(self, interaction: discord.Interaction):
        try:
            alliance_id = interaction.data['values'][0]
            if isinstance(alliance_id, str):
                alliance_id = ObjectId(alliance_id)
            alliances_cog = None
            for cog in interaction.client.cogs.values():
                if cog.__class__.__name__ == 'Alliances':
                    alliances_cog = cog
                    break
            if not alliances_cog:
                await interaction.response.send_message("❌ Ошибка: Cog не найден.", ephemeral=True)
                return
            result = await alliances_cog.delete_alliance(alliance_id)
            if result:
                await interaction.response.send_message("✅ Альянс удален.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Не удалось удалить альянс.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка: {str(e)}", ephemeral=True)

class AdminAllyDeleteButton(discord.ui.Button):
    def __init__(self, alliance_id, name):
        label = name[:76]
        super().__init__(label=f"❌ {label}", style=discord.ButtonStyle.danger)
        self.alliance_id = alliance_id

    async def callback(self, interaction: discord.Interaction):
        try:
            alliance_id = self.alliance_id
            if isinstance(alliance_id, str):
                alliance_id = ObjectId(alliance_id)
            alliances_cog = None
            for cog in interaction.client.cogs.values():
                if cog.__class__.__name__ == 'Alliances':
                    alliances_cog = cog
                    break
            if not alliances_cog:
                await interaction.response.send_message("❌ Ошибка: Cog не найден.", ephemeral=True)
                return
            result = await alliances_cog.delete_alliance(alliance_id)
            if result:
                await interaction.response.send_message("✅ Альянс удален.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Не удалось удалить альянс.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка: {str(e)}", ephemeral=True)

# ========== VIEW ДЛЯ ПРОДАЖИ ПРЕДМЕТОВ ==========
class TradeOfferView(View):
    def __init__(self, seller_id: int, buyer_id: int, item_name: str,
                 quantity: int, price: int, economy_cog):
        super().__init__(timeout=120)
        self.seller_id = seller_id
        self.buyer_id = buyer_id
        self.item_name = item_name
        self.quantity = quantity
        self.price = price
        self.economy_cog = economy_cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.buyer_id:
            await interaction.response.send_message("❌ Это предложение не для вас.", ephemeral=True)
            return False
        return True

    @button(label="Принять", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        buyer = await get_user(self.buyer_id)
        if buyer['balance'] < self.price:
            await interaction.response.send_message(
                f"❌ У вас недостаточно денег. Нужно **{self.price:,}** 💵, у вас **{buyer['balance']:,}** 💵.",
                ephemeral=True
            )
            return
        seller = await get_user(self.seller_id)
        success = await remove_item(self.seller_id, self.item_name, self.quantity)
        if not success:
            await interaction.response.send_message("❌ У продавца больше нет этого количества предмета.", ephemeral=True)
            return
        await update_user(self.seller_id, {'balance': seller['balance'] + self.price})
        await update_user(self.buyer_id, {'balance': buyer['balance'] - self.price})
        await add_item(self.buyer_id, self.item_name, self.quantity)
        embed = discord.Embed(
            title="✅ Сделка совершена",
            description=(
                f"Покупатель: <@{self.buyer_id}>\n"
                f"Продавец: <@{self.seller_id}>\n"
                f"Товар: **{self.item_name}** × {self.quantity}\n"
                f"Сумма: **{self.price:,}** 💵"
            ),
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=None)

    @button(label="Отклонить", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="❌ Предложение отклонено",
            description=f"Покупатель <@{self.buyer_id}> отказался от покупки.",
            color=discord.Color.red()
        )
        await interaction.response.edit_message(embed=embed, view=None)

    async def on_timeout(self):
        if hasattr(self, 'message') and self.message:
            embed = self.message.embeds[0]
            embed.color = discord.Color.light_grey()
            embed.set_footer(text="⏰ Время истекло, предложение больше не активно.")
            await self.message.edit(embed=embed, view=None)

class SellItemSelectView(View):
    def __init__(self, seller_id: int, matches: list, select: Select,
                 buyer: discord.Member, quantity: int, price: int, economy_cog):
        super().__init__(timeout=30)
        self.seller_id = seller_id
        self.matches = matches
        self.buyer = buyer
        self.quantity = quantity
        self.price = price
        self.economy_cog = economy_cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.seller_id:
            await interaction.response.send_message("❌ Это меню не для вас.", ephemeral=True)
            return False
        return True

    async def select_callback(self, interaction: discord.Interaction):
        selected_name = interaction.data['values'][0]
        item = next((it for it in self.matches if it['item_name'] == selected_name), None)
        if not item:
            await interaction.response.send_message("❌ Предмет не найден.", ephemeral=True)
            return
        if item['quantity'] < self.quantity:
            await interaction.response.send_message(
                f"❌ У вас только **{item['quantity']}** шт. предмета **{item['item_name']}**.",
                ephemeral=True
            )
            return
        embed = self.economy_cog._build_sell_offer_embed(
            discord.Object(id=self.seller_id), self.buyer,
            item['item_name'], self.quantity, self.price
        )
        view = TradeOfferView(self.seller_id, self.buyer.id, item['item_name'],
                              self.quantity, self.price, self.economy_cog)
        await interaction.channel.send(embed=embed, view=view)
        await interaction.message.delete()

class LicListPaginationView(View):
    def __init__(self, author_id, entries, per_page, total_pages, base_embed):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.entries = entries
        self.per_page = per_page
        self.total_pages = total_pages
        self.current_page = 0
        self.base_embed = base_embed
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.primary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await self.update_embed(interaction)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.primary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            await self.update_embed(interaction)

    async def update_embed(self, interaction: discord.Interaction):
        start = self.current_page * self.per_page
        end = start + self.per_page
        desc = "\n".join(self.entries[start:end])
        self.base_embed.description = desc
        self.base_embed.set_footer(text=f"Страница {self.current_page+1}/{self.total_pages}")
        await interaction.response.edit_message(embed=self.base_embed, view=self)

class TakeLicSelectView(View):
    def __init__(self, author_id, target_id, matches, select, shop_cog):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.target_id = target_id
        self.matches = matches
        self.shop_cog = shop_cog
        select.callback = self.select_callback
        self.add_item(select)

    async def interaction_check(self, interaction):
        return interaction.user.id == self.author_id

    async def select_callback(self, interaction):
        selected_name = interaction.data['values'][0]
        vehicle = next(v for v in self.matches if v['name'] == selected_name)
        result = await licenses_col.delete_one({
            'user_id': str(self.target_id),
            'vehicle_name': vehicle['name']
        })
        if result.deleted_count:
            await interaction.response.send_message(
                f"✅ Лицензия на **{vehicle['name']}** у <@{self.target_id}> забрана.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ У <@{self.target_id}> нет лицензии на **{vehicle['name']}**.",
                ephemeral=True
            )
        self.stop()
# ========== UI ДЛЯ РЕДАКТИРОВАНИЯ ТЕХНИКИ ==========

class EditVehicleSelectView(View):
    """Выбор техники, если найдено несколько совпадений"""
    def __init__(self, author_id: int, matches: list, select: Select, bot):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.matches = matches
        self.bot = bot
        select.callback = self.select_callback
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Это не ваша команда.", ephemeral=True)
            return False
        return True

    async def select_callback(self, interaction: discord.Interaction):
        selected_id = interaction.data['values'][0]
        vehicle = next((v for v in self.matches if str(v['_id']) == selected_id), None)
        if vehicle:
            shop_cog = self.bot.get_cog("🛒 Магазин")
            embed = await shop_cog.build_vehicle_info_embed(vehicle)
            view = EditVehicleView(self.author_id, vehicle['_id'], self.bot)
            await interaction.response.edit_message(embed=embed, view=view)


class EditVehicleView(View):
    def __init__(self, author_id: int, vehicle_id, bot):
        super().__init__(timeout=None)
        self.author_id = author_id
        self.vehicle_id = vehicle_id
        self.bot = bot
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Это не ваша команда.", ephemeral=True)
            return False
        return True

    @button(label="Изменить Название", style=discord.ButtonStyle.primary, row=0)
    async def edit_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        vehicle = await vehicles_col.find_one({'_id': self.vehicle_id})
        modal = EditVehicleNameModal(self.vehicle_id, vehicle.get('name', '') if vehicle else '')
        await interaction.response.send_modal(modal)

    @button(label="Изменить Стоимость", style=discord.ButtonStyle.primary, row=0)
    async def edit_price(self, interaction: discord.Interaction, button: discord.ui.Button):
        vehicle = await vehicles_col.find_one({'_id': self.vehicle_id})
        modal = EditVehiclePriceModal(self.vehicle_id, vehicle.get('price', 0) if vehicle else 0)
        await interaction.response.send_modal(modal)

    @button(label="Изменить Описание", style=discord.ButtonStyle.primary, row=0)
    async def edit_description(self, interaction: discord.Interaction, button: discord.ui.Button):
        vehicle = await vehicles_col.find_one({'_id': self.vehicle_id})
        modal = EditVehicleDescriptionModal(self.vehicle_id, vehicle.get('description', '') if vehicle else '')
        await interaction.response.send_modal(modal)

    @button(label="Изменить Страну Владельца", style=discord.ButtonStyle.secondary, row=1)
    async def edit_country(self, interaction: discord.Interaction, button: discord.ui.Button):
        users = await economy_col.find({'country': {'$ne': None}}).to_list(length=None)
        countries = sorted(set(u['country'] for u in users if u.get('country')))
        if not countries:
            await interaction.response.send_message("❌ Нет зарегистрированных стран.", ephemeral=True)
            return
        options = [discord.SelectOption(label=c[:100]) for c in countries[:25]]
        select = Select(placeholder="Выберите новую страну...", options=options)
        view = EditVehicleCountrySelectView(self.vehicle_id, select, self.author_id)
        await interaction.response.send_message("Выберите новую страну владельца:", view=view, ephemeral=True)

    @button(label="Изменить Изображение", style=discord.ButtonStyle.secondary, row=1)
    async def edit_image(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = EditVehicleImageModal(self.vehicle_id)
        await interaction.response.send_modal(modal)

    @button(label="Изменить Ссылку (Wiki)", style=discord.ButtonStyle.secondary, row=1)
    async def edit_wiki(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = EditVehicleWikiModal(self.vehicle_id)
        await interaction.response.send_modal(modal)

    @button(label="✅ Закончить Редактирование", style=discord.ButtonStyle.success, row=2)
    async def finish_edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        vehicle = await vehicles_col.find_one({'_id': self.vehicle_id})
        if not vehicle:
            await interaction.response.send_message("❌ Техника не найдена.", ephemeral=True)
            return
        shop_cog = self.bot.get_cog("🛒 Магазин")
        embed = await shop_cog.build_vehicle_info_embed(vehicle)
        embed.set_footer(text="✅ Редактирование завершено")
        await interaction.response.edit_message(embed=embed, view=None)


class EditVehicleCountrySelectView(View):
    def __init__(self, vehicle_id, select: Select, author_id: int):
        super().__init__(timeout=60)
        self.vehicle_id = vehicle_id
        self.author_id = author_id
        select.callback = self.select_callback
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Это не ваша команда.", ephemeral=True)
            return False
        return True

    async def select_callback(self, interaction: discord.Interaction):
        country = interaction.data['values'][0]
        await vehicles_col.update_one({'_id': self.vehicle_id}, {'$set': {'country': country}})
        await interaction.response.send_message(
            f"✅ Страна владельца изменена на **{country}**", ephemeral=True
        )


# ===== Модалки для EditVehicleView =====

class EditVehicleNameModal(Modal, title="Изменить Название"):
    new_name = TextInput(label="Новое название", placeholder="Т-90М", max_length=80)

    def __init__(self, vehicle_id, current_name: str = ''):
        super().__init__()
        self.vehicle_id = vehicle_id
        if current_name:
            self.new_name.default = current_name

    async def on_submit(self, interaction: discord.Interaction):
        name = self.new_name.value.strip()
        old_vehicle = await vehicles_col.find_one({'_id': self.vehicle_id})
        if not old_vehicle:
            await interaction.response.send_message("❌ Техника не найдена.", ephemeral=True)
            return
        old_name = old_vehicle['name']
        await vehicles_col.update_one({'_id': self.vehicle_id}, {'$set': {'name': name}})
        # Обновляем название во всех связанных коллекциях
        await licenses_col.update_many({'vehicle_name': old_name}, {'$set': {'vehicle_name': name}})
        await inventory_col.update_many({'item_name': old_name}, {'$set': {'item_name': name}})
        await interaction.response.send_message(
            f"✅ Название изменено: **{old_name}** → **{name}**\n"
            f"Инвентари и лицензии обновлены автоматически.", ephemeral=True
        )


class EditVehiclePriceModal(Modal, title="Изменить Стоимость"):
    new_price = TextInput(label="Новая стоимость (целое число)", placeholder="6000000", max_length=20)

    def __init__(self, vehicle_id, current_price: int = 0):
        super().__init__()
        self.vehicle_id = vehicle_id
        if current_price:
            self.new_price.default = str(current_price)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price = int(self.new_price.value.replace(',', '').replace(' ', ''))
            if price <= 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ Стоимость должна быть положительным целым числом.", ephemeral=True
            )
            return
        vehicle = await vehicles_col.find_one({'_id': self.vehicle_id})
        old_price = vehicle['price'] if vehicle else 0
        await vehicles_col.update_one({'_id': self.vehicle_id}, {'$set': {'price': price}})
        await interaction.response.send_message(
            f"✅ Стоимость изменена: **{old_price:,}** → **{price:,}** 💵", ephemeral=True
        )


class EditVehicleDescriptionModal(Modal, title="Изменить Описание"):
    new_desc = TextInput(
        label="Новое описание",
        style=discord.TextStyle.long,
        placeholder="Описание техники...",
        max_length=1000
    )

    def __init__(self, vehicle_id, current_desc: str = ''):
        super().__init__()
        self.vehicle_id = vehicle_id
        if current_desc:
            self.new_desc.default = current_desc[:1000]

    async def on_submit(self, interaction: discord.Interaction):
        desc = self.new_desc.value.strip()
        await vehicles_col.update_one({'_id': self.vehicle_id}, {'$set': {'description': desc}})
        await interaction.response.send_message("✅ Описание успешно обновлено.", ephemeral=True)


class EditVehicleImageModal(Modal, title="Изменить Изображение"):
    image_url = TextInput(
        label="Ссылка на изображение (http/https)",
        placeholder="https://i.imgur.com/example.png",
        max_length=500
    )

    def __init__(self, vehicle_id):
        super().__init__()
        self.vehicle_id = vehicle_id

    async def on_submit(self, interaction: discord.Interaction):
        url = self.image_url.value.strip()
        valid, err = validate_url(url)
        if not valid:
            await interaction.response.send_message(err, ephemeral=True)
            return
        await vehicles_col.update_one({'_id': self.vehicle_id}, {'$set': {'image_url': url}})
        await interaction.response.send_message("✅ Изображение успешно обновлено.", ephemeral=True)


class EditVehicleWikiModal(Modal, title="Изменить Ссылку на Википедию"):
    wiki_url = TextInput(
        label="Ссылка на Википедию (http/https)",
        placeholder="https://ru.wikipedia.org/wiki/Т-90",
        max_length=500
    )

    def __init__(self, vehicle_id):
        super().__init__()
        self.vehicle_id = vehicle_id

    async def on_submit(self, interaction: discord.Interaction):
        url = self.wiki_url.value.strip()
        valid, err = validate_url(url)
        if not valid:
            await interaction.response.send_message(err, ephemeral=True)
            return
        await vehicles_col.update_one({'_id': self.vehicle_id}, {'$set': {'wiki_link': url}})
        await interaction.response.send_message("✅ Ссылка на Википедию успешно обновлена.", ephemeral=True)
# ========== UI ДЛЯ КОМАНД !yes / !no ==========

class RejectModalTriggerView(View):
    """Кнопка-триггер для открытия модалки отклонения через !no"""
    def __init__(self, modal: "RejectApplicationModal", author_id: int):
        super().__init__(timeout=60)
        self.modal = modal
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Это не ваша команда.", ephemeral=True)
            return False
        return True

    @button(label="✏️ Указать причину отклонения", style=discord.ButtonStyle.danger)
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(self.modal)


class RejectApplicationModal(Modal, title="Причина отклонения"):
    reason = TextInput(
        label="Причина отклонения",
        style=discord.TextStyle.long,
        placeholder="Укажите причину...",
        max_length=500
    )

    def __init__(self, obj_id: ObjectId, app_type: str, app_name: str, admin_cog):
        super().__init__()
        self.obj_id = obj_id
        self.app_type = app_type   # 'vehicle' или 'alliance'
        self.app_name = app_name
        self.admin_cog = admin_cog

    async def on_submit(self, interaction: discord.Interaction):
        reason_text = self.reason.value.strip()

        if self.app_type == 'vehicle':
            shop_cog = self.admin_cog.bot.get_cog("🛒 Магазин")
            await shop_cog.reject_vehicle(self.obj_id, reason_text, interaction.user)
            doc = await vehicles_col.find_one({'_id': self.obj_id})
            if doc:
                await self.admin_cog._update_application_embed(doc, approved=False, moderator=interaction.user, reason=reason_text)
            await interaction.response.send_message(
                f"❌ Заявка на технику **{self.app_name}** отклонена.\nПричина: {reason_text}", ephemeral=True
            )

        elif self.app_type == 'alliance':
            doc = await alliances_col.find_one({'_id': self.obj_id})
            if doc:
                await self.admin_cog._update_application_embed(doc, approved=False, moderator=interaction.user, reason=reason_text, is_alliance=True)
            await alliances_col.delete_one({'_id': self.obj_id})
            creator_id = int(doc['owner_id']) if doc else None
            if creator_id:
                try:
                    creator = self.admin_cog.bot.get_user(creator_id)
                    if not creator:
                        creator = await self.admin_cog.bot.fetch_user(creator_id)
                    if creator:
                        await creator.send(
                            f"❌ Ваша заявка на альянс **{self.app_name}** отклонена.\n**Причина:** {reason_text}"
                        )
                except Exception:
                    pass
            await interaction.response.send_message(
                f"❌ Альянс **{self.app_name}** отклонён.\nПричина: {reason_text}", ephemeral=True
            )
# ===== ЗАГРУЗКА COG И ЗАПУСК =====
# ===== ФОНОВАЯ ЗАДАЧА АВТО-УДАЛЕНИЯ ЗАЯВОК =====
@tasks.loop(minutes=10)
async def auto_expire_applications():
    """Удаляет заявки старше 24 часов и уведомляет игроков"""
    now = datetime.now().timestamp()

    # Просроченные заявки на технику
    expired_vehicles = await vehicles_col.find({
        'approved': False,
        'expires_at': {'$lt': now}
    }).to_list(length=None)

    for vehicle in expired_vehicles:
        submitter_id = vehicle.get('submitter_id')
        # Редактируем embed в канале одобрения
        try:
            channel_id = vehicle.get('approval_channel_id')
            message_id = vehicle.get('approval_message_id')
            if channel_id and message_id:
                channel = bot.get_channel(channel_id)
                if channel:
                    msg = await channel.fetch_message(message_id)
                    if msg and msg.embeds:
                        embed = msg.embeds[0]
                        embed.color = discord.Color.dark_grey()
                        embed.title = "⏰ Заявка истекла (авто-удалена)"
                        embed.set_footer(text=f"Удалена автоматически через 24ч | ID: {vehicle['_id']}")
                        await msg.edit(embed=embed, view=None)
        except Exception:
            pass
        # Уведомляем игрока
        if submitter_id:
            try:
                user = bot.get_user(int(submitter_id))
                if not user:
                    user = await bot.fetch_user(int(submitter_id))
                if user:
                    await user.send(
                        f"⏰ Ваша заявка на технику **{vehicle['name']}** была автоматически удалена "
                        f"по истечению 24 часов. Если нужно — подайте новую заявку."
                    )
            except Exception:
                pass
        await vehicles_col.delete_one({'_id': vehicle['_id']})

    # Просроченные заявки на альянсы
    expired_alliances = await alliances_col.find({
        'approved': False,
        'expires_at': {'$lt': now}
    }).to_list(length=None)

    for alliance in expired_alliances:
        owner_id = alliance.get('owner_id')
        try:
            channel_id = alliance.get('approval_channel_id')
            message_id = alliance.get('approval_message_id')
            if channel_id and message_id:
                channel = bot.get_channel(channel_id)
                if channel:
                    msg = await channel.fetch_message(message_id)
                    if msg and msg.embeds:
                        embed = msg.embeds[0]
                        embed.color = discord.Color.dark_grey()
                        embed.title = "⏰ Заявка на альянс истекла (авто-удалена)"
                        embed.set_footer(text=f"Удалена автоматически через 24ч | ID: {alliance['_id']}")
                        await msg.edit(embed=embed, view=None)
        except Exception:
            pass
        if owner_id:
            try:
                user = bot.get_user(int(owner_id))
                if not user:
                    user = await bot.fetch_user(int(owner_id))
                if user:
                    await user.send(
                        f"⏰ Ваша заявка на альянс **{alliance['name']}** была автоматически удалена "
                        f"по истечению 24 часов."
                    )
            except Exception:
                pass
        await alliances_col.delete_one({'_id': alliance['_id']})
@tasks.loop(minutes=30)
async def auto_remove_temp_roles():
    """Снимает роль TEMP_ROLE_ID у игроков через 3 дня после выдачи"""
    now = datetime.now().timestamp()
    expired = await role_timers_col.find({'expires_at': {'$lt': now}}).to_list(length=None)

    for entry in expired:
        user_id = entry.get('user_id')
        role_id = entry.get('role_id')
        for guild in bot.guilds:
            member = guild.get_member(int(user_id))
            if member:
                role = guild.get_role(role_id)
                if role and role in member.roles:
                    try:
                        await member.remove_roles(role, reason="Автоматическое снятие роли через 3 дня")
                    except Exception:
                        pass
        await role_timers_col.delete_one({'_id': entry['_id']})

@auto_remove_temp_roles.before_loop
async def before_auto_remove_temp_roles():
    await bot.wait_until_ready()

@auto_expire_applications.before_loop
async def before_auto_expire():
    await bot.wait_until_ready()


# ===== ЗАГРУЗКА COG И ЗАПУСК =====
@bot.event
async def setup_hook():
    await bot.add_cog(General(bot))
    await bot.add_cog(Economy(bot))
    await bot.add_cog(Budget(bot))
    await bot.add_cog(Admin(bot))
    await bot.add_cog(Shop(bot))
    await bot.add_cog(Alliances(bot))
    auto_expire_applications.start() # ← запускаем фоновую задачу
    auto_remove_temp_roles.start()   


if __name__ == '__main__':
    bot.run(TOKEN) 
