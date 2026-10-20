"""Automated test suite for promotional image management in Arab Tili Bot.

Verifies:
1. Uploading and saving a valid Telegram photo.
2. Rejecting invalid uploads (documents, unsupported media, text).
3. Selecting the largest available PhotoSize.
4. Persisting image settings in MongoDB.
5. Adding multiple images and preventing duplicate entries.
6. Removing an individual image.
7. Clearing all images with explicit confirmation.
8. Displaying images to users (0, 1, and multiple images).
9. Working correctly when no images are configured.
10. Falling back to promotional text when Telegram rejects an image (no duplicate messages).
11. Preserving personalized referral links and the sharing button.
12. Preventing unauthorized image management.
13. Preserving settings after a simulated restart.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from aiogram.types import InputMediaPhoto, PhotoSize
from config import BotConfig
from database.models import BotSettingsDocument
from database.repository import SettingsRepository, UserRepository
from handlers.admin_handlers import AdminStates, create_admin_router
from handlers.middlewares import IsAdminFilter
from handlers.user_handlers import complete_registration_and_respond, create_user_router
from keyboards.admin_keyboards import get_promo_images_keyboard
from services.broadcast_service import BroadcastService
from services.referral_service import RegistrationResult
from tests.test_database_repository import AsyncMockDatabase


@pytest.fixture
def promo_setup():
    db = AsyncMockDatabase()
    cfg = BotConfig(
        BOT_TOKEN="123456:TEST_TOKEN",
        OWNER_IDS="5924300834",
        ADMIN_IDS="5364318707",
        MONGODB_URI="mongodb://localhost:27017",
        CLOSED_CHANNEL_LINK="https://t.me/+closed_link",
    )
    user_repo = UserRepository(db)
    settings_repo = SettingsRepository(db)
    broadcast_service = BroadcastService()

    return {
        "db": db,
        "cfg": cfg,
        "user_repo": user_repo,
        "settings_repo": settings_repo,
        "broadcast_service": broadcast_service,
    }


# ==============================================================================
# TEST 1, 3, 5: Upload valid photo, select largest PhotoSize, prevent duplicates
# ==============================================================================

def test_upload_and_save_largest_photo_and_prevent_duplicates(promo_setup):
    async def _test():
        cfg = promo_setup["cfg"]
        settings_repo = promo_setup["settings_repo"]
        user_repo = promo_setup["user_repo"]
        broadcast_service = promo_setup["broadcast_service"]

        await settings_repo.get_settings(cfg)
        admin_router = create_admin_router(cfg, user_repo, settings_repo, broadcast_service)

        # Locate handlers
        photo_handler = None
        confirm_handler = None
        for handler in admin_router.message.handlers:
            if getattr(handler.callback, "__name__", "") == "msg_receive_promo_photo":
                photo_handler = handler.callback
                break
        for handler in admin_router.callback_query.handlers:
            if getattr(handler.callback, "__name__", "") == "cb_promo_img_add_confirm":
                confirm_handler = handler.callback
                break

        assert photo_handler is not None
        assert confirm_handler is not None

        # 1. Admin sends photo with 3 sizes: small, medium, and largest
        msg = MagicMock()
        msg.from_user.id = 5924300834
        p_small = PhotoSize(file_id="fid_small_100", file_unique_id="u1", width=100, height=100)
        p_med = PhotoSize(file_id="fid_med_320", file_unique_id="u2", width=320, height=320)
        p_large = PhotoSize(file_id="fid_large_1280", file_unique_id="u3", width=1280, height=1280)
        msg.photo = [p_small, p_med, p_large]
        msg.answer_photo = AsyncMock()
        msg.answer = AsyncMock()

        state = MagicMock()
        state.update_data = AsyncMock()
        state.set_state = AsyncMock()
        state.get_data = AsyncMock(return_value={"pending_promo_image": "fid_large_1280"})
        state.clear = AsyncMock()

        await photo_handler(msg, state)

        # Verified: selected largest photo (fid_large_1280)
        state.update_data.assert_called_once_with(pending_promo_image="fid_large_1280")
        state.set_state.assert_called_once_with(AdminStates.waiting_for_promo_image_confirm)
        msg.answer_photo.assert_called_once()
        _, photo_kwargs = msg.answer_photo.call_args
        assert photo_kwargs["photo"] == "fid_large_1280"

        # 2. Confirm adding the image
        cb_confirm = MagicMock()
        cb_confirm.from_user.id = 5924300834
        cb_confirm.answer = AsyncMock()
        cb_confirm.message.answer = AsyncMock()
        cb_confirm.message.edit_text = AsyncMock()

        await confirm_handler(cb_confirm, state)
        cb_confirm.answer.assert_called_once_with("Muvaffaqiyatli saqlandi!")

        # Verified: Saved in MongoDB
        saved_images = await settings_repo.get_promo_images()
        assert "fid_large_1280" in saved_images
        assert len(saved_images) == 1

        # 3. Duplicate Prevention: Admin sends the exact same photo again
        msg_dup = MagicMock()
        msg_dup.from_user.id = 5924300834
        msg_dup.photo = [p_large]
        msg_dup.answer = AsyncMock()
        msg_dup.answer_photo = AsyncMock()
        state_dup = MagicMock()
        state_dup.update_data = AsyncMock()

        await photo_handler(msg_dup, state_dup)
        msg_dup.answer.assert_called_once()
        dup_text = msg_dup.answer.call_args[0][0]
        assert "allaqachon reklama rasmlari ro'yxatida mavjud" in dup_text
        state_dup.update_data.assert_not_called()
        msg_dup.answer_photo.assert_not_called()

        # Database still contains exactly 1 image
        assert len(await settings_repo.get_promo_images()) == 1

    asyncio.run(_test())


# ==============================================================================
# TEST 2: Reject invalid uploads (documents, unsupported media, text)
# ==============================================================================

def test_reject_invalid_uploads(promo_setup):
    async def _test():
        cfg = promo_setup["cfg"]
        settings_repo = promo_setup["settings_repo"]
        user_repo = promo_setup["user_repo"]
        broadcast_service = promo_setup["broadcast_service"]

        await settings_repo.get_settings(cfg)
        admin_router = create_admin_router(cfg, user_repo, settings_repo, broadcast_service)

        doc_handler = None
        invalid_media_handler = None
        for handler in admin_router.message.handlers:
            name = getattr(handler.callback, "__name__", "")
            if name == "msg_reject_promo_document":
                doc_handler = handler.callback
            elif name == "msg_reject_promo_invalid_media":
                invalid_media_handler = handler.callback

        assert doc_handler is not None
        assert invalid_media_handler is not None

        # 1. Admin sends a document/file
        msg_doc = MagicMock()
        msg_doc.from_user.id = 5924300834
        msg_doc.answer = AsyncMock()

        await doc_handler(msg_doc)
        msg_doc.answer.assert_called_once()
        rejection_text = msg_doc.answer.call_args[0][0]
        assert "Bu rasm emas, fayl (hujjat) ko'rinishida yuborildi" in rejection_text
        assert "oddiy rasm sifatida" in rejection_text

        # 2. Admin sends unsupported media or text
        msg_invalid = MagicMock()
        msg_invalid.from_user.id = 5924300834
        msg_invalid.answer = AsyncMock()

        await invalid_media_handler(msg_invalid)
        msg_invalid.answer.assert_called_once()
        invalid_text = msg_invalid.answer.call_args[0][0]
        assert "Noto'g'ri format" in invalid_text
        assert "Faqat haqiqiy rasm (photo) qabul qilinadi" in invalid_text

        # Verify no images were saved
        assert len(await settings_repo.get_promo_images()) == 0

    asyncio.run(_test())


# ==============================================================================
# TEST 4, 5, 6, 7: MongoDB persistence, adding multiple, removing single, clearing all
# ==============================================================================

def test_multiple_images_remove_and_clear_all(promo_setup):
    async def _test():
        settings_repo = promo_setup["settings_repo"]
        cfg = promo_setup["cfg"]
        user_repo = promo_setup["user_repo"]
        broadcast_service = promo_setup["broadcast_service"]

        await settings_repo.get_settings(cfg)

        # 1. Add multiple images
        await settings_repo.add_promo_image("promo_img_1")
        await settings_repo.add_promo_image("promo_img_2")
        await settings_repo.add_promo_image("promo_img_3")

        images = await settings_repo.get_promo_images()
        assert images == ["promo_img_1", "promo_img_2", "promo_img_3"]

        admin_router = create_admin_router(cfg, user_repo, settings_repo, broadcast_service)

        del_confirm_handler = None
        clear_confirm_handler = None
        for handler in admin_router.callback_query.handlers:
            name = getattr(handler.callback, "__name__", "")
            if name == "cb_promo_img_del_confirm":
                del_confirm_handler = handler.callback
            elif name == "cb_promo_img_clear_confirm":
                clear_confirm_handler = handler.callback

        assert del_confirm_handler is not None
        assert clear_confirm_handler is not None

        # 2. Remove an individual image (index 1 -> promo_img_2)
        cb_del = MagicMock()
        cb_del.data = "admin_promo_del_confirm_1"
        cb_del.answer = AsyncMock()
        cb_del.message.edit_text = AsyncMock()

        await del_confirm_handler(cb_del)
        cb_del.answer.assert_called_once_with("O'chirildi!")

        remaining = await settings_repo.get_promo_images()
        assert remaining == ["promo_img_1", "promo_img_3"]

        # 3. Clear all images with confirmation
        cb_clear = MagicMock()
        cb_clear.data = "admin_promo_img_clear_confirm"
        cb_clear.answer = AsyncMock()
        cb_clear.message.edit_text = AsyncMock()
        state_clear = MagicMock()
        state_clear.clear = AsyncMock()

        await clear_confirm_handler(cb_clear, state_clear)
        cb_clear.answer.assert_called_once_with("Barcha rasmlar o'chirildi!")

        cleared = await settings_repo.get_promo_images()
        assert cleared == []

    asyncio.run(_test())


# ==============================================================================
# TEST 8, 9, 11: Displaying images to users (0, 1, and multiple images)
# ==============================================================================

def test_user_delivery_modes_and_sharing_buttons(promo_setup):
    async def _test():
        settings_repo = promo_setup["settings_repo"]
        cfg = promo_setup["cfg"]
        user_id = 77777777
        await settings_repo.get_settings(cfg)

        # Case A: 0 images configured
        await settings_repo.clear_promo_images()
        settings_0 = await settings_repo.get_settings(cfg)
        assert len(settings_0.promo_images) == 0

        bot_mock = MagicMock()
        bot_mock.get_me = AsyncMock(return_value=MagicMock(username="TestArabTiliBot"))
        bot_mock.send_message = AsyncMock(return_value=MagicMock())
        bot_mock.send_photo = AsyncMock(return_value=MagicMock())
        bot_mock.send_media_group = AsyncMock(return_value=[MagicMock()])

        res = RegistrationResult(is_new_user=True, user_referrals_count=0, is_completed=False)

        await complete_registration_and_respond(
            bot=bot_mock,
            user_id=user_id,
            result=res,
            settings=settings_0,
            settings_repo=settings_repo,
        )

        # 0 images: photo and media group are NOT called; promotional text sent via send_message
        bot_mock.send_photo.assert_not_called()
        bot_mock.send_media_group.assert_not_called()
        # send_message called: welcome header + promo text
        assert bot_mock.send_message.call_count == 2
        promo_call = bot_mock.send_message.call_args_list[-1]
        sent_text = promo_call[0][1]
        sent_kb = promo_call[1]["reply_markup"]
        assert sent_kb is not None
        assert "Do'stlarga ulashish" in str(sent_kb)
        assert f"start%3D{user_id}" in str(sent_kb) or f"start={user_id}" in str(sent_kb)

        # Case B: 1 image configured
        bot_mock.reset_mock()
        bot_mock.get_me = AsyncMock(return_value=MagicMock(username="TestArabTiliBot"))
        bot_mock.send_message = AsyncMock(return_value=MagicMock())
        bot_mock.send_photo = AsyncMock(return_value=MagicMock())
        bot_mock.send_media_group = AsyncMock(return_value=[MagicMock()])

        await settings_repo.add_promo_image("single_promo_file_id")
        settings_1 = await settings_repo.get_settings(cfg)
        assert len(settings_1.promo_images) == 1

        await complete_registration_and_respond(
            bot=bot_mock,
            user_id=user_id,
            result=res,
            settings=settings_1,
            settings_repo=settings_repo,
        )

        # 1 image: send_photo called with the image, caption, and inline share_kb
        bot_mock.send_photo.assert_called_once()
        photo_kwargs = bot_mock.send_photo.call_args[1]
        assert photo_kwargs["photo"] == "single_promo_file_id"
        assert photo_kwargs["reply_markup"] is not None
        assert "Do'stlarga ulashish" in str(photo_kwargs["reply_markup"])
        assert f"start%3D{user_id}" in str(photo_kwargs["reply_markup"]) or f"start={user_id}" in str(photo_kwargs["reply_markup"])
        # No media group called
        bot_mock.send_media_group.assert_not_called()
        # Welcome message sent once, no duplicate promo message sent
        assert bot_mock.send_message.call_count == 1

        # Case C: Multiple images configured (3 images)
        bot_mock.reset_mock()
        bot_mock.get_me = AsyncMock(return_value=MagicMock(username="TestArabTiliBot"))
        bot_mock.send_message = AsyncMock(return_value=MagicMock())
        bot_mock.send_photo = AsyncMock(return_value=MagicMock())
        bot_mock.send_media_group = AsyncMock(return_value=[MagicMock(), MagicMock(), MagicMock()])

        await settings_repo.add_promo_image("second_promo_file_id")
        await settings_repo.add_promo_image("third_promo_file_id")
        settings_3 = await settings_repo.get_settings(cfg)
        assert len(settings_3.promo_images) == 3

        await complete_registration_and_respond(
            bot=bot_mock,
            user_id=user_id,
            result=res,
            settings=settings_3,
            settings_repo=settings_repo,
        )

        # Media group called with 3 InputMediaPhoto items
        bot_mock.send_media_group.assert_called_once()
        media_group = bot_mock.send_media_group.call_args[1]["media"]
        assert len(media_group) == 3
        assert media_group[0].media == "single_promo_file_id"
        assert "ARAB TILI MARAFONI" in media_group[0].caption
        assert media_group[1].media == "second_promo_file_id"
        assert media_group[2].media == "third_promo_file_id"

        # Separate follow-up message sent with share_kb button below album
        assert bot_mock.send_message.call_count == 2
        followup_call = bot_mock.send_message.call_args_list[-1]
        assert "Do'stlarga ulashish" in followup_call[0][1] or "quyidagi tugmani bosing" in followup_call[0][1]
        assert followup_call[1]["reply_markup"] is not None
        assert f"start%3D{user_id}" in str(followup_call[1]["reply_markup"]) or f"start={user_id}" in str(followup_call[1]["reply_markup"])

    asyncio.run(_test())


# ==============================================================================
# TEST 10: Fallback to text when Telegram rejects an image (no duplicate messages)
# ==============================================================================

def test_telegram_error_fallback_without_duplicates(promo_setup):
    async def _test():
        settings_repo = promo_setup["settings_repo"]
        cfg = promo_setup["cfg"]
        user_id = 88888888
        await settings_repo.get_settings(cfg)

        # 1. Single photo rejection fallback (e.g. "can't use file of type Thumbnail as Photo")
        await settings_repo.clear_promo_images()
        await settings_repo.add_promo_image("bad_thumbnail_file_id")
        settings = await settings_repo.get_settings(cfg)

        bot_mock = MagicMock()
        bot_mock.get_me = AsyncMock(return_value=MagicMock(username="TestArabTiliBot"))
        bot_mock.send_message = AsyncMock(return_value=MagicMock())
        # Photo sending raises Telegram BadRequest
        bot_mock.send_photo = AsyncMock(side_effect=Exception("Bad Request: can't use file of type Thumbnail as Photo"))

        res = RegistrationResult(is_new_user=True, user_referrals_count=0, is_completed=False)

        await complete_registration_and_respond(
            bot=bot_mock,
            user_id=user_id,
            result=res,
            settings=settings,
            settings_repo=settings_repo,
        )

        # Photo was attempted
        bot_mock.send_photo.assert_called_once()
        # Fallback text was delivered safely
        assert bot_mock.send_message.call_count == 2
        fallback_msg = bot_mock.send_message.call_args_list[-1]
        assert fallback_msg[1]["reply_markup"] is not None
        assert "Do'stlarga ulashish" in str(fallback_msg[1]["reply_markup"])
        assert f"start%3D{user_id}" in str(fallback_msg[1]["reply_markup"]) or f"start={user_id}" in str(fallback_msg[1]["reply_markup"])

        # 2. Album rejection fallback
        bot_mock.reset_mock()
        bot_mock.get_me = AsyncMock(return_value=MagicMock(username="TestArabTiliBot"))
        bot_mock.send_message = AsyncMock(return_value=MagicMock())
        bot_mock.send_media_group = AsyncMock(side_effect=Exception("Bad Request: wrong file id"))

        await settings_repo.add_promo_image("second_id")
        settings_multi = await settings_repo.get_settings(cfg)

        await complete_registration_and_respond(
            bot=bot_mock,
            user_id=user_id,
            result=res,
            settings=settings_multi,
            settings_repo=settings_repo,
        )

        # Media group attempted
        bot_mock.send_media_group.assert_called_once()
        # Fallback text was delivered safely, exactly once (no duplicate promotional messages!)
        # 1st call: welcome message, 2nd call: promotional text with share button
        assert bot_mock.send_message.call_count == 2
        album_fallback = bot_mock.send_message.call_args_list[-1]
        assert album_fallback[1]["reply_markup"] is not None
        assert "Do'stlarga ulashish" in str(album_fallback[1]["reply_markup"])
        assert f"start%3D{user_id}" in str(album_fallback[1]["reply_markup"]) or f"start={user_id}" in str(album_fallback[1]["reply_markup"])

    asyncio.run(_test())


# ==============================================================================
# TEST 12: Preventing unauthorized image management
# ==============================================================================

def test_prevent_unauthorized_image_management(promo_setup):
    async def _test():
        cfg = promo_setup["cfg"]
        settings_repo = promo_setup["settings_repo"]
        user_repo = promo_setup["user_repo"]
        unauth_id = 999999999

        await settings_repo.get_settings(cfg)
        admin_filter = IsAdminFilter(cfg, settings_repo)

        # 1. IsAdminFilter rejects callback query to promotional images
        cb = MagicMock()
        cb.data = "admin_promo_images"
        cb.from_user.id = unauth_id
        assert await admin_filter(cb) is False

        # 2. IsAdminFilter rejects photo message from unauthorized user
        msg = MagicMock()
        msg.from_user.id = unauth_id
        assert await admin_filter(msg) is False

        # 3. User router blocks unauthorized access to /admin
        user_router = create_user_router(cfg, user_repo, settings_repo)
        unauth_handler = None
        for handler in user_router.message.handlers:
            if getattr(handler.callback, "__name__", "") == "cmd_unauthorized_admin":
                unauth_handler = handler.callback
                break
        assert unauth_handler is not None

        unauth_msg = MagicMock()
        unauth_msg.from_user.id = unauth_id
        unauth_msg.answer = AsyncMock()
        await unauth_handler(unauth_msg)
        unauth_msg.answer.assert_called_once()
        assert "Ruxsat etilmadi" in unauth_msg.answer.call_args[0][0]

    asyncio.run(_test())


# ==============================================================================
# TEST 13: Preserving settings after a simulated restart
# ==============================================================================

def test_preserve_promo_images_across_restarts(promo_setup):
    async def _test():
        db = promo_setup["db"]
        cfg = promo_setup["cfg"]

        # Session 1: Add promotional images
        repo1 = SettingsRepository(db)
        await repo1.get_settings(cfg)
        await repo1.add_promo_image("restart_file_id_1")
        await repo1.add_promo_image("restart_file_id_2")

        # Session 2: Simulated bot restart (fresh repo instance with same DB)
        repo2 = SettingsRepository(db)
        settings_restart = await repo2.get_settings(cfg)

        assert settings_restart.promo_images == ["restart_file_id_1", "restart_file_id_2"]
        assert await repo2.get_promo_images() == ["restart_file_id_1", "restart_file_id_2"]

    asyncio.run(_test())


# ==============================================================================
# TEST 14: Admin UI navigation, callbacks, and keyboard structure
# ==============================================================================

def test_admin_promo_images_menu_navigation_and_keyboards(promo_setup):
    async def _test():
        cfg = promo_setup["cfg"]
        settings_repo = promo_setup["settings_repo"]
        user_repo = promo_setup["user_repo"]
        broadcast_service = promo_setup["broadcast_service"]

        await settings_repo.get_settings(cfg)
        admin_router = create_admin_router(cfg, user_repo, settings_repo, broadcast_service)

        # 1. Verify get_promo_images_keyboard buttons
        kb = get_promo_images_keyboard(count=2)
        button_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        button_callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]

        assert "➕ Rasm qo'shish" in button_texts
        assert "📋 Rasmlarni ko'rish" in button_texts
        assert "➖ Rasmni o'chirish" in button_texts
        assert "🗑 Barcha rasmlarni o'chirish" in button_texts
        assert "🔙 Orqaga" in button_texts

        assert "admin_promo_img_add" in button_callbacks
        assert "admin_promo_img_list" in button_callbacks
        assert "admin_promo_img_del_menu" in button_callbacks
        assert "admin_promo_img_clear_prompt" in button_callbacks
        assert "admin_main" in button_callbacks

        # 2. Test cb_admin_promo_images handler
        main_menu_handler = None
        list_handler = None
        del_menu_handler = None
        del_prompt_handler = None
        clear_prompt_handler = None
        for handler in admin_router.callback_query.handlers:
            name = getattr(handler.callback, "__name__", "")
            if name == "cb_admin_promo_images":
                main_menu_handler = handler.callback
            elif name == "cb_promo_img_list":
                list_handler = handler.callback
            elif name == "cb_promo_img_del_menu":
                del_menu_handler = handler.callback
            elif name == "cb_promo_img_del_prompt":
                del_prompt_handler = handler.callback
            elif name == "cb_promo_img_clear_prompt":
                clear_prompt_handler = handler.callback

        assert main_menu_handler is not None
        assert list_handler is not None
        assert del_menu_handler is not None
        assert del_prompt_handler is not None
        assert clear_prompt_handler is not None

        cb = MagicMock()
        cb.from_user.id = 5924300834
        cb.message.edit_text = AsyncMock()
        cb.message.answer = AsyncMock()
        cb.answer = AsyncMock()
        state = MagicMock()
        state.clear = AsyncMock()

        await main_menu_handler(cb, state)
        cb.message.edit_text.assert_called_once()
        text_arg, kwargs = cb.message.edit_text.call_args
        assert "Reklama rasmlarini boshqarish" in text_arg[0]
        assert "Hozirda saqlangan rasmlar soni:" in text_arg[0]
        assert kwargs["reply_markup"] is not None

        # 3. Test list handler with empty images
        await settings_repo.clear_promo_images()
        cb_list = MagicMock()
        cb_list.from_user.id = 5924300834
        cb_list.message.edit_text = AsyncMock()
        cb_list.answer = AsyncMock()

        await list_handler(cb_list, state)
        cb_list.message.edit_text.assert_called_once()
        list_text = cb_list.message.edit_text.call_args[0][0]
        assert "Hozircha hech qanday reklama rasmi saqlanmagan" in list_text

        # 4. Test list handler with populated images
        await settings_repo.add_promo_image("photo_123")
        cb_list_pop = MagicMock()
        cb_list_pop.from_user.id = 5924300834
        cb_list_pop.message.answer_photo = AsyncMock()
        cb_list_pop.message.answer = AsyncMock()
        cb_list_pop.answer = AsyncMock()

        await list_handler(cb_list_pop, state)
        cb_list_pop.message.answer_photo.assert_called_once()
        assert cb_list_pop.message.answer_photo.call_args[1]["photo"] == "photo_123"

        # 5. Test clear prompt asks explicit confirmation
        cb_clear = MagicMock()
        cb_clear.from_user.id = 5924300834
        cb_clear.message.edit_text = AsyncMock()
        cb_clear.answer = AsyncMock()

        await clear_prompt_handler(cb_clear, state)
        cb_clear.message.edit_text.assert_called_once()
        clear_prompt_text = cb_clear.message.edit_text.call_args[0][0]
        assert "DIQQAT: Barcha reklama rasmlarini o'chirish" in clear_prompt_text
        clear_kb = cb_clear.message.edit_text.call_args[1]["reply_markup"]
        assert any("barchasini o'chirish" in btn.text for row in clear_kb.inline_keyboard for btn in row)

    asyncio.run(_test())

