import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import random
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

# ===== DATABASE HELPERS =====

async def get_user(user_id: int) -> dict:
    """Get user data from MongoDB, create if not exists"""
    user = await economy_col.find_one({'_id': str(user_id)})
    if user is None:
        user = {
            '_id': str(user_id),
            'balance': 1000,
            'last_work': 0,
            'last_daily': 0
        }
        await economy_col.insert_one(user)
    return user

async def update_user(user_id: int, data: dict):
    """Update user data in MongoDB"""
    await economy_col.update_one(
        {'_id': str(user_id)},
        {'$set': data},
        upsert=True
    )

async def get_balance(user_id: int) -> int:
    """Get user balance"""
    user = await get_user(user_id)
    return user.get('balance', 1000)

# ===== BOT SETUP =====

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

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

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Команда не найдена. Используйте `!help`")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Не хватает аргументов. Используйте `!help` для подсказки.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Неверный аргумент. Используйте `!help` для подсказки.")
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏰ Подожди {error.retry_after:.1f} секунд!")
    else:
        print(f"Error: {error}")

# ===== GENERAL COMMANDS =====

@bot.command(name='help')
async def help_command(ctx):
    """Show all available commands"""
    embed = discord.Embed(
        title="📖 Список команд",
        description="Все доступные команды бота. Префикс: `!`",
        color=discord.Color.blurple()
    )
    embed.add_field(
        name="⚙️ Основные",
        value=(
            "`!help` — показать это сообщение\n"
            "`!ping` — проверить задержку бота\n"
            "`!hello` — поздороваться с ботом\n"
            "`!info` — информация о боте"
        ),
        inline=False
    )
    embed.add_field(
        name="💰 Экономика",
        value=(
            "`!balance [@пользователь]` — проверить баланс\n"
            "`!work` — поработать и заработать деньги (раз в час)\n"
            "`!daily` — получить ежедневную награду (500 💵)\n"
            "`!pay @пользователь <сумма>` — перевести деньги\n"
            "`!leaderboard` — топ-10 богатейших игроков"
        ),
        inline=False
    )
    embed.add_field(
        name="🎮 Игры",
        value="`!dice <ставка>` — кинуть кубик (выиграй x2 при ролле > 50)",
        inline=False
    )
    embed.set_footer(text=f"Запросил: {ctx.author.name}", icon_url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed)

@bot.command(name='ping')
async def ping(ctx):
    await ctx.send(f'Pong! 🏓 Latency: {round(bot.latency * 1000)}ms')

@bot.command(name='hello')
async def hello(ctx):
    await ctx.send(f'Привет, {ctx.author.mention}! 👋')

@bot.command(name='info')
async def info(ctx):
    embed = discord.Embed(
        title="Bot Information",
        description="Бот для сервера Военная-политическая-игра",
        color=discord.Color.blue()
    )
    embed.add_field(name="Создатель", value=f"{bot.owner_id if bot.owner_id else 'Unknown'}", inline=False)
    embed.add_field(name="Версия", value="1.0.0", inline=False)
    await ctx.send(embed=embed)

# ===== ECONOMY COMMANDS =====

@bot.command(name='balance')
async def balance(ctx, member: discord.Member = None):
    if member is None:
        member = ctx.author
    bal = await get_balance(member.id)
    embed = discord.Embed(
        title=f"💰 Баланс {member.name}",
        description=f"Баланс: **{bal}** 💵",
        color=discord.Color.gold()
    )
    await ctx.send(embed=embed)

@bot.command(name='work')
@commands.cooldown(1, 5, commands.BucketType.user)
async def work(ctx):
    user = await get_user(ctx.author.id)
    current_time = datetime.now().timestamp()
    last_work = user.get('last_work', 0)

    if current_time - last_work < 3600:
        remaining = int(3600 - (current_time - last_work))
        mins = remaining // 60
        await ctx.send(f"⏰ Ты уже работал! Приди через {mins} минут.")
        return

    earned = random.randint(100, 500)
    new_balance = user['balance'] + earned

    await update_user(ctx.author.id, {
        'balance': new_balance,
        'last_work': current_time
    })

    activities = [
        "срубил дерево 🌳",
        "поймал рыбу 🎣",
        "отремонтировал дорогу 🛠️",
        "собрал урожай 🌾",
        "выполнил боевое задание ⚔️"
    ]

    embed = discord.Embed(
        title="💼 Работа",
        description=f"Ты {random.choice(activities)}",
        color=discord.Color.green()
    )
    embed.add_field(name="Заработано", value=f"+{earned} 💵", inline=False)
    embed.add_field(name="Новый баланс", value=f"{new_balance} 💵", inline=False)
    await ctx.send(embed=embed)

@bot.command(name='daily')
@commands.cooldown(1, 5, commands.BucketType.user)
async def daily(ctx):
    user = await get_user(ctx.author.id)
    current_time = datetime.now().timestamp()
    last_daily = user.get('last_daily', 0)

    if current_time - last_daily < 86400:
        remaining = int(86400 - (current_time - last_daily))
        hours = remaining // 3600
        await ctx.send(f"⏰ Ты уже получал награду! Приди через {hours} часов.")
        return

    reward = 500
    new_balance = user['balance'] + reward

    await update_user(ctx.author.id, {
        'balance': new_balance,
        'last_daily': current_time
    })

    embed = discord.Embed(
        title="🎁 Ежедневная награда",
        description=f"Ты получил **{reward}** 💵",
        color=discord.Color.gold()
    )
    embed.add_field(name="Баланс", value=f"{new_balance} 💵", inline=False)
    await ctx.send(embed=embed)

@bot.command(name='pay')
@commands.cooldown(1, 3, commands.BucketType.user)
async def pay(ctx, member: discord.Member, amount: int):
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
        await ctx.send(f"❌ У тебя недостаточно денег! Баланс: {sender['balance']} 💵")
        return

    receiver = await get_user(member.id)
    await update_user(ctx.author.id, {'balance': sender['balance'] - amount})
    await update_user(member.id, {'balance': receiver['balance'] + amount})

    embed = discord.Embed(
        title="💸 Перевод денег",
        description=f"{ctx.author.mention} отправил {member.mention} **{amount}** 💵",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed)

@bot.command(name='leaderboard')
@commands.cooldown(1, 10, commands.BucketType.guild)
async def leaderboard(ctx):
    top_users = await economy_col.find().sort('balance', -1).limit(10).to_list(length=10)

    if not top_users:
        await ctx.send("📊 На сервере нет данных об экономике!")
        return

    description = ""
    for i, user_data in enumerate(top_users, 1):
        try:
            user = await bot.fetch_user(int(user_data['_id']))
            name = user.name
        except:
            name = f"User#{user_data['_id']}"
        description += f"{i}. {name} — **{user_data['balance']}** 💵\n"

    embed = discord.Embed(
        title="🏆 Рейтинг богачей",
        description=description,
        color=discord.Color.gold()
    )
    await ctx.send(embed=embed)

@bot.command(name='dice')
@commands.cooldown(1, 3, commands.BucketType.user)
async def dice(ctx, bet: int):
    if bet <= 0:
        await ctx.send("❌ Ставка должна быть больше 0!")
        return
    if bet > 10000:
        await ctx.send("❌ Максимальная ставка: 10,000 💵")
        return

    user = await get_user(ctx.author.id)
    if user['balance'] < bet:
        await ctx.send(f"❌ У тебя недостаточно денег! Баланс: {user['balance']} 💵")
        return

    roll = random.randint(1, 100)

    if roll > 50:
        new_balance = user['balance'] + bet
        await update_user(ctx.author.id, {'balance': new_balance})
        embed = discord.Embed(
            title="🎲 Ты выиграл!",
            description=f"Ролл: **{roll}** 🎉",
            color=discord.Color.green()
        )
        embed.add_field(name="Выигрыш", value=f"+{bet} 💵", inline=False)
    else:
        new_balance = user['balance'] - bet
        await update_user(ctx.author.id, {'balance': new_balance})
        embed = discord.Embed(
            title="🎲 Ты проиграл...",
            description=f"Ролл: **{roll}** 😢",
            color=discord.Color.red()
        )
        embed.add_field(name="Проигрыш", value=f"-{bet} 💵", inline=False)

    embed.add_field(name="Новый баланс", value=f"{new_balance} 💵", inline=False)
    await ctx.send(embed=embed)

# ===== RUN =====

if __name__ == '__main__':
    bot.run(TOKEN)