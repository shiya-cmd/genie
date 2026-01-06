import random
import string
import asyncio
import requests
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
        "price": 99,
        "service": "wa",
        "country": 22,
        "max_price": 0.4,
    },
    "tg": {
        "label": "Telegram Account",
        "price": 129,
        "service": "tg",
        "country": 22,
        "max_price": 0.5,
    },
}
# =========================================


# ================= ORDER ID =================
def generate_order_id(prefix="OOR", length=16):
    chars = string.ascii_uppercase + string.digits
    return prefix + "".join(random.choices(chars, k=length - len(prefix)))


def order_id_exists(order_id):
    r = requests.get(
        f"{FIREBASE_DB_URL}/orders/{order_id}.json",
        timeout=10,
    )
    return r.status_code == 200 and r.json() is not None


def generate_unique_order_id():
    while True:
        oid = generate_order_id()
        if not order_id_exists(oid):
            return oid
# =========================================


# ================= FIREBASE =================
def save_order(user_id, order_id, service_key):
    cfg = SERVICE_CONFIG[service_key]
    data = {
        "user_id": user_id,
        "order_id": order_id,
        "amount": cfg["price"],
        "status": "PENDING",
        "service": service_key,
        "phone": "",
        "otp": "",
    }
    requests.put(
        f"{FIREBASE_DB_URL}/orders/{order_id}.json",
        json=data,
        timeout=10,
    )


def mark_payment_success(order_id):
    requests.patch(
        f"{FIREBASE_DB_URL}/orders/{order_id}.json",
        json={"status": "SUCCESS"},
        timeout=10,
    )


def mark_payment_failed(order_id):
    requests.patch(
        f"{FIREBASE_DB_URL}/orders/{order_id}.json",
        json={"status": "FAILED"},
        timeout=10,
    )

def update_ph(order_id, phone):
    requests.patch(
        f"{FIREBASE_DB_URL}/orders/{order_id}.json",
        json={"phone": phone},
        timeout=10,
    )


def update_otp(order_id, otp):
    requests.patch(
        f"{FIREBASE_DB_URL}/orders/{order_id}.json",
        json={"otp": otp},
        timeout=10,
    )
# =========================================


# ================= QR =================
def generate_qr(order_id, amount):
    upi_uri = (
        f"upi://pay?"
        f"pa={UPI_VPA}&pn={MERCHANT_NAME}&am={amount}"
        f"&cu=INR&tn={order_id}&tr={order_id}&tid={order_id}"
    )
    file = f"{order_id}.png"
    segno.make(upi_uri, error="m").save(file, kind="png", scale=8, border=4)
    return file
# =========================================


# ================= PAYMENT =================
def check_payment(order_id):
    try:
        r = requests.get(
            PAYTM_WORKER_URL,
            params={"mid": PAYTM_MID, "id": order_id},
            timeout=10,
        )
        return r.status_code == 200 and r.json().get("STATUS") == "TXN_SUCCESS"
    except Exception:
        return False
# =========================================


# ================= SMSBOWER =================
def get_number(service_key):
    cfg = SERVICE_CONFIG[service_key]
    r = requests.get(
        "https://smsbower.online/stubs/handler_api.php",
        params={
            "api_key": SMSBOWER_API_KEY,
            "action": "getNumberV2",
            "service": cfg["service"],
            "country": cfg["country"],
            "maxPrice": cfg["max_price"],
        },
        timeout=10,
    )
    if r.status_code != 200 or not r.text:
        return None, None
    data = r.json()
    return data.get("activationId"), data.get("phoneNumber")


def get_otp(activation_id, order_id):
    r = requests.get(
        "https://smsbower.online/stubs/handler_api.php",
        params={
            "api_key": SMSBOWER_API_KEY,
            "action": "getStatus",
            "id": activation_id,
        },
        timeout=10,
    )
    text = r.text.strip()
    if text.startswith("STATUS_OK"):
        otp = text.split(":")[1]
        update_otp(order_id, otp)
        smsbower_complete_activation(activation_id)
        return otp
    return None


def smsbower_set_status(activation_id, status):
    try:
        r = requests.get(
            "https://smsbower.online/stubs/handler_api.php",
            params={
                "api_key": SMSBOWER_API_KEY,
                "action": "setStatus",
                "id": activation_id,
                "status": status,
            },
            timeout=10,
        )
        return r.text.strip().startswith(("OK", "ACCESS", "SUCCESS"))
    except:
        return False


def smsbower_complete_activation(activation_id):
    return smsbower_set_status(activation_id, 6)


def smsbower_cancel_activation(activation_id):
    return smsbower_set_status(activation_id, 8)
# =========================================


# ================= OTP TIMER =================
async def otp_timer_update(content, chat_id, message_id, activation_id, order_id, context):
    for remaining in range(300, 0, -1):
        kb = [
            [InlineKeyboardButton("Buy Again", callback_data="buy_again"),
             InlineKeyboardButton("Help❗️", callback_data="help")]
        ]

        if remaining % 5 == 0:
            code = get_otp(activation_id, order_id)
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

    smsbower_cancel_activation(activation_id)
    update_otp(order_id, "NONE")
    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text="⚠️ OTP did not arrive within 5 minutes.\n\nRefund will be processed automatically.\nDon't Panic 😱 \n\nPlease contact support -> @Shivam_cingh",
    )
# =========================================


# ================= BOT FLOW =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("WhatsApp", callback_data="service_wa"),
         InlineKeyboardButton("Telegram", callback_data="service_tg")]
    ]
    await update.message.reply_text(
        "👋 Welcome!\n\n✅Get instant temporary phone numbers with OTP for WhatsApp and Telegram — fast, reliable, and fully automated for seamless account verification.",
        reply_markup=InlineKeyboardMarkup(kb),
    )

async def buy_again(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("WhatsApp", callback_data="service_wa"),
         InlineKeyboardButton("Telegram", callback_data="service_tg")]
    ]
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "👋 Welcome!\n\n✅Get instant temporary phone numbers with OTP for WhatsApp and Telegram — fast, reliable, and fully automated for seamless account verification.",
        reply_markup=InlineKeyboardMarkup(kb),
    )

async def select_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    service_key = query.data.split("_")[1]
    context.user_data["service"] = service_key
    cfg = SERVICE_CONFIG[service_key]

    kb = [[InlineKeyboardButton("Buy Account", callback_data="pay")]]
    prev=await query.edit_message_text(
        f"{cfg['label']} - Phone Number\n\n🌍 Base : India\n💰 Price: ₹{cfg['price']}\n✅ Reliable | Affordable | Good Quality",
        reply_markup=InlineKeyboardMarkup(kb),
    )
    context.user_data["prev"] = prev



async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    service_key = context.user_data["service"]
    prev = context.user_data["prev"]
    await context.bot.delete_message(
        chat_id=prev.chat_id,
        message_id=prev.message_id
    )
    cfg = SERVICE_CONFIG[service_key]

    order_id = generate_unique_order_id()
    save_order(query.from_user.id, order_id, service_key)

    qr_file = generate_qr(order_id, cfg["price"])
    with open(qr_file, "rb") as f:
        prev=await query.message.reply_photo(
            photo=f,
            caption="📲 Scan & Pay\n⏳ Auto verifying (5 minutes)",
        )

    for _ in range(60):
        if check_payment(order_id):  # replace with check_payment(order_id) in production
            await context.bot.delete_message(
                chat_id=prev.chat_id,
                message_id=prev.message_id
            )
            mark_payment_success(order_id)
            activation_id, phone = get_number(service_key)
            update_ph(order_id, phone)

            kb = [
                [InlineKeyboardButton("Buy Again", callback_data="service_"),
                InlineKeyboardButton("Help❗️", callback_data="help")]
            ]

            msg = await query.message.reply_text(
                f"✅ Payment Successful\n\n📌Order ID: {order_id}\n\n📞 Number: {phone}\n\n⏳ Waiting for OTP… 5:00\n",
                reply_markup=InlineKeyboardMarkup(kb),
            )

            content = f"✅ Payment Successful\n\n📌Order ID: {order_id}\n\n📞 Number: {phone}\n\n"
            asyncio.create_task(
                otp_timer_update(
                    content,
                    msg.chat_id,
                    msg.message_id,
                    activation_id,
                    order_id,
                    context,
                )
            )
            return

        await asyncio.sleep(5)

    mark_payment_failed(order_id)
    await query.message.reply_text("❌ Payment timeout")


async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("Contact Here -> @Shivam_cingh")
# =========================================


# ================= MAIN =================
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(select_service, pattern="service_"))
app.add_handler(CallbackQueryHandler(pay, pattern="pay"))
app.add_handler(CallbackQueryHandler(help, pattern="help"))
app.add_handler(CallbackQueryHandler(buy_again, pattern="buy_again"))
app.run_polling()
