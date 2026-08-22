from html import escape

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from whaledecode.domain.entities.admin_audit_log import AdminAuditLog

admin_router = Router(name="admin")


def _is_admin(message: Message, settings) -> bool:
    return message.from_user.id in settings.ADMIN_USER_IDS


@admin_router.message(Command("admin"))
async def cmd_admin(message: Message, command: CommandObject, uow_factory, settings, **kwargs) -> None:
    if not _is_admin(message, settings):
        await message.answer("Access denied.")
        return

    parts = (command.args or "").split(maxsplit=1)
    if not parts:
        async with uow_factory() as uow:
            free = await uow.users.list_by_plan("free")
            paid = await uow.users.list_by_plan("paid")
            wallets = await uow.curated_wallets.list_active()
        await message.answer(
            f"<b>Admin Panel</b>\n\n"
            f"Users: {len(free) + len(paid)}\n"
            f"  Free: {len(free)}\n"
            f"  Paid: {len(paid)}\n"
            f"Curated wallets: {len(wallets)}\n\n"
            f"Commands:\n"
            f"<code>/admin stats</code> — detailed stats\n"
            f"<code>/admin grant &lt;tg_id&gt; paid</code> — grant paid plan\n"
            f"<code>/admin wallet add &lt;address&gt; &lt;chain&gt; &lt;label&gt;</code> — add wallet\n"
            f"<code>/admin wallet remove &lt;id&gt;</code> — remove wallet\n"
            f"<code>/admin wallet list</code> — list wallets"
        )
        return

    subcmd = parts[0]
    args = parts[1] if len(parts) > 1 else ""

    if subcmd == "stats":
        await _cmd_admin_stats(message, uow_factory)
    elif subcmd == "grant":
        await _cmd_admin_grant(message, args, uow_factory, settings)
    elif subcmd == "wallet":
        await _cmd_admin_wallet(message, args, uow_factory, settings)
    elif subcmd == "channel":
        await _cmd_admin_channel(message, args, settings)
    else:
        await message.answer(f"Unknown subcommand: <code>{subcmd}</code>")


async def _cmd_admin_stats(message: Message, uow_factory) -> None:
    async with uow_factory() as uow:
        free = await uow.users.list_by_plan("free")
        paid = await uow.users.list_by_plan("paid")
        alerts_today = await uow.alerts.list_by_status("sent", limit=1000)
    await message.answer(
        f"<b>Admin Stats</b>\n\n"
        f"Total users: {len(free) + len(paid)}\n"
        f"  Free: {len(free)}\n"
        f"  Paid: {len(paid)}\n"
        f"Recent alerts: {len(alerts_today)}"
    )


async def _cmd_admin_grant(message: Message, args: str, uow_factory, settings) -> None:
    if not _is_admin(message, settings):
        await message.answer("Access denied.")
        return
    pieces = args.split()
    if len(pieces) < 1:
        await message.answer("Usage: <code>/admin grant &lt;tg_id&gt;</code>")
        return
    target_tg_id = int(pieces[0].strip())
    plan_code = pieces[1] if len(pieces) > 1 else "paid"
    async with uow_factory() as uow:
        user = await uow.users.get_by_tg_id(target_tg_id)
        if user is None:
            await message.answer(f"User <code>{target_tg_id}</code> not found.")
            return
        old_plan = user.plan
        user.plan = plan_code
        await uow.users.update(user)
        audit = AdminAuditLog(
            admin_id=message.from_user.id,
            action="plan_granted",
            target_type="user",
            target_id=str(user.id),
            diff_json={"plan": old_plan, "new_plan": plan_code},
        )
        await uow.admin_audit_logs.create(audit)
        await uow.commit()
    await message.answer(f"✅ Granted {plan_code.upper()} plan to user <code>{target_tg_id}</code>")


async def _cmd_admin_wallet(message: Message, args: str, uow_factory, settings) -> None:
    if not _is_admin(message, settings):
        await message.answer("Access denied.")
        return
    pieces = args.split()
    if not pieces:
        await message.answer("Usage: <code>/admin wallet add|remove|list ...</code>")
        return

    action = pieces[0]
    async with uow_factory() as uow:
        if action == "list":
            wallets = await uow.curated_wallets.list_active()
            if not wallets:
                await message.answer("No curated wallets.")
                return
            lines = ["<b>Curated Wallets:</b>\n"]
            for w in wallets:
                addr_short = f"{w.address[:6]}...{w.address[-4:]}"
                lines.append(f"<code>{w.id}</code> | {addr_short} | {w.chain.name} | {w.label}")
            await message.answer("\n".join(lines))
        elif action == "add" and len(pieces) >= 4:
            address = pieces[1]
            chain = pieces[2].upper()
            label = pieces[3]
            from whaledecode.domain.entities.curated_wallet import CuratedWallet
            wallet = CuratedWallet(address=address, chain=chain, label=label)
            await uow.curated_wallets.create(wallet)
            audit = AdminAuditLog(
                admin_id=message.from_user.id,
                action="wallet_added",
                target_type="curated_wallet",
                target_id=address,
                diff_json={"chain": chain, "label": label},
            )
            await uow.admin_audit_logs.create(audit)
            await uow.commit()
            await message.answer(f"✅ Added wallet <code>{address[:6]}...{address[-4:]}</code> ({escape(label)})")
        elif action == "remove" and len(pieces) >= 2:
            wallet_id = int(pieces[1])
            from whaledecode.domain.entities.curated_wallet import CuratedWallet
            wallet = await uow.curated_wallets.get(wallet_id)
            if wallet is None:
                await message.answer(f"Wallet <code>{wallet_id}</code> not found.")
                return
            wallet.is_active = False
            await uow.curated_wallets.update(wallet)
            audit = AdminAuditLog(
                admin_id=message.from_user.id,
                action="wallet_removed",
                target_type="curated_wallet",
                target_id=str(wallet_id),
                diff_json={"address": wallet.address},
            )
            await uow.admin_audit_logs.create(audit)
            await uow.commit()
            await message.answer(f"✅ Removed wallet <code>{wallet_id}</code>")
        else:
            await message.answer("Usage:\n<code>/admin wallet list</code>\n<code>/admin wallet add &lt;address&gt; &lt;chain&gt; &lt;label&gt;</code>\n<code>/admin wallet remove &lt;id&gt;</code>")


async def _cmd_admin_channel(message: Message, args: str, settings) -> None:
    status = "✅ Enabled" if settings.CHANNEL_PUBLISH_ENABLED else "❌ Disabled"
    channel = settings.CHANNEL_CHAT_ID or "Not configured"
    await message.answer(
        f"<b>Channel Publishing</b>\n\n"
        f"Status: {status}\n"
        f"Channel: <code>{channel}</code>\n"
        f"Max daily: {settings.CHANNEL_MAX_DAILY}\n\n"
        f"Enable/disable via <code>CHANNEL_PUBLISH_ENABLED</code> env var (restart required)."
    )
