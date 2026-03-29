import asyncio
import aiohttp
import random
import string
import segno
import json

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

COUNTRY_MAP = {}
# ================= CONFIG =================
BOT_TOKEN = "8028279776:AAH4ZHbx2R-3t8h1XVTFz1ZlVg3PxYm0hXk"
API_KEY = "q3xSZbaPVpaZW5zsI4tzea7s0RlLfun3"
FIREBASE_DB = "https://genie-6bb04-default-rtdb.asia-southeast1.firebasedatabase.app"

UPI_VPA = "paytmqr2810050501013202t473pymf@paytm"
PAYTM_WORKER_URL = "https://paytm.udayscriptsx.workers.dev/"
PAYTM_MID = "OtWRkM00455638249469"

BASE_URL = "https://smsbower.page/stubs/handler_api.php"
# ==========================================


# ================= HTTP =================
async def http_get(params):
    async with aiohttp.ClientSession() as session:
        async with session.get(BASE_URL, params=params) as r:
            text = await r.text()
            try:
                return json.loads(text)
            except:
                return None


async def fb_get(path):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{FIREBASE_DB}/{path}.json") as r:
            return await r.json()


async def fb_patch(path, data):
    async with aiohttp.ClientSession() as session:
        async with session.patch(f"{FIREBASE_DB}/{path}.json", json=data):
            pass


# ================= WALLET =================
async def get_balance(user_id):
    data = await fb_get(f"users/{user_id}")
    return data.get("balance", 0) if data else 0


async def update_balance(user_id, amount):
    await fb_patch(f"users/{user_id}", {"balance": amount})


async def add_balance(user_id, amount):
    bal = await get_balance(user_id)
    await update_balance(user_id, bal + amount)


async def deduct_balance(user_id, amount):
    bal = await get_balance(user_id)
    if bal >= amount:
        await update_balance(user_id, bal - amount)
        return True
    return False


# ================= PRICE =================
def convert_price(usd):
    return round((usd * 100) * 2.5 * 2.9, 2)


# ================= SERVICES =================
async def get_services():
    data = await http_get({
        "api_key": API_KEY,
        "action": "getServicesList"
    })

    if not data or data.get("status") != "success":
        return {}

    return {s["code"]: s["name"] for s in data["services"]}


# ================= PRICES =================
async def get_prices(service):
    return await http_get({
        "api_key": API_KEY,
        "action": "getPricesV3",
        "service": service
    })


def best_provider(providers):
    valid = [
        p for p in providers.values()
        if p["count"] > 0 and p["price"] > 0.05
    ]
    if not valid:
        return None
    return min(valid, key=lambda x: x["price"])


async def get_country_list(service):
    data = await get_prices(service)

    if not data:
        return []

    result = []

    for country, services in data.items():
        if service not in services:
            continue

        best = best_provider(services[service])
        if not best:
            continue

        result.append({
            "country": country,
            "usd_price": best["price"],
            "count": best["count"]
        })

    return sorted(result, key=lambda x: (x["usd_price"], -x["count"]))


# ================= SMS =================
async def get_number(service, country, max_price):
    res = await http_get({
        "api_key": API_KEY,
        "action": "getNumberV2",
        "service": service,
        "country": country,
        "maxPrice": max_price
    })
    if isinstance(res, dict):
        return res.get("activationId"), res.get("phoneNumber")
    return None, None


async def get_otp(act_id):
    res = await http_get({
        "api_key": API_KEY,
        "action": "getStatus",
        "id": act_id
    })
    if isinstance(res, str) and res.startswith("STATUS_OK"):
        return res.split(":")[1]
    return None


async def set_status(act_id, status):
    await http_get({
        "api_key": API_KEY,
        "action": "setStatus",
        "id": act_id,
        "status": status
    })

async def cancel_activation(act_id):
    await set_status(act_id, 8)

async def refund_balance(user_id, amount):
    bal = await get_balance(user_id)
    await update_balance(user_id, bal + amount)

# ================= PAYMENT =================
def generate_order_id():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))


def generate_qr(order_id, amount):
    upi = (
        f"upi://pay?pa={UPI_VPA}&pn=GENIE"
        f"&am={amount}&cu=INR&tn={order_id}&tr={order_id}&tid={order_id}"
    )
    file = f"{order_id}.png"
    segno.make(upi).save(file, scale=6)
    return file


async def check_payment(order_id):
    async with aiohttp.ClientSession() as session:
        async with session.get(
            PAYTM_WORKER_URL,
            params={"mid": PAYTM_MID, "id": order_id}
        ) as r:
            try:
                data = await r.json()
                return data.get("STATUS") == "TXN_SUCCESS"
            except:
                return False


async def payment_watcher(order_id, user_id, amount, context):
    for _ in range(60):
        if await check_payment(order_id):
            await fb_patch(f"payments/{order_id}", {"status": "SUCCESS"})
            await add_balance(user_id, amount)

            await context.bot.send_message(
                user_id,
                f"✅ Payment Success\n💰 Added ₹{amount}"
            )
            return

        await asyncio.sleep(5)

    await fb_patch(f"payments/{order_id}", {"status": "FAILED"})

import requests
def http_get_sync(params):
    try:
        r = requests.get(BASE_URL, params=params, timeout=10)
        return json.loads(r.text)
    except Exception as e:
        print("HTTP ERROR:", e)
        return None
def load_country_map():
    global COUNTRY_MAP

    data = http_get_sync({
        "api_key": API_KEY,
        "action": "getCountries"
    })

    if not data:
        print("❌ Country API failed")
        return

    country_map = {}

    # handle both dict & list
    if isinstance(data, dict):
        data = data.values()

    for c in data:
        try:
            cid = str(c.get("id"))
            name = c.get("eng") or c.get("rus") or f"Country {cid}"
            country_map[cid] = f"🌍 {name}"
        except:
            continue

    COUNTRY_MAP = country_map
    print(f"✅ Loaded {len(COUNTRY_MAP)} countries")

# ================= BOT =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.message.from_user.id
    bal = await get_balance(user)

    kb = [
        [InlineKeyboardButton("💰 Add Balance", callback_data="add_money")],
        [InlineKeyboardButton("📲 Buy Number", callback_data="services")]
    ]

    await update.message.reply_text(
        f"👋 Welcome to GENIE\n\n"
        "⚡ Get instant temporary numbers for OTP verification\n"
        "🌍 Multiple countries & services\n"
        "🔒 Fast • Reliable • Automated\n\n"
        f"💰 Balance: ₹{bal}",
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def add_money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = [
        [
            InlineKeyboardButton("₹10", callback_data="amt_10"),
            InlineKeyboardButton("₹20", callback_data="amt_20"),
            InlineKeyboardButton("₹30", callback_data="amt_30"),
            InlineKeyboardButton("₹40", callback_data="amt_40"),
        ],
        [
            InlineKeyboardButton("₹50", callback_data="amt_10"),
            InlineKeyboardButton("₹20", callback_data="amt_20"),
            InlineKeyboardButton("₹50", callback_data="amt_50"),
            InlineKeyboardButton("₹60", callback_data="amt_60"),
        ],
        [
            InlineKeyboardButton("₹70", callback_data="amt_70"),
            InlineKeyboardButton("₹80", callback_data="amt_80"),
            InlineKeyboardButton("₹90", callback_data="amt_90"),
            InlineKeyboardButton("₹100", callback_data="amt_100"),
        ]
    ]
    await query.message.reply_text(
        "💰 Select amount to add:",
        reply_markup=InlineKeyboardMarkup(kb)
    )
async def select_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    amount = int(query.data.split("_")[1])
    user = query.from_user.id

    order_id =  generate_order_id()

    # save payment order in firebase
    await fb_patch(f"payments/{order_id}", {
        "user": user,
        "amount": amount,
        "status": "PENDING"
    })

    # 🔥 generate UPI QR
    file= generate_qr(order_id,amount)

    with open(file, "rb") as f:
        await query.message.reply_photo(
            photo=f,
            caption=f"💳 Pay ₹{amount}\n⏳ Auto verifying..."
        )

    # start payment watcher
    asyncio.create_task(payment_watcher(order_id, user, amount, context))







SERVICE_PAGE_SIZE = 6
def build_service_keyboard(services, page):
    keys = list(services.keys())

    start = page * SERVICE_PAGE_SIZE
    end = start + SERVICE_PAGE_SIZE
    chunk = keys[start:end]

    buttons = []

    # priority services on top (optional)
    priority = ["wa", "tg"]

    for k in chunk:
        label = services[k]
        emoji = "🔥 " if k in priority else ""
        buttons.append([
            InlineKeyboardButton(
                f"{emoji}{label}",
                callback_data=f"svc_{k}"
            )
        ])

    # navigation
    nav = []

    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"svcpage_{page-1}"))

    if end < len(keys):
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"svcpage_{page+1}"))

    if nav:
        buttons.append(nav)

    # page indicator
    buttons.append([
        InlineKeyboardButton(f"📄 Page {page+1}", callback_data="noop")
    ])

    return InlineKeyboardMarkup(buttons)
async def services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = await get_services()

    if not data:
        await query.message.reply_text("❌ Failed to load services")
        return

    # store services
    context.user_data["services"] = data
    context.user_data["svc_page"] = 0

    kb = build_service_keyboard(data, 0)

    await query.edit_message_text(
        "📲 Select Service:",
        reply_markup=kb
    )











PAGE_SIZE = 6
def build_country_keyboard(countries, page):
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    chunk = countries[start:end]

    buttons = []

    # countries list
    for c in chunk:
        country_name = COUNTRY_MAP.get(c["country"], f"🌍 {c['country']}")
        buttons.append([
            InlineKeyboardButton(
                f"{country_name} | ₹{convert_price(c['usd_price'])}",
                callback_data=f"cty_{c['country']}"
            )
        ])

    # navigation row
    nav = []

    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page_{page-1}"))

    if end < len(countries):
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"page_{page+1}"))

    if nav:
        buttons.append(nav)

    # page info
    buttons.append([
        InlineKeyboardButton(f"📄 Page {page+1}", callback_data="noop")
    ])

    return InlineKeyboardMarkup(buttons)
async def select_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    service = query.data.split("_")[1]
    context.user_data["service"] = service

    countries = await get_country_list(service)

    if not countries:
        await query.message.reply_text("❌ No stock available")
        return

    # store for pagination
    context.user_data["countries"] = countries
    context.user_data["page"] = 0

    kb = build_country_keyboard(countries, 0)

    await query.edit_message_text(
        "🌍 Select Country:",
        reply_markup=kb
    )

async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    country = query.data.split("_")[1]
    service = context.user_data["service"]

    countries = await get_country_list(service)
    selected = next((c for c in countries if c["country"] == country), None)

    if not selected:
        await query.message.reply_text("❌ Out of stock")
        return

    context.user_data.update(selected)
    context.user_data["price"] = convert_price(selected["usd_price"])

    kb = [[InlineKeyboardButton("Confirm Buy", callback_data="buy")]]

    await query.edit_message_text(
        f"{COUNTRY_MAP.get(selected['country'])}\n💰 ₹{context.user_data['price']}",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def change_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    page = int(query.data.split("_")[1])
    context.user_data["page"] = page

    countries = context.user_data["countries"]

    kb = build_country_keyboard(countries, page)

    await query.edit_message_reply_markup(reply_markup=kb)

async def change_service_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    page = int(query.data.split("_")[1])

    services = await get_services()  # 👈 NO CACHE (as you want)

    kb = build_service_keyboard(services, page)

    await query.edit_message_reply_markup(reply_markup=kb)


async def otp_worker(user_id, act_id, phone, price, message, context):
    total_time = 300  # 5 minutes
    bar_length = 10

    for t in range(total_time):
        # 🔍 check OTP every 5 sec
        if t % 5 == 0:
            otp = await get_otp(act_id)
            if otp:
                await message.edit_text(
                    f"📞 {phone}\n\n✅ OTP: {otp}"
                )
                return

        # 📊 progress calculation
        progress = t / total_time
        filled = int(bar_length * progress)
        bar = "■" * filled + "□" * (bar_length - filled)

        percent = int(progress * 100)

        # ⏱ remaining time
        remaining = total_time - t
        mins, secs = divmod(remaining, 60)

        # ✨ update message
        try:
            await message.edit_text(
                f"📞 +{phone}\n"
                f"⏳ Waiting OTP [{bar}] {percent}%\n"
                f"⏱ {mins:02d}:{secs:02d} remaining"
                f"\n\n\n If OTP doesn't arrive, then it will be automatically canceled and the amount will be refunded."
            )
        except:
            pass  # ignore edit errors

        await asyncio.sleep(1)

    # ❌ timeout → cancel + refund
    await cancel_activation(act_id)
    await refund_balance(user_id, price)

    await message.edit_text(
        "❌ OTP timeout\n💰 Refunded"
    )
async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user.id
    service = context.user_data["service"]
    country = context.user_data["country"]
    usd_price = context.user_data["usd_price"]
    final_price = context.user_data["price"]

    # 🔴 check balance
    bal = await get_balance(user)
    if bal < final_price:
        await query.message.reply_text("❌ Insufficient balance")
        return

    # 🔴 deduct immediately
    await deduct_balance(user, final_price)

    # 🔴 get number
    act_id, phone = await get_number(service, country, usd_price)

    if not phone:
        await refund_balance(user, final_price)
        await query.message.reply_text("❌ No number available")
        return


    # create NEW message for OTP
    msg = await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=f"Wait..."
    )
    # 🚀 NON-BLOCKING TASK
    asyncio.create_task(
        otp_worker(user, act_id, phone, final_price, msg, context)
    )


async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("📢 Join Channel", url="https://t.me/genie_tempotp")],
        [InlineKeyboardButton("💬 Contact Support", url="https://t.me/shivam_cingh")]
    ]

    await update.message.reply_text(
        "ℹ️ *About GENIE*\n\n"
        "GENIE provides instant temporary numbers for OTP verification.\n"
        "Fast, reliable, and fully automated service.\n\n"
        "🌍 Multiple countries\n"
        "⚡ Instant OTP delivery\n"
        "🔒 Secure & trusted\n",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )


# ================= MAIN =================
app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(add_money, pattern="add_money"))
app.add_handler(CallbackQueryHandler(services, pattern="services"))
# 🔥 pagination FIRST (important)
app.add_handler(CallbackQueryHandler(change_service_page, pattern="^svcpage_\\d+$"))
# then service select
app.add_handler(CallbackQueryHandler(select_service, pattern="^svc_"))
# countries
app.add_handler(CallbackQueryHandler(change_page, pattern="^page_"))
app.add_handler(CallbackQueryHandler(confirm, pattern="^cty_"))
# buy last
app.add_handler(CallbackQueryHandler(buy, pattern="^buy$"))
# about
app.add_handler(CommandHandler("about", about))
# select amount
app.add_handler(CallbackQueryHandler(select_amount, pattern="^amt_"))

load_country_map()
app.run_polling()
