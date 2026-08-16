import discord
from discord import app_commands
from discord.ext import commands

from core.db import pool
from core.stocks import (KIND_KO, KINDS, MIN_ORDER, get_cash,
                         place_buy, place_sell)
from core.ui import ActionButton, panel
from core.stocks import (DAILY_REWARD, KIND_KO, KINDS, MIN_ORDER, START_CASH,
                         get_cash, place_buy, place_sell, tick as stock_tick)

LIST_SQL = """
select l.puuid, s.game_name, gm.display_name, gm.is_virtual,
       p.price, p.prev_price
from stock_listings l
join summoners s      on s.puuid = l.puuid
join guild_members gm on gm.puuid = l.puuid and gm.guild_id = $1
join stock_prices p   on p.puuid = l.puuid and p.kind = $2
where not l.delisted
order by p.price desc
"""

HOLDINGS_SQL = """
select h.puuid, h.kind, h.shares, h.avg_cost, p.price,
       s.game_name, gm.display_name, gm.is_virtual
from holdings h
join stock_prices p   on p.puuid = h.puuid and p.kind = h.kind
join summoners s      on s.puuid = h.puuid
left join guild_members gm on gm.puuid = h.puuid and gm.guild_id = h.guild_id
where h.guild_id = $1 and h.discord_user_id = $2 and h.shares > 0.0001
order by h.shares * p.price desc
"""

PENDING_SQL = """
select o.side, o.kind, o.amount, s.game_name, gm.display_name, gm.is_virtual
from stock_orders o
join summoners s      on s.puuid = o.puuid
left join guild_members gm on gm.puuid = o.puuid and gm.guild_id = o.guild_id
where o.guild_id = $1 and o.discord_user_id = $2 and o.status = 'pending'
order by o.created_at
"""

RANKING_SQL = """
select w.discord_user_id, w.cash,
       coalesce(sum(h.shares * p.price), 0) as equity
from wallets w
left join holdings h on h.guild_id = w.guild_id
                    and h.discord_user_id = w.discord_user_id
left join stock_prices p on p.puuid = h.puuid and p.kind = h.kind
where w.guild_id = $1
group by w.discord_user_id, w.cash
order by w.cash + coalesce(sum(h.shares * p.price), 0) desc
limit 20
"""

KIND_CHOICES = [app_commands.Choice(name=KIND_KO[k], value=k) for k in KINDS]


def stock_name(r) -> str:
    if r.get("is_virtual") if isinstance(r, dict) else r["is_virtual"]:
        return r["display_name"] or r["game_name"]
    return r["game_name"]


class Stocks(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------- 종목 자동완성 ----------

    async def stock_autocomplete(self, interaction: discord.Interaction,
                                 current: str) -> list[app_commands.Choice[str]]:
        async with pool().acquire() as conn:
            rows = await conn.fetch(LIST_SQL, interaction.guild_id, "L1")
        out = []
        for r in rows:
            name = stock_name(r)
            if current and current.lower() not in name.lower():
                continue
            out.append(app_commands.Choice(
                name=f"{name} · {r['price']:,.0f}", value=r["puuid"]))
            if len(out) >= 25:
                break
        return out

    # ---------- 시세 ----------

    def _switch(self, kind: str):
        async def handler(interaction: discord.Interaction):
            view = await self._market_panel(interaction.guild, kind)
            await interaction.response.edit_message(view=view)
        return handler

    async def _market_panel(self, guild: discord.Guild, kind: str):
        async with pool().acquire() as conn:
            rows = await conn.fetch(LIST_SQL, guild.id, kind)

        if not rows:
            body = "상장된 종목이 없습니다. `/전체갱신` 으로 티어를 먼저 받아주세요."
        else:
            lines = []
            for i, r in enumerate(rows, 1):
                prev = r["prev_price"] or r["price"]
                rate = (r["price"] - prev) / prev * 100 if prev else 0
                arrow = "▲" if rate > 0.05 else ("▼" if rate < -0.05 else "―")
                lines.append(f"`{i:>2}.` **{stock_name(r)}** — "
                             f"{r['price']:,.0f} `{arrow}{abs(rate):.1f}%`")
            body = "\n".join(lines)

        buttons = [
            ActionButton(KIND_KO[k], self._switch(k),
                         discord.ButtonStyle.primary if k == kind
                         else discord.ButtonStyle.secondary)
            for k in KINDS]

        return panel(f"{guild.name} 시세 · {KIND_KO[kind]}", [("", body)],
                     footer="주문은 다음 시세 갱신 때 체결됩니다 · 30분 주기",
                     actions=buttons)

    @app_commands.command(name="시세", description="종목 시세를 봅니다.")
    @app_commands.guild_only()
    async def market(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        await interaction.followup.send(
            view=await self._market_panel(interaction.guild, "L1"))

    # ---------- 매수 ----------

    @app_commands.command(name="매수", description="예약 매수 주문을 넣습니다.")
    @app_commands.rename(stock="종목", kind="상품", amount="금액")
    @app_commands.describe(amount="투자할 코인 금액")
    @app_commands.choices(kind=KIND_CHOICES)
    @app_commands.autocomplete(stock=stock_autocomplete)
    @app_commands.guild_only()
    async def buy(self, interaction: discord.Interaction, stock: str,
                  kind: app_commands.Choice[str], amount: int):
        await interaction.response.defer(ephemeral=True)
        err = await place_buy(interaction.guild_id, interaction.user.id,
                              stock, kind.value, float(amount))
        if err:
            await interaction.followup.send(err)
            return
        cash = await get_cash(interaction.guild_id, interaction.user.id)
        await interaction.followup.send(
            f"매수 예약 완료 · {kind.name} {amount:,} 코인\n"
            f"다음 시세 갱신 때 체결됩니다. 잔액 {cash:,.0f}")

    # ---------- 매도 ----------

    @app_commands.command(name="매도", description="예약 매도 주문을 넣습니다.")
    @app_commands.rename(stock="종목", kind="상품", shares="수량")
    @app_commands.describe(shares="매도할 주식 수 (소수점 가능)")
    @app_commands.choices(kind=KIND_CHOICES)
    @app_commands.autocomplete(stock=stock_autocomplete)
    @app_commands.guild_only()
    async def sell(self, interaction: discord.Interaction, stock: str,
                   kind: app_commands.Choice[str], shares: float):
        await interaction.response.defer(ephemeral=True)
        err = await place_sell(interaction.guild_id, interaction.user.id,
                               stock, kind.value, float(shares))
        if err:
            await interaction.followup.send(err)
            return
        await interaction.followup.send(
            f"매도 예약 완료 · {kind.name} {shares:g}주\n"
            "다음 시세 갱신 때 체결됩니다.")

    # ---------- 지갑 ----------

    @app_commands.command(name="자산", description="보유 종목과 평가손익을 봅니다.")
    @app_commands.guild_only()
    async def assets(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        gid, uid = interaction.guild_id, interaction.user.id
        cash = await get_cash(gid, uid)

        async with pool().acquire() as conn:
            holds = await conn.fetch(HOLDINGS_SQL, gid, uid)
            pending = await conn.fetch(PENDING_SQL, gid, uid)

        equity = sum(h["shares"] * h["price"] for h in holds)
        invested = sum(h["shares"] * h["avg_cost"] for h in holds)
        pnl = equity - invested
        rate = (pnl / invested * 100) if invested else 0

        sections = [("자산",
                     f"코인 **{cash:,.0f}**\n"
                     f"평가액 **{equity:,.0f}**\n"
                     f"총자산 **{cash + equity:,.0f}**")]

        if holds:
            lines = []
            for h in holds:
                value = h["shares"] * h["price"]
                gain = (h["price"] - h["avg_cost"]) / h["avg_cost"] * 100 \
                    if h["avg_cost"] else 0
                sign = "+" if gain >= 0 else ""
                lines.append(
                    f"**{stock_name(h)}** {KIND_KO[h['kind']]} · **{h['shares']:.2f}주**\n"
                    f"　평가 {value:,.0f} · 평단 {h['avg_cost']:,.0f} → "
                    f"{h['price']:,.0f} `{sign}{gain:.1f}%`")
            sections.append((f"보유 종목 · 손익 {pnl:+,.0f} ({rate:+.1f}%)",
                             "\n".join(lines)))
        else:
            sections.append(("보유 종목", "없습니다. `/매수` 로 시작하세요."))

        if pending:
            lines = []
            for o in pending:
                unit = "코인" if o["side"] == "buy" else "주"
                side = "매수" if o["side"] == "buy" else "매도"
                lines.append(f"{stock_name(o)} {KIND_KO[o['kind']]} "
                             f"{side} {o['amount']:,.2f}{unit}")
            sections.append(("체결 대기", "\n".join(lines)))

        await interaction.followup.send(
            view=panel(f"{interaction.user.display_name} 님의 자산", sections,
                       footer=f"최소 주문 {int(MIN_ORDER):,} 코인 · 매도 수수료 1%"))

    @app_commands.command(name="출석", description="하루 한 번 코인을 받습니다.")
    @app_commands.guild_only()
    async def attendance(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        gid, uid = interaction.guild_id, interaction.user.id
        await get_cash(gid, uid)

        async with pool().acquire() as conn:
            row = await conn.fetchrow(
                "update wallets set cash = cash + $3, "
                "       last_attendance = (now() at time zone 'Asia/Seoul')::date "
                "where guild_id = $1 and discord_user_id = $2 "
                "  and (last_attendance is null "
                "       or last_attendance < (now() at time zone 'Asia/Seoul')::date) "
                "returning cash",
                gid, uid, DAILY_REWARD)

        if row is None:
            await interaction.followup.send(
                "오늘은 이미 출석했습니다. 한국 시간 자정에 초기화됩니다.")
            return

        await interaction.followup.send(
            f"출석 완료 · **{int(DAILY_REWARD):,} 코인** 지급\n"
            f"잔액 {row['cash']:,.0f}")

    # ---------- 순위 ----------

    @app_commands.command(name="투자순위", description="총자산 순위를 봅니다.")
    @app_commands.guild_only()
    async def ranking(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        async with pool().acquire() as conn:
            rows = await conn.fetch(RANKING_SQL, interaction.guild_id)

        if not rows:
            await interaction.followup.send("아직 투자자가 없습니다. `/매수` 로 시작하세요.")
            return

        lines = []
        for i, r in enumerate(rows, 1):
            total = r["cash"] + r["equity"]
            profit = total - START_CASH
            sign = "+" if profit >= 0 else ""
            lines.append(f"`{i:>2}.` <@{r['discord_user_id']}> — "
                         f"**{total:,.0f}** `{sign}{profit:,.0f}`")

        await interaction.followup.send(
            view=panel(f"{interaction.guild.name} 투자 순위", [("", "\n".join(lines))],
                       footer=f"시작 자본 {int(START_CASH):,} 코인 기준"))

async def setup(bot: commands.Bot):
    await bot.add_cog(Stocks(bot))