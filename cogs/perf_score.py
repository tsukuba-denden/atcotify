import math
import re

import discord
from discord import app_commands
from discord.ext import commands


NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")


def perf_to_score(performance: float) -> float:
    return 1000 * (2 ** (performance / 400))


def displayed_perf_to_internal_perf(performance: float) -> float:
    if performance <= 0:
        raise ValueError("displayed performance must be positive")
    if performance >= 400:
        return performance
    return 400 + 400 * math.log(performance / 400)


def internal_perf_to_displayed_perf(performance: float) -> float:
    if performance >= 400:
        return performance
    return 400 / math.exp((400 - performance) / 400)


def perfs_to_score(performances: list[float]) -> float:
    return sum(perf_to_score(performance) for performance in performances)


def score_to_perf(score: float) -> float:
    if score <= 0:
        raise ValueError("score must be positive")
    return 400 * math.log2(score / 1000)


def parse_numbers(value: str) -> list[float]:
    return [float(match.group()) for match in NUMBER_PATTERN.finditer(value)]


def format_number(value: float) -> str:
    rounded = round(value)
    if math.isclose(value, rounded, abs_tol=0.000001):
        return f"{rounded:,}"
    return f"{value:,.3f}"


class PerfScore(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="perf_score_convert",
        description="AJLのperfとscoreを相互変換します。",
    )
    @app_commands.describe(
        mode="変換方向",
        value="変換する値。複数perfはカンマ・空白区切りで入力できます。",
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="内部perf -> score", value="internal_perf_to_score"),
            app_commands.Choice(name="表示perf -> score", value="displayed_perf_to_score"),
            app_commands.Choice(name="score -> 内部perf", value="score_to_internal_perf"),
            app_commands.Choice(name="score -> 表示perf", value="score_to_displayed_perf"),
            app_commands.Choice(
                name="複数内部perf -> 合計score",
                value="internal_perfs_to_score",
            ),
            app_commands.Choice(
                name="複数表示perf -> 合計score",
                value="displayed_perfs_to_score",
            ),
        ]
    )
    async def perf_score_convert(
        self,
        interaction: discord.Interaction,
        mode: app_commands.Choice[str],
        value: str,
    ):
        numbers = parse_numbers(value)
        if not numbers:
            await interaction.response.send_message(
                "数値を入力してください。例: `1200` / `800, 1200, 1600`",
                ephemeral=True,
            )
            return

        try:
            if mode.value == "score_to_internal_perf":
                score = numbers[0]
                performance = score_to_perf(score)
                description = (
                    f"score `{format_number(score)}` は、単一コンテスト換算で "
                    f"内部perf `{format_number(performance)}` です。"
                )
            elif mode.value == "score_to_displayed_perf":
                score = numbers[0]
                internal_performance = score_to_perf(score)
                displayed_performance = internal_perf_to_displayed_perf(
                    internal_performance
                )
                description = (
                    f"score `{format_number(score)}` は、単一コンテスト換算で "
                    f"表示perf `{format_number(displayed_performance)}` です。"
                )
            elif mode.value == "internal_perfs_to_score":
                score = perfs_to_score(numbers)
                perf_values = ", ".join(format_number(number) for number in numbers)
                description = (
                    f"内部perf `{perf_values}` の合計scoreは "
                    f"`{format_number(score)}` です。"
                )
            elif mode.value == "displayed_perfs_to_score":
                internal_performances = [
                    displayed_perf_to_internal_perf(number) for number in numbers
                ]
                score = perfs_to_score(internal_performances)
                perf_values = ", ".join(format_number(number) for number in numbers)
                description = (
                    f"表示perf `{perf_values}` の合計scoreは "
                    f"`{format_number(score)}` です。"
                )
            elif mode.value == "displayed_perf_to_score":
                performance = numbers[0]
                internal_performance = displayed_perf_to_internal_perf(performance)
                score = perf_to_score(internal_performance)
                description = (
                    f"表示perf `{format_number(performance)}` のscoreは "
                    f"`{format_number(score)}` です。"
                )
            else:
                performance = numbers[0]
                score = perf_to_score(performance)
                description = (
                    f"内部perf `{format_number(performance)}` のscoreは "
                    f"`{format_number(score)}` です。"
                )
        except ValueError:
            await interaction.response.send_message(
                "scoreと表示perfは正の数を入力してください。",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="perf / score 変換",
            description=description,
            color=discord.Color.blue(),
        )
        embed.set_footer(text="score = 1000 * sum(2^(perf / 400))")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(PerfScore(bot))
