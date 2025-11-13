# KAI Privacy Kit - "Privacy Sentry" Bot
#
# @authors: Кирило Ревякін (Team Lead / Arch)
#            Олександр Лєбєдєв (Tech Lead)
# @link:     https://github.com/Kirill3224/KAI-Privacy-Kit
# @license:  MIT License (see LICENSE file)
#
# -*- coding: utf-8 -*-
"""
Головний файл бота "Privacy Sentry" (v3.8 - Фікс Чек-ліста)

Що нового:
- (v3.8) КРИТИЧНИЙ ФІКС (KeyError):
  - `checklist_conv_handler` тепер має НОВИЙ
    перший стан: `CHECKLIST_Q_PROJECT_NAME`.
  - Бот тепер питає "Назву Проєкту" перед початком
    Чек-ліста (як це роблять Політика та DPIA).
  - `checklist_generate` тепер коректно
    отримує `project_name`.
- (v3.8) ФІКС UX (Нумерація):
  - Повністю переписано шаблони Чек-ліста
    в `templates.py` (v3.8).
  - Прибрано "згортання" категорій (старий баг).
  - Змінено нумерацію на "Категорія X (Питання Y/9)".
"""

import logging
import os
import html
import asyncio # (v3.6) Потрібно для job_queue
from datetime import date
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest

# Локальні імпорти
import templates
# (Важливо!) Ми припускаємо, що це 'pdf_utils.py' від твого товариша (v3.2)
from pdf_utils import create_pdf_from_markdown, clear_temp_file

# Налаштування логування
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# (v3.6) Встановлюємо рівень логування для 'JobQueue' вище, щоб не спамив
logging.getLogger("telegram.ext.JobQueue").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Завантаження конфігурації ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("!!! Змінна BOT_TOKEN не знайдена в .env файлі !!!")
    exit()

# === Етапи для Conversation Handlers ===
# (v3.2) Всі стани перенумеровані для ЄДИНОГО обробника
# 10-19: Політика
# 20-39: DPIA
# 40-59: Чек-ліст

# --- Етапи для "Політики" (Безшовний UX) ---
(
    POLICY_Q_CONTACT, # 10
    POLICY_Q_DATA_COLLECTED, # 11
    POLICY_Q_DATA_STORAGE, # 12
    POLICY_Q_DELETE_MECHANISM, # 13
    POLICY_GENERATE, # 14
) = range(10, 15) # 5 станів

# --- Етапи для "DPIA" (Безшовний UX) ---
(
    DPIA_Q_TEAM, # 20
    DPIA_Q_GOAL, # 21
    DPIA_Q_DATA_LIST, # 22
    DPIA_Q_MINIMIZATION_START, # 23
    DPIA_Q_MINIMIZATION_STATUS, # 24
    DPIA_Q_MINIMIZATION_REASON, # 25
    DPIA_Q_RETENTION_PERIOD, # 26
    DPIA_Q_RETENTION_MECHANISM, # 27
    DPIA_Q_STORAGE, # 28
    DPIA_Q_RISK, # 29
    DPIA_Q_MITIGATION, # 30
    DPIA_GENERATE, # 31
) = range(20, 32) # 12 станів

# --- Етапи для "Чек-ліста" (v3.8 - Додано Q_PROJECT_NAME) ---
(
    CHECKLIST_Q_PROJECT_NAME, # 40 (НОВИЙ)
    C1_S1_NOTE, # 41
    C1_S2_STATUS, # 42
    C1_S2_NOTE, # 43
    C1_S3_STATUS, # 44
    C1_S3_NOTE, # 45
    C2_S1_STATUS, # 46
    C2_S1_NOTE, # 47
    C2_S2_STATUS, # 48
    C2_S2_NOTE, # 49
    C2_S3_STATUS, # 50
    C2_S3_NOTE, # 51
    C3_S1_STATUS, # 52
    C3_S1_NOTE, # 53
    C3_S2_STATUS, # 54
    C3_S2_NOTE, # 55
    C3_S3_STATUS, # 56
    C3_S3_NOTE, # 57
    CHECKLIST_GENERATE, # 58
) = range(40, 59) # 19 станів (було 18)


# === 1. Головне Меню та Допоміжні Функції ===

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """(v3.1) Повертає оновлене головне меню."""
    keyboard = [
        [InlineKeyboardButton("📄 Сгенерувати Політику", callback_data="start_policy")],
        [InlineKeyboardButton("📝 Пройти Оцінку (DPIA)", callback_data="start_dpia")],
        [InlineKeyboardButton("✅ Пройти Чек-ліст", callback_data="start_checklist")],
        [
            InlineKeyboardButton("❓ Допомога", callback_data="show_help"),
            InlineKeyboardButton("🔒 Наша Політика", callback_data="show_privacy")
        ],
        [InlineKeyboardButton("🐙 GitHub Репозиторій", url="https://github.com/Kirill3224/KAI-Privacy-Kit")]
    ]
    return InlineKeyboardMarkup(keyboard)

# (НОВЕ v3.2) Уніфікована клавіатура для "Повернення в меню"
def get_post_action_keyboard() -> InlineKeyboardMarkup:
    """Повертає стандартну клавіатуру 'Повернутись в меню'."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Повернутись до головного меню", callback_data="start_menu_post_generation")
    ]])

# (НОВЕ v3.3) Клавіатура для "Етичного Нагадування"
def get_policy_upsell_keyboard() -> InlineKeyboardMarkup:
    """Повертає клавіатуру "Нагадування" (Чек-ліст + Меню)."""
    keyboard = [
        [InlineKeyboardButton("✅ Пройти Чек-ліст (Крок 2)", callback_data="start_checklist_upsell")], # (v3.4) Змінено Крок 3 на 2
        [InlineKeyboardButton("⬅️ Повернутись до головного меню", callback_data="start_menu_post_generation")]
    ]
    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """(ОНОВЛЕНО v3.1) Надсилає головне меню (Inline)."""
    clear_user_data(context) # Очищуємо на /start

    query = update.callback_query
    
    text = "Привіт! Я бот 'Privacy Sentry'.\n\n" \
           "Я допоможу вам згенерувати артефакти приватності для вашого студентського проєкту, дотримуючись 'stateless' принципу (я нічого про вас не зберігаю).\n\n" \
           "Оберіть опцію:"
    
    reply_markup = get_main_menu_keyboard()

    if query:
        # Це 'Назад в меню' з /cancel або інлайн-кнопок
        try:
            await query.answer()
            # (v3.1) Видаляємо попереднє повідомлення, щоб уникнути спаму
            if query.data in ("start_menu", "start_menu_post_generation"):
                await delete_main_message(context, query.message.message_id)

            await context.bot.send_message(chat_id=query.message.chat_id, text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

        except BadRequest as e:
            if "Message is not modified" not in str(e):
                logger.error(f"Помилка в start (query): {e}")
            # Якщо повідомлення не знайдено, надсилаємо нове
            if "message to edit not found" in str(e) or "message to delete not found" in str(e):
                 await context.bot.send_message(chat_id=query.message.chat_id, text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    else:
        # Це команда /start
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            
    # (v3.2) Оскільки /start тепер поза ConversationHandler, він не повертає стан
    # return ConversationHandler.END 
    return ConversationHandler.END # (v3.2) Повертаємо END на випадок, якщо це викликано з /cancel

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """(v3.3) Показує /help (БЕЗ кнопки 'Повернутись')"""
    if not update.message:
        return # Безпека
        
    await update.message.reply_text(
        templates.BOT_HELP, 
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True
        # (v3.3) ВИДАЛЕНО 'reply_markup'
    )

async def show_privacy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """(v3.7) Оновлено ParseMode.HTML"""
    if not update.message:
        return
    await update.message.reply_text(
        templates.BOT_PRIVACY_POLICY, 
        parse_mode=ParseMode.HTML, # (v3.7) ЗМІНЕНО
        disable_web_page_preview=True # (v3.7) ДОДАНО
    )

async def show_help_inline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """(v3.0) Показує /help як редагування повідомлення."""
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("⬅️ Назад в меню", callback_data="start_menu")]]
    
    # Редагуємо, а не надсилаємо нове
    try:
        await query.edit_message_text(
            templates.BOT_HELP, 
            reply_markup=InlineKeyboardMarkup(keyboard), 
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )
    except BadRequest as e:
        if "Message is not modified" not in str(e):
             logger.warning(f"show_help_inline: {e}")

async def show_privacy_inline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """(v3.7) Оновлено ParseMode.HTML"""
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("⬅️ Назад в меню", callback_data="start_menu")]]
    
    try:
        await query.edit_message_text(
            templates.BOT_PRIVACY_POLICY, 
            reply_markup=InlineKeyboardMarkup(keyboard), 
            parse_mode=ParseMode.HTML, # (v3.7) ЗМІНЕНО
            disable_web_page_preview=True # (v3.7) ДОДАНО
        )
    except BadRequest as e:
        if "Message is not modified" not in str(e):
             logger.warning(f"show_privacy_inline: {e}")

# (НОВЕ v3.4) Клас-обгортка для 'start'
class _FakeUpdate:
    """(v3.4) 'Фальшивий' Update, щоб викликати start() з cancel() або з помилок."""
    def __init__(self, chat_id, bot):
        self.callback_query = None
        self.message = self._Message(chat_id, bot)
    
    class _Message:
        def __init__(self, chat_id, bot):
            self.chat = self._Chat(chat_id)
            self._bot = bot
        
        class _Chat:
            def __init__(self, chat_id):
                self.id = chat_id
        
        # start() викликає reply_text
        async def reply_text(self, text, reply_markup, parse_mode):
            await self._bot.send_message(chat_id=self.chat.id, text=text, reply_markup=reply_markup, parse_mode=parse_mode)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """(ОНОВЛЕНО v3.4) Скасовує поточну операцію, очищує дані та повертає в меню."""
    clear_user_data(context)
    
    query = update.callback_query
    message = update.message
    
    cancel_text = "Дію скасовано. Усі зібрані відповіді видалено з моєї пам'яті."
    
    if query:
        await query.answer()
        chat_id = query.message.chat_id
        # (v3.1) Намагаємося видалити "Головне" повідомлення
        await delete_main_message(context, query.message.message_id) 
        # ...і надсилаємо підтвердження
        await context.bot.send_message(chat_id=chat_id, text=cancel_text)
    elif message:
        chat_id = message.chat_id
        await message.reply_text(cancel_text, reply_markup=ReplyKeyboardRemove())
        
    # (v3.4) Викликаємо 'start' з фальшивим update
    await start(_FakeUpdate(chat_id, context.bot), context)
        
    return ConversationHandler.END

# (v3.6) Допоміжна функція для видалення повідомлення-блокувальника
async def _delete_blocker_message(context: ContextTypes.DEFAULT_TYPE) -> None:
    """(v3.6) Видаляє повідомлення 'Ви вже заповнюєте...'."""
    message_id = context.job.data.get('message_id')
    chat_id = context.job.data.get('chat_id')
    if message_id and chat_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            logger.info(f"Видалено 'повідомлення-блокувальник' {message_id}")
        except BadRequest as e:
            logger.warning(f"Не вдалося видалити 'повідомлення-блокувальник': {e}")


# (НОВЕ v3.3, ОНОВЛЕНО v3.6) "Блокувальник" перемикання воркфлоу
async def block_workflow_switch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    (v3.6) Якщо користувач вже *всередині* розмови, цей обробник
    блокує натискання кнопок, що починають *іншу* розмову.
    Повідомлення автоматично зникає через 5 секунд.
    """
    query = update.callback_query
    await query.answer() # Обов'язково відповідаємо на запит
    
    # (v3.5) КРИТИЧНИЙ ФІКС:
    # `context.conversation_data` НЕ ІСНУЄ без Persistence.
    # Ми маємо читати стан, який ми *вручну* зберегли у `context.user_data`.
    current_state = context.user_data.get('current_state') 
    
    if current_state is None:
        # Це не мало статися, але якщо стан втрачено, краще скасувати
        logger.warning(f"block_workflow_switch не зміг знайти 'current_state' для user {context._user_id}. Скасування.")
        return await cancel(update, context)

    # Надсилаємо тимчасове повідомлення-попередження
    try:
        # (v3.4) Додаємо кнопку Cancel для зручності
        keyboard = [[InlineKeyboardButton("❌ Скасувати поточний аудит", callback_data="cancel_from_block")]]
        sent_message = await query.message.reply_text(
            "⚠️ **Ви вже заповнюєте інший документ.**\n\n"
            "Будь ласка, спочатку завершіть поточний аудит, або натисніть 'Скасувати' нижче.\n"
            "_(Це повідомлення зникне через 5 секунд)_",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        
        # (v3.6) ПЛАНУЄМО ВИДАЛЕННЯ ЦЬОГО ПОВІДОМЛЕННЯ
        if context.job_queue:
            context.job_queue.run_once(
                _delete_blocker_message,
                5, # (v3.6) Видаляємо через 5 секунд
                data={'message_id': sent_message.message_id, 'chat_id': sent_message.chat_id},
                name=f"delete_blocker_{sent_message.message_id}"
            )
        else:
            # (v3.6.1) Додано захист від падіння, якщо JobQueue = None
            logger.warning("JobQueue не налаштовано. Не можу запланувати видалення 'блокувальника'.")

    except BadRequest as e:
        logger.warning(f"Не вдалося надіслати block_workflow_switch: {e}")
    
    # Повертаємо ПОТОЧНИЙ стан, щоб розмова не перервалася
    return current_state

# (НОВЕ v3.4) Обробник для кнопки "Скасувати" з 'block_workflow_switch'
async def cancel_from_block(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """(v3.4) Обробляє кнопку 'Скасувати' з повідомлення 'block_workflow_switch'."""
    query = update.callback_query
    await query.answer()
    
    # Видаляємо повідомлення "⚠️ Ви вже заповнюєте..."
    try:
        await query.message.delete()
    except BadRequest as e:
        logger.warning(f"Не вдалося видалити 'block' повідомлення: {e}")
        
    # Викликаємо стандартний cancel
    # (v3.4) Ми передаємо 'query', щоб 'cancel' міг видалити "Головне" повідомлення
    return await cancel(update, context)


def clear_user_data(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Безпечно очищує context.user_data."""
    user_id = context._user_id
    if context.user_data:
        logger.info(f"Очищення даних для user {user_id}.")
        context.user_data.clear()
    else:
        logger.info(f"Для user {user_id} немає даних для очищення.")

# === (v3.0) УНІФІКОВАНІ "БЕЗШОВНІ" ХЕЛПЕРИ ===

async def delete_main_message(context: ContextTypes.DEFAULT_TYPE, message_id: int = None) -> None:
    """Допоміжна функція для чистого видалення "Головного" повідомлення."""
    # (v3.1) Дозволяємо передавати message_id напряму (для 'start_menu_post_generation')
    msg_id_to_delete = message_id or context.user_data.pop('main_message_id', None)
    chat_id = context._chat_id
    
    if msg_id_to_delete:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id_to_delete)
            logger.info(f"Видалено 'Головне' повідомлення {msg_id_to_delete}")
        except BadRequest as e:
            logger.warning(f"Не вдалося видалити 'Головне' повідомлення {msg_id_to_delete}: {e}")
    else:
        logger.info("Немає 'Головного' повідомлення для видалення.")

async def edit_main_message(context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup: InlineKeyboardMarkup = None, new_message: bool = False) -> None:
    """Допоміжна функція для редагування/надсилання "Головного" повідомлення."""
    message_id = context.user_data.get('main_message_id')
    chat_id = context._chat_id
    
    if new_message and message_id:
        # Якщо ми хочемо нове повідомлення, але старе ще є, видаляємо старе
        await delete_main_message(context)
        message_id = None

    try:
        if not message_id or new_message:
            sent_message = await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data['main_message_id'] = sent_message.message_id
        else:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logger.info("Повідомлення не змінено, пропуск редагування.")
        elif "message to edit not found" in str(e):
             logger.warning(f"Не вдалося знайти повідомлення {message_id} для редагування. Надсилаю нове.")
             await edit_main_message(context, text, reply_markup, new_message=True)
        else:
            logger.error(f"Помилка під час редагування/надсилання повідомлення: {e}", exc_info=True)
            if message_id and not new_message:
                await edit_main_message(context, text, reply_markup, new_message=True)
    except Exception as e:
        logger.error(f"Невідома помилка в edit_main_message: {e}", exc_info=True)

async def delete_user_text_reply(update: Update) -> None:
    """Видаляє повідомлення користувача (його текстову відповідь), щоб чат був чистим."""
    try:
        await update.message.delete()
    except BadRequest as e:
        logger.warning(f"Не вдалося видалити текстову відповідь користувача: {e}")

# === 2. (ОНОВЛЕНО v3.0) Логіка "Політики Конфіденційності" (Безшовний UX) ===

def get_policy_template_data(data: dict) -> dict:
    """Готує словник для шаблонів Політики."""
    return {
        'project_name': html.escape(data.get('project_name', '...')),
        'contact': html.escape(data.get('contact', '...')),
        'data_collected': html.escape(data.get('data_collected', '...')),
        'data_storage': html.escape(data.get('data_storage', '...')),
        'delete_mechanism': html.escape(data.get('delete_mechanism', '...')),
    }

async def start_policy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """(v3.0) Починає "безшовну" розмову про Політику."""
    query = update.callback_query
    await query.answer()
            
    clear_user_data(context)
    logger.info(f"User {query.from_user.id} почав 'Політику'.") 
    context.user_data['policy'] = {}
    
    try:
        # Редагуємо головне меню, щоб почати воркфлоу
        text = templates.POLICY_Q_PROJECT_NAME.format(**get_policy_template_data({}))
        # new_message=True, щоб замінити меню, а не редагувати його
        await edit_main_message(context, text, new_message=True)
    except BadRequest as e:
        logger.warning(f"start_policy: Помилка: {e}")

    # (v3.5) Зберігаємо поточний стан
    context.user_data['current_state'] = POLICY_Q_CONTACT
    return POLICY_Q_CONTACT

async def policy_q_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['policy']['project_name'] = update.message.text
    await delete_user_text_reply(update)
    
    text = templates.POLICY_Q_CONTACT.format(**get_policy_template_data(context.user_data['policy']))
    await edit_main_message(context, text)
    
    # (v3.5) Зберігаємо поточний стан
    context.user_data['current_state'] = POLICY_Q_DATA_COLLECTED
    return POLICY_Q_DATA_COLLECTED

async def policy_q_data_collected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['policy']['contact'] = update.message.text
    await delete_user_text_reply(update)

    text = templates.POLICY_Q_DATA_COLLECTED.format(**get_policy_template_data(context.user_data['policy']))
    await edit_main_message(context, text)
    
    # (v3.5) Зберігаємо поточний стан
    context.user_data['current_state'] = POLICY_Q_DATA_STORAGE
    return POLICY_Q_DATA_STORAGE

async def policy_q_data_storage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['policy']['data_collected'] = update.message.text
    await delete_user_text_reply(update)
    
    text = templates.POLICY_Q_DATA_STORAGE.format(**get_policy_template_data(context.user_data['policy']))
    await edit_main_message(context, text)
    
    # (v3.5) Зберігаємо поточний стан
    context.user_data['current_state'] = POLICY_Q_DELETE_MECHANISM
    return POLICY_Q_DELETE_MECHANISM

async def policy_q_delete_mechanism(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['policy']['data_storage'] = update.message.text
    await delete_user_text_reply(update)
    
    text = templates.POLICY_Q_DELETE_MECHANISM.format(**get_policy_template_data(context.user_data['policy']))
    await edit_main_message(context, text)
    
    # (v3.5) Зберігаємо поточний стан
    context.user_data['current_state'] = POLICY_GENERATE
    return POLICY_GENERATE

async def policy_generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """(ОНОВЛЕНО v3.3) Генерує PDF Політики та показує "Етичне Нагадування"."""
    context.user_data['policy']['delete_mechanism'] = update.message.text
    user_id = update.effective_user.id
    logger.info(f"User {user_id}: генерація PDF Політики.")

    await delete_user_text_reply(update)
    await delete_main_message(context)
    
    generating_msg = await update.message.reply_text("Дякую! Генерую ваш PDF...")

    data_dict = {
        'project_name': html.escape(context.user_data['policy'].get('project_name', '[Назва Вашого Проєкту]')),
        'contact': html.escape(context.user_data['policy'].get('contact', '[Ваш @username або email]')),
        'data_collected': html.escape(context.user_data['policy'].get('data_collected', '[Дані, які ви збираєте]')),
        'data_storage': html.escape(context.user_data['policy'].get('data_storage', '[Де ви зберігаєте дані]')),
        'delete_mechanism': html.escape(context.user_data['policy'].get('delete_mechanism', '[Опишіть простий механізм]')),
        'date': date.today().strftime("%d.%m.%Y"),
    }
    
    # (v3.0) Очищуємо дані ДО генерації
    clear_user_data(context)

    try:
        filled_markdown = templates.POLICY_TEMPLATE.format(**data_dict)
        
        pdf_file_path = create_pdf_from_markdown(
            content=filled_markdown,
            is_html=False, 
            output_filename=f"policy_{user_id}.pdf"
        )
        
        await context.bot.send_document(chat_id=update.message.chat_id, document=open(pdf_file_path, 'rb'))
        
        # (ОНОВЛЕНО v3.3) Надсилаємо "Етичне Нагадування"
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=templates.POST_POLICY_UPSELL, # (v3.3) Новий текст
            reply_markup=get_policy_upsell_keyboard(), # (v3.3) Нові кнопки
            parse_mode=ParseMode.MARKDOWN
        )
        clear_temp_file(pdf_file_path)

    except Exception as e:
        logger.error(f"PDF generation failed for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(f"Під час генерації PDF сталася помилка: {e}")
        # (v3.4) Викликаємо 'start' з фальшивим update
        await start(_FakeUpdate(update.message.chat.id, context.bot), context)
    
    finally:
        try:
            await generating_msg.delete()
        except Exception as e:
            logger.warning(f"Не вдалося видалити 'Генерую...' {e}")
            
        return ConversationHandler.END


# === 3. (ОНОВЛЕНО v3.0) Логіка "DPIA Lite" (Безшовний UX) ===

def get_dpia_template_data(data: dict) -> dict:
    """Готує словник для шаблонів DPIA."""
    # Готуємо дані для мінімізації
    minimization_text = ""
    minimization_data = data.get('minimization_data', [])
    if data.get('data_list') and not minimization_data:
        # Етап, коли список є, але цикл ще не почався
        for i, item in enumerate(data.get('data_list', [])):
             minimization_text += f"\n**{i+1}. {html.escape(item)}:** [Очікує...] "
    else:
        # Етап, коли цикл триває
        for i, item_data in enumerate(minimization_data):
            item = html.escape(item_data['item'])
            reason = html.escape(item_data['reason'])
            if item_data['needed']:
                minimization_text += f"\n**{i+1}. {item}:** ✅ **Так** (Навіщо: `{reason}`)"
            else:
                minimization_text += f"\n**{i+1}. {item}:** ❌ **Ні** (`{reason}`)"

    return {
        'project_name': html.escape(data.get('project_name', '...')),
        'team': html.escape(data.get('team', '...')),
        'goal': html.escape(data.get('goal', '...')),
        'data_list': "\n".join([f"- `{html.escape(item)}`" for item in data.get('data_list', [])]),
        'minimization_summary': minimization_text.strip(),
        'retention_period': html.escape(data.get('retention_period', '...')),
        'retention_mechanism': html.escape(data.get('retention_mechanism', '...')),
        'storage': html.escape(data.get('storage', '...')),
        'risk': html.escape(data.get('risk', '...')),
        'mitigation': html.escape(data.get('mitigation', '...')),
    }

async def start_dpia(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """(v3.0) Починає "безшовну" розмову про DPIA."""
    query = update.callback_query
    await query.answer()

    clear_user_data(context)
    logger.info(f"User {query.from_user.id} почав 'DPIA'.")
    
    context.user_data['dpia'] = {
        'minimization_data': [],
        'data_list': [],
        'current_data_index': 0
    }
    
    text = templates.DPIA_Q_PROJECT_NAME.format(**get_dpia_template_data({}))
    await edit_main_message(context, text, new_message=True)
    
    # (v3.5) Зберігаємо поточний стан
    context.user_data['current_state'] = DPIA_Q_TEAM
    return DPIA_Q_TEAM

async def dpia_q_team(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['dpia']['project_name'] = update.message.text
    await delete_user_text_reply(update)
    
    text = templates.DPIA_Q_TEAM.format(**get_dpia_template_data(context.user_data['dpia']))
    await edit_main_message(context, text)
    
    # (v3.5) Зберігаємо поточний стан
    context.user_data['current_state'] = DPIA_Q_GOAL
    return DPIA_Q_GOAL

async def dpia_q_goal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['dpia']['team'] = update.message.text
    await delete_user_text_reply(update)
    
    text = templates.DPIA_Q_GOAL.format(**get_dpia_template_data(context.user_data['dpia']))
    await edit_main_message(context, text)
    
    # (v3.5) Зберігаємо поточний стан
    context.user_data['current_state'] = DPIA_Q_DATA_LIST
    return DPIA_Q_DATA_LIST

async def dpia_q_data_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['dpia']['goal'] = update.message.text
    await delete_user_text_reply(update)
    
    text = templates.DPIA_Q_DATA_LIST.format(**get_dpia_template_data(context.user_data['dpia']))
    await edit_main_message(context, text)
    
    # (v3.5) Зберігаємо поточний стан
    context.user_data['current_state'] = DPIA_Q_MINIMIZATION_START
    return DPIA_Q_MINIMIZATION_START

async def dpia_q_minimization_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отримує список даних і запускає цикл мінімізації."""
    data_list = [item.strip() for item in update.message.text.split('\n') if item.strip()]
    await delete_user_text_reply(update)

    if not data_list:
        text = templates.DPIA_Q_DATA_LIST_ERROR.format(**get_dpia_template_data(context.user_data['dpia']))
        await edit_main_message(context, text)
        # (v3.5) Зберігаємо поточний стан (залишаємось тут)
        context.user_data['current_state'] = DPIA_Q_MINIMIZATION_START
        return DPIA_Q_MINIMIZATION_START

    context.user_data['dpia']['data_list'] = data_list
    context.user_data['dpia']['current_data_index'] = 0
    context.user_data['dpia']['minimization_data'] = []
    
    return await dpia_ask_minimization_status(context)

async def dpia_ask_minimization_status(context: ContextTypes.DEFAULT_TYPE) -> int:
    """(v3.0) Динамічно ставить питання про статус для поточного пункту даних."""
    index = context.user_data['dpia']['current_data_index']
    data_list = context.user_data['dpia']['data_list']
    
    if index >= len(data_list):
        return await dpia_minimization_finished(context)

    current_data_item = data_list[index]
    context.user_data['dpia']['current_data_item'] = current_data_item # Зберігаємо для наступного кроку
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Так", callback_data="min_yes"),
            InlineKeyboardButton("❌ Ні", callback_data="min_no"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    template_data = get_dpia_template_data(context.user_data['dpia'])
    text = templates.DPIA_Q_MINIMIZATION_ASK.format(
        **template_data,
        count=f"{index + 1}/{len(data_list)}",
        item=f"`{html.escape(current_data_item)}`"
    )

    await edit_main_message(context, text, reply_markup)
    
    # (v3.5) Зберігаємо поточний стан
    context.user_data['current_state'] = DPIA_Q_MINIMIZATION_REASON
    return DPIA_Q_MINIMIZATION_REASON

async def dpia_q_minimization_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """(v3.0) Обробляє відповідь 'Так'/'Ні' (CallbackQuery)."""
    query = update.callback_query
    await query.answer()
    
    current_data_item = context.user_data['dpia'].get('current_data_item', '...')
    
    if query.data == "min_yes":
        context.user_data['dpia']['minimization_data'].append({
            "item": current_data_item,
            "needed": True,
            "reason": "" 
        })
        
        template_data = get_dpia_template_data(context.user_data['dpia'])
        text = templates.DPIA_Q_MINIMIZATION_REASON.format(
            **template_data,
            item=f"`{html.escape(current_data_item)}`"
        )
        await edit_main_message(context, text)
        
        # (v3.5) Зберігаємо поточний стан
        context.user_data['current_state'] = DPIA_Q_MINIMIZATION_STATUS
        return DPIA_Q_MINIMIZATION_STATUS
        
    elif query.data == "min_no":
        context.user_data['dpia']['minimization_data'].append({
            "item": current_data_item,
            "needed": False,
            "reason": "Відмовлено (мінімізовано)"
        })
        
        context.user_data['dpia']['current_data_index'] += 1
        return await dpia_ask_minimization_status(context)

async def dpia_q_minimization_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """(v3.0) Отримує текстову причину для відповіді 'Так'."""
    reason = update.message.text
    await delete_user_text_reply(update)
    
    if context.user_data['dpia']['minimization_data']:
        context.user_data['dpia']['minimization_data'][-1]['reason'] = reason
    
    context.user_data['dpia']['current_data_index'] += 1
    return await dpia_ask_minimization_status(context)

async def dpia_minimization_finished(context: ContextTypes.DEFAULT_TYPE) -> int:
    """Викликається, коли цикл мінімізації завершено."""
    
    text = templates.DPIA_Q_RETENTION_PERIOD.format(**get_dpia_template_data(context.user_data['dpia']))
    await edit_main_message(context, text)
    
    # (v3.5) Зберігаємо поточний стан
    context.user_data['current_state'] = DPIA_Q_RETENTION_MECHANISM
    return DPIA_Q_RETENTION_MECHANISM

async def dpia_q_retention_mechanism(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['dpia']['retention_period'] = update.message.text
    await delete_user_text_reply(update)
    
    text = templates.DPIA_Q_RETENTION_MECHANISM.format(**get_dpia_template_data(context.user_data['dpia']))
    await edit_main_message(context, text)
    
    # (v3.5) Зберігаємо поточний стан
    context.user_data['current_state'] = DPIA_Q_STORAGE
    return DPIA_Q_STORAGE

async def dpia_q_storage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['dpia']['retention_mechanism'] = update.message.text
    await delete_user_text_reply(update)
    
    text = templates.DPIA_Q_STORAGE.format(**get_dpia_template_data(context.user_data['dpia']))
    await edit_main_message(context, text)
    
    # (v3.5) Зберігаємо поточний стан
    context.user_data['current_state'] = DPIA_Q_RISK
    return DPIA_Q_RISK

async def dpia_q_risk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['dpia']['storage'] = update.message.text
    await delete_user_text_reply(update)
    
    text = templates.DPIA_Q_RISK.format(**get_dpia_template_data(context.user_data['dpia']))
    await edit_main_message(context, text)
    
    # (v3.5) Зберігаємо поточний стан
    context.user_data['current_state'] = DPIA_Q_MITIGATION
    return DPIA_Q_MITIGATION

async def dpia_q_mitigation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['dpia']['risk'] = update.message.text
    await delete_user_text_reply(update)
    
    text = templates.DPIA_Q_MITIGATION.format(**get_dpia_template_data(context.user_data['dpia']))
    await edit_main_message(context, text)
    
    # (v3.5) Зберігаємо поточний стан
    context.user_data['current_state'] = DPIA_GENERATE
    return DPIA_GENERATE

async def dpia_generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """(ОНОВЛЕНО v3.1) Збирає останню відповідь і генерує PDF для DPIA."""
    context.user_data['dpia']['mitigation'] = update.message.text
    user_id = update.effective_user.id
    logger.info(f"User {user_id}: генерація PDF DPIA.")

    await delete_user_text_reply(update)
    await delete_main_message(context)
    
    generating_msg = await update.message.reply_text("Дякую! Аудит завершено. Генерую ваш PDF...")

    data = context.user_data['dpia']
    
    def get_data(key, default='[Не вказано]'):
        return html.escape(data.get(key, default))

    # Готуємо дані для PDF
    table_rows = []
    table_rows.append(f"| Назва проєкту: | {get_data('project_name')} |")
    table_rows.append(f"| Керівник/Розробник: | {get_data('team')} |")
    table_rows.append(f"| Мета: | {get_data('goal')} |")
    
    minimization_data = data.get('minimization_data', [])
    if not minimization_data:
        table_rows.append("| Дані: | [Не вказано] |")
    else:
        for i, item in enumerate(minimization_data):
            data_name = f"Дані (пункт {i+1}):"
            item_name = html.escape(item['item'])
            item_reason = html.escape(item['reason'])
            
            if item['needed']:
                data_value = f"{item_name} (✅ **Навіщо:** {item_reason})"
            else:
                data_value = f"~~{item_name}~~ (❌ **Відмовлено**)"
            
            table_rows.append(f"| {data_name} | {data_value} |")

    table_rows.append(f"| Строк Зберігання: | {get_data('retention_period')} |")
    table_rows.append(f"| Механізм Видалення: | {get_data('retention_mechanism')} |")
    table_rows.append(f"| Місце Зберігання: | {get_data('storage')} |")
    table_rows.append(f"| Головний Ризик: | {get_data('risk')} |")
    table_rows.append(f"| Мінімізація Ризику: | {get_data('mitigation')} |")

    table_header = "| Питання | Відповідь |\n| :--- | :--- |\n"
    dpia_table_string = table_header + "\n".join(table_rows)

    data_dict = {
        'project_name': get_data('project_name'),
        'date': date.today().strftime("%d.%m.%Y"),
        'dpia_table': dpia_table_string
    }
    
    # (v3.0) Очищуємо дані ДО генерації
    clear_user_data(context)

    try:
        filled_markdown = templates.DPIA_TEMPLATE.format(**data_dict)
        
        pdf_file_path = create_pdf_from_markdown(
            content=filled_markdown,
            is_html=False, 
            output_filename=f"dpia_{user_id}.pdf"
        )
        
        await context.bot.send_document(chat_id=update.message.chat_id, document=open(pdf_file_path, 'rb'))
        
        # (v3.2) Використовуємо helper-функцію
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text="Ваш DPIA Lite готовий. Я видалив усі ваші відповіді зі своєї пам'яті.",
            reply_markup=get_post_action_keyboard()
        )
        clear_temp_file(pdf_file_path)

    except Exception as e:
        logger.error(f"PDF DPIA generation failed for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(f"Під час генерації PDF сталася помилка: {e}")
        # (v3.4) Викликаємо 'start' з фальшивим update
        await start(_FakeUpdate(update.message.chat.id, context.bot), context)
    
    finally:
        try:
            await generating_msg.delete()
        except Exception as e:
            logger.warning(f"Не вдалося видалити 'Генерую...' {e}")
            
        return ConversationHandler.END


# === 4. Логіка "Чек-ліста" (3/3) - v3.8 ===

def get_checklist_status_keyboard() -> InlineKeyboardMarkup:
    """Повертає клавіатуру Так/Ні для Чек-ліста."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Виконано", callback_data="cl_yes"),
            InlineKeyboardButton("❌ Не виконано", callback_data="cl_no"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_skip_note_keyboard() -> InlineKeyboardMarkup:
    """Повертає клавіатуру 'Пропустити нотатку'."""
    keyboard = [
        [
            InlineKeyboardButton("➡️ Пропустити нотатку", callback_data="cl_skip_note"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_status_text_md(status: str) -> str:
    """(v2.8) Повертає текстовий статус (для Telegram UI)."""
    if status == "yes":
        return "✅ **Виконано**"
    elif status == "no":
        return "❌ **Не виконано**"
    else:
        return "" 

def get_note_text_md(note: str) -> str:
    """(v2.8) Повертає відформатовану нотатку (без ✅)."""
    if not note:
        return ""
    if note == "*Пропущено*":
        return "Нотатка: *Пропущено*"
    return f"Нотатка: `{html.escape(note)}`"

# (НОВЕ v3.8) Ця функція будує історію відповідей для Чек-ліста
def get_checklist_summary_text(cl_data: dict) -> str:
    """(v3.8) Генерує 'безшовний' підсумок відповідей для Чек-ліста."""
    
    # (v3.8) Завжди показуємо назву проєкту
    summary = f"✅ **Назва Проєкту:** `{html.escape(cl_data.get('project_name', '...'))}`\n\n"
    
    items = [
        ('c1_s1', "1.1. 2FA"),
        ('c1_s2', "1.2. 'Найменші привілеї'"),
        ('c1_s3', "1.3. БЕЗ ПУБЛІЧНИХ ПОСИЛАНЬ"),
        ('c2_s1', "2.1. Публічна Політика"),
        ('c2_s2', "2.2. Механізм Видалення"),
        ('c2_s3', "2.3. Контакт для скарг"),
        ('c3_s1', "3.1. Безпека Токенів"),
        ('c3_s2', "3.2. Планування Строків"),
        ('c3_s3', "3.3. Шифрування"),
    ]
    
    last_category = ""
    for key, name in items:
        status_key = f"{key}_status"
        note_key = f"{key}_note"
        
        status_val = cl_data.get(status_key)
        note_val = cl_data.get(note_key)
        
        if status_val:
            # (v3.8) Визначаємо категорію (перший символ 'c1', 'c2'...)
            category = key[1] 
            if category != last_category:
                if last_category != "":
                    summary += "\n" # Додаємо відступ між категоріями
                summary += f"**Категорія {category} (Контроль Доступу):**\n"
                last_category = category

            # Додаємо сам пункт
            summary += f"**{name}:** {get_status_text_md(status_val)}\n"
            if note_val:
                summary += f"{get_note_text_md(note_val)}\n"
                
    return summary.strip()


def get_checklist_template_data(cl_data: dict) -> dict:
    """(v3.8) Готує словник для заповнення шаблонів v3.8."""
    # (v3.8) Більшість ключів тепер генеруються в `get_checklist_summary_text`
    # Нам потрібні лише ключі для *поточного* питання, яке ми ставимо
    data = {
        'project_name': html.escape(cl_data.get('project_name', '...')),
        'summary_text': get_checklist_summary_text(cl_data),
        'status': "", # Це заповнюється для шаблонів *_NOTE
    }
    return data

async def start_checklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """(v3.8) Починає "безшовну" розмову про Чек-ліст (з CallbackQuery)."""
    query = update.callback_query
    await query.answer()

    clear_user_data(context)
    logger.info(f"User {query.from_user.id} почав 'Чек-ліст'.")
    context.user_data['cl'] = {} 
    
    # (v3.8) Крок 1: Питаємо "Назву Проєкту"
    text = templates.CHECKLIST_Q_PROJECT_NAME
    await edit_main_message(context, text, new_message=True)
    
    # (v3.8) Зберігаємо поточний стан
    context.user_data['current_state'] = CHECKLIST_Q_PROJECT_NAME
    return CHECKLIST_Q_PROJECT_NAME

# (НОВЕ v3.4) Обробник для "Етичного Нагадування"
async def start_checklist_from_upsell(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """(v3.8) Обробляє кнопку 'upsell', видаляє повідомлення і запускає чек-ліст."""
    query = update.callback_query
    await query.answer()
    
    # Видаляємо повідомлення "Вітаю! Ви завершили 'Крок 1'..."
    await delete_main_message(context, query.message.message_id) 
    
    # Тепер коректно запускаємо воркфлоу чек-ліста
    clear_user_data(context)
    logger.info(f"User {query.from_user.id} почав 'Чек-ліст' (з Нагадування).")
    context.user_data['cl'] = {} 
    
    # (v3.8) Крок 1: Питаємо "Назву Проєкту"
    text = templates.CHECKLIST_Q_PROJECT_NAME
    # new_message=True, тому що ми видалили попереднє
    await edit_main_message(context, text, new_message=True)
    
    # (v3.8) Зберігаємо поточний стан
    context.user_data['current_state'] = CHECKLIST_Q_PROJECT_NAME
    return CHECKLIST_Q_PROJECT_NAME

# (НОВЕ v3.8) Обробник для "Назви Проєкту" в Чек-лісті
async def checklist_q_project_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """(v3.8) Отримує Назву Проєкту і ставить перше питання Чек-ліста."""
    context.user_data['cl']['project_name'] = update.message.text
    await delete_user_text_reply(update)
    
    # Ставимо перше питання
    template_data = get_checklist_template_data(context.user_data['cl'])
    text = templates.CHECKLIST_C1_S1_STATUS.format(**template_data)
    await edit_main_message(context, text, get_checklist_status_keyboard())
    
    # (v3.8) Зберігаємо поточний стан
    context.user_data['current_state'] = C1_S1_NOTE
    return C1_S1_NOTE


# --- Категорія 1 (Логіка v3.8 - Виправлено "Skip" та UX) ---

async def checklist_c1_s1_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    status_val = "yes" if query.data == "cl_yes" else "no"
    context.user_data['cl']['c1_s1_status'] = status_val
    
    template_data = get_checklist_template_data(context.user_data['cl'])
    # (v3.8) Ми маємо передати 'status' окремо, оскільки 'summary_text' ще не містить його
    template_data['status'] = get_status_text_md(status_val) 
    
    text = templates.CHECKLIST_C1_S1_NOTE.format(**template_data)
    await edit_main_message(context, text, get_skip_note_keyboard())
    
    # (v3.6) Зберігаємо поточний стан
    context.user_data['current_state'] = C1_S2_STATUS
    return C1_S2_STATUS 

async def _ask_c1_s2_status(context: ContextTypes.DEFAULT_TYPE) -> int:
    template_data = get_checklist_template_data(context.user_data['cl'])
    text = templates.CHECKLIST_C1_S2_STATUS.format(**template_data)
    await edit_main_message(context, text, get_checklist_status_keyboard())

    # (v3.6) Зберігаємо поточний стан
    context.user_data['current_state'] = C1_S2_NOTE
    return C1_S2_NOTE

async def checklist_c1_s2_status_from_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['cl']['c1_s1_note'] = update.message.text
    await delete_user_text_reply(update)
    return await _ask_c1_s2_status(context)

async def checklist_c1_s2_status_from_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['cl']['c1_s1_note'] = "*Пропущено*"
    return await _ask_c1_s2_status(context)

async def checklist_c1_s2_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    status_val = "yes" if query.data == "cl_yes" else "no"
    context.user_data['cl']['c1_s2_status'] = status_val
    
    template_data = get_checklist_template_data(context.user_data['cl'])
    template_data['status'] = get_status_text_md(status_val)

    text = templates.CHECKLIST_C1_S2_NOTE.format(**template_data)
    await edit_main_message(context, text, get_skip_note_keyboard())

    # (v3.6) Зберігаємо поточний стан
    context.user_data['current_state'] = C1_S3_STATUS
    return C1_S3_STATUS

async def _ask_c1_s3_status(context: ContextTypes.DEFAULT_TYPE) -> int:
    template_data = get_checklist_template_data(context.user_data['cl'])
    text = templates.CHECKLIST_C1_S3_STATUS.format(**template_data)
    await edit_main_message(context, text, get_checklist_status_keyboard())

    # (v3.6) Зберігаємо поточний стан
    context.user_data['current_state'] = C1_S3_NOTE
    return C1_S3_NOTE

async def checklist_c1_s3_status_from_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['cl']['c1_s2_note'] = update.message.text
    await delete_user_text_reply(update)
    return await _ask_c1_s3_status(context)

async def checklist_c1_s3_status_from_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['cl']['c1_s2_note'] = "*Пропущено*"
    return await _ask_c1_s3_status(context)

async def checklist_c1_s3_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    status_val = "yes" if query.data == "cl_yes" else "no"
    context.user_data['cl']['c1_s3_status'] = status_val

    template_data = get_checklist_template_data(context.user_data['cl'])
    template_data['status'] = get_status_text_md(status_val)

    text = templates.CHECKLIST_C1_S3_NOTE.format(**template_data)
    await edit_main_message(context, text, get_skip_note_keyboard())

    # (v3.6) Зберігаємо поточний стан
    context.user_data['current_state'] = C2_S1_STATUS
    return C2_S1_STATUS

# --- Категорія 2 (Логіка v3.8 - Виправлено "Skip" та UX) ---

async def _ask_c2_s1_status(context: ContextTypes.DEFAULT_TYPE) -> int:
    template_data = get_checklist_template_data(context.user_data['cl'])
    text = templates.CHECKLIST_C2_S1_STATUS.format(**template_data)
    await edit_main_message(context, text, get_checklist_status_keyboard())

    # (v3.6) Зберігаємо поточний стан
    context.user_data['current_state'] = C2_S1_NOTE
    return C2_S1_NOTE

async def checklist_c2_s1_status_from_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['cl']['c1_s3_note'] = update.message.text
    await delete_user_text_reply(update)
    return await _ask_c2_s1_status(context)

async def checklist_c2_s1_status_from_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['cl']['c1_s3_note'] = "*Пропущено*"
    return await _ask_c2_s1_status(context)

async def checklist_c2_s1_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    status_val = "yes" if query.data == "cl_yes" else "no"
    context.user_data['cl']['c2_s1_status'] = status_val

    template_data = get_checklist_template_data(context.user_data['cl'])
    template_data['status'] = get_status_text_md(status_val)
    
    text = templates.CHECKLIST_C2_S1_NOTE.format(**template_data)
    await edit_main_message(context, text, get_skip_note_keyboard())

    # (v3.6) Зберігаємо поточний стан
    context.user_data['current_state'] = C2_S2_STATUS
    return C2_S2_STATUS

async def _ask_c2_s2_status(context: ContextTypes.DEFAULT_TYPE) -> int:
    template_data = get_checklist_template_data(context.user_data['cl'])
    text = templates.CHECKLIST_C2_S2_STATUS.format(**template_data)
    await edit_main_message(context, text, get_checklist_status_keyboard())

    # (v3.6) Зберігаємо поточний стан
    context.user_data['current_state'] = C2_S2_NOTE
    return C2_S2_NOTE

async def checklist_c2_s2_status_from_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['cl']['c2_s1_note'] = update.message.text
    await delete_user_text_reply(update)
    return await _ask_c2_s2_status(context)

async def checklist_c2_s2_status_from_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['cl']['c2_s1_note'] = "*Пропущено*"
    return await _ask_c2_s2_status(context)

async def checklist_c2_s2_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    status_val = "yes" if query.data == "cl_yes" else "no"
    context.user_data['cl']['c2_s2_status'] = status_val

    template_data = get_checklist_template_data(context.user_data['cl'])
    template_data['status'] = get_status_text_md(status_val)

    text = templates.CHECKLIST_C2_S2_NOTE.format(**template_data)
    await edit_main_message(context, text, get_skip_note_keyboard())

    # (v3.6) Зберігаємо поточний стан
    context.user_data['current_state'] = C2_S3_STATUS
    return C2_S3_STATUS

async def _ask_c2_s3_status(context: ContextTypes.DEFAULT_TYPE) -> int:
    template_data = get_checklist_template_data(context.user_data['cl'])
    text = templates.CHECKLIST_C2_S3_STATUS.format(**template_data)
    await edit_main_message(context, text, get_checklist_status_keyboard())

    # (v3.6) Зберігаємо поточний стан
    context.user_data['current_state'] = C2_S3_NOTE
    return C2_S3_NOTE

async def checklist_c2_s3_status_from_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['cl']['c2_s2_note'] = update.message.text
    await delete_user_text_reply(update)
    return await _ask_c2_s3_status(context)

async def checklist_c2_s3_status_from_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['cl']['c2_s2_note'] = "*Пропущено*"
    return await _ask_c2_s3_status(context)

async def checklist_c2_s3_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    status_val = "yes" if query.data == "cl_yes" else "no"
    context.user_data['cl']['c2_s3_status'] = status_val
    
    template_data = get_checklist_template_data(context.user_data['cl'])
    template_data['status'] = get_status_text_md(status_val)

    text = templates.CHECKLIST_C2_S3_NOTE.format(**template_data)
    await edit_main_message(context, text, get_skip_note_keyboard())

    # (v3.6) Зберігаємо поточний стан
    context.user_data['current_state'] = C3_S1_STATUS
    return C3_S1_STATUS

# --- Категорія 3 (Логіка v3.8 - Виправлено "Skip" та UX) ---

async def _ask_c3_s1_status(context: ContextTypes.DEFAULT_TYPE) -> int:
    template_data = get_checklist_template_data(context.user_data['cl'])
    text = templates.CHECKLIST_C3_S1_STATUS.format(**template_data)
    await edit_main_message(context, text, get_checklist_status_keyboard())

    # (v3.6) Зберігаємо поточний стан
    context.user_data['current_state'] = C3_S1_NOTE
    return C3_S1_NOTE

async def checklist_c3_s1_status_from_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['cl']['c2_s3_note'] = update.message.text
    await delete_user_text_reply(update)
    return await _ask_c3_s1_status(context)

async def checklist_c3_s1_status_from_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['cl']['c2_s3_note'] = "*Пропущено*"
    return await _ask_c3_s1_status(context)

async def checklist_c3_s1_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    status_val = "yes" if query.data == "cl_yes" else "no"
    context.user_data['cl']['c3_s1_status'] = status_val

    template_data = get_checklist_template_data(context.user_data['cl'])
    template_data['status'] = get_status_text_md(status_val)

    text = templates.CHECKLIST_C3_S1_NOTE.format(**template_data)
    await edit_main_message(context, text, get_skip_note_keyboard())

    # (v3.6) Зберігаємо поточний стан
    context.user_data['current_state'] = C3_S2_STATUS
    return C3_S2_STATUS

async def _ask_c3_s2_status(context: ContextTypes.DEFAULT_TYPE) -> int:
    template_data = get_checklist_template_data(context.user_data['cl'])
    text = templates.CHECKLIST_C3_S2_STATUS.format(**template_data)
    await edit_main_message(context, text, get_checklist_status_keyboard())

    # (v3.6) Зберігаємо поточний стан
    context.user_data['current_state'] = C3_S2_NOTE
    return C3_S2_NOTE

async def checklist_c3_s2_status_from_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['cl']['c3_s1_note'] = update.message.text
    await delete_user_text_reply(update)
    return await _ask_c3_s2_status(context)

async def checklist_c3_s2_status_from_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int: 
    query = update.callback_query
    await query.answer()
    context.user_data['cl']['c3_s1_note'] = "*Пропущено*"
    return await _ask_c3_s2_status(context)

async def checklist_c3_s2_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    status_val = "yes" if query.data == "cl_yes" else "no"
    context.user_data['cl']['c3_s2_status'] = status_val

    template_data = get_checklist_template_data(context.user_data['cl'])
    template_data['status'] = get_status_text_md(status_val)

    text = templates.CHECKLIST_C3_S2_NOTE.format(**template_data)
    await edit_main_message(context, text, get_skip_note_keyboard())

    # (v3.6) Зберігаємо поточний стан
    context.user_data['current_state'] = C3_S3_STATUS
    return C3_S3_STATUS

async def _ask_c3_s3_status(context: ContextTypes.DEFAULT_TYPE) -> int:
    template_data = get_checklist_template_data(context.user_data['cl'])
    text = templates.CHECKLIST_C3_S3_STATUS.format(**template_data)
    await edit_main_message(context, text, get_checklist_status_keyboard())

    # (v3.6) Зберігаємо поточний стан
    context.user_data['current_state'] = C3_S3_NOTE
    return C3_S3_NOTE

async def checklist_c3_s3_status_from_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['cl']['c3_s2_note'] = update.message.text
    await delete_user_text_reply(update)
    return await _ask_c3_s3_status(context)

async def checklist_c3_s3_status_from_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['cl']['c3_s2_note'] = "*Пропущено*"
    return await _ask_c3_s3_status(context)

async def checklist_c3_s3_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    status_val = "yes" if query.data == "cl_yes" else "no"
    context.user_data['cl']['c3_s3_status'] = status_val

    template_data = get_checklist_template_data(context.user_data['cl'])
    template_data['status'] = get_status_text_md(status_val)

    text = templates.CHECKLIST_C3_S3_NOTE.format(**template_data)
    await edit_main_message(context, text, get_skip_note_keyboard())

    # (v3.6) Зберігаємо поточний стан
    context.user_data['current_state'] = CHECKLIST_GENERATE
    return CHECKLIST_GENERATE

# --- Генерація (Логіка v3.6 - Виправлено "Skip") ---

async def checklist_generate_from_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['cl']['c3_s3_note'] = update.message.text
    await delete_user_text_reply(update)
    return await checklist_generate(update, context)

async def checklist_generate_from_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['cl']['c3_s3_note'] = "*Пропущено*"
    return await checklist_generate(update, context)

async def checklist_generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """(ОНОВЛЕНО v3.8) Генерує PDF Чек-ліста та показує кнопку "Повернутись"."""
    user_id = context._user_id
    logger.info(f"User {user_id}: генерація PDF Чек-ліста.")
    
    await delete_main_message(context)
    
    # Визначаємо chat_id для відповіді
    chat_id = update.message.chat_id if update.message else update.callback_query.message.chat_id
    
    generating_msg = await context.bot.send_message(
        chat_id=chat_id,
        text="Дякую! Аудит 9/9 завершено. Генерую ваш Чек-ліст PDF..."
    )

    data = context.user_data['cl']
    
    def get_status_md_text(status_key: str) -> str:
        status = data.get(status_key)
        if status == "yes":
            return "Виконано"
        elif status == "no":
            return "Не виконано"
        else:
            return "Не заповнено"

    def get_note_md_text_pdf(note_key: str) -> str:
        note = data.get(note_key, "*Не заповнено*")
        if note == "*Пропущено*":
            return note
        note_safe = html.escape(note)
        # (v3.6) Замінюємо markdown-escape на html <br>
        return note_safe.replace("\n", "<br>") 

    table_header = "| Пункт | Статус | Ваші Нотатки (для себе) |\n| :--- | :--- | :--- |\n"
    
    cat_1_header = "### Категорія 1: Контроль Доступу\n\n"
    cat_1_rows = [
        f"| 1.1. 2FA (Двофакторна Автентифікація) | {get_status_md_text('c1_s1_status')} | {get_note_md_text_pdf('c1_s1_note')} |",
        f"| 1.2. Принцип 'Найменших привілеїв' | {get_status_md_text('c1_s2_status')} | {get_note_md_text_pdf('c1_s2_note')} |",
        f"| 1.3. БЕЗ ПУБЛІЧНИХ ПОСИЛАНЬ | {get_status_md_text('c1_s3_status')} | {get_note_md_text_pdf('c1_s3_note')} |",
    ]
    cat_1_table = cat_1_header + table_header + "\n".join(cat_1_rows)

    cat_2_header = "\n\n### Категорія 2: Права Користувачів\n\n"
    cat_2_rows = [
        f"| 2.1. Публічна Політика | {get_status_md_text('c2_s1_status')} | {get_note_md_text_pdf('c2_s1_note')} |",
        f"| 2.2. Механізм Видалення (Ст. 8) | {get_status_md_text('c2_s2_status')} | {get_note_md_text_pdf('c2_s2_note')} |",
        f"| 2.3. Контакт для скарг | {get_status_md_text('c2_s3_status')} | {get_note_md_text_pdf('c2_s3_note')} |",
    ]
    cat_2_table = cat_2_header + table_header + "\n".join(cat_2_rows)

    cat_3_header = "\n\n### Категорія 3: Технічна Гігієна\n\n"
    cat_3_rows = [
        f"| 3.1. Безпека Токенів | {get_status_md_text('c3_s1_status')} | {get_note_md_text_pdf('c3_s1_note')} |",
        f"| 3.2. Планування Строків (Retention) | {get_status_md_text('c3_s2_status')} | {get_note_md_text_pdf('c3_s2_note')} |",
        f"| 3.3. Шифрування (Якщо є паролі) | {get_status_md_text('c3_s3_status')} | {get_note_md_text_pdf('c3_s3_note')} |",
    ]
    cat_3_table = cat_3_header + table_header + "\n".join(cat_3_rows)

    checklist_content = f"{cat_1_table}{cat_2_table}{cat_3_table}"

    # (v3.8) КРИТИЧНИЙ ФІКС: Додаємо 'project_name'
    data_dict = {
        'project_name': html.escape(data.get('project_name', '[Назва Проєкту]')),
        'date': date.today().strftime("%d.%m.%Y"),
        'checklist_content': checklist_content 
    }
    
    # (v3.0) Очищуємо дані ДО генерації
    clear_user_data(context)

    try:
        # (v3.8) Тепер .format() отримає 'project_name'
        filled_markdown = templates.CHECKLIST_TEMPLATE_PDF.format(**data_dict)
        
        pdf_file_path = create_pdf_from_markdown(
            content=filled_markdown,
            is_html=False, 
            output_filename=f"checklist_{user_id}.pdf"
        )
        
        await generating_msg.delete()
        
        await context.bot.send_document(chat_id=chat_id, document=open(pdf_file_path, 'rb'))
        
        # (v3.2) Використовуємо helper-функцію
        await context.bot.send_message(
            chat_id=chat_id,
            text="Ваш детальний Чек-ліст готовий. Я видалив усі ваші відповіді зі своєї пам'яті.",
            reply_markup=get_post_action_keyboard()
        )
        clear_temp_file(pdf_file_path)

    except Exception as e:
        logger.error(f"PDF Checklist generation failed for user {user_id}: {e}", exc_info=True)
        try:
            await generating_msg.delete()
        except Exception:
            pass
        await context.bot.send_message(chat_id=chat_id, text=f"Під час генерації PDF сталася помилка: {e}")
        # (v3.4) Викликаємо 'start' з фальшивим update
        await start(_FakeUpdate(chat_id, context.bot), context)
    
    finally:
        return ConversationHandler.END


# === 5. Налаштування та Запуск Бота ===

def main() -> None: # (v3.1.2) Повернено до СИНХРОННОЇ
    """Запускає бота."""
    application = Application.builder().token(BOT_TOKEN).build()

    # (v3.2) СТВОРЮЄМО ОДИН ЄДИНИЙ ОБРОБНИК РОЗМОВ
    main_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_policy, pattern="^start_policy$"),
            CallbackQueryHandler(start_dpia, pattern="^start_dpia$"),
            CallbackQueryHandler(start_checklist, pattern="^start_checklist$"),
            # (НОВЕ v3.4) Вхідна точка для "Етичного Нагадування"
            CallbackQueryHandler(start_checklist_from_upsell, pattern="^start_checklist_upsell$")
        ],
        states={
            # --- Стани "Політики" (10-14) ---
            POLICY_Q_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, policy_q_contact)],
            POLICY_Q_DATA_COLLECTED: [MessageHandler(filters.TEXT & ~filters.COMMAND, policy_q_data_collected)],
            POLICY_Q_DATA_STORAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, policy_q_data_storage)],
            POLICY_Q_DELETE_MECHANISM: [MessageHandler(filters.TEXT & ~filters.COMMAND, policy_q_delete_mechanism)],
            POLICY_GENERATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, policy_generate)],
            
            # --- Стани "DPIA" (20-31) ---
            DPIA_Q_TEAM: [MessageHandler(filters.TEXT & ~filters.COMMAND, dpia_q_team)],
            DPIA_Q_GOAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, dpia_q_goal)],
            DPIA_Q_DATA_LIST: [MessageHandler(filters.TEXT & ~filters.COMMAND, dpia_q_data_list)],
            DPIA_Q_MINIMIZATION_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, dpia_q_minimization_start)],
            DPIA_Q_MINIMIZATION_REASON: [CallbackQueryHandler(dpia_q_minimization_reason, pattern="^min_(yes|no)$")],
            DPIA_Q_MINIMIZATION_STATUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, dpia_q_minimization_status)],
            DPIA_Q_RETENTION_MECHANISM: [MessageHandler(filters.TEXT & ~filters.COMMAND, dpia_q_retention_mechanism)],
            DPIA_Q_STORAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, dpia_q_storage)],
            DPIA_Q_RISK: [MessageHandler(filters.TEXT & ~filters.COMMAND, dpia_q_risk)],
            DPIA_Q_MITIGATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, dpia_q_mitigation)],
            DPIA_GENERATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, dpia_generate)],

            # --- Стани "Чек-ліста" (40-58) --- (v3.8)
            # (v3.8) НОВИЙ СТАН
            CHECKLIST_Q_PROJECT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, checklist_q_project_name)],
            
            # (v3.6) Повністю перероблений state machine
            # Cat 1
            C1_S1_NOTE: [CallbackQueryHandler(checklist_c1_s1_note, pattern="^cl_(yes|no)$")],
            C1_S2_STATUS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, checklist_c1_s2_status_from_text),
                CallbackQueryHandler(checklist_c1_s2_status_from_skip, pattern="^cl_skip_note$")
            ],
            C1_S2_NOTE: [CallbackQueryHandler(checklist_c1_s2_note, pattern="^cl_(yes|no)$")],
            C1_S3_STATUS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, checklist_c1_s3_status_from_text),
                CallbackQueryHandler(checklist_c1_s3_status_from_skip, pattern="^cl_skip_note$")
            ],
            C1_S3_NOTE: [CallbackQueryHandler(checklist_c1_s3_note, pattern="^cl_(yes|no)$")],
            
            # Cat 2
            C2_S1_STATUS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, checklist_c2_s1_status_from_text),
                CallbackQueryHandler(checklist_c2_s1_status_from_skip, pattern="^cl_skip_note$")
            ],
            C2_S1_NOTE: [CallbackQueryHandler(checklist_c2_s1_note, pattern="^cl_(yes|no)$")],
            C2_S2_STATUS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, checklist_c2_s2_status_from_text),
                CallbackQueryHandler(checklist_c2_s2_status_from_skip, pattern="^cl_skip_note$")
            ],
            C2_S2_NOTE: [CallbackQueryHandler(checklist_c2_s2_note, pattern="^cl_(yes|no)$")],
            C2_S3_STATUS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, checklist_c2_s3_status_from_text),
                CallbackQueryHandler(checklist_c2_s3_status_from_skip, pattern="^cl_skip_note$")
            ],
            C2_S3_NOTE: [CallbackQueryHandler(checklist_c2_s3_note, pattern="^cl_(yes|no)$")],
            
            # Cat 3
            C3_S1_STATUS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, checklist_c3_s1_status_from_text),
                CallbackQueryHandler(checklist_c3_s1_status_from_skip, pattern="^cl_skip_note$")
            ],
            C3_S1_NOTE: [CallbackQueryHandler(checklist_c3_s1_note, pattern="^cl_(yes|no)$")],
            C3_S2_STATUS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, checklist_c3_s2_status_from_text),
                CallbackQueryHandler(checklist_c3_s2_status_from_skip, pattern="^cl_skip_note$")
            ],
            C3_S2_NOTE: [CallbackQueryHandler(checklist_c3_s2_note, pattern="^cl_(yes|no)$")],
            C3_S3_STATUS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, checklist_c3_s3_status_from_text),
                CallbackQueryHandler(checklist_c3_s3_status_from_skip, pattern="^cl_skip_note$")
            ],
            C3_S3_NOTE: [CallbackQueryHandler(checklist_c3_s3_note, pattern="^cl_(yes|no)$")],

            # Generate
            CHECKLIST_GENERATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, checklist_generate_from_text),
                CallbackQueryHandler(checklist_generate_from_skip, pattern="^cl_skip_note$")
            ],
        },
        fallbacks=[
            # (НОВЕ v3.4) "Блокувальник"
            CallbackQueryHandler(
                block_workflow_switch, 
                pattern="^start_policy$|^start_dpia$|^start_checklist$"
            ),
            # (НОВЕ v3.4) Кнопка "Скасувати" з "Блокувальника"
            CallbackQueryHandler(cancel_from_block, pattern="^cancel_from_block$"),
            
            # Стандартний /cancel
            CommandHandler("cancel", cancel)
        ],
        # (v3.4) ВИДАЛЕНО 'allow_reentry=True'. Тепер бот "блокується".
    )

    application.add_handler(main_conv_handler)
    
    # Головні команди та кнопки меню (вони поза розмовою)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(start, pattern="^start_menu$")) # Кнопка "Назад в меню"
    # (v3.1) Нова кнопка "Повернутись" після генерації
    application.add_handler(CallbackQueryHandler(start, pattern="^start_menu_post_generation$")) 
    
    application.add_handler(CommandHandler("privacy", show_privacy))
    application.add_handler(CallbackQueryHandler(show_privacy_inline, pattern="^show_privacy$"))
    
    application.add_handler(CommandHandler("help", show_help))
    application.add_handler(CallbackQueryHandler(show_help_inline, pattern="^show_help$"))

    # Глобальний fallback 'cancel' (ловить /cancel будь-де)
    # (v3.2) Цей 'cancel' обробляється, лише якщо ми НЕ в 'main_conv_handler'
    application.add_handler(CommandHandler("cancel", cancel)) 

    # (v3.1.2) Ми не можемо отримати username до запуску run_polling(),
    # тому що run_polling() - це синхронний блокуючий виклик.
    # ЛОГ про username з'явиться автоматично ПІСЛЯ запуску.
    logger.info("Бот запускається...")
    
    # (v3.1.2) run_polling() - це блокуюча, синхронна функція.
    application.run_polling() 

if __name__ == "__main__":
    # (v3.1.2) Запускаємо синхронну main
    main()