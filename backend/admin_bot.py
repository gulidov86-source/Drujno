"""
Модуль: admin_bot.py
Описание: Telegram бот для администрирования GroupBuy
Проект: GroupBuy Mini App

Команды:
    /start              — Главное меню
    /orders [status]    — Заказы
    /order <id>         — Детали заказа
    /ship <id> <трек>   — Отправить заказ
    /returns            — Возвраты
    /return <id> approve/reject — Решение по возврату
    /tickets            — Обращения
    /ticket <id>        — Детали
    /reply <id> <текст> — Ответить
    /stats              — Статистика
    /users              — Пользователи

Запуск: python admin_bot.py
Деплой: Railway Worker или systemd на VPS
"""

import asyncio
import json
import uuid as uuid_lib
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.enums import ParseMode

import sys
sys.path.append("..")
from config import settings
from database.connection import get_supabase_client

ADMIN_BOT_TOKEN = getattr(settings, 'ADMIN_BOT_TOKEN', '')
ADMIN_IDS = []  # Вставь свой Telegram ID

bot = Bot(token=ADMIN_BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

SE = {"pending":"⏳","frozen":"🧊","paid":"💳","processing":"⚙️","shipped":"🚚","delivered":"✅","cancelled":"❌","refunded":"🔄"}
LE = {"newcomer":"🌱","buyer":"🛒","activist":"⭐","expert":"🔥","ambassador":"👑"}
RD = {"wrong_size":"Не подошёл размер","defect":"Брак","not_as_described":"Не соответствует описанию","changed_mind":"Передумал"}

def is_admin(uid): return not ADMIN_IDS or uid in ADMIN_IDS
async def chk(msg):
    if not is_admin(msg.from_user.id):
        await msg.answer("⛔ Доступ запрещён."); return False
    return True

@dp.message(CommandStart())
async def cmd_start(msg: types.Message):
    if not await chk(msg): return
    await msg.answer(
        "🔧 <b>GroupBuy Admin</b>\n\n"
        "📦 /orders [status] — Заказы\n📦 /order id — Детали\n🚚 /ship id трек — Отправить\n\n"
        "🔄 /returns — Возвраты\n🔄 /return id approve|reject — Решение\n\n"
        "💬 /tickets — Обращения\n💬 /reply id текст — Ответить\n\n"
        "📊 /stats — Статистика\n👤 /users — Пользователи\n\n"
        f"Ваш ID: <code>{msg.from_user.id}</code>")

@dp.message(Command("stats"))
async def cmd_stats(msg: types.Message):
    if not await chk(msg): return
    db = get_supabase_client()
    try:
        ua = db.table("users").select("id", count="exact").execute()
        ut = db.table("users").select("id", count="exact").gte("created_at", datetime.utcnow().replace(hour=0,minute=0,second=0).isoformat()).execute()
        oa = db.table("orders").select("id", count="exact").execute()
        op = db.table("orders").select("id", count="exact").eq("status","pending").execute()
        opd = db.table("orders").select("id", count="exact").eq("status","paid").execute()
        os = db.table("orders").select("id", count="exact").eq("status","shipped").execute()
        ga = db.table("groups").select("id", count="exact").eq("status","active").execute()
        gd = db.table("groups").select("id", count="exact").eq("status","completed").execute()
        rp = db.table("returns").select("id", count="exact").eq("status","pending").execute()
        to = db.table("support_tickets").select("id", count="exact").eq("status","open").execute()
        await msg.answer(
            f"📊 <b>Статистика</b>\n\n👤 {ua.count or 0} польз. (+{ut.count or 0} сегодня)\n\n"
            f"📦 Заказы: {oa.count or 0}\n  ⏳{op.count or 0} 💳{opd.count or 0} 🚚{os.count or 0}\n\n"
            f"👥 Сборы: 🟢{ga.count or 0} ✅{gd.count or 0}\n\n"
            f"⚠️ Возвраты: {rp.count or 0} | Обращения: {to.count or 0}")
    except Exception as e: await msg.answer(f"❌ {e}")

@dp.message(Command("orders"))
async def cmd_orders(msg: types.Message):
    if not await chk(msg): return
    db = get_supabase_client()
    args = msg.text.split(maxsplit=1)
    sf = args[1].strip() if len(args) > 1 else None
    try:
        q = db.table("orders").select("*")
        if sf: q = q.eq("status", sf)
        r = q.order("created_at", desc=True).limit(20).execute()
        if not r.data: await msg.answer("📦 Не найдено"); return
        t = f"📦 <b>Заказы</b>{f' ({sf})' if sf else ''}\n\n"
        for o in r.data:
            t += f"{SE.get(o['status'],'❓')} <b>#{o['id']}</b> | {o['status']} | {o['total_amount']}₽ | {o['created_at'][:10]}\n"
        t += f"\nВсего: {len(r.data)} | /order id"
        await msg.answer(t)
    except Exception as e: await msg.answer(f"❌ {e}")

@dp.message(Command("order"))
async def cmd_order(msg: types.Message):
    if not await chk(msg): return
    args = msg.text.split()
    if len(args)<2: await msg.answer("/order id"); return
    try: oid = int(args[1])
    except: await msg.answer("❌ ID=число"); return
    db = get_supabase_client()
    try:
        r = db.table("orders").select("*").eq("id",oid).execute()
        if not r.data: await msg.answer(f"❌ #{oid} не найден"); return
        o = r.data[0]
        u = db.table("users").select("telegram_id,username,first_name,phone").eq("id",o["user_id"]).execute()
        user = u.data[0] if u.data else {}
        pn = "—"
        g = db.table("groups").select("product_id").eq("id",o["group_id"]).execute()
        if g.data:
            p = db.table("products").select("name").eq("id",g.data[0]["product_id"]).execute()
            if p.data: pn = p.data[0]["name"]
        at = "—"
        a = db.table("addresses").select("*").eq("id",o["address_id"]).execute()
        if a.data:
            ad = a.data[0]
            at = f"{ad.get('city','')}, {ad.get('street','')}, д.{ad.get('building','')}"
            if ad.get("apartment"): at += f", кв.{ad['apartment']}"

        t = (f"📦 <b>#{o['id']}</b>\n{'─'*30}\n\n"
             f"📌 {SE.get(o['status'],'❓')} {o['status']}\n🛍 {pn}\n"
             f"💰 {o['total_amount']}₽ (товар {o['final_price']}₽ + дост. {o.get('delivery_cost',0)}₽)\n\n"
             f"👤 @{user.get('username','—')} ({user.get('first_name','—')})\n📞 {user.get('phone','—')}\n\n"
             f"📍 {o.get('delivery_type','—')} | {at}\n🚚 Трек: {o.get('tracking_number','—')}\n📅 {o['created_at'][:16]}")

        kb = []
        if o["status"] in ("paid","processing"):
            kb.append([InlineKeyboardButton(text="🚚 Отправить", callback_data=f"ship_{o['id']}")])
        if o["status"] not in ("cancelled","refunded","delivered"):
            kb.append([InlineKeyboardButton(text="❌ Отменить", callback_data=f"cncl_{o['id']}")])
        mk = InlineKeyboardMarkup(inline_keyboard=kb) if kb else None
        await msg.answer(t, reply_markup=mk)
    except Exception as e: await msg.answer(f"❌ {e}")

@dp.message(Command("ship"))
async def cmd_ship(msg: types.Message):
    if not await chk(msg): return
    args = msg.text.split(maxsplit=2)
    if len(args)<3: await msg.answer("/ship id трек"); return
    try: oid = int(args[1])
    except: await msg.answer("❌ ID=число"); return
    track = args[2].strip()
    db = get_supabase_client()
    try:
        r = db.table("orders").update({"status":"shipped","tracking_number":track,"delivery_service":"cdek"}).eq("id",oid).execute()
        if not r.data: await msg.answer(f"❌ #{oid} не найден"); return
        await msg.answer(f"✅ #{oid} отправлен! Трек: {track}")
    except Exception as e: await msg.answer(f"❌ {e}")

@dp.message(Command("returns"))
async def cmd_returns(msg: types.Message):
    if not await chk(msg): return
    db = get_supabase_client()
    try:
        r = db.table("returns").select("*").order("created_at",desc=True).limit(20).execute()
        if not r.data: await msg.answer("🔄 Нет возвратов"); return
        t = "🔄 <b>Возвраты</b>\n\n"
        for x in r.data:
            e = {"pending":"⏳","approved":"✅","rejected":"❌","awaiting_item":"📬","completed":"✔️"}.get(x["status"],"❓")
            t += f"{e} <b>#{x['id']}</b> | Заказ #{x['order_id']} | {x['status']} | {x['reason']}\n"
        t += "\n/return id — детали"
        await msg.answer(t)
    except Exception as e: await msg.answer(f"❌ {e}")

@dp.message(Command("return"))
async def cmd_return(msg: types.Message):
    if not await chk(msg): return
    args = msg.text.split(maxsplit=2)
    if len(args)<2: await msg.answer("/return id [approve|reject причина]"); return
    try: rid = int(args[1])
    except: await msg.answer("❌ ID=число"); return
    db = get_supabase_client()
    if len(args)>=3:
        act = args[2].split()[0].lower()
        if act == "approve":
            db.table("returns").update({"status":"approved","admin_comment":"Одобрено"}).eq("id",rid).execute()
            await msg.answer(f"✅ Возврат #{rid} одобрен"); return
        elif act == "reject":
            rsn = " ".join(args[2].split()[1:]) or "Отклонено"
            db.table("returns").update({"status":"rejected","admin_comment":rsn}).eq("id",rid).execute()
            await msg.answer(f"❌ #{rid} отклонён: {rsn}"); return
    try:
        r = db.table("returns").select("*").eq("id",rid).execute()
        if not r.data: await msg.answer(f"❌ #{rid} не найден"); return
        x = r.data[0]
        t = (f"🔄 <b>Возврат #{x['id']}</b>\n\n📦 Заказ #{x['order_id']}\n📌 {x['status']}\n"
             f"❓ {RD.get(x['reason'],x['reason'])}\n📝 {x['description']}\n💰 {x.get('refund_amount','—')}₽\n📅 {x['created_at'][:16]}")
        if x["status"]=="pending": t += f"\n\n/return {rid} approve\n/return {rid} reject причина"
        await msg.answer(t)
    except Exception as e: await msg.answer(f"❌ {e}")

@dp.message(Command("tickets"))
async def cmd_tickets(msg: types.Message):
    if not await chk(msg): return
    db = get_supabase_client()
    try:
        r = db.table("support_tickets").select("*").in_("status",["open","in_progress"]).order("created_at",desc=True).limit(20).execute()
        if not r.data: await msg.answer("💬 Нет обращений 🎉"); return
        t = "💬 <b>Обращения</b>\n\n"
        for x in r.data:
            ms = x.get("messages",[])
            if isinstance(ms,str): ms = json.loads(ms)
            last = ms[-1]["text"][:50] if ms else "—"
            ic = "🔴" if x["status"]=="open" else "🟡"
            t += f"{ic} <b>#{x['id']}</b> | {x['category']} | {last}...\n"
        t += "\n/ticket id | /reply id текст"
        await msg.answer(t)
    except Exception as e: await msg.answer(f"❌ {e}")

@dp.message(Command("ticket"))
async def cmd_ticket(msg: types.Message):
    if not await chk(msg): return
    args = msg.text.split()
    if len(args)<2: await msg.answer("/ticket id"); return
    try: tid = int(args[1])
    except: await msg.answer("❌ ID=число"); return
    db = get_supabase_client()
    try:
        r = db.table("support_tickets").select("*").eq("id",tid).execute()
        if not r.data: await msg.answer(f"❌ #{tid} не найдено"); return
        x = r.data[0]
        ms = x.get("messages",[])
        if isinstance(ms,str): ms = json.loads(ms)
        u = db.table("users").select("username,first_name").eq("id",x["user_id"]).execute()
        user = u.data[0] if u.data else {}
        t = f"💬 <b>#{x['id']}</b> | {x['category']} | {x['status']}\n👤 @{user.get('username','—')}\n\n"
        for m in ms[-10:]:
            s = "👤" if m.get("sender_type")=="user" else "🔧"
            t += f"{s} {m.get('created_at','')[:16]}\n{m.get('text','')}\n\n"
        t += f"/reply {tid} текст"
        await msg.answer(t)
    except Exception as e: await msg.answer(f"❌ {e}")

@dp.message(Command("reply"))
async def cmd_reply(msg: types.Message):
    if not await chk(msg): return
    args = msg.text.split(maxsplit=2)
    if len(args)<3: await msg.answer("/reply id текст"); return
    try: tid = int(args[1])
    except: await msg.answer("❌ ID=число"); return
    txt = args[2]
    db = get_supabase_client()
    try:
        r = db.table("support_tickets").select("*").eq("id",tid).execute()
        if not r.data: await msg.answer(f"❌ #{tid} не найдено"); return
        x = r.data[0]
        ms = x.get("messages",[])
        if isinstance(ms,str): ms = json.loads(ms)
        ms.append({"id":str(uuid_lib.uuid4()),"sender_type":"support","sender_id":msg.from_user.id,"text":txt,"created_at":datetime.utcnow().isoformat()})
        db.table("support_tickets").update({"messages":json.dumps(ms),"status":"waiting_user"}).eq("id",tid).execute()
        await msg.answer(f"✅ Ответ → #{tid}")
    except Exception as e: await msg.answer(f"❌ {e}")

@dp.message(Command("users"))
async def cmd_users(msg: types.Message):
    if not await chk(msg): return
    db = get_supabase_client()
    try:
        lvs = {}
        for lv in ["newcomer","buyer","activist","expert","ambassador"]:
            c = db.table("users").select("id",count="exact").eq("level",lv).execute()
            lvs[lv] = c.count or 0
        rec = db.table("users").select("username,first_name,created_at").order("created_at",desc=True).limit(5).execute()
        t = "👤 <b>Пользователи</b>\n\n"
        for lv,cnt in lvs.items(): t += f"  {LE.get(lv,'')} {lv}: {cnt}\n"
        t += f"\n  Всего: {sum(lvs.values())}\n\n<b>Последние:</b>\n"
        for u in (rec.data or []): t += f"  @{u.get('username','—')} — {u['created_at'][:10]}\n"
        await msg.answer(t)
    except Exception as e: await msg.answer(f"❌ {e}")

@dp.callback_query(F.data.startswith("ship_"))
async def cb_ship(cb: types.CallbackQuery):
    oid = cb.data.split("_")[1]
    await cb.message.answer(f"/ship {oid} ТРЕК-НОМЕР")
    await cb.answer()

@dp.callback_query(F.data.startswith("cncl_"))
async def cb_cancel(cb: types.CallbackQuery):
    oid = cb.data.split("_")[1]
    db = get_supabase_client()
    db.table("orders").update({"status":"cancelled"}).eq("id",int(oid)).execute()
    await cb.message.answer(f"❌ #{oid} отменён")
    await cb.answer("Отменён")

async def main():
    print("🚀 Запуск админ-бота GroupBuy...")
    print(f"   Администраторы: {ADMIN_IDS or 'все (ADMIN_IDS пуст)'}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
