import discord
from discord.ext import commands
from discord.ui import Select, View, Modal, TextInput, button
import os
import re
import asyncio
from dotenv import load_dotenv
from datetime import datetime, timedelta
import motor.motor_asyncio

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
alliances_col = db['alliances']  # Альянсы

# ID ролей и каналов
REGISTERED_ROLE_ID = 1501510805169115176
UNREGISTERED_ROLE_ID = 1141339127367880764
COUNTRY_ROLE_ID = 1141340397558321313
ALLIANCE_CHANNEL_ID = 1501932162381906020  # Канал для веток альянсов

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

SOLDIER_MAINTENANCE_PER_HOUR = 10_000

# ===== СОБЫТИЯ =====
@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user.name} запущен')
    print(f'Bot ID: {bot.user.id}')
    print(f'✅ Подключение к MongoDB Atlas установлено')
    await bot.change_presence(activity=discord.Game(name="Военная-политическая-игра"))

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
    'ally-create': '❌ Команда `!ally-create` не требует аргументов. Откроет анкету создания альянса.',
    'ally': '❌ Команда `!ally` не требует аргументов. Показывает панель управления вашим альянсом.',
    'ally-invite': '❌ Использование: `!ally-invite @игрок`',
    'ally-delete': '❌ (Админ) `!ally-delete`',
    'ally-remove': '❌ (Владелец) `!ally-remove`',
    'ally-kick': '❌ Использование: `!ally-kick @игрок`',
    'iso-ally': '❌ Использование: `!iso-ally <название альянса> <ссылка>`',
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
        embed.add_field(name="Версия", value="2.9.0", inline=False)
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
        """Собрать доход и прирост населения (с учётом содержания и баффов/дебаффов и налогов альянса)"""
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
            else:
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

        net_income = gross_income - total_budget_deduct - vehicle_cost - soldier_cost

        # Налоги альянсов
        alliances = await get_user_alliances(ctx.author.id)
        alliance_taxes = {}
        total_tax = 0
        for alliance in alliances:
            tax_rate = alliance.get('tax_rate', 2)
            tax_amount = int(net_income * tax_rate / 100)
            if tax_amount > 0:
                alliance_taxes[alliance['_id']] = (alliance['name'], tax_amount)
                total_tax += tax_amount
        net_income -= total_tax

        new_balance = user['balance'] + net_income

        # Обновление казны альянсов
        for aid, (aname, tax) in alliance_taxes.items():
            await alliances_col.update_one({'_id': aid}, {'$inc': {'treasury': tax}})

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

        # Отображение налогов альянсов
        if alliance_taxes:
            tax_desc = "\n".join(f"**{aname}** ({tax_rate}%): -{tax:,} 💵" for aid, (aname, tax) in alliance_taxes.items())
            embed.add_field(name="🏛️ Налоги альянсов", value=tax_desc, inline=False)

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
            view = DeleteSelectView(ctx.author.id, matches, select)
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
    async def ally_delete(self, ctx):
        """Удалить любой альянс (администратор)"""
        alliances = await alliances_col.find().to_list(length=100)
        if not alliances:
            await ctx.send("Нет альянсов.")
            return
        options = [discord.SelectOption(label=a['name'][:100]) for a in alliances]
        select = Select(placeholder="Выберите альянс для удаления...", options=options)
        view = AdminAllyDeleteView(ctx.author.id, alliances, select)
        await ctx.send("Выберите альянс для удаления:", view=view)

# ===========================
# 🌐 COG: АЛЬЯНСЫ
# ===========================
class Alliance(commands.Cog, name="🌐 Альянсы"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='ally-create')
    @is_registered()
    async def ally_create(self, ctx):
        """Создать новый альянс (макс. 2 альянса на игрока)"""
        owned = await alliances_col.count_documents({'owner_id': str(ctx.author.id)})
        if owned >= 2:
            await ctx.send("❌ Вы уже создали 2 альянса. Больше нельзя!")
            return
        modal = AllyCreateModal()
        await ctx.send("Заполните анкету альянса:", view=None, delete_after=1)
        await ctx.send(embed=discord.Embed(description="Нажмите на кнопку ниже, чтобы ввести данные.", color=discord.Color.blue()),
                       view=AllyCreateButton(ctx.author.id))
    # Вспомогательная кнопка для открытия модального окна
    class AllyCreateButton(View):
        def __init__(self, user_id):
            super().__init__(timeout=60)
            self.user_id = user_id
        @button(label="Создать альянс", style=discord.ButtonStyle.primary)
        async def create(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.send_modal(AllyCreateModal())

    @commands.command(name='ally')
    @is_registered()
    async def ally(self, ctx):
        """Просмотр и управление вашим альянсом"""
        alliances = await get_user_alliances(ctx.author.id)
        if not alliances:
            await ctx.send("❌ Вы не состоите ни в одном альянсе.")
            return
        if len(alliances) == 1:
            await self.show_alliance_panel(ctx, alliances[0])
        else:
            # Если в нескольких, даём выбрать
            options = [discord.SelectOption(label=a['name'][:100]) for a in alliances]
            select = Select(placeholder="Выберите альянс...", options=options)
            view = AllySelectView(ctx.author.id, alliances, select, self)
            await ctx.send("Вы состоите в нескольких альянсах. Выберите один:", view=view)

    async def show_alliance_panel(self, ctx, alliance: dict):
        embed = await self.build_alliance_embed(alliance, ctx.guild)
        owner = str(ctx.author.id) == alliance['owner_id']
        view = AllyManageView(alliance, ctx.author.id, self.bot) if owner else None
        await ctx.send(embed=embed, view=view)

    @commands.command(name='ally-invite')
    @is_registered()
    async def ally_invite(self, ctx, member: discord.Member):
        """Пригласить игрока в ваш альянс (отправляет ЛС)"""
        if member.bot:
            await ctx.send("❌ Ботов нельзя приглашать.")
            return
        # Найти альянс, которым владеет пользователь
        alliance = await alliances_col.find_one({'owner_id': str(ctx.author.id)})
        if not alliance:
            await ctx.send("❌ У вас нет своего альянса для приглашения.")
            return
        if str(member.id) in alliance['members']:
            await ctx.send("❌ Игрок уже в альянсе.")
            return
        embed = discord.Embed(
            title="Приглашение в альянс",
            description=f"Вас приглашает {ctx.author.name} в альянс **{alliance['name']}**.",
            color=discord.Color.green()
        )
        view = AllyInviteView(alliance['_id'], member.id, ctx.author.id)
        try:
            await member.send(embed=embed, view=view)
            await ctx.send(f"📨 Приглашение отправлено {member.mention} в ЛС.")
        except:
            await ctx.send("❌ Не могу отправить ЛС этому игроку.")

    @commands.command(name='ally-remove')
    @is_registered()
    async def ally_remove(self, ctx):
        """Удалить ваш собственный альянс (только владелец)"""
        alliances = await alliances_col.find({'owner_id': str(ctx.author.id)}).to_list(length=100)
        if not alliances:
            await ctx.send("❌ У вас нет альянсов для удаления.")
            return
        if len(alliances) == 1:
            view = ConfirmDeleteAllyView(alliances[0]['_id'], ctx.author.id)
            await ctx.send(f"Вы уверены, что хотите удалить альянс **{alliances[0]['name']}**?", view=view)
        else:
            options = [discord.SelectOption(label=a['name'][:100]) for a in alliances]
            select = Select(placeholder="Выберите альянс...", options=options)
            view = AllyRemoveSelectView(ctx.author.id, alliances, select)
            await ctx.send("Выберите альянс для удаления:", view=view)

    @commands.command(name='ally-kick')
    @is_registered()
    async def ally_kick(self, ctx, member: discord.Member):
        """Кикнуть участника из вашего альянса"""
        alliance = await alliances_col.find_one({'owner_id': str(ctx.author.id), 'members': str(member.id)})
        if not alliance:
            await ctx.send("❌ Этот игрок не состоит в вашем альянсе.")
            return
        # Удаляем участника
        await alliances_col.update_one({'_id': alliance['_id']}, {'$pull': {'members': str(member.id)}})
        thread = self.bot.get_channel(alliance['thread_id'])
        if thread:
            await thread.remove_user(member)
        await ctx.send(f"{member.mention} исключён из альянса.")

    @commands.command(name='iso-ally')
    @is_registered()
    async def iso_ally(self, ctx, *, args: str):
        """Установить изображение альянса: !iso-ally <название> <ссылка>"""
        parts = args.rsplit(' ', 1)
        if len(parts) < 2:
            await ctx.send("❌ Использование: `!iso-ally <название альянса> <ссылка>`")
            return
        name = parts[0].strip()
        url = parts[1].strip()
        alliance = await alliances_col.find_one({'name': name, 'owner_id': str(ctx.author.id)})
        if not alliance:
            await ctx.send("❌ Альянс не найден или вы не его владелец.")
            return
        await alliances_col.update_one({'_id': alliance['_id']}, {'$set': {'image_url': url}})
        await ctx.send("✅ Изображение альянса обновлено.")

    async def build_alliance_embed(self, alliance: dict, guild: discord.Guild) -> discord.Embed:
        embed = discord.Embed(title=alliance['name'], description=alliance.get('description', ''), color=discord.Color.gold())
        embed.add_field(name="Тип", value=alliance['type'], inline=True)
        embed.add_field(name="Казна", value=f"{alliance.get('treasury', 0):,} 💵", inline=True)
        embed.add_field(name="Налог", value=f"{alliance.get('tax_rate', 2)}%", inline=True)
        owner = guild.get_member(int(alliance['owner_id']))
        embed.add_field(name="Глава", value=owner.mention if owner else "Неизвестно", inline=False)
        members = []
        for uid in alliance['members']:
            if uid != alliance['owner_id']:
                member = guild.get_member(int(uid))
                if member:
                    user_data = await get_user(member.id)
                    country = user_data.get('country')
                    if country:
                        members.append(f"{country} ({member.name})")
                    else:
                        members.append(member.name)
        if members:
            embed.add_field(name="Участники", value="\n".join(f"{i+1}. {m}" for i, m in enumerate(members)), inline=False)
        else:
            embed.add_field(name="Участники", value="Нет", inline=False)
        if alliance.get('image_url'):
            embed.set_thumbnail(url=alliance['image_url'])
        return embed

# ========== ДОПОЛНИТЕЛЬНЫЕ VIEW ДЛЯ АЛЬЯНСОВ ==========
class AllyCreateModal(Modal, title="Создание альянса"):
    name = TextInput(label="Название", placeholder="Введите название", max_length=80)
    description = TextInput(label="Описание", style=discord.TextStyle.long, placeholder="Описание альянса", max_length=500)
    type = TextInput(label="Тип (Военный/Экономический/Военно-Экономический)", placeholder="Военный", max_length=30)

    async def on_submit(self, interaction: discord.Interaction):
        # Проверка типа
        valid_types = ["Военный", "Экономический", "Военно-Экономический"]
        atype = self.type.value.strip()
        if atype not in valid_types:
            await interaction.response.send_message("❌ Неверный тип. Допустимые: Военный, Экономический, Военно-Экономический.", ephemeral=True)
            return
        user_id = interaction.user.id
        # Проверка лимита
        owned = await alliances_col.count_documents({'owner_id': str(user_id)})
        if owned >= 2:
            await interaction.response.send_message("❌ Вы уже создали 2 альянса.", ephemeral=True)
            return
        # Создаём документ
        alliance = {
            'name': self.name.value.strip(),
            'description': self.description.value.strip(),
            'type': atype,
            'owner_id': str(user_id),
            'members': [str(user_id)],
            'treasury': 0,
            'tax_rate': 2,
            'image_url': None,
            'thread_id': None,
            'created_at': datetime.now().timestamp()
        }
        result = await alliances_col.insert_one(alliance)
        alliance['_id'] = result.inserted_id

        # Создаём приватную ветку
        guild = interaction.guild
        channel = guild.get_channel(ALLIANCE_CHANNEL_ID)
        if not channel:
            await interaction.response.send_message("❌ Канал для альянсов не найден.", ephemeral=True)
            return
        # Получаем роль администратора сервера для добавления
        admin_role = discord.utils.get(guild.roles, permissions=discord.Permissions(administrator=True))
        thread = await channel.create_thread(
            name=f"Альянс {alliance['name']}",
            type=discord.ChannelType.private_thread,
            invitable=False
        )
        await thread.add_user(interaction.user)
        if admin_role:
            # Добавляем админов (через роль нельзя, но можно добавить всех админов индивидуально - тяжело. Упростим: добавим только владельца)
            pass
        await alliances_col.update_one({'_id': alliance['_id']}, {'$set': {'thread_id': thread.id}})
        await interaction.response.send_message(f"✅ Альянс **{alliance['name']}** создан! Ветка: {thread.mention}", ephemeral=True)

class AllySelectView(View):
    def __init__(self, user_id, alliances, select, cog):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.alliances = alliances
        self.cog = cog
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        name = interaction.data['values'][0]
        alliance = next(a for a in self.alliances if a['name'] == name)
        await self.cog.show_alliance_panel(interaction, alliance)
        await interaction.response.edit_message(view=None)

class AllyManageView(View):
    def __init__(self, alliance, user_id, bot):
        super().__init__(timeout=300)
        self.alliance = alliance
        self.user_id = user_id
        self.bot = bot

    @button(label="Переименовать Альянс", style=discord.ButtonStyle.primary)
    async def rename(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        modal = AllyRenameModal(self.alliance['_id'])
        await interaction.response.send_modal(modal)

    @button(label="Выгнать из Альянса", style=discord.ButtonStyle.danger)
    async def kick_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        members = self.alliance['members'][:]
        if self.user_id in members: members.remove(self.user_id)  # не выгонять владельца
        if not members:
            await interaction.response.send_message("Некого выгонять.", ephemeral=True)
            return
        view = AllyKickListView(self.alliance['_id'], members, self.bot)
        await interaction.response.send_message("Выберите кого выгнать:", view=view, ephemeral=True)

    @button(label="Пополнить Казну", style=discord.ButtonStyle.success)
    async def deposit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        modal = AllyDepositModal(self.alliance['_id'])
        await interaction.response.send_modal(modal)

    @button(label="Установить Налог Альянса", style=discord.ButtonStyle.secondary)
    async def set_tax(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        modal = AllyTaxModal(self.alliance['_id'])
        await interaction.response.send_modal(modal)

    @button(label="Снять деньги с Казны", style=discord.ButtonStyle.danger)
    async def withdraw(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        modal = AllyWithdrawModal(self.alliance['_id'])
        await interaction.response.send_modal(modal)

class AllyRenameModal(Modal, title="Переименовать альянс"):
    new_name = TextInput(label="Новое название", placeholder="Введите имя", max_length=80)
    def __init__(self, alliance_id):
        super().__init__()
        self.aid = alliance_id
    async def on_submit(self, interaction: discord.Interaction):
        await alliances_col.update_one({'_id': self.aid}, {'$set': {'name': self.new_name.value.strip()}})
        await interaction.response.send_message("✅ Альянс переименован.", ephemeral=True)

class AllyDepositModal(Modal, title="Пополнить казну"):
    amount = TextInput(label="Сумма", placeholder="100000", max_length=20)
    def __init__(self, alliance_id):
        super().__init__()
        self.aid = alliance_id
    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = int(self.amount.value)
        except:
            await interaction.response.send_message("❌ Неверная сумма.", ephemeral=True)
            return
        user = await get_user(interaction.user.id)
        if user['balance'] < amt:
            await interaction.response.send_message("❌ Недостаточно денег.", ephemeral=True)
            return
        await update_user(interaction.user.id, {'balance': user['balance'] - amt})
        await alliances_col.update_one({'_id': self.aid}, {'$inc': {'treasury': amt}})
        await interaction.response.send_message(f"✅ В казну добавлено {amt:,} 💵.", ephemeral=True)

class AllyTaxModal(Modal, title="Установить налог"):
    percent = TextInput(label="Процент (1-100)", placeholder="5", max_length=3)
    def __init__(self, alliance_id):
        super().__init__()
        self.aid = alliance_id
    async def on_submit(self, interaction: discord.Interaction):
        try:
            p = int(self.percent.value)
            if not 1 <= p <= 100: raise ValueError
        except:
            await interaction.response.send_message("❌ Введите число от 1 до 100.", ephemeral=True)
            return
        await alliances_col.update_one({'_id': self.aid}, {'$set': {'tax_rate': p}})
        await interaction.response.send_message(f"✅ Налог установлен: {p}%.", ephemeral=True)

class AllyWithdrawModal(Modal, title="Снять из казны"):
    amount = TextInput(label="Сумма", placeholder="50000", max_length=20)
    def __init__(self, alliance_id):
        super().__init__()
        self.aid = alliance_id
    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = int(self.amount.value)
        except:
            await interaction.response.send_message("❌ Неверная сумма.", ephemeral=True)
            return
        alliance = await alliances_col.find_one({'_id': self.aid})
        if alliance['treasury'] < amt:
            await interaction.response.send_message("❌ В казне недостаточно средств.", ephemeral=True)
            return
        await alliances_col.update_one({'_id': self.aid}, {'$inc': {'treasury': -amt}})
        user = await get_user(interaction.user.id)
        await update_user(interaction.user.id, {'balance': user['balance'] + amt})
        await interaction.response.send_message(f"✅ Вы сняли {amt:,} 💵.", ephemeral=True)

class AllyKickListView(View):
    def __init__(self, alliance_id, members, bot):
        super().__init__(timeout=120)
        self.aid = alliance_id
        self.bot = bot
        for uid in members:
            self.add_item(AllyKickButton(uid, alliance_id, bot))
        self.add_item(CancelButton())

class AllyKickButton(discord.ui.Button):
    def __init__(self, user_id, alliance_id, bot):
        super().__init__(style=discord.ButtonStyle.danger, label=f"Выгнать {user_id}")
        self.uid = user_id
        self.aid = alliance_id
        self.bot = bot
    async def callback(self, interaction: discord.Interaction):
        await alliances_col.update_one({'_id': self.aid}, {'$pull': {'members': self.uid}})
        alliance = await alliances_col.find_one({'_id': self.aid})
        thread = self.bot.get_channel(alliance['thread_id'])
        if thread:
            member = interaction.guild.get_member(int(self.uid))
            if member:
                await thread.remove_user(member)
        await interaction.response.send_message(f"Игрок исключён.", ephemeral=True)
        self.view.stop()

class CancelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(style=discord.ButtonStyle.secondary, label="Отмена")
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message("Действие отменено.", ephemeral=True)
        self.view.stop()

class AllyInviteView(View):
    def __init__(self, alliance_id, invited_id, owner_id):
        super().__init__(timeout=120)
        self.aid = alliance_id
        self.invited = invited_id
        self.owner = owner_id

    @button(label="Да", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.invited:
            await interaction.response.send_message("Не вам.", ephemeral=True)
            return
        # Добавляем в альянс
        await alliances_col.update_one({'_id': self.aid}, {'$addToSet': {'members': str(self.invited)}})
        alliance = await alliances_col.find_one({'_id': self.aid})
        # Даём доступ к ветке
        thread = interaction.client.get_channel(alliance['thread_id'])
        if thread:
            await thread.add_user(interaction.user)
        await interaction.response.send_message("✅ Вы вступили в альянс!", ephemeral=True)
        self.stop()

    @button(label="Нет", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.invited:
            await interaction.response.send_message("Не вам.", ephemeral=True)
            return
        await interaction.response.send_message("❌ Приглашение отклонено.", ephemeral=True)
        self.stop()

    async def on_timeout(self):
        # Уведомить владельца? Необязательно.
        pass

class ConfirmDeleteAllyView(View):
    def __init__(self, alliance_id, user_id):
        super().__init__(timeout=60)
        self.aid = alliance_id
        self.user_id = user_id

    @button(label="Удалить", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        await delete_alliance(self.aid, interaction.client)
        await interaction.response.send_message("✅ Альянс удалён.", ephemeral=True)

    @button(label="Отмена", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Отменено.", ephemeral=True)

class AllyRemoveSelectView(View):
    def __init__(self, user_id, alliances, select):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.alliances = alliances
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        name = interaction.data['values'][0]
        alliance = next(a for a in self.alliances if a['name'] == name)
        view = ConfirmDeleteAllyView(alliance['_id'], self.user_id)
        await interaction.response.send_message(f"Удалить альянс **{alliance['name']}**?", view=view, ephemeral=True)

class AdminAllyDeleteView(View):
    def __init__(self, admin_id, alliances, select):
        super().__init__(timeout=120)
        self.admin_id = admin_id
        self.alliances = alliances
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.admin_id: return
        name = interaction.data['values'][0]
        alliance = next(a for a in self.alliances if a['name'] == name)
        await interaction.response.send_message(f"Удалить альянс **{name}**?", view=ConfirmDeleteAllyView(alliance['_id'], self.admin_id), ephemeral=True)

async def delete_alliance(alliance_id, client):
    alliance = await alliances_col.find_one({'_id': alliance_id})
    if not alliance:
        return
    # Удаляем ветку
    thread = client.get_channel(alliance['thread_id'])
    if thread:
        try:
            await thread.delete()
        except:
            pass
    # Удаляем документ
    await alliances_col.delete_one({'_id': alliance_id})

# ========== UI Баффов/Дебаффов (добавлено ранее) ==========
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

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
async def get_user_alliances(user_id: int) -> list:
    cursor = alliances_col.find({'members': str(user_id)})
    return await cursor.to_list(length=None)

# ===== ЗАГРУЗКА COG И ЗАПУСК =====
@bot.event
async def setup_hook():
    await bot.add_cog(General(bot))
    await bot.add_cog(Economy(bot))
    await bot.add_cog(Budget(bot))
    await bot.add_cog(Admin(bot))
    await bot.add_cog(Alliance(bot))
    await bot.add_cog(Shop(bot))

if __name__ == '__main__':
    bot.run(TOKEN)