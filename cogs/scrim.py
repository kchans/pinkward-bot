import discord
from discord import app_commands
from discord.ext import commands

from core.balance import balance_all
from core.db import pool
from core.ovr import POSITIONS, POSITION_KO

DEFAULT_OVR = 50
FULL = 10
PINK = 0xE91E63

PLAYERS_SQL = """
select sp.puuid, sp.locked_position, s.game_name, s.tag_line,
       gm.discord_user_id, gm.is_virtual, gm.display_name,
       pr.position, pr.ovr
from scrim_participants sp
join guild_members gm on gm.puuid = sp.puuid and gm.guild_id = $2
join summoners s      on s.puuid  = sp.puuid
left join position_ratings pr on pr.puuid = sp.puuid
where sp.scrim_id = $1
order by sp.joined_at
"""

CANDIDATES_SQL = """
select s.puuid, s.game_name, s.tag_line, gm.is_virtual, gm.display_name
from guild_members gm
join summoners s on s.puuid = gm.puuid
where gm.guild_id = $1
  and gm.puuid not in (select puuid from scrim_participants where scrim_id = $2)
order by gm.is_virtual, s.game_name
limit 25
"""


# ---------- 데이터 ----------

async def get_scrim(scrim_id: int):
    async with pool().acquire() as conn:
        return await conn.fetchrow(
            "select id, host_id, channel_id, message_id, status, games_played "
            "from scrims where id = $1", scrim_id)


async def fetch_players(scrim_id: int, guild_id: int) -> list[dict]:
    async with pool().acquire() as conn:
        rows = await conn.fetch(PLAYERS_SQL, scrim_id, guild_id)

    players: dict[str, dict] = {}
    for r in rows:
        p = players.setdefault(r["puuid"], {
            "puuid": r["puuid"],
            "game_name": r["game_name"],
            "tag_line": r["tag_line"],
            "display_name": r["display_name"],
            "discord_user_id": r["discord_user_id"],
            "is_virtual": r["is_virtual"],
            "lock": r["locked_position"],
            "ovr": {pos: DEFAULT_OVR for pos in POSITIONS},
        })
        if r["position"]:
            p["ovr"][r["position"]] = r["ovr"]
    return list(players.values())


def label(p) -> str:
    if p["is_virtual"]:
        return p["display_name"] or p["game_name"]
    return f"<@{p['discord_user_id']}>"


def plain(p) -> str:
    """셀렉트 옵션용 순수 텍스트 이름."""
    if p["is_virtual"]:
        return p["display_name"] or f"{p['game_name']}#{p['tag_line']}"
    return f"{p['game_name']}#{p['tag_line']}"


async def lock_taken(conn, scrim_id: int, lock: str, puuid: str) -> bool:
    n = await conn.fetchval(
        "select count(*) from scrim_participants "
        "where scrim_id = $1 and locked_position = $2 and puuid <> $3",
        scrim_id, lock, puuid)
    return n >= 2


async def save_teams(scrim_id: int, players, cand) -> None:
    _, (a_idx, a_pos, _), (b_idx, b_pos, _) = cand
    async with pool().acquire() as conn:
        async with conn.transaction():
            for team, idxs, poss in ((1, a_idx, a_pos), (2, b_idx, b_pos)):
                for k, i in enumerate(idxs):
                    await conn.execute(
                        "update scrim_participants set team = $1, position = $2 "
                        "where scrim_id = $3 and puuid = $4",
                        team, poss[k], scrim_id, players[i]["puuid"])
            await conn.execute(
                "update scrims set status = 'drafted' where id = $1", scrim_id)


async def record_result(guild_id: int, scrim_id: int, winner: int) -> int:
    async with pool().acquire() as conn:
        async with conn.transaction():
            n = await conn.fetchval(
                "update scrims set games_played = games_played + 1 "
                "where id = $1 returning games_played", scrim_id)
            match_id = f"SCRIM-{scrim_id}-{n}"
            await conn.execute(
                "insert into matches (match_id, source, guild_id, game_start) "
                "values ($1, 'scrim', $2, now()) on conflict do nothing",
                match_id, guild_id)
            rows = await conn.fetch(
                "select puuid, team, position from scrim_participants "
                "where scrim_id = $1 and team is not null", scrim_id)
            for r in rows:
                await conn.execute(
                    "insert into match_participants "
                    "(match_id, puuid, team_id, position, win) "
                    "values ($1,$2,$3,$4,$5) on conflict do nothing",
                    match_id, r["puuid"], r["team"] * 100,
                    r["position"], r["team"] == winner)
    return n


async def move_players(guild: discord.Guild, scrim_id: int,
                       blue_id: int, red_id: int) -> tuple[int, list[str]]:
    """배정된 팀에 따라 참가자를 음성채널로 옮긴다."""
    async with pool().acquire() as conn:
        rows = await conn.fetch(
            "select sp.discord_user_id, sp.team, gm.is_virtual, "
            "       gm.display_name, s.game_name "
            "from scrim_participants sp "
            "join guild_members gm on gm.puuid = sp.puuid and gm.guild_id = $2 "
            "join summoners s      on s.puuid  = sp.puuid "
            "where sp.scrim_id = $1 and sp.team is not null",
            scrim_id, guild.id)

    channels = {1: guild.get_channel(blue_id), 2: guild.get_channel(red_id)}
    moved, skipped = 0, []

    for r in rows:
        if r["is_virtual"]:
            skipped.append(r["display_name"] or r["game_name"])
            continue
        member = guild.get_member(r["discord_user_id"])
        if member is None:
            try:
                member = await guild.fetch_member(r["discord_user_id"])
            except discord.NotFound:
                continue
        if member.voice is None or member.voice.channel is None:
            skipped.append(member.display_name)
            continue
        try:
            await member.move_to(channels[r["team"]])
            moved += 1
        except discord.Forbidden:
            raise
        except discord.HTTPException:
            skipped.append(member.display_name)

    return moved, skipped


# ---------- 임베드 ----------

def recruit_embed(players, scrim) -> discord.Embed:
    lines = []
    for i, p in enumerate(players, 1):
        lock = f"  `{POSITION_KO[p['lock']]}`" if p["lock"] else ""
        lines.append(f"`{i:>2}.` {label(p)}{lock}")
    embed = discord.Embed(
        title="내전 모집",
        description=f"주최자: <@{scrim['host_id']}>\n\n"
                    + ("\n".join(lines) or "아직 참가자가 없습니다."),
        color=PINK)
    embed.set_footer(text=f"{len(players)} / {FULL} 명"
                          + ("  ·  포지션 표시는 고정된 라인" if any(
                              p["lock"] for p in players) else ""))
    return embed


def team_embed(players, cand, index: int, total: int) -> discord.Embed:
    diff, (a_idx, a_pos, a_sum), (b_idx, b_pos, b_sum) = cand
    embed = discord.Embed(title="팀 배정 완료", color=PINK)
    for name, idxs, poss, ovr_sum in (("블루팀", a_idx, a_pos, a_sum),
                                      ("레드팀", b_idx, b_pos, b_sum)):
        by_pos = {poss[k]: players[i] for k, i in enumerate(idxs)}
        body = "\n".join(
            f"`{POSITION_KO[pos]:<3}` {label(by_pos[pos])} "
            f"— {by_pos[pos]['ovr'][pos]}"
            f"{' 🔒' if by_pos[pos]['lock'] else ''}"
            for pos in POSITIONS)
        embed.add_field(name=f"{name}  (전력 {ovr_sum})", value=body, inline=False)
    embed.set_footer(text=f"전력 차 {diff}점 · 후보 {index + 1}/{total}")
    return embed


async def refresh_public(guild: discord.Guild, scrim_id: int) -> None:
    scrim = await get_scrim(scrim_id)
    if scrim is None or not scrim["message_id"]:
        return
    channel = guild.get_channel(scrim["channel_id"])
    if channel is None:
        return
    try:
        msg = await channel.fetch_message(scrim["message_id"])
    except discord.NotFound:
        return
    players = await fetch_players(scrim_id, guild.id)
    await msg.edit(embed=recruit_embed(players, scrim))


# ---------- 주최자 메뉴 ----------

class AddSelect(discord.ui.Select):
    def __init__(self, scrim_id: int, rows):
        super().__init__(
            placeholder="참가자 추가",
            row=0,
            options=[discord.SelectOption(
                label=plain(r)[:100],
                value=r["puuid"],
                description="테스트 계정" if r["is_virtual"] else None)
                for r in rows])
        self.scrim_id = scrim_id

    async def callback(self, interaction: discord.Interaction):
        puuid = self.values[0]
        async with pool().acquire() as conn:
            count = await conn.fetchval(
                "select count(*) from scrim_participants where scrim_id = $1",
                self.scrim_id)
            if count >= FULL:
                await interaction.response.send_message(
                    "이미 10명이 찼습니다.", ephemeral=True)
                return
            uid = await conn.fetchval(
                "select discord_user_id from guild_members "
                "where guild_id = $1 and puuid = $2",
                interaction.guild_id, puuid)
            await conn.execute(
                "insert into scrim_participants (scrim_id, puuid, discord_user_id) "
                "values ($1,$2,$3) on conflict do nothing",
                self.scrim_id, puuid, uid)
        await refresh_public(interaction.guild, self.scrim_id)
        await rerender_manage(interaction, self.scrim_id)


class RemoveSelect(discord.ui.Select):
    def __init__(self, scrim_id: int, players):
        super().__init__(
            placeholder="참가자 제외",
            row=1,
            options=[discord.SelectOption(label=plain(p)[:100], value=p["puuid"])
                     for p in players[:25]])
        self.scrim_id = scrim_id

    async def callback(self, interaction: discord.Interaction):
        async with pool().acquire() as conn:
            await conn.execute(
                "delete from scrim_participants where scrim_id = $1 and puuid = $2",
                self.scrim_id, self.values[0])
        await refresh_public(interaction.guild, self.scrim_id)
        await rerender_manage(interaction, self.scrim_id)


class AssignTargetSelect(discord.ui.Select):
    def __init__(self, scrim_id: int, players):
        super().__init__(
            placeholder="포지션 지정할 참가자",
            row=2,
            options=[discord.SelectOption(
                label=plain(p)[:100],
                value=p["puuid"],
                description=f"현재: {POSITION_KO[p['lock']]} 고정" if p["lock"] else None)
                for p in players[:25]])
        self.scrim_id = scrim_id

    async def callback(self, interaction: discord.Interaction):
        view = discord.ui.View(timeout=120)
        view.add_item(AssignPositionSelect(self.scrim_id, self.values[0]))
        await interaction.response.send_message(
            "고정할 포지션을 고르세요.", view=view, ephemeral=True)


class AssignPositionSelect(discord.ui.Select):
    def __init__(self, scrim_id: int, puuid: str):
        super().__init__(
            placeholder="포지션 선택",
            options=[discord.SelectOption(label="자동 배정", value="AUTO")]
                    + [discord.SelectOption(label=POSITION_KO[p], value=p)
                       for p in POSITIONS])
        self.scrim_id = scrim_id
        self.puuid = puuid

    async def callback(self, interaction: discord.Interaction):
        value = None if self.values[0] == "AUTO" else self.values[0]
        async with pool().acquire() as conn:
            if value and await lock_taken(conn, self.scrim_id, value, self.puuid):
                await interaction.response.edit_message(
                    content=f"{POSITION_KO[value]} 는 이미 2명이 고정했습니다.", view=None)
                return
            await conn.execute(
                "update scrim_participants set locked_position = $1 "
                "where scrim_id = $2 and puuid = $3",
                value, self.scrim_id, self.puuid)
        await refresh_public(interaction.guild, self.scrim_id)
        name = "자동 배정" if value is None else POSITION_KO[value]
        await interaction.response.edit_message(content=f"{name} 으로 설정했습니다.", view=None)


class ManageView(discord.ui.View):
    def __init__(self, scrim_id: int, candidates, players):
        super().__init__(timeout=600)
        self.scrim_id = scrim_id
        if candidates:
            self.add_item(AddSelect(scrim_id, candidates))
        if players:
            self.add_item(RemoveSelect(scrim_id, players))
            self.add_item(AssignTargetSelect(scrim_id, players))

    @discord.ui.button(label="내전 종료", style=discord.ButtonStyle.danger, row=3)
    async def finish(self, interaction: discord.Interaction, _b: discord.ui.Button):
        async with pool().acquire() as conn:
            played = await conn.fetchval(
                "update scrims set status = 'done' where id = $1 "
                "returning games_played", self.scrim_id)
        await interaction.response.edit_message(
            content=f"내전을 종료했습니다. (기록된 세트: {played})",
            embed=None, view=None)


async def build_manage(guild: discord.Guild, scrim_id: int):
    players = await fetch_players(scrim_id, guild.id)
    async with pool().acquire() as conn:
        candidates = await conn.fetch(CANDIDATES_SQL, guild.id, scrim_id)

    embed = discord.Embed(title="주최자 메뉴", color=PINK,
                          description=f"현재 {len(players)} / {FULL} 명")
    if not candidates:
        embed.add_field(name="참가자 추가", value="추가할 등록 계정이 없습니다.",
                        inline=False)
    return embed, ManageView(scrim_id, candidates, players)


async def rerender_manage(interaction: discord.Interaction, scrim_id: int):
    embed, view = await build_manage(interaction.guild, scrim_id)
    await interaction.response.edit_message(embed=embed, view=view)


# ---------- 결과 ----------

class VoiceSetupView(discord.ui.View):
    """팀별 음성채널 지정."""

    def __init__(self, scrim_id: int):
        super().__init__(timeout=300)
        self.scrim_id = scrim_id
        self.blue_id: int | None = None
        self.red_id: int | None = None

    @discord.ui.select(cls=discord.ui.ChannelSelect, row=0,
                       placeholder="블루팀 음성채널",
                       channel_types=[discord.ChannelType.voice])
    async def pick_blue(self, interaction: discord.Interaction, select):
        self.blue_id = select.values[0].id
        await interaction.response.defer()

    @discord.ui.select(cls=discord.ui.ChannelSelect, row=1,
                       placeholder="레드팀 음성채널",
                       channel_types=[discord.ChannelType.voice])
    async def pick_red(self, interaction: discord.Interaction, select):
        self.red_id = select.values[0].id
        await interaction.response.defer()

    @discord.ui.button(label="저장하고 이동", style=discord.ButtonStyle.success, row=2)
    async def save_and_move(self, interaction: discord.Interaction,
                            _b: discord.ui.Button):
        if not self.blue_id or not self.red_id:
            await interaction.response.send_message(
                "두 채널을 모두 골라주세요.", ephemeral=True)
            return
        if self.blue_id == self.red_id:
            await interaction.response.send_message(
                "블루팀과 레드팀 채널이 같습니다.", ephemeral=True)
            return

        await interaction.response.defer()
        async with pool().acquire() as conn:
            await conn.execute(
                "update guilds set blue_channel_id = $1, red_channel_id = $2 "
                "where guild_id = $3",
                self.blue_id, self.red_id, interaction.guild_id)

        try:
            moved, skipped = await move_players(
                interaction.guild, self.scrim_id, self.blue_id, self.red_id)
        except discord.Forbidden:
            await interaction.edit_original_response(
                content="봇에게 **멤버 이동** 권한이 없습니다. "
                        "서버 설정 → 역할에서 봇 역할에 권한을 켜주세요.", view=None)
            return

        text = f"채널을 저장하고 {moved}명을 이동했습니다."
        if skipped:
            text += f"\n이동 불가: {', '.join(skipped)}"
        await interaction.edit_original_response(content=text, view=None)


class ResultView(discord.ui.View):
    def __init__(self, scrim_id: int, host_id: int, guild_id: int,
                 players, candidates, index: int = 0):
        super().__init__(timeout=None)
        self.scrim_id, self.host_id, self.guild_id = scrim_id, host_id, guild_id
        self.players, self.candidates, self.index = players, candidates, index

    async def _host_only(self, interaction) -> bool:
        if interaction.user.id != self.host_id:
            await interaction.response.send_message(
                "주최자만 실행할 수 있습니다.", ephemeral=True)
            return False
        return True

    async def _win(self, interaction: discord.Interaction, team: int, name: str):
        if not await self._host_only(interaction):
            return
        await interaction.response.defer()
        game_no = await record_result(self.guild_id, self.scrim_id, team)
        for child in self.children:
            child.disabled = True
        await interaction.edit_original_response(view=self)
        await interaction.followup.send(
            f"**{game_no}세트 — {name} 승리** 기록 완료\n"
            "다음 세트는 `/내전`, 전적은 `/내전순위`")

    @discord.ui.button(label="블루팀 승리", style=discord.ButtonStyle.primary, row=0)
    async def blue(self, interaction: discord.Interaction, _b: discord.ui.Button):
        await self._win(interaction, 1, "블루팀")

    @discord.ui.button(label="레드팀 승리", style=discord.ButtonStyle.danger, row=0)
    async def red(self, interaction: discord.Interaction, _b: discord.ui.Button):
        await self._win(interaction, 2, "레드팀")

    @discord.ui.button(label="다시 짜기", style=discord.ButtonStyle.secondary, row=0)
    async def reroll(self, interaction: discord.Interaction, _b: discord.ui.Button):
        if not await self._host_only(interaction):
            return
        await interaction.response.defer()
        self.index = (self.index + 1) % len(self.candidates)
        cand = self.candidates[self.index]
        await save_teams(self.scrim_id, self.players, cand)
        await interaction.edit_original_response(
            embed=team_embed(self.players, cand, self.index, len(self.candidates)),
            view=self)

    @discord.ui.button(label="음성채널 이동", style=discord.ButtonStyle.success, row=1)
    async def move_voice(self, interaction: discord.Interaction, _b: discord.ui.Button):
        if not await self._host_only(interaction):
            return

        async with pool().acquire() as conn:
            row = await conn.fetchrow(
                "select blue_channel_id, red_channel_id from guilds where guild_id = $1",
                interaction.guild_id)

        blue = interaction.guild.get_channel(row["blue_channel_id"]) if row and row["blue_channel_id"] else None
        red = interaction.guild.get_channel(row["red_channel_id"]) if row and row["red_channel_id"] else None

        if blue is None or red is None:
            await interaction.response.send_message(
                "팀별 음성채널을 지정해주세요. 한 번만 정해두면 다음부터는 자동입니다.",
                view=VoiceSetupView(self.scrim_id), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            moved, skipped = await move_players(
                interaction.guild, self.scrim_id, blue.id, red.id)
        except discord.Forbidden:
            await interaction.followup.send(
                "봇에게 **멤버 이동** 권한이 없습니다. "
                "서버 설정 → 역할에서 봇 역할에 권한을 켜주세요.", ephemeral=True)
            return

        text = f"{moved}명 이동 완료 · {blue.name} / {red.name}"
        if skipped:
            text += f"\n이동 불가: {', '.join(skipped)}"
        await interaction.followup.send(text, ephemeral=True)

    @discord.ui.button(label="채널 재설정", style=discord.ButtonStyle.secondary, row=1)
    async def reset_voice(self, interaction: discord.Interaction, _b: discord.ui.Button):
        if not await self._host_only(interaction):
            return
        await interaction.response.send_message(
            "팀별 음성채널을 다시 지정하세요.",
            view=VoiceSetupView(self.scrim_id), ephemeral=True)


# ---------- 공개 모집창 ----------

class MyPositionSelect(discord.ui.Select):
    def __init__(self, scrim_id: int):
        super().__init__(
            placeholder="내 포지션 고정 (선택 사항)",
            row=1,
            options=[discord.SelectOption(label="자동 배정", value="AUTO")]
                    + [discord.SelectOption(label=POSITION_KO[p], value=p)
                       for p in POSITIONS])
        self.scrim_id = scrim_id

    async def callback(self, interaction: discord.Interaction):
        value = None if self.values[0] == "AUTO" else self.values[0]
        async with pool().acquire() as conn:
            row = await conn.fetchrow(
                "select puuid from scrim_participants "
                "where scrim_id = $1 and discord_user_id = $2",
                self.scrim_id, interaction.user.id)
            if row is None:
                await interaction.response.send_message(
                    "먼저 참가 버튼을 눌러주세요.", ephemeral=True)
                return
            if value and await lock_taken(conn, self.scrim_id, value, row["puuid"]):
                await interaction.response.send_message(
                    f"{POSITION_KO[value]} 는 이미 2명이 고정했습니다.", ephemeral=True)
                return
            await conn.execute(
                "update scrim_participants set locked_position = $1 "
                "where scrim_id = $2 and puuid = $3",
                value, self.scrim_id, row["puuid"])
        await self.view.refresh(interaction)


class RecruitView(discord.ui.View):
    def __init__(self, scrim_id: int, host_id: int):
        super().__init__(timeout=None)
        self.scrim_id, self.host_id = scrim_id, host_id
        self.add_item(MyPositionSelect(scrim_id))

    async def refresh(self, interaction: discord.Interaction):
        scrim = await get_scrim(self.scrim_id)
        players = await fetch_players(self.scrim_id, interaction.guild_id)
        await interaction.response.edit_message(
            embed=recruit_embed(players, scrim), view=self)

    @discord.ui.button(label="참가", style=discord.ButtonStyle.success, row=0)
    async def join(self, interaction: discord.Interaction, _b: discord.ui.Button):
        async with pool().acquire() as conn:
            row = await conn.fetchrow(
                "select puuid from guild_members "
                "where guild_id = $1 and discord_user_id = $2 "
                "order by is_main desc limit 1",
                interaction.guild_id, interaction.user.id)
            if row is None:
                await interaction.response.send_message(
                    "먼저 `/등록` 으로 계정을 연결하세요.", ephemeral=True)
                return
            count = await conn.fetchval(
                "select count(*) from scrim_participants where scrim_id = $1",
                self.scrim_id)
            if count >= FULL:
                await interaction.response.send_message(
                    "이미 10명이 찼습니다.", ephemeral=True)
                return
            await conn.execute(
                "insert into scrim_participants (scrim_id, puuid, discord_user_id) "
                "values ($1,$2,$3) on conflict do nothing",
                self.scrim_id, row["puuid"], interaction.user.id)
        await self.refresh(interaction)

    @discord.ui.button(label="나가기", style=discord.ButtonStyle.secondary, row=0)
    async def leave(self, interaction: discord.Interaction, _b: discord.ui.Button):
        async with pool().acquire() as conn:
            await conn.execute(
                "delete from scrim_participants "
                "where scrim_id = $1 and discord_user_id = $2",
                self.scrim_id, interaction.user.id)
        await self.refresh(interaction)

    @discord.ui.button(label="팀 짜기", style=discord.ButtonStyle.primary, row=0)
    async def draft(self, interaction: discord.Interaction, _b: discord.ui.Button):
        if interaction.user.id != self.host_id:
            await interaction.response.send_message(
                "주최자만 실행할 수 있습니다.", ephemeral=True)
            return

        players = await fetch_players(self.scrim_id, interaction.guild_id)
        if len(players) != FULL:
            await interaction.response.send_message(
                f"10명이 모여야 합니다. (현재 {len(players)}명)", ephemeral=True)
            return

        await interaction.response.defer()
        candidates = balance_all(players)
        if not candidates:
            await interaction.followup.send(
                "포지션 고정이 충돌해 팀을 나눌 수 없습니다. "
                "같은 포지션을 3명 이상 고정하지 않았는지 확인하세요.", ephemeral=True)
            return

        await save_teams(self.scrim_id, players, candidates[0])
        for child in self.children:
            child.disabled = True
        await interaction.edit_original_response(view=self)

        await interaction.followup.send(
            embed=team_embed(players, candidates[0], 0, len(candidates)),
            view=ResultView(self.scrim_id, self.host_id, interaction.guild_id,
                            players, candidates))

    @discord.ui.button(label="주최자 메뉴", style=discord.ButtonStyle.secondary, row=2)
    async def manage(self, interaction: discord.Interaction, _b: discord.ui.Button):
        if interaction.user.id != self.host_id:
            await interaction.response.send_message(
                "주최자만 열 수 있습니다.", ephemeral=True)
            return
        embed, view = await build_manage(interaction.guild, self.scrim_id)
        await interaction.response.send_message(
            embed=embed, view=view, ephemeral=True)


class Scrim(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="내전", description="내전을 시작합니다.")
    @app_commands.guild_only()
    async def scrim(self, interaction: discord.Interaction):
        async with pool().acquire() as conn:
            await conn.execute(
                "update scrims set status = 'cancelled' "
                "where guild_id = $1 and status = 'recruiting'",
                interaction.guild_id)
            scrim_id = await conn.fetchval(
                "insert into scrims (guild_id, channel_id, host_id) "
                "values ($1,$2,$3) returning id",
                interaction.guild_id, interaction.channel_id, interaction.user.id)

        scrim = await get_scrim(scrim_id)
        await interaction.response.send_message(
            embed=recruit_embed([], scrim),
            view=RecruitView(scrim_id, interaction.user.id))
        msg = await interaction.original_response()

        async with pool().acquire() as conn:
            await conn.execute(
                "update scrims set message_id = $1 where id = $2", msg.id, scrim_id)


async def setup(bot: commands.Bot):
    await bot.add_cog(Scrim(bot))