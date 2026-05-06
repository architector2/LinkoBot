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
        update = {}
        if 'gdp' not in user: update['gdp'] = 0
        if 'last_collect' not in user: update['last_collect'] = 0
        if 'balance' not in user: update['balance'] = 0
        if 'population' not in user: update['population'] = 0
        if 'pop_growth_yearly' not in user: update['pop_growth_yearly'] = 2.0
        if 'last_pop_update' not in user: update['last_pop_update'] = 0
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

# ===== EVENTS =====

@bot.event
async def on_ready():
    print(f'✅ Bot logged in as {bot.user.name}')
    print(f'✅ Connected to MongoDB Atlas')
    await bot.change_presence(activity=discord.Game(name="Военная-политическая-игра"))

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    await bot.process_commands(message)

USAGE_HINTS = {
    'pay': '❌ Использование: `!pay @игрок <сумма>`',
    'give-vvp': '❌ Использование: `!give-vvp @игрок <сумма>`',
    'reforms': '❌ Использование: `!reforms <сумма>`',
    'naselprocent': '❌ Использование: `!naselprocent @игрок <1-100>`',
    'nasel-redakt': '❌ Использование: `!nasel-redakt @игрок <число>`',
}

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Команда не найдена. Используйте `!help`")
    elif isinstance(error, (commands.MissingRequiredArgument, commands.BadArgument)):
        hint = USAGE_HINTS.get(ctx.command.name)
        await ctx.send(hint if hint else "❌ Ошибка в аргументах.")
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏰ Подожди {error.retry_after:.1f} секунд!")
    elif not isinstance(error, commands.CheckFailure):
        pass

# ===========================
# ⚙️ COG: GENERAL
# ===========================

class General(commands.Cog, name="⚙️ Основные"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='help')
    async def help_command(self, ctx):
        embed = discord.Embed(title="📖 Список команд", color=discord.Color.blurple())
        excluded_cogs = {"👑 Админ"}
        for cog_name, cog in self.bot.cogs.items():
            if cog_name in excluded_cogs: continue
            cmds = cog.get_commands()
            if cmds:
                value = "\n".join(f"`!{c.name}` — {c.help or '...'}" for c in cmds)
                embed.add_field(name=cog_name, value=value, inline=False)
        await ctx.send(embed=embed)

    @commands.command(name='ping')
    async def ping(self, ctx):
        await ctx.send(f'Pong! 🏓 {round(self.bot.latency * 1000)}ms')

# ===========================
# 💰 COG: ECONOMY
# ===========================

class Economy(commands.Cog, name="💰 Экономика"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='balance')
    @is_registered()
    async def balance(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        user = await get_user(member.id)
        embed = discord.Embed(title=f"💰 Баланс {member.name}", description=f"**{user['balance']:,}** 💵", color=discord.Color.gold())
        await ctx.send(embed=embed)

    @commands.command(name='collect', aliases=['coll'])
    @is_registered()
    async def collect(self, ctx):
        """Собрать налоги и население (макс 12 часов)"""
        user = await get_user(ctx.author.id)
        if user['gdp'] <= 0:
            await ctx.send("❌ У тебя нет ВВП!")
            return

        current_time = datetime.now().timestamp()
        last_collect = user.get('last_collect', 0)
        
        # Считаем время (макс 12ч)
        hours_passed = (current_time - last_collect) / 3600 if last_collect > 0 else 1
        hours_passed = min(hours_passed, 12)

        if hours_passed < 1 and last_collect > 0:
            rem_mins = int((1 - hours_passed) * 60)
            await ctx.send(f"⏰ Подожди еще **{rem_mins}** мин. для сбора!")
            return

        # 1. Считаем деньги
        income_h = user['gdp'] / 48
        earned_money = int(income_h * hours_passed)
        
        # 2. Считаем население
        pop = user.get('population', 0)
        pop_gained = 0
        new_pop = pop
        if pop > 0:
            yearly_pct = user.get('pop_growth_yearly', 2.0)
            hourly_pct = yearly_pct / 48.0
            growth_factor = (1 + hourly_pct / 100) ** hours_passed
            new_pop = int(pop * growth_factor)
            pop_gained = new_pop - pop

        await update_user(ctx.author.id, {
            'balance': user['balance'] + earned_money,
            'population': new_pop,
            'last_collect': current_time,
            'last_pop_update': current_time
        })

        embed = discord.Embed(title="📦 Сбор ресурсов завершен", color=discord.Color.green())
        embed.add_field(name="💵 Деньги", value=f"+{earned_money:,} 💵", inline=True)
        if pop > 0:
            embed.add_field(name="👥 Население", value=f"+{pop_gained:,} чел.", inline=True)
        embed.set_footer(text=f"Собрано за {hours_passed:.1f} ч. накоплений")
        await ctx.send(embed=embed)

    @commands.command(name='cab')
    @is_registered()
    async def cab(self, ctx, member: discord.Member = None):
        """Статистика игрока"""
        member = member or ctx.author
        user = await get_user(member.id)
        current_time = datetime.now().timestamp()

        # Топ
        top_users = await economy_col.find().sort('balance', -1).to_list(length=None)
        pos = next((i + 1 for i, u in enumerate(top_users) if u['_id'] == str(member.id)), "—")

        # Расчет ожидаемого дохода (визуально)
        income_h = user['gdp'] / 48
        time_diff = (current_time - user.get('last_collect', 0)) / 3600 if user.get('last_collect', 0) > 0 else 0
        pending = int(income_h * min(time_diff, 12))

        embed = discord.Embed(title=f"📊 Кабинет: {member.name}", color=discord.Color.blurple())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="💰 Баланс", value=f"{user['balance']:,} 💵", inline=True)
        embed.add_field(name="📈 ВВП", value=f"{user['gdp']:,} 💵", inline=True)
        embed.add_field(name="🏆 Место", value=f"#{pos}", inline=True)
        embed.add_field(name="⏱️ В час", value=f"{income_h:,.0f} 💵", inline=True)
        embed.add_field(name="📦 Готово к сбору", value=f"{pending:,} 💵", inline=True)
        
        pop = user.get('population', 0)
        pop_str = f"👥 **{pop:,} чел.**\n📈 Прирост: **{user.get('pop_growth_yearly', 2.0):.2f}%** / год" if pop > 0 else "👥 Не выдано"
        embed.add_field(name="🌍 Население", value=pop_str, inline=False)
        await ctx.send(embed=embed)

    @commands.command(name='reforms')
    @is_registered()
    async def reforms(self, ctx, amount: int):
        user = await get_user(ctx.author.id)
        if amount <= 0 or user['balance'] < amount:
            await ctx.send("❌ Недостаточно средств.")
            return
        
        if amount > user['gdp'] * 2:
            await ctx.send(f"❌ Лимит инвестиции: {user['gdp']*2:,} 💵")
            return

        eff = 0.5 if user['gdp'] < 300e9 else 0.3 if user['gdp'] < 900e9 else 0.1
        gain = int(amount * eff)
        
        await update_user(ctx.author.id, {'balance': user['balance'] - amount, 'gdp': user['gdp'] + gain})
        await ctx.send(f"✅ Реформы проведены! ВВП: `+{gain:,}`")

    @commands.command(name='pay')
    @is_registered()
    async def pay(self, ctx, member: discord.Member, amount: int):
        if member.bot or member == ctx.author or amount <= 0: return
        sender = await get_user(ctx.author.id)
        if sender['balance'] < amount:
            await ctx.send("❌ Нет денег.")
            return
        
        receiver = await get_user(member.id)
        await update_user(ctx.author.id, {'balance': sender['balance'] - amount})
        await update_user(member.id, {'balance': receiver['balance'] + amount})
        await ctx.send(f"✅ {ctx.author.name} перевел {amount:,} 💵 игроку {member.name}")

# ===========================
# 👑 COG: ADMIN
# ===========================

class Admin(commands.Cog, name="👑 Админ"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='give-vvp')
    @commands.has_permissions(administrator=True)
    async def give_gdp(self, ctx, member: discord.Member, amount: int):
        user = await get_user(member.id)
        await update_user(member.id, {'gdp': user['gdp'] + amount})
        await ctx.send(f"✅ ВВП {member.name} изменен на {amount:,}")

    @commands.command(name='naselprocent')
    @commands.has_permissions(administrator=True)
    async def nasel_procent(self, ctx, member: discord.Member, percent: float):
        await update_user(member.id, {'pop_growth_yearly': percent})
        await ctx.send(f"✅ Прирост населения {member.name} теперь {percent}% в год")

    @commands.command(name='nasel-redakt')
    @commands.has_permissions(administrator=True)
    async def nasel_redakt(self, ctx, member: discord.Member, amount: int):
        user = await get_user(member.id)
        new_pop = max(0, user.get('population', 0) + amount)
        await update_user(member.id, {'population': new_pop, 'last_pop_update': datetime.now().timestamp()})
        await ctx.send(f"✅ Население {member.name} изменено. Итого: {new_pop:,}")

# ===== LOAD & RUN =====

@bot.event
async def setup_hook():
    await bot.add_cog(General(bot))
    await bot.add_cog(Economy(bot))
    await bot.add_cog(Admin(bot))

if __name__ == '__main__':
    bot.run(TOKEN)