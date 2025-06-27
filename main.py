import traceback

import discord
from discord.ext import commands

from env.config import Config

INITIAL_EXTENSIONS = [
    "cogs.tsukuba_rank",
    "cogs.tsukuba_student_rank",
    "cogs.help",
    "cogs.reminder",
    "cogs.result",
    "cogs.threads",
    "cogs.contest_data",
    "cogs.welcome",
]

config = Config()

TOKEN = config.token

intents = discord.Intents.all()
activity = discord.Activity(name="起動中", type=discord.ActivityType.playing)

bot = commands.Bot(command_prefix="/", intents=intents, activity=activity)


@bot.event
async def on_ready():
    await bot.change_presence(
        activity=discord.Activity(
            name=str(len(bot.guilds)) + "サーバー", type=discord.ActivityType.competing
        )
    )
    try:
        await bot.load_extension("jishaku")
        print("jishakuを読み込みました\n")
    except Exception as e:
        print(
            "jishakuの読み込み中にエラーが発生しました: ",
            "".join(traceback.format_exception(e)),
        )
    try:
        print("スラッシュコマンドを読み込み中...\n")
        await load_extension()
        print("スラッシュコマンドを読み込みました\n")
    except Exception as e:
        print(
            "スラッシュコマンドの読み込み中にエラーが発生しました: ",
            "".join(traceback.format_exception(e)),
        )

    try:
        print("スラッシュコマンドを同期中...")
        synced = await bot.tree.sync()
        print("スラッシュコマンドを同期しました: ", len(synced))
        print("-----------")
        print("起動しました")
        print("-----------")
    except Exception as e:
        print(
            "スラッシュコマンドの同期中にエラーが発生しました: ",
            "".join(traceback.format_exception(e)),
        )


async def load_extension():
    for cog in INITIAL_EXTENSIONS:
        try:
            await bot.load_extension(cog)
            print(f"{cog}を読み込みました")
        except Exception as e:
            print(
                f"{cog}の読み込み中にエラーが発生しました: ",
                "".join(traceback.format_exception(e)),
            )


@bot.tree.error
async def on_error(interaction, error):
    await discord.app_commands.CommandTree.on_error(bot.tree, interaction, error)
    err = "".join(traceback.format_exception(error))
    embed = discord.Embed(description=f"```py\n{err}\n```"[:4095])
    if interaction.response.is_done():
        await interaction.channel.send("An error has occurred.", embed=embed)
    else:
        await interaction.response.send_message("An error has occurred.", embed=embed)


bot.run(token=TOKEN)
