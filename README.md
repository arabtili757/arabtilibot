# Arab Tili Marathon Telegram Bot

A modular, production-ready Telegram bot built with **Aiogram 3.x**, **MongoDB Atlas (Motor)**, and **aiosqlite**. The bot facilitates referral-based user onboarding for the Arab Tili Marathon, verifies mandatory channel subscriptions, provides personal referral links, and gives access to the closed marathon channel upon reaching the referral threshold.

---

## 1. Project Architecture

```
Arab Tili Bot/
├── bot.py                        # Clean application entry point
├── config.py                     # Pydantic-backed environment configuration
├── database/
│   ├── __init__.py
│   ├── connection.py             # MongoDB Atlas connection manager (Motor)
│   ├── models.py                 # Pydantic document schemas (User, Channels, Settings)
│   ├── repository.py             # UserRepository and SettingsRepository for MongoDB
│   ├── sqlite_repository.py      # SQLite & memory fallback for local execution
│   └── migration.py              # CLI migration utility (SQLite -> MongoDB Atlas)
├── handlers/
│   ├── __init__.py
│   ├── middlewares.py            # IsAdminFilter permission guard
│   ├── user_handlers.py          # /start, checksub callback, share post flow
│   └── admin_handlers.py         # Full admin dashboard (/admin, /panel)
├── keyboards/
│   ├── __init__.py
│   ├── user_keyboards.py         # Channel subscription links and check button
│   └── admin_keyboards.py        # Admin panel menus and confirmation dialogs
├── services/
│   ├── __init__.py
│   ├── subscription_service.py   # Telegram channel membership verification
│   ├── referral_service.py       # Referral validation and progress notifications
│   └── broadcast_service.py      # Rate-limited broadcasting with deduplication
├── utils/
│   ├── __init__.py
│   └── telegram_helpers.py       # Exception-safe senders (safe_send, safe_sticker)
├── tests/                        # 30 comprehensive unit & integration tests
├── .env.example                  # Safe configuration template
├── .gitignore                    # Excludes secrets, databases, backups, caches
└── requirements.txt              # Pinned Python package dependencies
```

---

## 2. Installation and Environment Setup

### Prerequisites
* Python 3.10+ (tested on Python 3.12)
* Active Telegram Bot Token from [@BotFather](https://t.me/BotFather)
* MongoDB Atlas connection string (or local SQLite for development)

### Setup Steps
1. **Clone or navigate to the project directory:**
   ```bash
   cd "Arab Tili Bot"
   ```

2. **Create and activate a virtual environment (optional but recommended):**
   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # Linux/macOS:
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables:**
   Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
   Fill in your actual credentials in `.env`:
   * `BOT_TOKEN`: Your Telegram Bot API token.
   * `ADMIN_IDS`: Comma-separated list of Telegram admin user IDs.
   * `REQUIRED_REFERRALS`: Number of referrals needed to unlock the closed channel (e.g. `3`).
   * `CLOSED_CHANNEL_LINK`: The invite link to the closed marathon channel.
   * `SUBSCRIPTION_CHECK_ENABLED`: Set to `true` or `false`.
   * `MANDATORY_CHANNELS`: JSON array of required channels (`[{"name": "...", "url": "...", "id": -100...}]`).
   * `MONGODB_URI`: MongoDB Atlas connection string (leave blank to run in local SQLite fallback mode).
   * `MONGODB_DB_NAME`: Database name (e.g. `arab_tili_marathon`).

---

## 3. Required Telegram Bot Permissions

For the subscription check (`bot.get_chat_member`) to function correctly:
1. **Administrator in Mandatory Channels:**
   * The bot **must be added as an administrator** to every channel listed in `MANDATORY_CHANNELS`.
   * Required channel admin rights: **Invite Users via Link** (or basic admin permissions).
   * *Note:* If the bot is not an admin, Telegram's API raises a permission error and rejects subscription checks.
2. **Channel Privacy:**
   * For private channels, use the bot-generated invite links.

---

## 4. Running the Bot

Run the application entry point locally:
```bash
python bot.py
```

### Deploying on Render (Web Service)

The bot includes a built-in non-blocking HTTP health check server that listens on `0.0.0.0:$PORT` (or default 10000) alongside Aiogram Telegram polling. This satisfies Render's HTTP port check requirement without requiring a Background Worker.

1. Create a **Web Service** on [Render](https://render.com).
2. Connect your GitHub repository: `arabtili757/arabtilibot`.
3. Configure the following settings:
   * **Runtime:** `Python 3`
   * **Build Command:** `pip install -r requirements.txt`
   * **Start Command:** `python bot.py`
   * **Health Check Path:** `/health` (or `/`)
4. Add your environment variables in the Render Dashboard (**Environment** tab):
   * `BOT_TOKEN`
   * `ADMIN_IDS`
   * `MONGODB_URI`
   * `MONGODB_DB_NAME`
   * `REQUIRED_REFERRALS`
   * `CLOSED_CHANNEL_LINK`
   * `SUBSCRIPTION_CHECK_ENABLED`
   * `MANDATORY_CHANNELS`
   * `PHOTO_1`, `PHOTO_2`, `WELCOME_STICKER`, `SUCCESS_STICKER` (optional)

---

## 5. SQLite to MongoDB Atlas Migration

A dedicated, idempotent migration tool is provided in `database/migration.py`.

### Migration Guarantees
* **Data Safety:** Never deletes or alters the source SQLite database.
* **Automatic Backup:** Creates a timestamped backup in `backups/` and verifies it using `PRAGMA integrity_check`.
* **Idempotence:** Safe to rerun multiple times; uses stable upserts on `user_id` so referral counts and relationships are never duplicated.
* **Privacy:** Reports only aggregate counts (e.g. `Source: N, Verified: N, Mismatches: 0`), never individual user IDs or secrets.
* **Strict Verification:** Compares every record in SQLite against MongoDB after upserting.

### Step 1: Run Dry-Run (Verification without writing)
```bash
python -m database.migration --source konkurs.db --mongo-uri "mongodb+srv://..." --dry-run
```

### Step 2: Run Full Migration (Requires `--confirm`)
```bash
python -m database.migration --source konkurs.db --mongo-uri "mongodb+srv://..." --db-name arab_tili_marathon --confirm
```

### Recovery from a Failed Migration
* If a network or verification error occurs:
  1. The source SQLite database (`konkurs.db`) remains completely untouched.
  2. The timestamped backup is preserved in `backups/konkurs_backup_YYYYMMDD_HHMMSS.db`.
  3. Investigate the connection or network issue, verify MongoDB credentials, and re-run the migration command. Because it is idempotent, it will safely reconcile any records.

---

## 6. Admin Workflows

Administrators (`ADMIN_IDS`) have access to protected management tools:

### Accessing Admin Panel
Send `/admin` or `/panel` in the Telegram bot chat. Unauthorized users are blocked from executing admin commands or clicking admin callback buttons.

### Workflows Available:
1. **📊 Statistika (Accurate Admin Statistics):**
   * **A. Foydalanuvchilar statistikasi:**
     * Jami ro'yxatdan o'tgan foydalanuvchilar soni.
     * Bugun ro'yxatdan o'tganlar (Toshkent vaqti - `Asia/Tashkent` bo'yicha).
     * Oxirgi 7 kunda ro'yxatdan o'tganlar.
     * Referal havola orqali ro'yxatdan o'tganlar soni.
     * Marafonda ishtirok etish huquqiga ega (barcha majburiy kanallarga a'zo) foydalanuvchilar.
     * Majburiy obunani to'liq bajarmagan / jarayondagi foydalanuvchilar.
     * Sanasiz eski foydalanuvchilar (mavjud bo'lsa, alohida ko'rsatiladi).
   * **B. Majburiy kanallar statistikasi:**
     * Har bir kanal nomi va ID si.
     * A'zo bo'lgan bot foydalanuvchilari soni.
     * A'zo bo'lmagan foydalanuvchilar soni.
     * A'zoligi tekshirib bo'lmaganlar (masalan, bot admin bo'lmagan holatlarda) alohida ko'rsatiladi.
     * Botning kanaldagi admin huquqi holati va ogohlantirishlar.
   * **C. Referal statistikasi:**
     * Jami muvaffaqiyatli, noyob referallar (haqiqiy munosabatlar asosida).
     * Barcha majburiy obunalarni bajargan taklif qilinganlar soni.
     * Eng faol taklif qiluvchilar (Top 10) ro'yxati, takliflar soni va ularning shaxsiy havolalari (`https://t.me/ArabiyaBoost_bot?start=USER_ID`).
   * **Keshlash va Yangilash:**
     * Natijalar 5 daqiqa davomida keshlanadi va Telegram API cheklovlariga (flood limit) tushmaslik uchun navbat bilan tekshiriladi.
     * `🔄 Yangilash` tugmasi orqali istalgan payt statistikani qayta tekshirish mumkin.

2. **📢 Kanallarni Boshqarish (Channels Management):**
   * **Avtomatik obunani tekshirish:** Foydalanuvchilar kanallarga a'zo bo'lishi bilanoq Telegram `chat_member` hodisasi orqali avtomatik ro'yxatdan o'tkaziladi (qo'shimcha tugma bosish shart emas).
   * **MUHIM TELEGRAM TALABI:** Bot barcha majburiy kanallarda **administrator** (admin) huquqiga ega bo'lishi shart! Agar bot kanalda admin bo'lmasa, Telegram `chat_member` hodisalarini yetkazib bermaydi va a'zolikni tekshirib bo'lmaydi.
   * **Toggle Check:** Majburiy obuna tekshirishni yoqish/o'chirish.
   * **Add Channel:** Input `Name | Link | ChannelID`. Bot kanaldagi adminlik huquqini avtomatik tekshiradi.
   * **Delete Channel:** Kanalni o'chirish.

3. **📝 Asosiy Xabarni Tahrirlash (Edit Promotional Message):**
   * Admin panelidagi `📝 Asosiy xabarni tahrirlash` tugmasi orqali yangi reklama matni kiritiladi.
   * Telegram HTML teglari (qalin, kursiv, havolalar, blockquote) to'liq qo'llab-quvvatlanadi.
   * Matnda `{link}` tegi mavjudligi avtomatik tekshiriladi va foydalanuvchiga tasdiqlashdan oldin ko'rinishi (Preview) taqdim etiladi.
   * `✅ Tasdiqlash` bosilganda matn MongoDB ga saqlanadi va botni qayta yoqmasdan darhol yangi foydalanuvchilarga ko'rsatiladi.

4. **📤 Shaxsiy Do'stlarga Ulashish Tugmasi (Personalized Share Button):**
   * Reklama posti ostida `📤 Do'stlarga ulashish` tugmasi joylashadi.
   * Bosilganda Telegramning rasmiy chat tanlash oynasi ochiladi va avtomatik tayyor o'zbekcha matn kiritiladi:
     `"Shu botga kirib ko'ring, zo'r ekan! Arab tili marafoniga qo'shiling!"`
   * Har bir foydalanuvchining shaxsiy referal havolasi (`https://t.me/ArabiyaBoost_bot?start=USER_ID`) xavfsiz URL-kodlash orqali ulanadi.
   * Ikki rasmli albom posti (media group) inline tugmalarni to'g'ridan-to'g'ri qabul qilmasligi sababli, tugma albomning darhol ketidan alohida qisqa xabar bilan yuboriladi.

5. **⚙️ Marafon Sozlamalari (Marathon Settings):**
   * Referal chegarasini o'zgartirish (masalan, 3 tadan 5 taga).
   * Yopiq kanal havolasini o'zgartirish.

6. **🖼 Media va Matnlar (Media & Texts):**
   * Rasm va stiker file ID larini o'zgartirish.
   * *Admin Helper:* Admin botga rasm yoki stiker yuborsa, bot uning `file_id` sini qaytaradi.

7. **✉️ Xabar Yuborish (Safe Broadcasting):**
   * Barcha ro'yxatdan o'tgan foydalanuvchilarga xabar yuborish.
   * Tasdiqlash, flood control va yakuniy hisobot.

---

## 7. Credential Rotation Guide

If a bot token or MongoDB URI was ever committed to version control or shared in an insecure channel:

1. **Telegram Bot Token:**
   * Open [@BotFather](https://t.me/BotFather).
   * Send `/revoke` and select your bot.
   * Copy the newly generated token.
   * Update `BOT_TOKEN` in your `.env` file.
   * Restart the bot.

2. **MongoDB Atlas URI:**
   * Go to MongoDB Atlas -> **Database Access**.
   * Edit or delete the exposed database user and create a new secure password.
   * Update `MONGODB_URI` in `.env`.
   * Restart the bot.

---

## 8. Running Automated Tests

Run the test suite using `pytest`:
```bash
python -m pytest -v
```
All 30 tests cover configuration validation, referral edge cases, subscription flows, admin authorization, database repository operations, and migration idempotency.
