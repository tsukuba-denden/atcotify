import os

import discord
from discord import app_commands


def _allowed_school_admin_user_ids() -> set[int]:
    raw_user_ids = os.getenv("SCHOOL_ADMIN_USER_IDS", "")
    user_ids = set()
    for raw_user_id in raw_user_ids.replace(" ", "").split(","):
        if raw_user_id.isdigit():
            user_ids.add(int(raw_user_id))
    return user_ids


def can_manage_school_settings():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.permissions.administrator:
            return True
        if interaction.user.id in _allowed_school_admin_user_ids():
            return True
        raise app_commands.MissingPermissions(["administrator"])

    return app_commands.check(predicate)
