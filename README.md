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

Run the application entry point:
```bash
python bot.py
```

* If `MONGODB_URI` is set: Connects to MongoDB Atlas, verifies indexes, and initializes repositories.
* If `MONGODB_URI` is empty: Automatically runs in safe local mode using SQLite (`konkurs.db`), ensuring uninterrupted operation while you prepare your MongoDB cluster.

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
1. **📊 Statistika (Statistics):**
   * Total registered users.
   * Users who completed the referral threshold.
   * Pending users.
   * Total referrals made.
   * Top 5 referrers (with privacy-masked IDs: e.g. `885***3957: 5 ta`).
   * Current status of mandatory subscription checks.

2. **📢 Kanallarni Boshqarish (Channels Management):**
   * **Toggle Check:** Enable or disable mandatory subscription checking with one click.
   * **Add Channel:** Input `Name | Link | ChannelID`. Bot automatically tests administrative privileges in the channel.
   * **Delete Channel:** Remove a channel with a confirmation prompt.

3. **⚙️ Marafon Sozlamalari (Marathon Settings):**
   * Update referral threshold (e.g., change from 3 to 5).
   * Update closed channel invite URL.

4. **🖼 Media va Matnlar (Media & Texts):**
   * Edit promotional share post text (validates `{link}` presence).
   * Update photo file IDs (`PHOTO_1`, `PHOTO_2`).
   * Update sticker file IDs (`WELCOME_STICKER`, `SUCCESS_STICKER`).
   * *Admin Helper:* When an admin sends any photo or sticker to the bot, the bot replies with its Telegram `file_id`.

5. **✉️ Xabar Yuborish (Safe Broadcasting):**
   * Send any post, image, text, or video to all registered users.
   * Prompts with the exact recipient count and requires explicit confirmation.
   * Rate-limited to ~25 messages/second to comply with Telegram flood limits.
   * Handles blocked/deactivated users without interrupting delivery.
   * Concurrency lock prevents accidental duplicate broadcasts.
   * Generates a completion report: Total, Sent, Failed.

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
