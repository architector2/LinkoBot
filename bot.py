import discord
from discord.ext import commands
from discord.ui import Select, View, Modal, TextInput, button
import os
import re
from dotenv import load_dotenv
from datetime import datetime, timedelta
import motor.motor_asyncio
from bson import ObjectId

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
daily_mobilization_col = db['daily_mobilization']
buffs_col = db['buffs']
alliances_col = db['alliances']
alliance_invites_col = db['alliance_invites']

# ID ролей и каналов
REGISTERED_ROLE_ID = 1501510805169115176
UNREGISTERED_ROLE_ID = 1141339127367880764
COUNTRY_ROLE_ID = 1141340397558321313
ALLIANCES_THREADS_CHANNEL_ID = 1502968035235987487
ALLIANCES_APPROVAL_CHANNEL_ID = 1502009375324110968

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
            'mobilization_percent': 2.5,
            'mobilization_used': False,
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
        if 'unhappiness' not in user:
            update['unhappiness'] = 0.0
        if 'last_unhappiness_update' not in user:
            update['last_unhappiness_update'] = 0
        if 'country' not in user:
            update['country'] = None
        if 'mobilization_percent' not in user:
            update['mobilization_percent'] = 2.5
        if 'mobilization_used' not in user:
            update['mobilization_used'] = False
        if 'alliance_id' not in user:
            update['alliance_id'] = None
        if 'alliance_role' not in user:
            update['alliance_role'] = None
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

def is_registered():
    async def predicate(ctx):
        role = ctx.guild.get_role(REGISTERED_ROLE_ID)
        if role is None or role not in ctx.author.roles:
            await ctx.send("❌ Ты не зарегистрирован! Открой тикет для регистрации.")
            return False
        return True
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
    today = datetime.now().strftime('%Y-%m-%d')
    doc = await daily_submissions_col.find_one({'user_id': str(user_id)})
    if not doc or doc.get('date_str') != today:
        await daily_submissions_col.update_one(
            {'user_id': str(user_id)},
            {'$set': {'date_str': today, 'count': 5, 'first_submission_time': 0, 'last_submission_time': 0}},
            upsert=True
        )
        return True, ''
    if doc['count'] <= 0:
        t0 = doc.get('first_submission_time', 0)
        if t0:
            reset_at = datetime.fromtimestamp(t0) + timedelta(hours=24)
            remaining = reset_at - datetime.now()
            if remaining.total_seconds() > 0:
                hours, rem = divmod(remaining.seconds, 3600)
                mins = rem // 60
                return False, f"❌ Лимит заявок исчерпан. Сброс через {hours}ч {mins}мин."
        return False, "❌ Лимит заявок исчерпан."
    last_time = doc.get('last_submission_time', 0)
    if last_time:
        elapsed = datetime.now().timestamp() - last_time
        if elapsed < 3600:
            remaining = int(3600 - elapsed)
            mins = remaining // 60
            secs = remaining % 60
            return False, f"⏰ Кулдаун! Подождите ещё {mins}м {secs}с перед следующей заявкой."
    return True, ''

async def record_submission(user_id: int):
    today = datetime.now().strftime('%Y-%m-%d')
    doc = await daily_submissions_col.find_one({'user_id': str(user_id)})
    if not doc or doc.get('date_str') != today:
        await daily_submissions_col.update_one(
            {'user_id': str(user_id)},
            {'$set': {'date_str': today, 'count': 4, 'first_submission_time': datetime.now().timestamp(), 'last_submission_time': datetime.now().timestamp()}},
            upsert=True
        )
    else:
        new_count = max(doc['count'] - 1, 0)
        update = {'count': new_count, 'last_submission_time': datetime.now().timestamp()}
        if doc.get('first_submission_time', 0) == 0:
            update['first_submission_time'] = datetime.now().timestamp()
        await daily_submissions_col.update_one({'user_id': str(user_id)}, {'$set': update})

async def get_daily_submission_info(user_id: int) -> str:
    today = datetime.now().strftime('%Y-%m-%d')
    doc = await daily_submissions_col.find_one({'user_id': str(user_id)})
    if not doc or doc.get('date_str') != today:
        return "5/5"
    return f"{doc['count']}/5"

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
def get_vehicle_maintenance_cost_per_hour(gdp: int) -> int:
    if gdp < 200_000_000_000:
        return 500_000
    elif gdp <= 500_000_000_000:
        return 1_000_000
    elif gdp <= 1_000_000_000_000:
        return 2_500_000
    else:
        return 5_000_000

SOLDIER_MAINTENANCE_PER_HOUR = 100

# ===== СОБЫТИЯ =====
@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user.name} запущен')
    print(f'Bot ID: {bot.user.id}')
    print(f'✅ Подключение к MongoDB Atlas установлено')
    await bot.change_presence(activity=discord.Game(name="Linko VPI"))

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    await bot.process_commands(message)

USAGE_HINTS = {
    'collect': '❌ Команда `!collect` не требует аргументов.\nПросто напиши `!collect` для сбора дохода.',
    'reforms': '❌ Использование: `!reforms <сумма> <ссылка на сообщение из канала реформ>`\nПример: `!reforms 1000000 https://discord.com/channels/...`',
    'pay': '❌ Использование: `!pay @игрок <сумма>`\nПример: `!pay @Undervud 5000`',
    'cab': '❌ Использование: `!cab` или `!cab @игрок`',
    'budjet': '❌ Использование: `!budjet <категория> <процент>`\nКатегории: `социальные-расходы`, `образование`, `здравоохранение`\nПример: `!budjet образование 10`',
    'budjet-info': '❌ Использование: `!budjet-info` или `!budjet-info @игрок`',
    'shop': '❌ Команда `!shop` не требует аргументов.\nПросто напиши `!shop`.',
    'add-vehicle': '❌ Команда `!add-vehicle` не требует аргументов.\nПросто напиши `!add-vehicle` и следуй инструкциям.',
    'give-lic': '❌ Использование: `!give-lic @игрок <название техники или all>`\nПример: `!give-lic @Undervud Т-90` или `!give-lic @Undervud all`',
    'buy': '❌ Использование: `!buy <количество> <название техники>`\nПример: `!buy 3 Т-90`\nПри частичном совпадении будет предложен выбор.',
    'inv': '❌ Команда `!inv` не требует аргументов.\nПросто напиши `!inv` — инвентарь придёт в ЛС.',
    'invsee': '❌ Использование: `!invsee @игрок`',
    'take-item': '❌ Использование: `!take-item @игрок <количество> <название или часть названия>`\nПример: `!take-item @Undervud 100 Т-`',
    'give-item': '❌ Использование: `!give-item @игрок <количество> <название>`\nПример: `!give-item @Undervud 5 Т-90`',
    'use': '❌ Использование: `!use <количество> <название предмета>`\nПример: `!use 50 Т-90`',
    'give-vvp': '❌ Использование: `!give-vvp @игрок <сумма>`\nПример: `!give-vvp @Undervud 1000000000`',
    'naselprocent': '❌ Использование: `!naselprocent @игрок <1-100>`\nПример: `!naselprocent @Undervud 3`',
    'nasel-redakt': '❌ Использование: `!nasel-redakt @игрок <число>`\nПример: `!nasel-redakt @Undervud 1000000` или `!nasel-redakt @Undervud -500000`',
    'happines': '❌ Использование: `!happines @игрок <процент>`\nПример: `!happines @Undervud 80`',
    'reg': '❌ Использование: `!reg @игрок <название страны>`\nПример: `!reg @Undervud Франция`',
    'unreg': '❌ Использование: `!unreg @игрок`',
    'delete-vehicle': '❌ Использование: `!delete-vehicle <название или часть названия>`\nПример: `!delete-vehicle Т-90`',
    'players-country': '❌ Команда `!players-country` не требует аргументов.',
    'add-money': '❌ Использование: `!add-money @игрок <сумма>`\nПример: `!add-money @Undervud 1000000`',
    'top': '❌ Команда `!top` не требует аргументов.',
    'vehicle-info': '❌ Использование: `!vehicle-info <название/часть названия>`\nПример: `!vehicle-info Т-90`',
    'iso': '❌ Использование: `!iso <название/часть названия> <ссылка на изображение>`\nПример: `!iso Т-90 https://i.imgur.com/abc.png` (доступно только владельцу техники)',
    'mobilization': '❌ Команда `!mobilization` не требует аргументов. Открывает панель мобилизации.',
    'remove-sol': '❌ Использование: `!remove-sol @игрок <число>`\nПример: `!remove-sol @Undervud 5000`',
    'add-sol': '❌ Использование: `!add-sol @игрок <число>`\nПример: `!add-sol @Undervud 10000`',
    'priziv-redakt': '❌ Использование: `!priziv-redakt @игрок <число от 2.5 до 25>`',
    'abb-baff': '❌ Использование: `!abb-baff @игрок`',
    'modernization': '❌ Команда `!modernization` не требует аргументов.',
    'ally-create': '❌ Команда `!ally-create` не требует аргументов. Просто напиши `!ally-create`.',
    'ally': '❌ Команда `!ally` не требует аргументов.',
    'ally-invite': '❌ Использование: `!ally-invite @игрок`\nПример: `!ally-invite @Undervud`',
    'ally-kick': '❌ Использование: `!ally-kick @игрок`',
    'ally-remove': '❌ Команда `!ally-remove` не требует аргументов.',
    'ally-delete': '❌ Команда `!ally-delete` не требует аргументов (админ).',
    'iso-ally': '❌ Использование: `!iso-ally <название альянса> <ссылка на изображение>`',
    'edit-buy': '❌ Использование: `!edit-buy <название/часть названия> <новая стоимость>`\nПример: `!edit-buy Т-90 6000000`',
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
        print(f"Ошибка: {error}")

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

    @commands.command(name='ping')
    async def ping(self, ctx):
        """Проверить задержку бота"""
        await ctx.send(f'Pong! 🏓 Задержка: {round(self.bot.latency * 1000)}мс')

    @commands.command(name='info')
    async def info(self, ctx):
        """Информация о боте"""
        embed = discord.Embed(title="LinkoBot", description="Бот для сервера Военная-политическая-игра", color=discord.Color.blue())
        embed.add_field(name="Версия", value="3.0.0", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name='players-country')
    @is_registered()
    async def players_country(self, ctx):
        """Показать список игроков по государствам и других"""
        view = PlayersCountryView(ctx.guild)
        embed = await view.build_embed('states')
        view.message = await ctx.send(embed=embed, view=view)

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
        buffs = await buffs_col.find({'user_id': str(ctx.author.id)}).to_list(length=100)
        total_buff_percent = 0
        for b in buffs:
            if b['type'] == 'buff':
                total_buff_percent += b['percent']
            else:  # debuff
                total_buff_percent -= b['percent']
        if total_buff_percent != 0:
            gross_income = int(gross_income * (1 + total_buff_percent / 100))

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
        inventory = await get_inventory(ctx.author.id)
        vehicle_cost_per_hour = get_vehicle_maintenance_cost_per_hour(user['gdp'])
        total_vehicle_maintenance = 0
        total_soldier_maintenance = 0
        total_units = 0
        total_soldiers = 0

        for item in inventory:
            name = item['item_name']
            qty = item['quantity']
            if name == "Обученный Солдат":
                total_soldiers += qty
                total_soldier_maintenance += qty * SOLDIER_MAINTENANCE_PER_HOUR
            else:
                total_units += qty
                total_vehicle_maintenance += qty * vehicle_cost_per_hour

        vehicle_cost = int(total_vehicle_maintenance * hours_passed)
        soldier_cost = int(total_soldier_maintenance * hours_passed)

        # ===== НАЛОГ АЛЬЯНСА =====
        alliance_tax = 0
        alliance = await get_user_alliance(ctx.author.id)
        if alliance:
            alliance_tax_percent = alliance.get('tax_percent', 2)
            alliance_tax = int(gross_income * alliance_tax_percent / 100)
            # Добавляем в казну альянса
            await alliances_col.update_one(
                {'_id': alliance['_id']},
                {'$inc': {'treasury': alliance_tax}}
            )

        net_income = gross_income - total_budget_deduct - vehicle_cost - soldier_cost - alliance_tax
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
        elif population > 0 and user.get('last_pop_update', 0) == 0:
            update_data['last_pop_update'] = current_time

        await update_user(ctx.author.id, update_data)

        embed = discord.Embed(
            title="💵 Коллект",
            description=f"Ты собрал доход за **{hours_passed:.1f}** ч.",
            color=discord.Color.green()
        )
        embed.add_field(name="ВВП", value=f"{user['gdp']:,} 💵", inline=True)
        embed.add_field(name="Доход в час", value=f"{income_per_hour:,.0f} 💵", inline=True)
        embed.add_field(name="Валовый доход", value=f"{gross_income:,} 💵", inline=False)

        if total_buff_percent != 0:
            embed.add_field(name="🔥 Баффы/Дебаффы", value=f"{'+' if total_buff_percent > 0 else ''}{total_buff_percent}%", inline=False)

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
                name="🛠️ Содержание техники",
                value=f"Кол-во единиц: {total_units:,}\nРасход: -{vehicle_cost:,} 💵",
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

        embed.add_field(name="📌 Чистая прибыль", value=f"+{net_income:,} 💵", inline=False)
        embed.add_field(name="💰 Новый баланс", value=f"{new_balance:,} 💵", inline=False)

        if population > 0:
            if pop_gained > 0:
                embed.add_field(name="👥 Прирост населения", value=f"+{pop_gained:,} чел.", inline=True)
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

        pattern = r"https://discord\.com/channels/\d+/(\d+)/(\d+)"
        match = re.match(pattern, message_link)
        if not match:
            await ctx.send("❌ Неверный формат ссылки. Ожидается ссылка на сообщение Discord.")
            return
        channel_id = match.group(1)
        message_id = match.group(2)
        if channel_id != "1363585142593032412":
            await ctx.send("❌ Ссылка должна вести в канал реформ (<#1363585142593032412>).")
            return

        # Проверяем, что сообщение принадлежит автору команды
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

    @commands.command(name='top')
    @is_registered()
    async def top(self, ctx):
        """Топ-10 по ВВП, населению или балансу"""
        view = TopSelectView(ctx)
        embed = await view.build_embed('balance')
        view.message = await ctx.send(embed=embed, view=view)

    @commands.command(name='cab')
    @is_registered()
    async def cab(self, ctx, member: discord.Member = None):
        """Статистика игрока — ВВП, баланс, население, недовольство, баффы"""
        if member is None:
            member = ctx.author

        user = await get_user(member.id)
        unhappiness = await update_unhappiness(member.id, user)

        income_per_hour = user['gdp'] / 48 if user['gdp'] > 0 else 0

        current_time = datetime.now().timestamp()
        last_collect = user.get('last_collect', 0)
        if last_collect > 0:
            hours_since = (current_time - last_collect) / 3600
            hours_since = min(hours_since, 12)
            pending = int(income_per_hour * hours_since)
        else:
            pending = 0

        yearly_pct = user.get('pop_growth_yearly', 2.0)

        country = user.get('country')
        if country:
            display_name = f"{country} ({member.name})"
        else:
            display_name = member.name

        embed = discord.Embed(
            title=f"📊 Статистика {display_name}",
            color=discord.Color.blurple()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="💰 Баланс", value=f"{user['balance']:,} 💵", inline=True)
        embed.add_field(name="📈 ВВП", value=f"{user['gdp']:,} 💵", inline=True)
        embed.add_field(name="⏱️ Доход в час", value=f"{income_per_hour:,.0f} 💵", inline=True)
        embed.add_field(name="📦 Ожидает коллекта", value=f"{pending:,} 💵", inline=True)

        population = user.get('population', 0)
        if population > 0:
            pop_block = (
                f"👥 **{population:,} чел.**\n"
                f"📊 Рост Населения в Год: **{yearly_pct:.2f}%**"
            )
        else:
            pop_block = "👥 Население не выдано"
        embed.add_field(name="🌍 Население", value=pop_block, inline=False)

        unhappiness_speed = calculate_unhappiness_speed(user)
        speed_str = f"{unhappiness_speed:+.2f}%/ч" if unhappiness_speed else "0%/ч"
        unhappiness_block = f"😡 **{unhappiness:.2f}%**\n({speed_str})"
        embed.add_field(name="🗳️ Недовольство", value=unhappiness_block, inline=False)

        # Баффы/дебаффы
        buffs = await get_buffs(member.id)
        if buffs:
            total_buff = sum(b['percent'] if b['type']=='buff' else -b['percent'] for b in buffs)
            buff_str = f"{'+' if total_buff > 0 else ''}{total_buff}% к доходу"
            embed.add_field(name="🔥 Баффы/Дебаффы", value=buff_str, inline=False)

        # Альянс
        alliance = await get_user_alliance(member.id)
        if alliance:
            embed.add_field(name="🏛️ Альянс", value=f"**{alliance['name']}**\nНалог: {alliance.get('tax_percent', 2)}%", inline=False)

        await ctx.send(embed=embed)

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
    @commands.has_permissions(administrator=True)
    async def help_admin(self, ctx):
        """Показать все админ-команды"""
        embed = discord.Embed(title="👑 Админ-команды", description="Доступны только администраторам. Префикс: `!`", color=discord.Color.red())
        cmds = self.get_commands()
        for cmd in cmds:
            embed.add_field(name=f"`!{cmd.name}`", value=cmd.help or "Нет описания", inline=False)
        embed.set_footer(text=f"Запросил: {ctx.author.name}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name='give-vvp')
    @commands.has_permissions(administrator=True)
    async def give_gdp(self, ctx, member: discord.Member, amount: int):
        """Выдать ВВП игроку"""
        if amount <= 0:
            await ctx.send("❌ Сумма должна быть больше 0!"); return
        user = await get_user(member.id)
        new_gdp = user['gdp'] + amount
        await update_user(member.id, {'gdp': new_gdp})
        embed = discord.Embed(title="📈 ВВП выдан", description=f"{member.mention} получил **{amount:,}** ВВП", color=discord.Color.green())
        embed.add_field(name="Новый ВВП", value=f"{new_gdp:,} 💵", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name='naselprocent')
    @commands.has_permissions(administrator=True)
    async def nasel_procent(self, ctx, member: discord.Member, percent: float):
        """Установить годовой % прироста населения игроку (1–100)"""
        if percent < 1 or percent > 100:
            await ctx.send("❌ Процент должен быть от **1** до **100**!"); return
        await update_user(member.id, {'pop_growth_yearly': percent})
        embed = discord.Embed(title="📊 Прирост населения обновлён", description=f"{member.mention} — новый годовой прирост: **{percent:.2f}%**", color=discord.Color.blue())
        hourly = percent / 48
        embed.add_field(name="Прирост в час", value=f"{hourly:.4f}% (1 игровой год = 48 ч)", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name='nasel-redakt')
    @commands.has_permissions(administrator=True)
    async def nasel_redakt(self, ctx, member: discord.Member, amount: int):
        """Изменить количество населения у игрока"""
        user = await get_user(member.id)
        old_population = user.get('population', 0)
        new_population = old_population + amount
        if new_population < 0:
            await ctx.send(f"❌ Нельзя уйти в минус! Текущее население: **{old_population:,}** чел.")
            return
        current_time = datetime.now().timestamp()
        update_data = {'population': new_population}
        if old_population == 0 and new_population > 0:
            update_data['last_pop_update'] = current_time
        if new_population == 0:
            update_data['last_pop_update'] = 0
        await update_user(member.id, update_data)
        action = "получил" if amount >= 0 else "потерял"
        sign = "+" if amount >= 0 else ""
        color = discord.Color.green() if amount >= 0 else discord.Color.red()
        embed = discord.Embed(title="👥 Население изменено", description=f"{member.mention} {action} **{sign}{amount:,}** чел.", color=color)
        embed.add_field(name="Было", value=f"{old_population:,} чел.", inline=True)
        embed.add_field(name="Стало", value=f"{new_population:,} чел.", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name='happines')
    @commands.has_permissions(administrator=True)
    async def happines(self, ctx, member: discord.Member, percent: float):
        """Установить недовольство игроку (0-100)"""
        if percent < 0 or percent > 100:
            await ctx.send("❌ Процент недовольства должен быть от 0 до 100."); return
        current_time = datetime.now().timestamp()
        await update_user(member.id, {
            'unhappiness': percent,
            'last_unhappiness_update': current_time
        })
        embed = discord.Embed(title="😡 Недовольство изменено", description=f"{member.mention} теперь имеет недовольство **{percent:.1f}%**", color=discord.Color.red())
        await ctx.send(embed=embed)

    @commands.command(name='reg')
    @commands.has_permissions(administrator=True)
    async def reg(self, ctx, member: discord.Member, *, country_name: str):
        """Зарегистрировать страну за игроком (напр. !reg @User Франция)"""
        await update_user(member.id, {'country': country_name.strip()})
        reg_role = ctx.guild.get_role(REGISTERED_ROLE_ID)
        unreg_role = ctx.guild.get_role(UNREGISTERED_ROLE_ID)
        country_role = ctx.guild.get_role(COUNTRY_ROLE_ID)
        if reg_role:
            await member.add_roles(reg_role)
        if unreg_role:
            await member.remove_roles(unreg_role)
        if country_role:
            await member.add_roles(country_role)
        await ctx.send(f"✅ Игрок {member.mention} теперь представляет страну **{country_name.strip()}**.")

    @commands.command(name='unreg')
    @commands.has_permissions(administrator=True)
    async def unreg(self, ctx, member: discord.Member):
        """Сбросить всю статистику игрока и снять регистрацию страны"""
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
            'mobilization_percent': 2.5,
            'mobilization_used': False,
            'alliance_id': None,
            'alliance_role': None,
        }
        await update_user(member.id, default_user)
        await inventory_col.delete_many({'user_id': str(member.id)})
        await licenses_col.delete_many({'user_id': str(member.id)})
        reg_role = ctx.guild.get_role(REGISTERED_ROLE_ID)
        unreg_role = ctx.guild.get_role(UNREGISTERED_ROLE_ID)
        country_role = ctx.guild.get_role(COUNTRY_ROLE_ID)
        if reg_role:
            await member.remove_roles(reg_role)
        if unreg_role:
            await member.add_roles(unreg_role)
        if country_role:
            await member.remove_roles(country_role)
        await ctx.send(f"✅ Статистика игрока {member.mention} полностью сброшена, роли обновлены.")

    @commands.command(name='delete-vehicle', aliases=['del-vehicle'])
    @commands.has_permissions(administrator=True)
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
            options = [discord.SelectOption(label=v['name'][:100]) for v in matches[:25]]
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

    @commands.command(name='take-item')
    @commands.has_permissions(administrator=True)
    async def take_item(self, ctx, member: discord.Member, quantity: int, *, item_name: str):
        """Забрать предмет у игрока (с частичным поиском и автоподбором количества)"""
        if quantity <= 0:
            await ctx.send("❌ Количество должно быть больше 0.")
            return
        items = await get_inventory(member.id)
        if not items:
            await ctx.send("❌ У игрока нет предметов.")
            return
        regex = re.compile(re.escape(item_name.strip()), re.IGNORECASE)
        matches = [it for it in items if regex.search(it['item_name'])]
        if not matches:
            await ctx.send("❌ У игрока нет предметов с таким названием.")
            return
        if len(matches) == 1:
            await self._process_take_removal(ctx, member, matches[0], quantity, interaction=None)
        else:
            options = [discord.SelectOption(label=it['item_name'][:100]) for it in matches[:25]]
            select = Select(placeholder="Выберите предмет для изъятия...", options=options)
            view = TakeSelectView(ctx.author.id, member, quantity, matches, select, self)
            await ctx.send("Найдено несколько предметов. Выберите:", view=view)

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

    @commands.command(name='add-money')
    @commands.has_permissions(administrator=True)
    async def add_money(self, ctx, member: discord.Member, amount: int):
        """Выдать деньги на баланс игроку"""
        if amount <= 0:
            await ctx.send("❌ Сумма должна быть больше 0.")
            return
        user = await get_user(member.id)
        new_balance = user['balance'] + amount
        await update_user(member.id, {'balance': new_balance})
        embed = discord.Embed(
            title="💰 Деньги выданы",
            description=f"{member.mention} получил **{amount:,}** 💵",
            color=discord.Color.green()
        )
        embed.add_field(name="Новый баланс", value=f"{new_balance:,} 💵")
        await ctx.send(embed=embed)

    @commands.command(name='remove-sol')
    @commands.has_permissions(administrator=True)
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
    @commands.has_permissions(administrator=True)
    async def add_soldiers(self, ctx, member: discord.Member, quantity: int):
        """Добавить солдат игроку"""
        if quantity <= 0:
            await ctx.send("❌ Количество должно быть больше 0.")
            return
        await add_item(member.id, "Обученный Солдат", quantity)
        await ctx.send(f"✅ {member.mention} получил **{quantity}** обученных солдат.")

    @commands.command(name='priziv-redakt')
    @commands.has_permissions(administrator=True)
    async def priziv_redakt(self, ctx, member: discord.Member, percent: float):
        """Изменить процент мобилизации для игрока (2.5 - 25)"""
        if percent < 2.5 or percent > 25.0:
            await ctx.send("❌ Процент должен быть от 2.5 до 25.")
            return
        await update_user(member.id, {
            'mobilization_percent': percent,
            'mobilization_used': False
        })
        embed = discord.Embed(title="⚙️ Лимит мобилизации изменён",
                              description=f"{member.mention} теперь может мобилизовать до **{percent}%** населения.",
                              color=discord.Color.green())
        await ctx.send(embed=embed)

    @commands.command(name='abb-baff')
    @commands.has_permissions(administrator=True)
    async def abb_baff(self, ctx, member: discord.Member):
        """Управление баффами/дебаффами игрока"""
        view = BuffManageView(member, ctx.author)
        await ctx.send(f"Управление баффами/дебаффами для {member.mention}", view=view)

    @commands.command(name='ally-delete')
    @commands.has_permissions(administrator=True)
    async def ally_delete_admin(self, ctx):
        """Удалить альянс (админ)"""
        alliances = await alliances_col.find().to_list(length=None)
        if not alliances:
            await ctx.send("❌ Альянсов не найдено.")
            return
        
        # Если много альянсов, используем select вместо кнопок
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
    @commands.has_permissions(administrator=True)
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

        embed = discord.Embed(
            title="💰 Стоимость изменена",
            description=f"Техника: **{vehicle['name']}**",
            color=discord.Color.blue()
        )
        embed.add_field(name="Старая стоимость", value=f"{old_price:,} 💵", inline=True)
        embed.add_field(name="Новая стоимость", value=f"{new_price:,} 💵", inline=True)
        await ctx.send(embed=embed)

# ===========================
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
            filter_desc = f"Категория: {view.filter_value}"
        elif view.filter_type == 'search':
            vehicles = [v for v in all_vehicles if v.get('country', '').lower() == view.filter_value.lower()]
            filter_desc = f"Поиск по стране: {view.filter_value}"
        else:
            vehicles = all_vehicles
            filter_desc = "Вся техника"

        total = len(vehicles)
        per_page = 5
        max_page = max(0, (total - 1) // per_page)
        view.current_page = min(view.current_page, max_page)
        start = view.current_page * per_page
        end = start + per_page
        page_vehicles = vehicles[start:end]

        embed = discord.Embed(
            title="🛒 Магазин техники",
            description=f"**{filter_desc}**\nСтраница {view.current_page+1}/{max_page+1}",
            color=discord.Color.dark_teal()
        )
        if not page_vehicles:
            embed.add_field(name="Нет техники", value="Здесь пока пусто", inline=False)
        else:
            for v in page_vehicles:
                name = f"**{v['name']}** — {v['price']:,} 💵"
                desc = v['description'][:80] + ('...' if len(v['description']) > 80 else '')
                embed.add_field(name=name, value=desc, inline=False)
        return embed

    @commands.command(name='add-vehicle', aliases=['add_vehicle'])
    @is_registered()
    async def add_vehicle(self, ctx):
        """Добавить заявку на новую технику в магазин"""
        user = await get_user(ctx.author.id)
        if not user.get('country'):
            await ctx.send("❌ У вас не зарегистрирована страна. Используйте `!reg @вы <название>` для регистрации.")
            return

        can_submit, msg = await check_daily_submission_limit(ctx.author.id)
        if not can_submit:
            await ctx.send(msg)
            return

        info = await get_daily_submission_info(ctx.author.id)
        view = StartAddView(self, ctx.author.id, info)
        await ctx.send(
            f"Нажмите на кнопку чтобы зарегистрировать технику\n"
            f"Лимит заявок за день {info}\n"
            f"КД после отправки 1 час",
            view=view
        )

    @commands.command(name='modernization')
    @is_registered()
    async def modernization(self, ctx):
        """Подать заявку на модернизацию техники (без википедии)"""
        user = await get_user(ctx.author.id)
        if not user.get('country'):
            await ctx.send("❌ У вас не зарегистрирована страна.")
            return
        can_submit, msg = await check_daily_submission_limit(ctx.author.id)
        if not can_submit:
            await ctx.send(msg)
            return
        info = await get_daily_submission_info(ctx.author.id)
        embed = discord.Embed(
            title="🔧 Модернизация техники",
            description="Чтобы модернизировать технику, нажмите на кнопку снизу.",
            color=discord.Color.purple()
        )
        view = ModernizationStartView(self, ctx.author.id, info)
        await ctx.send(embed=embed, view=view)

    async def submit_application(self, user_id: int, data: dict):
        now = datetime.now().timestamp()
        user = await get_user(user_id)
        country = user.get('country', '?')
        vehicle = {
            "name": data['name'],
            "description": data['description'],
            "price": data['price'],
            "category": data['category'],
            "country": country,
            "wiki_link": data.get('wiki_link') if not data.get('is_modernization') else None,
            "image_url": None,
            "submitter_id": str(user_id),
            "approved": False,
            "created_at": now,
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
            embed = discord.Embed(title=title, color=discord.Color.orange() if not data.get('is_modernization') else discord.Color.purple())
            embed.add_field(name="Название", value=data['name'], inline=False)
            embed.add_field(name="Описание", value=data['description'], inline=False)
            embed.add_field(name="Стоимость", value=f"{data['price']:,} 💵", inline=True)
            embed.add_field(name="Категория", value=data['category'], inline=True)
            embed.add_field(name="Страна", value=country, inline=True)
            if data.get('wiki_link'):
                embed.add_field(name="Википедия", value=data['wiki_link'], inline=False)
            embed.set_footer(text=f"Отправитель: {self.bot.get_user(user_id)}")
            view = ApprovalView(self, vehicle['_id'])
            await channel.send(embed=embed, view=view)

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
                options = [discord.SelectOption(label=v['name'][:100]) for v in matches[:25]]
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

    @commands.command(name='mobilization')
    @is_registered()
    async def mobilization(self, ctx):
        """Мобилизовать часть населения в солдат"""
        user = await get_user(ctx.author.id)
        population = user.get('population', 0)
        if population == 0:
            await ctx.send("❌ У вас нет населения.")
            return

        if user.get('mobilization_used', False):
            await ctx.send("❌ Вы уже мобилизовали население. Обратитесь к администратору для изменения лимита.")
            return

        mob_percent = user.get('mobilization_percent', 2.5)
        max_mobilizable = int(population * mob_percent / 100)
        if max_mobilizable <= 0:
            await ctx.send("❌ Недостаточно населения для мобилизации (нужен хотя бы 1 человек).")
            return

        today = datetime.now().strftime('%Y-%m-%d')
        daily_doc = await daily_mobilization_col.find_one({'user_id': str(ctx.author.id), 'date_str': today})
        already_mobilized = daily_doc['total'] if daily_doc else 0
        remaining_daily = max(0, 350_000 - already_mobilized)
        if remaining_daily == 0:
            await ctx.send("❌ Дневной лимит мобилизации (350,000) уже исчерпан.")
            return

        embed = discord.Embed(
            title="📯 Мобилизация",
            description=f"Текущее население: **{population:,}**\n"
                        f"Можно мобилизовать до **{max_mobilizable:,}** ({mob_percent}%)\n"
                        f"Дневной лимит: уже мобилизовано **{already_mobilized:,}** / 350,000",
            color=discord.Color.orange()
        )
        view = MobilizationView(ctx.author.id, max_mobilizable, remaining_daily, self)
        await ctx.send(embed=embed, view=view)

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
        population = user.get('population', 0)
        mob_percent = user.get('mobilization_percent', 2.5)
        max_mobilizable = int(population * mob_percent / 100)
        if quantity > max_mobilizable:
            return f"❌ Нельзя мобилизовать больше **{max_mobilizable:,}**."
        if quantity <= 0:
            return "❌ Количество должно быть положительным."

        today = datetime.now().strftime('%Y-%m-%d')
        daily_doc = await daily_mobilization_col.find_one({'user_id': str(user_id), 'date_str': today})
        already = daily_doc['total'] if daily_doc else 0
        if already + quantity > 350_000:
            return f"❌ Превышен дневной лимит (уже {already:,}, можно ещё {max(0, 350_000 - already):,})."

        new_population = population - quantity
        await update_user(user_id, {
            'population': new_population,
            'mobilization_used': True
        })
        await add_item(user_id, "Обученный Солдат", quantity)

        await daily_mobilization_col.update_one(
            {'user_id': str(user_id), 'date_str': today},
            {'$inc': {'total': quantity}, '$setOnInsert': {'date_str': today}},
            upsert=True
        )
        await mobilization_links_col.insert_one({
            "message_id": message_id,
            "channel_id": channel_id,
            "used_by": str(user_id),
            "used_at": datetime.now().timestamp()
        })

        return f"✅ Мобилизовано **{quantity:,}** солдат. Население: {new_population:,}."

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
        # Проверяем, не создал ли уже 2 альянса
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

        # Проверяем, владелец ли это
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

        # Проверяем, не является ли цель уже членом
        target_user = await get_user(target.id)
        if target_user.get('alliance_id') == alliance_id:
            await ctx.send("❌ Этот игрок уже является членом вашего альянса.")
            return

        # Создаем приглашение
        invite_id = await alliance_invites_col.insert_one({
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

        # Выгоняем из альянса
        await update_user(target.id, {'alliance_id': None, 'alliance_role': None})

        # Удаляем из ветки (если она существует)
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
            # Ищем альянс владельца
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
            # Показываем список альянсов
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

        # Обновляем изображение
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

        # Члены
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
        # Конвертируем в ObjectId если это строка
        if isinstance(alliance_id, str):
            try:
                alliance_id = ObjectId(alliance_id)
            except:
                return False
        
        alliance = await get_alliance(alliance_id)
        if not alliance:
            return False

        # Удаляем налог у всех членов
        members = alliance.get('members', [])
        for member_id in members:
            await update_user(int(member_id), {'alliance_id': None, 'alliance_role': None})

        # Удаляем владельца
        owner_id = int(alliance.get('owner_id', 0))
        if owner_id:
            await update_user(owner_id, {'alliance_id': None, 'alliance_role': None})

        # Удаляем ветку
        if alliance.get('thread_id'):
            try:
                thread = self.bot.get_channel(alliance['thread_id'])
                if thread and isinstance(thread, discord.Thread):
                    await thread.delete()
            except:
                pass

        # Удаляем альянс из БД
        await alliances_col.delete_one({'_id': alliance_id})
        return True

# ========== UI ДЛЯ МАГАЗИНА ==========
class ShopView(View):
    def __init__(self, cog: Shop, author_id: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.author_id = author_id
        self.filter_type = 'all'
        self.filter_value = None
        self.current_page = 0
        self.message = None

        self.add_item(CategoryButton("Все", 'all', discord.ButtonStyle.primary))
        for cat in Shop.VEHICLE_CATEGORIES:
            self.add_item(CategoryButton(cat, cat, discord.ButtonStyle.secondary))
        self.add_item(SearchButton("🔍 Поиск по стране", discord.ButtonStyle.success))
        self.add_item(PageButton("⬅️", -1, discord.ButtonStyle.gray))
        self.add_item(PageButton("➡️", 1, discord.ButtonStyle.gray))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    async def update_message(self, interaction: discord.Interaction):
        embed = await self.cog.build_shop_embed(self)
        await interaction.response.edit_message(embed=embed, view=self)

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
        modal = CountrySearchModal(self.view)
        await interaction.response.send_modal(modal)

class CountrySearchModal(Modal, title="Поиск по стране"):
    country = TextInput(label="Введите название страны", placeholder="Франция", max_length=50)
    def __init__(self, shop_view: ShopView):
        super().__init__()
        self.shop_view = shop_view
    async def on_submit(self, interaction: discord.Interaction):
        self.shop_view.filter_type = 'search'
        self.shop_view.filter_value = self.country.value.strip()
        self.shop_view.current_page = 0
        await self.shop_view.update_message(interaction)

class PageButton(discord.ui.Button):
    def __init__(self, label, delta, style):
        super().__init__(label=label, style=style)
        self.delta = delta
    async def callback(self, interaction: discord.Interaction):
        all_vehicles = await vehicles_col.find({"approved": True}).to_list(length=None)
        if self.view.filter_type == 'category':
            vehicles = [v for v in all_vehicles if v.get('category') == self.view.filter_value]
        elif self.view.filter_type == 'search':
            vehicles = [v for v in all_vehicles if v.get('country', '').lower() == (self.view.filter_value or '').lower()]
        else:
            vehicles = all_vehicles
        total = len(vehicles)
        per_page = 5
        max_page = max(0, (total - 1) // per_page)
        new_page = self.view.current_page + self.delta
        if 0 <= new_page <= max_page:
            self.view.current_page = new_page
        await self.view.update_message(interaction)

# ========== UI ДЛЯ ДОБАВЛЕНИЯ ТЕХНИКИ ==========
class StartAddView(View):
    def __init__(self, cog: Shop, user_id: int, limit_info: str):
        super().__init__(timeout=120)
        self.cog = cog
        self.user_id = user_id
        self.limit_info = limit_info
    @button(label="Заполнить заявку", style=discord.ButtonStyle.primary)
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VehicleInfoModal(self.cog, self.user_id))

class ModernizationStartView(View):
    def __init__(self, cog: Shop, user_id: int, limit_info: str):
        super().__init__(timeout=120)
        self.cog = cog
        self.user_id = user_id
        self.limit_info = limit_info

    @button(label="Модернизировать технику", style=discord.ButtonStyle.primary)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ModernizationModal(self.cog, self.user_id))

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

class CategorySelectView(View):
    def __init__(self, cog: Shop, user_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.user_id = user_id
        select = Select(placeholder="Выберите категорию...", options=[discord.SelectOption(label=cat) for cat in Shop.VEHICLE_CATEGORIES])
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        category = interaction.data['values'][0]
        data = self.cog.pending_add.get(self.user_id)
        if not data:
            await interaction.response.send_message("⚠️ Данные утеряны, начните заново.", ephemeral=True)
            return
        data['category'] = category
        user = await get_user(self.user_id)
        country = user.get('country', '?')
        embed = discord.Embed(title="Подтверждение заявки", color=discord.Color.green())
        embed.add_field(name="Название", value=data['name'], inline=False)
        embed.add_field(name="Описание", value=data['description'], inline=False)
        embed.add_field(name="Стоимость", value=f"{data['price']:,} 💵", inline=True)
        embed.add_field(name="Категория", value=category, inline=True)
        embed.add_field(name="Страна", value=country, inline=True)
        if data.get('wiki_link'):
            embed.add_field(name="Википедия", value=data['wiki_link'], inline=False)
        submit_view = SubmitView(self.cog, self.user_id)
        await interaction.response.send_message(embed=embed, view=submit_view, ephemeral=True)

class SubmitView(View):
    def __init__(self, cog: Shop, user_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.user_id = user_id
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
        selected_name = interaction.data['values'][0]
        vehicle = next((v for v in self.matches if v['name'] == selected_name), None)
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

    @button(label="В ЛС", style=discord.ButtonStyle.primary)
    async def to_dm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.admin_id: return
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
        if interaction.user.id != self.admin_id: return
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

    @button(label="Удалить", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Вы не можете использовать это.", ephemeral=True)
            return
        await self.admin_cog.delete_vehicle_by_id(self.vehicle_id, self.name, interaction)

    @button(label="Отмена", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Удаление отменено.", view=None)

class DeleteSelectView(View):
    def __init__(self, author_id, matches, select: Select, admin_cog):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.matches = matches
        self.admin_cog = admin_cog        # сохраняем ссылку на ког
        select.callback = self.select_callback
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    async def select_callback(self, interaction: discord.Interaction):
        selected_name = interaction.data['values'][0]
        vehicle = next(v for v in self.matches if v['name'] == selected_name)
        # вызываем метод через сохранённый экземпляр кога
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
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=180)
        self.guild = guild
        self.mode = 'states'
        self.message = None

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
        super().__init__(timeout=120)
        self.ctx = ctx
        self.mode = 'balance'
        self.message = None

    async def build_embed(self, mode: str) -> discord.Embed:
        if mode == 'gdp':
            top = await economy_col.find().sort('gdp', -1).limit(10).to_list(length=10)
            title = "📈 Топ-10 по ВВП"
            value_key = 'gdp'
        elif mode == 'population':
            top = await economy_col.find().sort('population', -1).limit(10).to_list(length=10)
            title = "👥 Топ-10 по населению"
            value_key = 'population'
        else:
            top = await economy_col.find().sort('balance', -1).limit(10).to_list(length=10)
            title = "💰 Топ-10 по балансу"
            value_key = 'balance'

        embed = discord.Embed(title=title, color=discord.Color.gold())
        if not top:
            embed.description = "Нет данных."
            return embed

        description = ""
        for i, user_data in enumerate(top, 1):
            try:
                member = self.ctx.guild.get_member(int(user_data['_id']))
                name = member.name if member else f"User{user_data['_id']}"
            except:
                name = f"User{user_data['_id']}"
            country = user_data.get('country')
            display = f"{country} ({name})" if country else name
            value = user_data[value_key]
            if value_key == 'population':
                description += f"**{i}.** {display} — 👥 **{value:,}** чел.\n"
            else:
                description += f"**{i}.** {display} — 💵 **{value:,}**\n"
        embed.description = description
        return embed

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

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.ctx.author.id

# ========== UI ДЛЯ МОБИЛИЗАЦИИ ==========
class MobilizationView(View):
    def __init__(self, user_id: int, max_mobilizable: int, remaining_daily: int, cog: Shop):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.max_mobilizable = max_mobilizable
        self.remaining_daily = remaining_daily
        self.cog = cog

    @button(label="Мобилизовать население", style=discord.ButtonStyle.primary)
    async def mobilize_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Это не ваше меню.", ephemeral=True)
            return
        modal = MobilizationModal(self.max_mobilizable, self.remaining_daily, self.cog)
        await interaction.response.send_modal(modal)

class MobilizationModal(Modal, title="Мобилизация населения"):
    qty = TextInput(label="Количество солдат", placeholder="Введите число", max_length=10)
    link = TextInput(label="Ссылка на сообщение в канале реформ", placeholder="https://discord.com/channels/...", max_length=200)

    def __init__(self, max_mobilizable, remaining_daily, cog):
        super().__init__()
        self.max_mobilizable = max_mobilizable
        self.remaining_daily = remaining_daily
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            qty = int(self.qty.value)
        except ValueError:
            await interaction.response.send_message("❌ Количество должно быть числом.", ephemeral=True)
            return
        result = await self.cog.perform_mobilization(interaction, interaction.user.id, qty, self.link.value.strip())
        await interaction.response.send_message(result, ephemeral=True)

# ========== UI Баффов/Дебаффов ==========
async def get_buffs(user_id: int) -> list:
    cursor = buffs_col.find({'user_id': str(user_id)})
    return await cursor.to_list(length=100)

class BuffManageView(View):
    def __init__(self, target: discord.Member, admin: discord.Member):
        super().__init__(timeout=180)
        self.target = target
        self.admin = admin

    @button(label="Дать бафф", style=discord.ButtonStyle.success)
    async def give_buff(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.admin.id:
            await interaction.response.send_message("Недоступно.", ephemeral=True)
            return
        await interaction.response.send_modal(BuffModal(self.target, 'buff'))

    @button(label="Дать дебафф", style=discord.ButtonStyle.danger)
    async def give_debuff(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.admin.id:
            await interaction.response.send_message("Недоступно.", ephemeral=True)
            return
        await interaction.response.send_modal(BuffModal(self.target, 'debuff'))

    @button(label="Список Баффов/дебаффов", style=discord.ButtonStyle.primary)
    async def list_buffs(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.admin.id:
            await interaction.response.send_message("Недоступно.", ephemeral=True)
            return
        buffs = await get_buffs(self.target.id)
        if not buffs:
            await interaction.response.send_message("У игрока нет активных баффов/дебаффов.", ephemeral=True)
            return
        view = BuffListView(self.target, buffs, self.admin)
        await interaction.response.send_message(f"Активные эффекты {self.target.mention}:", view=view, ephemeral=True)

class BuffModal(Modal, title="Добавить эффект"):
    percent = TextInput(label="Процент (1-100)", placeholder="10", max_length=3)
    reason = TextInput(label="Причина", style=discord.TextStyle.long, placeholder="За активность...", max_length=200)

    def __init__(self, target: discord.Member, buff_type: str):
        super().__init__()
        self.target = target
        self.buff_type = buff_type

    async def on_submit(self, interaction: discord.Interaction):
        try:
            p = int(self.percent.value)
            if not (1 <= p <= 100):
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ Процент должен быть целым числом от 1 до 100.", ephemeral=True)
            return
        reason = self.reason.value.strip() or "Без причины"
        await buffs_col.insert_one({
            'user_id': str(self.target.id),
            'type': self.buff_type,
            'percent': p,
            'reason': reason,
            'issued_by': str(interaction.user.id),
            'issued_at': datetime.now().timestamp()
        })
        embed = discord.Embed(title="✅ Эффект добавлен",
                              description=f"{'Бафф' if self.buff_type == 'buff' else 'Дебафф'} **{p}%** для {self.target.mention}\nПричина: {reason}",
                              color=discord.Color.green() if self.buff_type == 'buff' else discord.Color.red())
        await interaction.response.send_message(embed=embed)

class BuffListView(View):
    def __init__(self, target: discord.Member, buffs: list, admin: discord.Member):
        super().__init__(timeout=120)
        self.target = target
        self.admin = admin
        for b in buffs:
            sign = '+' if b['type'] == 'buff' else '-'
            label = f"{sign}{b['percent']}% - {b['reason'][:50]}"
            self.add_item(RemoveBuffButton(b['_id'], label))

class RemoveBuffButton(discord.ui.Button):
    def __init__(self, buff_id, label):
        super().__init__(style=discord.ButtonStyle.secondary, label=label)
        self.buff_id = buff_id

    async def callback(self, interaction: discord.Interaction):
        result = await buffs_col.delete_one({'_id': self.buff_id})
        if result.deleted_count:
            await interaction.response.send_message("✅ Эффект удалён.", ephemeral=True)
            buffs = await get_buffs(self.view.target.id)
            if not buffs:
                await interaction.edit_original_response(view=None, content="Эффекты отсутствуют.")
                return
            new_view = BuffListView(self.view.target, buffs, self.view.admin)
            await interaction.edit_original_response(view=new_view)
        else:
            await interaction.response.send_message("❌ Не удалось удалить.", ephemeral=True)

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
            'created_at': datetime.now().timestamp()
        }

        result = await alliances_col.insert_one(alliance_data)
        alliance_data['_id'] = result.inserted_id

        # Отправляем заявку на одобрение
        approval_channel = self.guild.get_channel(ALLIANCES_APPROVAL_CHANNEL_ID)
        if approval_channel:
            embed = discord.Embed(
                title="📥 Новая заявка на создание альянса",
                color=discord.Color.gold()
            )
            embed.add_field(name="Название", value=name, inline=False)
            embed.add_field(name="Описание", value=desc, inline=False)
            embed.add_field(name="Тип", value=atype, inline=True)
            creator = self.guild.get_member(self.user_id)
            creator_name = creator.name if creator else f"User{self.user_id}"
            embed.add_field(name="Создатель", value=creator_name, inline=True)
            embed.set_footer(text=f"ID альянса: {result.inserted_id}")
            
            view = AllyApprovalView(result.inserted_id, self.guild, self.user_id)
            await approval_channel.send(embed=embed, view=view)
            
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
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Только администраторы могут одобрять альянсы.", ephemeral=True)
            return

        alliance = await get_alliance(self.alliance_id)
        if not alliance:
            await interaction.response.send_message("❌ Альянс не найден.", ephemeral=True)
            return

        try:
            # Создаем тред в канале для веток альянсов
            thread_channel = self.guild.get_channel(ALLIANCES_THREADS_CHANNEL_ID)
            if thread_channel:
                thread = await thread_channel.create_thread(
                    name=f"🏛️ {alliance['name']}",
                    auto_archive_duration=1440,
                    reason=f"Альянс {alliance['name']}"
                )

                # Добавляем создателя в тред
                creator = self.guild.get_member(self.creator_id)
                if creator:
                    await thread.add_user(creator)

                # Обновляем альянс
                await alliances_col.update_one(
                    {'_id': self.alliance_id},
                    {'$set': {'thread_id': thread.id, 'approved': True}}
                )

                # Обновляем пользователя
                await update_user(self.creator_id, {'alliance_id': self.alliance_id, 'alliance_role': 'owner'})

                # Обновляем сообщение
                embed = interaction.message.embeds[0]
                embed.color = discord.Color.green()
                embed.title = "✅ Альянс одобрен"
                embed.set_footer(text=f"Одобрено: {interaction.user.name}")
                await interaction.message.edit(embed=embed, view=None)

                # Отправляем DM создателю
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
        if not interaction.user.guild_permissions.administrator:
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

        # Удаляем альянс
        await alliances_col.delete_one({'_id': self.alliance_id})

        # Обновляем сообщение
        embed = self.message.embeds[0]
        embed.color = discord.Color.red()
        embed.title = "❌ Альянс отклонен"
        embed.add_field(name="Причина", value=reason, inline=False)
        embed.set_footer(text=f"Отклонено: {interaction.user.name}")
        await self.message.edit(embed=embed, view=None)

        # Отправляем DM создателю
        creator = self.guild.get_member(self.creator_id)
        if creator:
            try:
                alliance = await get_alliance(self.alliance_id)
                if alliance:
                    await creator.send(f"❌ Ваша заявка на альянс **{alliance['name']}** отклонена.\n**Причина:** {reason}")
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

                # Удаляем из ветки
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
            if amount <= 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ Сумма должна быть положительным числом.", ephemeral=True)
            return

        user = await get_user(self.user_id)
        if user['balance'] < amount:
            await interaction.response.send_message(f"❌ Недостаточно денег. Баланс: {user['balance']:,} 💵", ephemeral=True)
            return

        # Пополняем казну
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
            if not (1 <= percent <= 100):
                raise ValueError
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
            if amount <= 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ Сумма должна быть положительным числом.", ephemeral=True)
            return

        alliance = await get_alliance(self.alliance_id)
        if alliance['treasury'] < amount:
            await interaction.response.send_message(f"❌ В казне недостаточно денег. Доступно: {alliance['treasury']:,} 💵", ephemeral=True)
            return

        # Снимаем с казны
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

        # Обновляем ветку
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

    @button(label="Да", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Это приглашение не для вас.", ephemeral=True)
            return

        user = await get_user(self.user_id)
        if user.get('alliance_id'):
            await interaction.response.send_message("❌ Вы уже являетесь членом другого альянса.", ephemeral=True)
            return

        alliance = await get_alliance(self.alliance_id)
        if not alliance:
            await interaction.response.send_message("❌ Альянс не найден.", ephemeral=True)
            return

        # Добавляем в альянс
        members = alliance.get('members', [])
        members.append(str(self.user_id))
        await alliances_col.update_one({'_id': self.alliance_id}, {'$set': {'members': members}})
        await update_user(self.user_id, {'alliance_id': self.alliance_id, 'alliance_role': 'member'})

        # Добавляем в ветку
        if alliance.get('thread_id'):
            try:
                thread = interaction.client.get_channel(alliance['thread_id'])
                if thread:
                    await thread.add_user(interaction.user)
            except:
                pass

        embed = discord.Embed(
            title=f"✅ Вы вступили в альянс **{self.alliance_name}**!",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @button(label="Нет", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Это приглашение не для вас.", ephemeral=True)
            return

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
            
            # Получаем Alliances cog по названию класса
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
        label = name[:76]  # Max 80 chars for label
        super().__init__(label=f"❌ {label}", style=discord.ButtonStyle.danger)
        self.alliance_id = alliance_id

    async def callback(self, interaction: discord.Interaction):
        try:
            alliance_id = self.alliance_id
            if isinstance(alliance_id, str):
                alliance_id = ObjectId(alliance_id)
            
            # Получаем Alliances cog по названию класса
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

# ===== ЗАГРУЗКА COG И ЗАПУСК =====
@bot.event
async def setup_hook():
    await bot.add_cog(General(bot))
    await bot.add_cog(Economy(bot))
    await bot.add_cog(Budget(bot))
    await bot.add_cog(Admin(bot))
    await bot.add_cog(Shop(bot))
    await bot.add_cog(Alliances(bot))

if __name__ == '__main__':
    bot.run(TOKEN)