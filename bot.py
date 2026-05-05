import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import json
import random
from datetime import datetime

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Economy file
ECONOMY_FILE = 'economy.json'

def load_economy():
    """Load economy data from file"""
    if os.path.exists(ECONOMY_FILE):
        with open(ECONOMY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_economy(data):
    """Save economy data to file"""
    with open(ECONOMY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_balance(user_id):
    """Get user balance"""
    economy = load_economy()
    return economy.get(str(user_id), {'balance': 1000, 'last_work': 0}).get('balance', 1000)

def set_balance(user_id, amount):
    """Set user balance"""
    economy = load_economy()
    user_id_str = str(user_id)
    if user_id_str not in economy:
        economy[user_id_str] = {'balance': amount, 'last_work': 0}
    else:
        economy[user_id_str]['balance'] = amount
    save_economy(economy)

# Create bot with intents
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)  # Disable default help

@bot.event
async def on_ready():
    """Called when bot successfully logs in"""
    print(f'✅ Bot logged in as {bot.user.name}')
    print(f'Bot ID: {bot.user.id}')
    await bot.change_presence(activity=discord.Game(name="Военная-политическая-игра"))

@bot.command(name='ping')
async def ping(ctx):
    """Ping command to check bot response"""
    await ctx.send(f'Pong! 🏓 Latency: {round(bot.latency * 1000)}ms')

@bot.command(name='hello')
async def hello(ctx):
    """Greet the user"""
    await ctx.send(f'Привет, {ctx.author.mention}! 👋')

@bot.command(name='info')
async def info(ctx):
    """Show bot info"""
    embed = discord.Embed(
        title="Bot Information",
        description="Бот для сервера Военная-политическая-игра",
        color=discord.Color.blue()
    )
    embed.add_field(name="Создатель", value=f"{bot.owner_id if bot.owner_id else 'Unknown'}", inline=False)
    embed.add_field(name="Версия", value="1.0.0", inline=False)
    await ctx.send(embed=embed)

# ===== HELP COMMAND =====

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
        value=(
            "`!dice <ставка>` — кинуть кубик (выиграй x2 при ролле > 50)"
        ),
        inline=False
    )

    embed.set_footer(text=f"Запросил: {ctx.author.name}", icon_url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed)

# ===== ECONOMY COMMANDS =====

@bot.command(name='balance')
async def balance(ctx, member: discord.Member = None):
    """Check user balance"""
    if member is None:
        member = ctx.author
    
    bal = get_balance(member.id)
    embed = discord.Embed(
        title=f"💰 Баланс {member.name}",
        description=f"Твой баланс: **{bal}** 💵",
        color=discord.Color.gold()
    )
    await ctx.send(embed=embed)

@bot.command(name='work')
async def work(ctx):
    """Work to earn money"""
    economy = load_economy()
    user_id_str = str(ctx.author.id)
    
    if user_id_str not in economy:
        economy[user_id_str] = {'balance': 1000, 'last_work': 0}
    
    # Cooldown: can work once per hour
    current_time = datetime.now().timestamp()
    last_work = economy[user_id_str].get('last_work', 0)
    
    if current_time - last_work < 3600:  # 1 hour cooldown
        remaining = int(3600 - (current_time - last_work))
        mins = remaining // 60
        await ctx.send(f"⏰ Ты уже работал! Приди через {mins} минут.")
        return
    
    # Earn random amount
    earned = random.randint(100, 500)
    economy[user_id_str]['balance'] += earned
    economy[user_id_str]['last_work'] = current_time
    save_economy(economy)
    
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
    embed.add_field(name="Новый баланс", value=f"{economy[user_id_str]['balance']} 💵", inline=False)
    await ctx.send(embed=embed)

@bot.command(name='pay')
async def pay(ctx, member: discord.Member, amount: int):
    """Transfer money to another user"""
    if member.bot:
        await ctx.send("❌ Нельзя платить ботам!")
        return
    
    if amount <= 0:
        await ctx.send("❌ Сумма должна быть больше 0!")
        return
    
    sender_balance = get_balance(ctx.author.id)
    
    if sender_balance < amount:
        await ctx.send(f"❌ У тебя недостаточно денег! Баланс: {sender_balance} 💵")
        return
    
    set_balance(ctx.author.id, sender_balance - amount)
    receiver_balance = get_balance(member.id)
    set_balance(member.id, receiver_balance + amount)
    
    embed = discord.Embed(
        title="💸 Перевод денег",
        description=f"{ctx.author.mention} отправил {member.mention} **{amount}** 💵",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed)

@bot.command(name='leaderboard')
async def leaderboard(ctx):
    """Show top 10 richest users"""
    economy = load_economy()
    
    if not economy:
        await ctx.send("📊 На сервере нет данных об экономике!")
        return
    
    # Sort by balance
    sorted_users = sorted(economy.items(), key=lambda x: x[1]['balance'], reverse=True)[:10]
    
    description = ""
    for i, (user_id, data) in enumerate(sorted_users, 1):
        try:
            user = await bot.fetch_user(int(user_id))
            description += f"{i}. {user.name} - **{data['balance']}** 💵\n"
        except:
            description += f"{i}. User#{user_id} - **{data['balance']}** 💵\n"
    
    embed = discord.Embed(
        title="🏆 Рейтинг богачей",
        description=description,
        color=discord.Color.gold()
    )
    await ctx.send(embed=embed)

@bot.command(name='dice')
async def dice(ctx, bet: int):
    """Dice game - bet money. Win if you roll higher than 50"""
    balance = get_balance(ctx.author.id)
    
    if bet <= 0:
        await ctx.send("❌ Ставка должна быть больше 0!")
        return
    
    if balance < bet:
        await ctx.send(f"❌ У тебя недостаточно денег для ставки {bet}! Баланс: {balance}")
        return
    
    roll = random.randint(1, 100)
    
    if roll > 50:
        # Win - double the bet
        winnings = bet * 2
        new_balance = balance - bet + winnings
        set_balance(ctx.author.id, new_balance)
        
        embed = discord.Embed(
            title="🎲 Ты выиграл!",
            description=f"Ролл: **{roll}** 🎉",
            color=discord.Color.green()
        )
        embed.add_field(name="Выигрыш", value=f"+{bet} 💵", inline=False)
        embed.add_field(name="Новый баланс", value=f"{new_balance} 💵", inline=False)
    else:
        # Loss
        new_balance = balance - bet
        set_balance(ctx.author.id, new_balance)
        
        embed = discord.Embed(
            title="🎲 Ты проиграл...",
            description=f"Ролл: **{roll}** 😢",
            color=discord.Color.red()
        )
        embed.add_field(name="Проигрыш", value=f"-{bet} 💵", inline=False)
        embed.add_field(name="Новый баланс", value=f"{new_balance} 💵", inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='daily')
async def daily(ctx):
    """Claim daily reward"""
    economy = load_economy()
    user_id_str = str(ctx.author.id)
    
    if user_id_str not in economy:
        economy[user_id_str] = {'balance': 1000, 'last_daily': 0}
    
    # Cooldown: once per 24 hours
    current_time = datetime.now().timestamp()
    last_daily = economy[user_id_str].get('last_daily', 0)
    
    if current_time - last_daily < 86400:  # 24 hours
        remaining = int(86400 - (current_time - last_daily))
        hours = remaining // 3600
        await ctx.send(f"⏰ Ты уже получал награду! Приди через {hours} часов.")
        return
    
    reward = 500
    economy[user_id_str]['balance'] += reward
    economy[user_id_str]['last_daily'] = current_time
    save_economy(economy)
    
    embed = discord.Embed(
        title="🎁 Ежедневная награда",
        description=f"Ты получил **{reward}** 💵",
        color=discord.Color.gold()
    )
    embed.add_field(name="Баланс", value=f"{economy[user_id_str]['balance']} 💵", inline=False)
    await ctx.send(embed=embed)

@bot.event
async def on_message(message):
    """Handle incoming messages"""
    # Don't respond to ourselves
    if message.author == bot.user:
        return
    
    # Process commands
    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors"""
    if isinstance(error, commands.CommandNotFound):
        await ctx.send(f"❌ Команда не найдена. Используйте `!help`")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Не хватает аргументов. Используйте `!help` для подсказки.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Неверный аргумент. Используйте `!help` для подсказки.")
    else:
        print(f"Error: {error}")

# Run the bot
if __name__ == '__main__':
    bot.run(TOKEN)