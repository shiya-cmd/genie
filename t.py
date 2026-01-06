import random
import string
import asyncio
import aiohttp
import segno
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ================= CONFIG =================
BOT_TOKEN = "8028279776:AAH4ZHbx2R-3t8h1XVTFz1ZlVg3PxYm0hXk"

UPI_VPA = "paytmqr2810050501013202t473pymf@paytm"
MERCHANT_NAME = "OORPAY"

FIREBASE_DB_URL = "https://genie-6bb04-default-rtdb.asia-southeast1.firebasedatabase.app"

PAYTM_WORKER_URL = "https://paytm.udayscriptsx.workers.dev/"
PAYTM_MID = "OtWRkM00455638249469"

SMSBOWER_API_KEY = "q3xSZbaPVpaZW5zsI4tzea7s0RlLfun3"
# =========================================


# ================= SERVICE CONFIG =================
SERVICE_CONFIG = {
    "wa": {
        "label": "WhatsApp Account",
        "price": 79,
        "service": "wa",
        "country": 22,
        "max_price": 0.4,
    },
    "tg": {
        "label": "Telegram Account",
        "price": 89,
        "service": "tg",
        "country": 22,
        "max_price": 0.5,
    },
}
# =========================================


# ================= HTTP HELPERS (PER REQUEST) =================
async def http_get(url, params=None):
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, timeout=10) as resp:
            text = await resp.text()
            try:
                return resp.status, await resp.json()
            except:
                return resp.status, text


async def http_put(url, json=None):
    async with aiohttp.ClientSession() as session:
        async with session.put(url, json=json, timeout=10):
            return True


async def http_patch(url, json=None):
    async with aiohttp.ClientSession() as session:
        async with session.patch(url, json=json, timeout=10):
            return True
# ===============================================================


# ================= ORDER ID =================
def generate_order_id(prefix="OOR", length=16):
    chars = string.ascii_uppercase + string.digits
    return prefix + "".join(random.choices(chars, k=length - len(prefix)))


async def order_id_exists(order_id):
    status, data = await http_get(
        f"{FIREBASE_DB_URL}/orders/{order_id}.json"
    )
    return status == 200 and data is not None


async def generate_unique_order_id():
    while True:
        oid = generate_order_id()
        if not await order_id_exists(oid):
            return oid
# =========================================


# ================= FIREBASE =================
async def save_order(user_id, order_id, service_key):
    cfg = SERVICE_CONFIG[service_key]
    await http_put(
        f"{FIREBASE_DB_URL}/orders/{order_id}.json",
        json={
            "user_id": user_id,
            "order_id": order_id,
            "amount": cfg["price"],
            "status": "PENDING",
            "service": service_key,
            "phone": "",
            "otp": "",
        },
    )


async def mark_payment_success(order_id):
    await http_patch(
        f"{FIREBASE_DB_URL}/orders/{order_id}.json",
        json={"status": "SUCCESS"},
    )


async def mark_payment_failed(order_id):
    await http_patch(
        f"{FIREBASE_DB_URL}/orders/{order_id}.json",
        json={"status": "FAILED"},
    )


async def update_ph(order_id, phone):
    await http_patch(
        f"{FIREBASE_DB_URL}/orders/{order_id}.json",
        json={"phone": phone},
    )


async def update_otp(order_id, otp):
    await http_patch(
        f"{FIREBASE_DB_URL}/orders/{order_id}.json",
        json={"otp": otp},
    )
# =========================================


# ================= QR =================
def generate_qr(order_id, amount):
    upi_uri = (
        f"upi://pay?pa={UPI_VPA}&pn={MERCHANT_NAME}"
        f"&am={amount}&cu=INR&tn={order_id}&tr={order_id}&tid={order_id}"
    )
    file = f"{order_id}.png"
    segno.make(upi_uri, error="m").save(file, kind="png", scale=8, border=4)
    return file
# =========================================


# ================= PAYMENT =================
async def check_payment(order_id):
    status, data = await http_get(
        PAYTM_WORKER_URL,
        params={"mid": PAYTM_MID, "id": order_id},
    )
    return status == 200 and isinstance(data, dict) and data.get("STATUS") == "TXN_SUCCESS"
# =========================================


# ================= SMSBOWER =================
async def get_number(service_key):
    cfg = SERVICE_CONFIG[service_key]
    status, data = await http_get(
        "https://smsbower.online/stubs/handler_api.php",
        params={
            "api_key": SMSBOWER_API_KEY,
            "action": "getNumberV2",
            "service": cfg["service"],
            "country": cfg["country"],
            "maxPrice": cfg["max_price"],
        },
    )
    if status != 200 or not isinstance(data, dict):
        return None, None
    return data.get("activationId"), data.get("phoneNumber")


async def get_otp(activation_id, order_id):
    _, text = await http_get(
        "https://smsbower.online/stubs/handler_api.php",
        params={
            "api_key": SMSBOWER_API_KEY,
            "action": "getStatus",
            "id": activation_id,
        },
    )
    if isinstance(text, str) and text.startswith("STATUS_OK"):
        otp = text.split(":")[1]
        await update_otp(order_id, otp)
        await smsbower_complete_activation(activation_id)
        return otp
    return None


async def smsbower_set_status(activation_id, status):
    _, text = await http_get(
        "https://smsbower.online/stubs/handler_api.php",
        params={
            "api_key": SMSBOWER_API_KEY,
            "action": "setStatus",
            "id": activation_id,
            "status": status,
        },
    )
    return isinstance(text, str) and text.startswith(("OK", "ACCESS", "SUCCESS"))


async def smsbower_complete_activation(activation_id):
    return await smsbower_set_status(activation_id, 6)


async def smsbower_cancel_activation(activation_id):
    return await smsbower_set_status(activation_id, 8)
# =========================================


# ================= OTP TIMER =================
async def otp_timer_update(content, chat_id, message_id, activation_id, order_id, context):
    for remaining in range(300, 0, -1):
        kb = [[
            InlineKeyboardButton("Buy Again", callback_data="buy_again"),
            InlineKeyboardButton("Help❗️", callback_data="help"),
        ]]

        if remaining % 5 == 0:
            code = await get_otp(activation_id, order_id)
            if code:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"{content}🎉 OTP Received!\n\n📩 OTP Code: {code}",
                    reply_markup=InlineKeyboardMarkup(kb),
                )
                return

        mins, secs = divmod(remaining, 60)
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"{content}⏳ Waiting for OTP… {mins}:{secs:02d}",
                reply_markup=InlineKeyboardMarkup(kb),
            )
        except:
            pass

        await asyncio.sleep(1)

    await smsbower_cancel_activation(activation_id)
    await update_otp(order_id, "NONE")
    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=(
            "⚠️ OTP did not arrive within 5 minutes.\n\n"
            "Refund will be processed automatically.\n"
            "Don't Panic 😱\n\n"
            "Please contact support -> @Shivam_cingh"
        ),
    )

async def payment_watcher(
    order_id,
    service_key,
    query,
    context,
):
    for _ in range(60):
        if await check_payment(order_id):
            await mark_payment_success(order_id)

            activation_id, phone = await get_number(service_key)
            await update_ph(order_id, phone)

            kb = [[
                InlineKeyboardButton("Buy Again", callback_data="buy_again"),
                InlineKeyboardButton("Help❗️", callback_data="help"),
            ]]

            msg = await query.message.reply_text(
                f"✅ Payment Successful\n\n"
                f"📌Order ID: {order_id}\n\n"
                f"📞 Number: {phone}\n\n"
                "⏳ Waiting for OTP… 5:00\n",
                reply_markup=InlineKeyboardMarkup(kb),
            )

            asyncio.create_task(
                otp_timer_update(
                    f"✅ Payment Successful\n\n📌Order ID: {order_id}\n\n📞 Number: {phone}\n\n",
                    msg.chat_id,
                    msg.message_id,
                    activation_id,
                    order_id,
                    context,
                )
            )
            return

        await asyncio.sleep(5)

    await mark_payment_failed(order_id)
    await query.message.reply_text("❌ Payment timeout")

# =========================================


# ================= BOT FLOW =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[
        InlineKeyboardButton("WhatsApp", callback_data="service_wa"),
        InlineKeyboardButton("Telegram", callback_data="service_tg"),
    ]]
    await update.message.reply_text(
        "👋 Welcome!\n\n"
        "✅Get instant temporary phone numbers with OTP for WhatsApp and Telegram — "
        "fast, reliable, and fully automated for seamless account verification.",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def buy_again(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await start(update, context)


async def select_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    service_key = query.data.split("_")[1]
    context.user_data["service"] = service_key
    cfg = SERVICE_CONFIG[service_key]

    kb = [[InlineKeyboardButton("Buy Account", callback_data="pay")]]
    prev = await query.edit_message_text(
        f"{cfg['label']} - Phone Number\n\n🌍 Base : India\n"
        f"💰 Price: ₹{cfg['price']}\n"
        "✅ Reliable | Affordable | Good Quality",
        reply_markup=InlineKeyboardMarkup(kb),
    )
    context.user_data["prev"] = prev


async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    service_key = context.user_data["service"]
    prev = context.user_data.get("prev")
    if prev:
        await context.bot.delete_message(prev.chat_id, prev.message_id)

    cfg = SERVICE_CONFIG[service_key]
    order_id = await generate_unique_order_id()
    await save_order(query.from_user.id, order_id, service_key)

    qr_file = generate_qr(order_id, cfg["price"])
    with open(qr_file, "rb") as f:
        qr_msg = await query.message.reply_photo(
            photo=f,
            caption="📲 Scan & Pay\n⏳ Auto verifying (5 minutes)",
        )

    # Start payment watcher in background
    asyncio.create_task(
        payment_watcher(
            order_id=order_id,
            service_key=service_key,
            query=query,
            context=context,
        )
    )

    # IMPORTANT: return immediately
    return




async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("Contact Here -> @Shivam_cingh")
# =========================================


# ================= MAIN =================
app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(select_service, pattern="service_"))
app.add_handler(CallbackQueryHandler(pay, pattern="pay"))
app.add_handler(CallbackQueryHandler(help, pattern="help"))
app.add_handler(CallbackQueryHandler(buy_again, pattern="buy_again"))

app.run_polling()
