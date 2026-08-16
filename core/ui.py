from typing import Awaitable, Callable

import discord

PINK = discord.Colour(0xE91E63)

Handler = Callable[[discord.Interaction], Awaitable[None]]


class ActionButton(discord.ui.Button):
    """누르면 지정한 함수를 실행하는 버튼."""

    def __init__(self, label: str, handler: Handler,
                 style: discord.ButtonStyle = discord.ButtonStyle.secondary):
        super().__init__(label=label, style=style)
        self._handler = handler

    async def callback(self, interaction: discord.Interaction):
        await self._handler(interaction)


class Panel(discord.ui.LayoutView):
    def __init__(self, container: discord.ui.Container):
        super().__init__(timeout=None)
        self.add_item(container)


def panel(title: str,
          sections: list[tuple],
          footer: str | None = None,
          colour: discord.Colour = PINK,
          actions: list[discord.ui.Button] | None = None) -> Panel:
    """섹션은 (제목, 본문) 또는 (제목, 본문, 우측버튼) 형태."""
    items: list = [discord.ui.TextDisplay(f"## {title}")]

    for sec in sections:
        heading, body = sec[0], sec[1]
        accessory = sec[2] if len(sec) > 2 else None
        items.append(discord.ui.Separator())
        text = f"**{heading}**\n{body}" if heading else body
        if accessory is not None:
            items.append(discord.ui.Section(
                discord.ui.TextDisplay(text), accessory=accessory))
        else:
            items.append(discord.ui.TextDisplay(text))

    if footer:
        items.append(discord.ui.Separator())
        items.append(discord.ui.TextDisplay(f"-# {footer}"))

    if actions:
        items.append(discord.ui.Separator())
        for i in range(0, len(actions), 5):
            items.append(discord.ui.ActionRow(*actions[i:i + 5]))

    return Panel(discord.ui.Container(*items, accent_colour=colour))