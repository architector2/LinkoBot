import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
from datetime import datetime
import motor.motor_asyncio

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
MONGODB_URI = os.getenv('MONGODB_URI')

# MongoDB setup
mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)
db = mongo_client['discord_bot']
economy_col = db['economy']

# Role ID for registered players
REGISTERED_ROLE_ID = 1501510805169115176

# ===== BOT SETUP =====

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# ===== DATABASE HELPERS =====

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
        }
        await economy_col.insert_one(user)
    else:
        # Add missing fields for old users
        update = {}
        if 'gdp' not in user:
            update['gdp'] = 0
        if 'last_collect' not in user:
            update['last_collect'] = 0
        if 'balance' not in user:
            update['balance'] = 0
        if 'population' not in user:
            update['population'] = 0
        if 'pop_growth_yearly' not in user:
            update['pop_growth_yearly'] = 2.0
        if 'last_pop_update' not in user:
            update['last_pop_update'] = 0
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

def make_bar(current: float, maximum: float, length: int = 10) -> str:
    """
    Возвращает ASCII-прогресс бар.
    Например: [████████░░] 80%
    """
    if maximum <= 0:
        return f"[{'░' * length}] 0%"
    ratio = min(current / maximum, 1.0)
    filled = int(ratio * length)
    bar = '█' * filled + '░' * (length - filled)
    percent = ratio * 100
    return f"[{bar}] {percent:.1f}%"

def calculate_population_growth(user: dict) -> tuple[int, float]:
    """
    Рассчитывает накопленный прирост населения.
    Возвращает (новое_население, часов_прошло).
    1 игровой год = 48 часов реального времени.
    """
    population = user.get('population', 0)
    if population == 0:
        return population, 0.0

    last_pop_update = user.get('last_pop_update', 0)
    if last_pop_update == 0:
        return population, 0.0

    yearly_pct = user.get('pop_growth_yearly', 2.0)
    hourly_pct = yearly_pct / 48.0  # % в час (1 игровой год = 48ч)

    current_time = datetime.now().timestamp()
    hours_passed = (current_time - last_pop_update) / 3600

    if hours_passed < 0.01:
        return population, 0.0

    growth_multiplier = (1 + hourly_pct / 100) ** hours_passed
    new_population = int(population * growth_multiplier)

    return new_population, hours_passed

def is_registered():
    """Check decorator - user must have registered role"""
    async def predicate(ctx):
        role = ctx.guild.get_role(REGISTERED_ROLE_ID)
        if role is None or role not in ctx.author.roles:
            await ctx.send("❌ Ты не зарегистрирован! Открой тикет для регистрации.")
            return False
        return True
    return commands.check(predicate)

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
    'reforms': '❌ Использование: `!reforms <сумма>`\nПример: `!reforms 1000000`',
    'balance': '❌ Использование: `!balance` или `!balance @игрок`',
    'cab': '❌ Использование: `!cab` или `!cab @игрок`',
    'naselprocent': '❌ Использование: `!naselprocent @игрок <1-100>`\nПример: `!naselprocent @Undervud 3`',
    'nasel-redakt': '❌ Использование: `!nasel-redakt @игрок <число>`\nПример: `!nasel-redakt @Undervud 1000000` или `!nasel-redakt @Undervud -500000`',
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
        # Show only non-admin cogs in !help
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
        """Собрать доход на основе ВВП (макс 12 часов)"""
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
        earned = int(income_per_hour * hours_passed)
        new_balance = user['balance'] + earned

        await update_user(ctx.author.id, {
            'balance': new_balance,
            'last_collect': current_time
        })

        embed = discord.Embed(
            title="💵 Коллект",
            description=f"Ты собрал доход за **{hours_passed:.1f}** ч.",
            color=discord.Color.green()
        )
        embed.add_field(name="ВВП", value=f"{user['gdp']:,} 💵", inline=True)
        embed.add_field(name="Доход в час", value=f"{income_per_hour:,.0f} 💵", inline=True)
        embed.add_field(name="Получено", value=f"+{earned:,} 💵", inline=False)
        embed.add_field(name="Новый баланс", value=f"{new_balance:,} 💵", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name='reforms')
    @is_registered()
    async def reforms(self, ctx, amount: int = None):
        """Вложить деньги в ВВП (макс x2 от текущего ВВП)"""
        if amount is None:
            await ctx.send("❌ Укажи сумму! Пример: `!reforms 1000000`")
            return
        if amount <= 0:
            await ctx.send("❌ Сумма должна быть больше 0!")
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

        # GDP efficiency tiers
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

        await update_user(ctx.author.id, {
            'gdp': new_gdp,
            'balance': new_balance
        })

        embed = discord.Embed(
            title="🏗️ Реформы",
            description=f"{ctx.author.mention} вложил **{amount:,}** 💵 в ВВП",
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
        """Статистика игрока — ВВП, баланс, население, место в топе"""
        if member is None:
            member = ctx.author

        user = await get_user(member.id)

        # ── Население: начислить накопленный прирост ──
        current_time = datetime.now().timestamp()
        new_population, pop_hours_passed = calculate_population_growth(user)
        pop_gained = new_population - user.get('population', 0)

        if pop_gained > 0:
            await update_user(member.id, {
                'population': new_population,
                'last_pop_update': current_time
            })
            user['population'] = new_population

        # Если население > 0, но last_pop_update ещё не выставлен — выставим
        if user.get('population', 0) > 0 and user.get('last_pop_update', 0) == 0:
            await update_user(member.id, {'last_pop_update': current_time})

        # ── Рейтинг по балансу ──
        top_users = await economy_col.find().sort('balance', -1).to_list(length=None)
        position = next(
            (i + 1 for i, u in enumerate(top_users) if u['_id'] == str(member.id)),
            None
        )

        # ── Доход от ВВП ──
        income_per_hour = user['gdp'] / 48 if user['gdp'] > 0 else 0

        last_collect = user.get('last_collect', 0)
        if last_collect > 0:
            hours_since = (current_time - last_collect) / 3600
            hours_since = min(hours_since, 12)
            pending = int(income_per_hour * hours_since)
        else:
            pending = 0

        # ── Прирост населения в % за игровой год ──
        yearly_pct = user.get('pop_growth_yearly', 2.0)
        hourly_pct = yearly_pct / 48.0

        embed = discord.Embed(
            title=f"📊 Статистика {member.name}",
            color=discord.Color.blurple()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="💰 Баланс", value=f"{user['balance']:,} 💵", inline=True)
        embed.add_field(name="📈 ВВП", value=f"{user['gdp']:,} 💵", inline=True)
        embed.add_field(name="⏱️ Доход в час", value=f"{income_per_hour:,.0f} 💵", inline=True)
        embed.add_field(name="📦 Ожидает коллекта", value=f"{pending:,} 💵", inline=True)
        embed.add_field(name="🏆 Место в топе", value=f"#{position}" if position else "—", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer

        # ── Блок населения со шкалой ──
        population = user.get('population', 0)
        last_pop_update = user.get('last_pop_update', 0)

        if population > 0:
            # Прогресс внутри текущего часа (сколько минут прошло из 60)
            if last_pop_update > 0:
                mins_in_hour = ((current_time - last_pop_update) % 3600) / 60
            else:
                mins_in_hour = 0
            hour_bar = make_bar(mins_in_hour, 60, length=12)

            # Прогресс в игровом году (сколько часов из 48)
            if last_pop_update > 0:
                hours_in_year = ((current_time - last_pop_update) % (48 * 3600)) / 3600
            else:
                hours_in_year = 0
            year_bar = make_bar(hours_in_year, 48, length=12)

            gained_str = f"+{pop_gained:,} чел." if pop_gained > 0 else "0 чел."

            pop_block = (
                f"👥 **{population:,} чел.**\n"
                f"Прирост за сеанс: **{gained_str}**\n"
                f"\n"
                f"**Прогресс часа:**\n"
                f"{hour_bar}\n"
                f"`{mins_in_hour:.1f} мин из 60`\n"
                f"\n"
                f"**Прогресс игр. года (48 ч):**\n"
                f"{year_bar}\n"
                f"`{hours_in_year:.1f} ч из 48`\n"
                f"\n"
                f"📊 Прирост: **{yearly_pct:.2f}%/игр.год** · **{hourly_pct:.4f}%/ч**"
            )
        else:
            pop_block = "👥 Население не выдано"

        embed.add_field(name="🌍 Население", value=pop_block, inline=False)

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

        # Если население впервые стало > 0, выставляем таймер прироста
        if old_population == 0 and new_population > 0:
            update_data['last_pop_update'] = current_time

        # Если население обнулили — сбрасываем таймер
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

# ===== LOAD COGS & RUN =====

@bot.event
async def setup_hook():
    await bot.add_cog(General(bot))
    await bot.add_cog(Economy(bot))
    await bot.add_cog(Admin(bot))

if __name__ == '__main__':
    bot.run(TOKEN)