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
        for cog_name, cog in self.bot.cogs.items():
            cmds = cog.get_commands()
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
        embed.add_field(name="Версия", value="2.0.0", inline=False)
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
        """Статистика игрока — ВВП, баланс, место в топе"""
        if member is None:
            member = ctx.author

        user = await get_user(member.id)

        top_users = await economy_col.find().sort('balance', -1).to_list(length=None)
        position = next(
            (i + 1 for i, u in enumerate(top_users) if u['_id'] == str(member.id)),
            None
        )

        income_per_hour = user['gdp'] / 48 if user['gdp'] > 0 else 0

        last_collect = user.get('last_collect', 0)
        if last_collect > 0:
            hours_since = (datetime.now().timestamp() - last_collect) / 3600
            hours_since = min(hours_since, 12)
            pending = int(income_per_hour * hours_since)
        else:
            pending = 0

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
        await ctx.send(embed=embed)

# ===========================
# 👑 COG: ADMIN
# ===========================

class Admin(commands.Cog, name="👑 Админ"):

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='give-vvp')
    @commands.has_permissions(administrator=True)
    async def give_gdp(self, ctx, member: discord.Member, amount: int):
        """[Админ] Выдать ВВП игроку"""
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

# ===== LOAD COGS & RUN =====

@bot.event
async def setup_hook():
    await bot.add_cog(General(bot))
    await bot.add_cog(Economy(bot))
    await bot.add_cog(Admin(bot))

if __name__ == '__main__':
    bot.run(TOKEN)