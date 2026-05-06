import discord
from discord.ext import commands
import os
import re
from dotenv import load_dotenv
from datetime import datetime, timedelta
import motor.motor_asyncio

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
MONGODB_URI = os.getenv('MONGODB_URI')

# MongoDB setup
mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)
db = mongo_client['discord_bot']
economy_col = db['economy']
reform_links_col = db['reform_links']

# Role ID for registered players
REGISTERED_ROLE_ID = 1501510805169115176

# ===== BOT SETUP =====

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# ===== DATABASE HELPERS =====

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

# ===== EVENTS =====

@bot.event
async def on_ready():
    print(f'✅ Bot logged in as {bot.user.name}')
    print(f'Bot ID: {bot.user.id}')
    print(f'✅ Connected to MongoDB Atlas')
    await bot.change_presence(activity=discord.Game(name="Военная-политическая-игра"))

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    await bot.process_commands(message)

USAGE_HINTS = {
    'pay': '❌ Использование: `!pay @игрок <сумма>`\nПример: `!pay @Undervud 5000`',
    'give-vvp': '❌ Использование: `!give-vvp @игрок <сумма>`\nПример: `!give-vvp @Undervud 1000000000`',
    'reforms': '❌ Использование: `!reforms <сумма> <ссылка на сообщение из канала реформ>`\nПример: `!reforms 1000000 https://discord.com/channels/...`',
    'balance': '❌ Использование: `!balance` или `!balance @игрок`',
    'cab': '❌ Использование: `!cab` или `!cab @игрок`',
    'naselprocent': '❌ Использование: `!naselprocent @игрок <1-100>`\nПример: `!naselprocent @Undervud 3`',
    'nasel-redakt': '❌ Использование: `!nasel-redakt @игрок <число>`\nПример: `!nasel-redakt @Undervud 1000000` или `!nasel-redakt @Undervud -500000`',
    'budjet': '❌ Использование: `!budjet <категория> <процент>`\nКатегории: `социальные-расходы`, `образование`, `здравоохранение`\nПример: `!budjet образование 10`',
    'happines': '❌ Использование: `!happines @игрок <процент>`\nПример: `!happines @Undervud 80`',
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
        print(f"Error: {error}")

# ===========================
# ⚙️ COG: GENERAL
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
        embed.set_footer(
            text=f"Запросил: {ctx.author.name}",
            icon_url=ctx.author.display_avatar.url
        )
        await ctx.send(embed=embed)

    @commands.command(name='ping')
    async def ping(self, ctx):
        """Проверить задержку бота"""
        await ctx.send(f'Pong! 🏓 Latency: {round(self.bot.latency * 1000)}ms')

    @commands.command(name='info')
    async def info(self, ctx):
        """Информация о боте"""
        embed = discord.Embed(
            title="LinkoBot",
            description="Бот для сервера Военная-политическая-игра",
            color=discord.Color.blue()
        )
        embed.add_field(name="Версия", value="2.1.0", inline=False)
        await ctx.send(embed=embed)

# ===========================
# 💰 COG: ECONOMY
# ===========================

class Economy(commands.Cog, name="💰 Экономика"):

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='balance')
    @is_registered()
    async def balance(self, ctx, member: discord.Member = None):
        """Проверить баланс"""
        if member is None:
            member = ctx.author
        user = await get_user(member.id)
        embed = discord.Embed(
            title=f"💰 Баланс {member.name}",
            description=f"Баланс: **{user['balance']:,}** 💵",
            color=discord.Color.gold()
        )
        await ctx.send(embed=embed)

    @commands.command(name='collect', aliases=['coll'])
    @is_registered()
    async def collect(self, ctx):
        """Собрать доход (с учётом бюджета) и прирост населения"""
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

        # Бюджетные вычеты
        budget_social = user.get('budget_social', DEFAULT_BUDGETS['budget_social'])
        budget_education = user.get('budget_education', DEFAULT_BUDGETS['budget_education'])
        budget_healthcare = user.get('budget_healthcare', DEFAULT_BUDGETS['budget_healthcare'])
        budget_other = DEFAULT_BUDGETS['budget_other']  # всегда 1%

        deduct_social = int(gross_income * budget_social / 100)
        deduct_education = int(gross_income * budget_education / 100)
        deduct_healthcare = int(gross_income * budget_healthcare / 100)
        deduct_other = int(gross_income * budget_other / 100)

        total_deduct = deduct_social + deduct_education + deduct_healthcare + deduct_other
        net_income = gross_income - total_deduct

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
        embed.add_field(
            name="Вычеты бюджета",
            value=(
                f"🏛️ Социальные расходы ({budget_social}%): -{deduct_social:,} 💵\n"
                f"📚 Образование ({budget_education}%): -{deduct_education:,} 💵\n"
                f"🏥 Здравоохранение ({budget_healthcare}%): -{deduct_healthcare:,} 💵\n"
                f"📋 Иные расходы ({budget_other}%): -{deduct_other:,} 💵\n"
                f"**Всего вычетов: -{total_deduct:,} 💵**"
            ),
            inline=False
        )
        embed.add_field(name="📌 Чистая прибыль", value=f"+{net_income:,} 💵", inline=False)
        embed.add_field(name="💰 Новый баланс", value=f"{new_balance:,} 💵", inline=False)

        if population > 0:
            if pop_gained > 0:
                embed.add_field(
                    name="👥 Прирост населения",
                    value=f"+{pop_gained:,} чел.",
                    inline=True
                )
            else:
                embed.add_field(
                    name="👥 Прирост населения",
                    value="0 чел. (слишком мало времени)",
                    inline=True
                )
            embed.add_field(
                name="🌍 Новое население",
                value=f"{new_population:,} чел.",
                inline=False
            )

        await ctx.send(embed=embed)

    @commands.command(name='reforms')
    @is_registered()
    async def reforms(self, ctx, amount: int = None, *, message_link: str = None):
        """Вложить деньги в ВВП (требуется ссылка на сообщение из канала реформ)"""
        if amount is None or message_link is None:
            await ctx.send("❌ Использование: `!reforms <сумма> <ссылка на сообщение из канала реформ>`\nПример: `!reforms 1000000 https://discord.com/channels/...`")
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
            efficiency = 0.50
            tier = "50%"
        elif gdp <= 500_000_000_000:
            efficiency = 0.40
            tier = "40%"
        elif gdp <= 900_000_000_000:
            efficiency = 0.30
            tier = "30%"
        elif gdp <= 2_800_000_000_000:
            efficiency = 0.15
            tier = "15%"
        else:
            efficiency = 0.10
            tier = "10%"

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

        reason_display = f"[Ссылка]({message_link})"

        embed = discord.Embed(
            title="🏗️ Реформы",
            description=f"{ctx.author.mention} вложил **{amount:,}** 💵 в ВВП\nПричина: {reason_display}",
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
            await ctx.send("❌ Нельзя платить ботам!")
            return
        if member == ctx.author:
            await ctx.send("❌ Нельзя платить самому себе!")
            return
        if amount <= 0:
            await ctx.send("❌ Сумма должна быть больше 0!")
            return

        sender = await get_user(ctx.author.id)
        if sender['balance'] < amount:
            await ctx.send(f"❌ Недостаточно денег! Баланс: {sender['balance']:,} 💵")
            return

        receiver = await get_user(member.id)
        await update_user(ctx.author.id, {'balance': sender['balance'] - amount})
        await update_user(member.id, {'balance': receiver['balance'] + amount})

        embed = discord.Embed(
            title="💸 Перевод денег",
            description=f"{ctx.author.mention} отправил {member.mention} **{amount:,}** 💵",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)

    @commands.command(name='leaderboard')
    @is_registered()
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def leaderboard(self, ctx):
        """Топ-10 богатейших игроков"""
        top_users = await economy_col.find().sort('balance', -1).limit(10).to_list(length=10)

        if not top_users:
            await ctx.send("📊 Нет данных!")
            return

        description = ""
        for i, user_data in enumerate(top_users, 1):
            try:
                user = await self.bot.fetch_user(int(user_data['_id']))
                name = user.name
            except:
                name = f"User#{user_data['_id']}"
            description += f"{i}. {name} — **{user_data['balance']:,}** 💵\n"

        embed = discord.Embed(
            title="🏆 Рейтинг богачей",
            description=description,
            color=discord.Color.gold()
        )
        await ctx.send(embed=embed)

    @commands.command(name='cab')
    @is_registered()
    async def cab(self, ctx, member: discord.Member = None):
        """Статистика игрока — ВВП, баланс, население, недовольство"""
        if member is None:
            member = ctx.author

        user = await get_user(member.id)

        # Обновляем недовольство
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

        embed = discord.Embed(
            title=f"📊 Статистика {member.name}",
            color=discord.Color.blurple()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="💰 Баланс", value=f"{user['balance']:,} 💵", inline=True)
        embed.add_field(name="📈 ВВП", value=f"{user['gdp']:,} 💵", inline=True)
        embed.add_field(name="⏱️ Доход в час", value=f"{income_per_hour:,.0f} 💵", inline=True)
        embed.add_field(name="📦 Ожидает коллекта", value=f"{pending:,} 💵", inline=True)

        # Блок населения (сразу после ожидания коллекта)
        population = user.get('population', 0)
        if population > 0:
            pop_block = (
                f"👥 **{population:,} чел.**\n"
                f"📊 Рост Населения в Год: **{yearly_pct:.2f}%**"
            )
        else:
            pop_block = "👥 Население не выдано"
        embed.add_field(name="🌍 Население", value=pop_block, inline=False)

        # Недовольство (после населения)
        unhappiness_speed = calculate_unhappiness_speed(user)
        speed_str = f"{unhappiness_speed:+.2f}%/ч" if unhappiness_speed else "0%/ч"
        unhappiness_block = f"😡 **{unhappiness:.2f}%**\n({speed_str})"
        embed.add_field(name="🗳️ Недовольство", value=unhappiness_block, inline=False)

        await ctx.send(embed=embed)

# ===========================
# 📊 COG: BUDGET
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
        """Посмотреть текущий бюджет"""
        if member is None:
            member = ctx.author

        user = await get_user(member.id)
        unhappiness = await update_unhappiness(member.id, user)

        embed = discord.Embed(
            title=f"📊 Бюджет {member.name}",
            color=discord.Color.teal()
        )
        for key, name in self.CATEGORY_NAMES.items():
            value = user.get(key, DEFAULT_BUDGETS.get(key, 0))
            default = DEFAULT_BUDGETS.get(key, 0)
            if key == 'budget_other':
                embed.add_field(name=name, value=f"**{value}%** (фиксировано)", inline=True)
            else:
                embed.add_field(name=name, value=f"**{value}%** (по умолч. {default}%)", inline=True)

        speed = calculate_unhappiness_speed(user)
        embed.add_field(
            name="😡 Недовольство",
            value=f"{unhappiness:.2f}%\nСкорость: {speed:+.2f}%/ч",
            inline=False
        )
        embed.set_footer(text="Изменить: !budjet <категория> <процент>")
        await ctx.send(embed=embed)

# ===========================
# 👑 COG: ADMIN
# ===========================

class Admin(commands.Cog, name="👑 Админ"):

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='help-adm')
    @commands.has_permissions(administrator=True)
    async def help_admin(self, ctx):
        """Показать все админ-команды"""
        embed = discord.Embed(
            title="👑 Админ-команды",
            description="Доступны только администраторам. Префикс: `!`",
            color=discord.Color.red()
        )
        cmds = self.get_commands()
        for cmd in cmds:
            embed.add_field(
                name=f"`!{cmd.name}`",
                value=cmd.help or "Нет описания",
                inline=False
            )
        embed.set_footer(
            text=f"Запросил: {ctx.author.name}",
            icon_url=ctx.author.display_avatar.url
        )
        await ctx.send(embed=embed)

    @commands.command(name='give-vvp')
    @commands.has_permissions(administrator=True)
    async def give_gdp(self, ctx, member: discord.Member, amount: int):
        """Выдать ВВП игроку"""
        if amount <= 0:
            await ctx.send("❌ Сумма должна быть больше 0!")
            return

        user = await get_user(member.id)
        new_gdp = user['gdp'] + amount

        await update_user(member.id, {'gdp': new_gdp})

        embed = discord.Embed(
            title="📈 ВВП выдан",
            description=f"{member.mention} получил **{amount:,}** ВВП",
            color=discord.Color.green()
        )
        embed.add_field(name="Новый ВВП", value=f"{new_gdp:,} 💵", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name='naselprocent')
    @commands.has_permissions(administrator=True)
    async def nasel_procent(self, ctx, member: discord.Member, percent: float):
        """Установить годовой % прироста населения игроку (1–100)"""
        if percent < 1 or percent > 100:
            await ctx.send("❌ Процент должен быть от **1** до **100**!")
            return

        await update_user(member.id, {'pop_growth_yearly': percent})

        embed = discord.Embed(
            title="📊 Прирост населения обновлён",
            description=f"{member.mention} — новый годовой прирост: **{percent:.2f}%**",
            color=discord.Color.blue()
        )
        hourly = percent / 48
        embed.add_field(
            name="Прирост в час",
            value=f"{hourly:.4f}% (1 игровой год = 48 ч)",
            inline=False
        )
        await ctx.send(embed=embed)

    @commands.command(name='nasel-redakt')
    @commands.has_permissions(administrator=True)
    async def nasel_redakt(self, ctx, member: discord.Member, amount: int):
        """Выдать или забрать население у игрока (минус — забрать)"""
        user = await get_user(member.id)
        old_population = user.get('population', 0)
        new_population = old_population + amount

        if new_population < 0:
            await ctx.send(
                f"❌ Нельзя уйти в минус! Текущее население: **{old_population:,}** чел."
            )
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

        embed = discord.Embed(
            title="👥 Население изменено",
            description=f"{member.mention} {action} **{sign}{amount:,}** чел.",
            color=color
        )
        embed.add_field(name="Было", value=f"{old_population:,} чел.", inline=True)
        embed.add_field(name="Стало", value=f"{new_population:,} чел.", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name='happines')
    @commands.has_permissions(administrator=True)
    async def happines(self, ctx, member: discord.Member, percent: float):
        """Установить недовольство игроку (0-100)"""
        if percent < 0 or percent > 100:
            await ctx.send("❌ Процент недовольства должен быть от 0 до 100.")
            return

        current_time = datetime.now().timestamp()
        await update_user(member.id, {
            'unhappiness': percent,
            'last_unhappiness_update': current_time
        })

        embed = discord.Embed(
            title="😡 Недовольство изменено",
            description=f"{member.mention} теперь имеет недовольство **{percent:.1f}%**",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

# ===== LOAD COGS & RUN =====

@bot.event
async def setup_hook():
    await bot.add_cog(General(bot))
    await bot.add_cog(Economy(bot))
    await bot.add_cog(Budget(bot))
    await bot.add_cog(Admin(bot))

if __name__ == '__main__':
    bot.run(TOKEN)