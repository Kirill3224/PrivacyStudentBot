# -*- coding: utf-8 -*-
"""
Головний файл бота "Privacy Sentry" (v3.1 - Фінальний UX)

Що нового:
- Уніфікований "Безшовний" UX: "Політика" та "DPIA" тепер
  також редагують одне повідомлення, як і "Чек-ліст".
- Нове Головне Меню: Додано кнопки GitHub, Допомога, Політика.
- Покращена логіка /cancel та повернення в меню.
- (v3.1) Новий потік після генерації PDF (PDF -> Повідомлення з кнопкою -> Меню).
- (v3.1) Видалені всі номери версій ("v2.9") з тексту для користувача.
"""

import logging
import os
import html
# (v3.1.2) ВИДАЛЕНО import asyncio
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
logger = logging.getLogger(__name__)

# --- Завантаження конфігурації ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("!!! Змінна BOT_TOKEN не знайдена в .env файлі !!!")
    exit()

# === Етапи для Conversation Handlers ===

# --- Етапи для "Політики" (Безшовний UX) ---
(
    POLICY_START, # Не використовується, але для повноти
    POLICY_Q_CONTACT,
    POLICY_Q_DATA_COLLECTED,
    POLICY_Q_DATA_STORAGE,
    POLICY_Q_DELETE_MECHANISM,
    POLICY_GENERATE,
) = range(6)

# --- Етапи для "DPIA" (Безшовний UX) ---
(
    DPIA_START, # Не використовується
    DPIA_Q_TEAM,
    DPIA_Q_GOAL,
    DPIA_Q_DATA_LIST,
    DPIA_Q_MINIMIZATION_START,
    DPIA_Q_MINIMIZATION_STATUS,
    DPIA_Q_MINIMIZATION_REASON,
    DPIA_Q_RETENTION_PERIOD,
    DPIA_Q_RETENTION_MECHANISM,
    DPIA_Q_STORAGE,
    DPIA_Q_RISK,
    DPIA_Q_MITIGATION,
    DPIA_GENERATE,
) = range(13)

# --- Етапи для "Чек-ліста" (19 етапів + 9 'skip' станів = 28) ---
(
    CHECKLIST_START, # C0
    C1_S1_NOTE, # C1
    C1_S2_STATUS, # C2
    C1_S2_NOTE, # C3
    C1_S3_STATUS, # C4
    C1_S3_NOTE, # C5
    C2_S1_STATUS, # C6
    C2_S1_NOTE, # C7
    C2_S2_STATUS, # C8
    C2_S2_NOTE, # C9
    C2_S3_STATUS, # C10
    C2_S3_NOTE, # C11
    C3_S1_STATUS, # C12
    C3_S1_NOTE, # C13
    C3_S2_STATUS, # C14
    C3_S2_NOTE, # C15
    C3_S3_STATUS, # C16
    C3_S3_NOTE, # C17
    CHECKLIST_GENERATE, # C18
    # (v2.8) Етапи для "Skip Logic"
    C1_S2_STATUS_SKIP,
    C1_S3_STATUS_SKIP,
    C2_S1_STATUS_SKIP,
    C2_S2_STATUS_SKIP,
    C2_S3_STATUS_SKIP,
    C3_S1_STATUS_SKIP,
    C3_S2_STATUS_SKIP,
    C3_S3_STATUS_SKIP,
    CHECKLIST_GENERATE_SKIP,
) = range(28) 


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
            
    return ConversationHandler.END 

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
    """(v3.3) Показує /privacy (БЕЗ кнопки 'Повернутись')"""
    if not update.message:
        return
    await update.message.reply_text(
        templates.BOT_PRIVACY_POLICY, 
        parse_mode=ParseMode.MARKDOWN
        # (v3.3) ВИДАЛЕНО 'reply_markup'
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
    """(v3.0) Показує /privacy як редагування повідомлення."""
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("⬅️ Назад в меню", callback_data="start_menu")]]
    
    try:
        await query.edit_message_text(
            templates.BOT_PRIVACY_POLICY, 
            reply_markup=InlineKeyboardMarkup(keyboard), 
            parse_mode=ParseMode.MARKDOWN
        )
    except BadRequest as e:
        if "Message is not modified" not in str(e):
             logger.warning(f"show_privacy_inline: {e}")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """(ОНОВЛЕНО v3.1) Скасовує поточну операцію, очищує дані та повертає в меню."""
    clear_user_data(context)
    
    query = update.callback_query
    message = update.message
    
    cancel_text = "Дію скасовано. Усі зібрані відповіді видалено з моєї пам'яті."
    
    if query:
        await query.answer()
        # (v3.1) Намагаємося видалити "Головне" повідомлення
        await delete_main_message(context, query.message.message_id) 
        # ...і надсилаємо підтвердження
        await context.bot.send_message(chat_id=query.message.chat_id, text=cancel_text)
    elif message:
        await message.reply_text(cancel_text, reply_markup=ReplyKeyboardRemove())
        
    # (v3.0) Відразу показуємо головне меню
    await start(update, context)
        
    return ConversationHandler.END

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

    return POLICY_Q_CONTACT

async def policy_q_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['policy']['project_name'] = update.message.text
    await delete_user_text_reply(update)
    
    text = templates.POLICY_Q_CONTACT.format(**get_policy_template_data(context.user_data['policy']))
    await edit_main_message(context, text)
    return POLICY_Q_DATA_COLLECTED

async def policy_q_data_collected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['policy']['contact'] = update.message.text
    await delete_user_text_reply(update)

    text = templates.POLICY_Q_DATA_COLLECTED.format(**get_policy_template_data(context.user_data['policy']))
    await edit_main_message(context, text)
    return POLICY_Q_DATA_STORAGE

async def policy_q_data_storage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['policy']['data_collected'] = update.message.text
    await delete_user_text_reply(update)
    
    text = templates.POLICY_Q_DATA_STORAGE.format(**get_policy_template_data(context.user_data['policy']))
    await edit_main_message(context, text)
    return POLICY_Q_DELETE_MECHANISM

async def policy_q_delete_mechanism(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['policy']['data_storage'] = update.message.text
    await delete_user_text_reply(update)
    
    text = templates.POLICY_Q_DELETE_MECHANISM.format(**get_policy_template_data(context.user_data['policy']))
    await edit_main_message(context, text)
    return POLICY_GENERATE

async def policy_generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """(ОНОВЛЕНО v3.1) Генерує PDF Політики та показує кнопку "Повернутись"."""
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
        
        # (v3.2) Використовуємо helper-функцію
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text="Ваша Політика Конфіденційності готова. Я видалив усі ваші відповіді зі своєї пам'яті.",
            reply_markup=get_post_action_keyboard()
        )
        clear_temp_file(pdf_file_path)

    except Exception as e:
        logger.error(f"PDF generation failed for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(f"Під час генерації PDF сталася помилка: {e}")
        # (v3.1) Все одно повертаємо в меню, навіть якщо помилка
        await start(update, context)
    
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
    return DPIA_Q_TEAM

async def dpia_q_team(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['dpia']['project_name'] = update.message.text
    await delete_user_text_reply(update)
    
    text = templates.DPIA_Q_TEAM.format(**get_dpia_template_data(context.user_data['dpia']))
    await edit_main_message(context, text)
    return DPIA_Q_GOAL

async def dpia_q_goal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['dpia']['team'] = update.message.text
    await delete_user_text_reply(update)
    
    text = templates.DPIA_Q_GOAL.format(**get_dpia_template_data(context.user_data['dpia']))
    await edit_main_message(context, text)
    return DPIA_Q_DATA_LIST

async def dpia_q_data_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['dpia']['goal'] = update.message.text
    await delete_user_text_reply(update)
    
    text = templates.DPIA_Q_DATA_LIST.format(**get_dpia_template_data(context.user_data['dpia']))
    await edit_main_message(context, text)
    return DPIA_Q_MINIMIZATION_START

async def dpia_q_minimization_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отримує список даних і запускає цикл мінімізації."""
    data_list = [item.strip() for item in update.message.text.split('\n') if item.strip()]
    await delete_user_text_reply(update)

    if not data_list:
        text = templates.DPIA_Q_DATA_LIST_ERROR.format(**get_dpia_template_data(context.user_data['dpia']))
        await edit_main_message(context, text)
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
    return DPIA_Q_RETENTION_MECHANISM

async def dpia_q_retention_mechanism(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['dpia']['retention_period'] = update.message.text
    await delete_user_text_reply(update)
    
    text = templates.DPIA_Q_RETENTION_MECHANISM.format(**get_dpia_template_data(context.user_data['dpia']))
    await edit_main_message(context, text)
    return DPIA_Q_STORAGE

async def dpia_q_storage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['dpia']['retention_mechanism'] = update.message.text
    await delete_user_text_reply(update)
    
    text = templates.DPIA_Q_STORAGE.format(**get_dpia_template_data(context.user_data['dpia']))
    await edit_main_message(context, text)
    return DPIA_Q_RISK

async def dpia_q_risk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['dpia']['storage'] = update.message.text
    await delete_user_text_reply(update)
    
    text = templates.DPIA_Q_RISK.format(**get_dpia_template_data(context.user_data['dpia']))
    await edit_main_message(context, text)
    return DPIA_Q_MITIGATION

async def dpia_q_mitigation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['dpia']['risk'] = update.message.text
    await delete_user_text_reply(update)
    
    text = templates.DPIA_Q_MITIGATION.format(**get_dpia_template_data(context.user_data['dpia']))
    await edit_main_message(context, text)
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
        # (v3.1) Все одно повертаємо в меню, навіть якщо помилка
        await start(update, context)
    
    finally:
        try:
            await generating_msg.delete()
        except Exception as e:
            logger.warning(f"Не вдалося видалити 'Генерую...' {e}")
            
        return ConversationHandler.END


# === 4. Логіка "Чек-ліста" (3/3) - v2.8 (Без змін, вона ідеальна) ===

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

def get_checklist_template_data(cl_data: dict) -> dict:
    """(v2.8) Готує словник для заповнення шаблонів v2.8."""
    data = {
        'c1_s1_status': get_status_text_md(cl_data.get('c1_s1_status', '')),
        'c1_s1_note': get_note_text_md(cl_data.get('c1_s1_note', '')),
        'c1_s2_status': get_status_text_md(cl_data.get('c1_s2_status', '')),
        'c1_s2_note': get_note_text_md(cl_data.get('c1_s2_note', '')),
        'c1_s3_status': get_status_text_md(cl_data.get('c1_s3_status', '')),
        'c1_s3_note': get_note_text_md(cl_data.get('c1_s3_note', '')),
        
        'c2_s1_status': get_status_text_md(cl_data.get('c2_s1_status', '')),
        'c2_s1_note': get_note_text_md(cl_data.get('c2_s1_note', '')),
        'c2_s2_status': get_status_text_md(cl_data.get('c2_s2_status', '')),
        'c2_s2_note': get_note_text_md(cl_data.get('c2_s2_note', '')),
        'c2_s3_status': get_status_text_md(cl_data.get('c2_s3_status', '')),
        'c2_s3_note': get_note_text_md(cl_data.get('c2_s3_note', '')),

        'c3_s1_status': get_status_text_md(cl_data.get('c3_s1_status', '')),
        'c3_s1_note': get_note_text_md(cl_data.get('c3_s1_note', '')),
        'c3_s2_status': get_status_text_md(cl_data.get('c3_s2_status', '')),
        'c3_s2_note': get_note_text_md(cl_data.get('c3_s2_note', '')),
        'c3_s3_status': get_status_text_md(cl_data.get('c3_s3_status', '')),
        'c3_s3_note': get_note_text_md(cl_data.get('c3_s3_note', '')),
    }
    return data

async def start_checklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """(v2.9) Починає "безшовну" розмову про Чек-ліст (з CallbackQuery)."""
    query = update.callback_query
    await query.answer()

    clear_user_data(context)
    logger.info(f"User {query.from_user.id} почав 'Чек-ліст'.")
    context.user_data['cl'] = {} 
    
    # (v3.0) Редагуємо головне меню, щоб почати
    text = templates.CHECKLIST_C1_S1_STATUS.format(**get_checklist_template_data({}))
    await edit_main_message(context, text, get_checklist_status_keyboard(), new_message=True)
    
    return C1_S1_NOTE

# --- Категорія 1 (Логіка v2.8) ---

async def checklist_c1_s1_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['cl']['c1_s1_status'] = "yes" if query.data == "cl_yes" else "no"
    
    template_data = get_checklist_template_data(context.user_data['cl'])
    text = templates.CHECKLIST_C1_S1_NOTE.format(**template_data)
    await edit_main_message(context, text, get_skip_note_keyboard())
    return C1_S2_STATUS 

async def _ask_c1_s2_status(context: ContextTypes.DEFAULT_TYPE) -> int:
    template_data = get_checklist_template_data(context.user_data['cl'])
    text = templates.CHECKLIST_C1_S2_STATUS.format(**template_data)
    await edit_main_message(context, text, get_checklist_status_keyboard())
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
    context.user_data['cl']['c1_s2_status'] = "yes" if query.data == "cl_yes" else "no"
    template_data = get_checklist_template_data(context.user_data['cl'])
    text = templates.CHECKLIST_C1_S2_NOTE.format(**template_data)
    await edit_main_message(context, text, get_skip_note_keyboard())
    return C1_S3_STATUS

async def _ask_c1_s3_status(context: ContextTypes.DEFAULT_TYPE) -> int:
    template_data = get_checklist_template_data(context.user_data['cl'])
    text = templates.CHECKLIST_C1_S3_STATUS.format(**template_data)
    await edit_main_message(context, text, get_checklist_status_keyboard())
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
    context.user_data['cl']['c1_s3_status'] = "yes" if query.data == "cl_yes" else "no"
    template_data = get_checklist_template_data(context.user_data['cl'])
    text = templates.CHECKLIST_C1_S3_NOTE.format(**template_data)
    await edit_main_message(context, text, get_skip_note_keyboard())
    return C2_S1_STATUS

# --- Категорія 2 (Логіка v2.8) ---

async def _ask_c2_s1_status(context: ContextTypes.DEFAULT_TYPE) -> int:
    template_data = get_checklist_template_data(context.user_data['cl'])
    text = templates.CHECKLIST_C2_S1_STATUS.format(**template_data)
    await edit_main_message(context, text, get_checklist_status_keyboard())
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
    context.user_data['cl']['c2_s1_status'] = "yes" if query.data == "cl_yes" else "no"
    template_data = get_checklist_template_data(context.user_data['cl'])
    text = templates.CHECKLIST_C2_S1_NOTE.format(**template_data)
    await edit_main_message(context, text, get_skip_note_keyboard())
    return C2_S2_STATUS

async def _ask_c2_s2_status(context: ContextTypes.DEFAULT_TYPE) -> int:
    template_data = get_checklist_template_data(context.user_data['cl'])
    text = templates.CHECKLIST_C2_S2_STATUS.format(**template_data)
    await edit_main_message(context, text, get_checklist_status_keyboard())
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
    context.user_data['cl']['c2_s2_status'] = "yes" if query.data == "cl_yes" else "no"
    template_data = get_checklist_template_data(context.user_data['cl'])
    text = templates.CHECKLIST_C2_S2_NOTE.format(**template_data)
    await edit_main_message(context, text, get_skip_note_keyboard())
    return C2_S3_STATUS

async def _ask_c2_s3_status(context: ContextTypes.DEFAULT_TYPE) -> int:
    template_data = get_checklist_template_data(context.user_data['cl'])
    text = templates.CHECKLIST_C2_S3_STATUS.format(**template_data)
    await edit_main_message(context, text, get_checklist_status_keyboard())
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
    context.user_data['cl']['c2_s3_status'] = "yes" if query.data == "cl_yes" else "no"
    template_data = get_checklist_template_data(context.user_data['cl'])
    text = templates.CHECKLIST_C2_S3_NOTE.format(**template_data)
    await edit_main_message(context, text, get_skip_note_keyboard())
    return C3_S1_STATUS

# --- Категорія 3 (Логіка v2.8) ---

async def _ask_c3_s1_status(context: ContextTypes.DEFAULT_TYPE) -> int:
    template_data = get_checklist_template_data(context.user_data['cl'])
    text = templates.CHECKLIST_C3_S1_STATUS.format(**template_data)
    await edit_main_message(context, text, get_checklist_status_keyboard())
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
    context.user_data['cl']['c3_s1_status'] = "yes" if query.data == "cl_yes" else "no"
    template_data = get_checklist_template_data(context.user_data['cl'])
    text = templates.CHECKLIST_C3_S1_NOTE.format(**template_data)
    await edit_main_message(context, text, get_skip_note_keyboard())
    return C3_S2_STATUS

async def _ask_c3_s2_status(context: ContextTypes.DEFAULT_TYPE) -> int:
    template_data = get_checklist_template_data(context.user_data['cl'])
    text = templates.CHECKLIST_C3_S2_STATUS.format(**template_data)
    await edit_main_message(context, text, get_checklist_status_keyboard())
    return C3_S2_NOTE

async def checklist_c3_s2_status_from_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['cl']['c3_s1_note'] = update.message.text
    await delete_user_text_reply(update)
    return await _ask_c3_s2_status(context)

async def checklist_c3_s2_status_from_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int: # (v3.1.1) ВИПРАВЛЕНО ОДРУКІВКУ TPE -> TYPE
    query = update.callback_query
    await query.answer()
    context.user_data['cl']['c3_s1_note'] = "*Пропущено*"
    return await _ask_c3_s2_status(context)

async def checklist_c3_s2_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['cl']['c3_s2_status'] = "yes" if query.data == "cl_yes" else "no"
    template_data = get_checklist_template_data(context.user_data['cl'])
    text = templates.CHECKLIST_C3_S2_NOTE.format(**template_data)
    await edit_main_message(context, text, get_skip_note_keyboard())
    return C3_S3_STATUS

async def _ask_c3_s3_status(context: ContextTypes.DEFAULT_TYPE) -> int:
    template_data = get_checklist_template_data(context.user_data['cl'])
    text = templates.CHECKLIST_C3_S3_STATUS.format(**template_data)
    await edit_main_message(context, text, get_checklist_status_keyboard())
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
    context.user_data['cl']['c3_s3_status'] = "yes" if query.data == "cl_yes" else "no"
    template_data = get_checklist_template_data(context.user_data['cl'])
    text = templates.CHECKLIST_C3_S3_NOTE.format(**template_data)
    await edit_main_message(context, text, get_skip_note_keyboard())
    return CHECKLIST_GENERATE

# --- Генерація (Логіка v2.8) ---

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
    """(ОНОВЛЕНО v3.1) Генерує PDF Чек-ліста та показує кнопку "Повернутись"."""
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

    data_dict = {
        'date': date.today().strftime("%d.%m.%Y"),
        'checklist_content': checklist_content 
    }
    
    # (v3.0) Очищуємо дані ДО генерації
    clear_user_data(context)

    try:
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
        # (v3.1) Все одно повертаємо в меню, навіть якщо помилка
        await start(update, context)
    
    finally:
        return ConversationHandler.END


# === 5. Налаштування та Запуск Бота ===

def main() -> None: # (v3.1.2) Повернено до СИНХРОННОЇ
    """Запускає бота."""
    application = Application.builder().token(BOT_TOKEN).build()

    # (ОНОВЛЕНО v3.0) Entry points тепер реагують на CallbackQuery з меню /start
    policy_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_policy, pattern="^start_policy$")],
        states={
            POLICY_Q_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, policy_q_contact)],
            POLICY_Q_DATA_COLLECTED: [MessageHandler(filters.TEXT & ~filters.COMMAND, policy_q_data_collected)],
            POLICY_Q_DATA_STORAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, policy_q_data_storage)],
            POLICY_Q_DELETE_MECHANISM: [MessageHandler(filters.TEXT & ~filters.COMMAND, policy_q_delete_mechanism)],
            POLICY_GENERATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, policy_generate)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    dpia_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_dpia, pattern="^start_dpia$")],
        states={
            DPIA_Q_TEAM: [MessageHandler(filters.TEXT & ~filters.COMMAND, dpia_q_team)],
            DPIA_Q_GOAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, dpia_q_goal)],
            DPIA_Q_DATA_LIST: [MessageHandler(filters.TEXT & ~filters.COMMAND, dpia_q_data_list)],
            DPIA_Q_MINIMIZATION_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, dpia_q_minimization_start)],
            DPIA_Q_MINIMIZATION_REASON: [CallbackQueryHandler(dpia_q_minimization_reason, pattern="^min_(yes|no)$")],
            DPIA_Q_MINIMIZATION_STATUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, dpia_q_minimization_status)],
            # (v3.1 fix) DPIA_Q_RETENTION_PERIOD - це стан, а не функція. 
            # Функція dpia_minimization_finished() повертає стан DPIA_Q_RETENTION_MECHANISM, 
            # але має повертати DPIA_Q_RETENTION_PERIOD. 
            # Але оскільки dpia_minimization_finished викликає edit_main_message з текстом для DPIA_Q_RETENTION_PERIOD, 
            # наступний MessageHandler має бути DPIA_Q_RETENTION_MECHANISM. 
            # Тому:
            # 1. dpia_minimization_finished -> повертає DPIA_Q_RETENTION_MECHANISM
            # 2. states[DPIA_Q_RETENTION_MECHANISM] -> викликає dpia_q_retention_mechanism
            # Це вірно.
            DPIA_Q_RETENTION_MECHANISM: [MessageHandler(filters.TEXT & ~filters.COMMAND, dpia_q_retention_mechanism)],
            DPIA_Q_STORAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, dpia_q_storage)],
            DPIA_Q_RISK: [MessageHandler(filters.TEXT & ~filters.COMMAND, dpia_q_risk)],
            DPIA_Q_MITIGATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, dpia_q_mitigation)],
            DPIA_GENERATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, dpia_generate)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    checklist_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_checklist, pattern="^start_checklist$")],
        states={
            # Cat 1
            C1_S1_NOTE: [CallbackQueryHandler(checklist_c1_s1_note, pattern="^cl_(yes|no)$")],
            C1_S2_STATUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, checklist_c1_s2_status_from_text)],
            C1_S2_STATUS_SKIP: [CallbackQueryHandler(checklist_c1_s2_status_from_skip, pattern="^cl_skip_note$")],
            C1_S2_NOTE: [CallbackQueryHandler(checklist_c1_s2_note, pattern="^cl_(yes|no)$")],
            C1_S3_STATUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, checklist_c1_s3_status_from_text)],
            C1_S3_STATUS_SKIP: [CallbackQueryHandler(checklist_c1_s3_status_from_skip, pattern="^cl_skip_note$")],
            C1_S3_NOTE: [CallbackQueryHandler(checklist_c1_s3_note, pattern="^cl_(yes|no)$")],
            
            # Cat 2
            C2_S1_STATUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, checklist_c2_s1_status_from_text)],
            C2_S1_STATUS_SKIP: [CallbackQueryHandler(checklist_c2_s1_status_from_skip, pattern="^cl_skip_note$")],
            C2_S1_NOTE: [CallbackQueryHandler(checklist_c2_s1_note, pattern="^cl_(yes|no)$")],
            C2_S2_STATUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, checklist_c2_s2_status_from_text)],
            C2_S2_STATUS_SKIP: [CallbackQueryHandler(checklist_c2_s2_status_from_skip, pattern="^cl_skip_note$")],
            C2_S2_NOTE: [CallbackQueryHandler(checklist_c2_s2_note, pattern="^cl_(yes|no)$")],
            C2_S3_STATUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, checklist_c2_s3_status_from_text)],
            C2_S3_STATUS_SKIP: [CallbackQueryHandler(checklist_c2_s3_status_from_skip, pattern="^cl_skip_note$")],
            C2_S3_NOTE: [CallbackQueryHandler(checklist_c2_s3_note, pattern="^cl_(yes|no)$")],
            
            # Cat 3
            C3_S1_STATUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, checklist_c3_s1_status_from_text)],
            C3_S1_STATUS_SKIP: [CallbackQueryHandler(checklist_c3_s1_status_from_skip, pattern="^cl_skip_note$")],
            C3_S1_NOTE: [CallbackQueryHandler(checklist_c3_s1_note, pattern="^cl_(yes|no)$")],
            C3_S2_STATUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, checklist_c3_s2_status_from_text)],
            C3_S2_STATUS_SKIP: [CallbackQueryHandler(checklist_c3_s2_status_from_skip, pattern="^cl_skip_note$")],
            C3_S2_NOTE: [CallbackQueryHandler(checklist_c3_s2_note, pattern="^cl_(yes|no)$")],
            C3_S3_STATUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, checklist_c3_s3_status_from_text)],
            C3_S3_STATUS_SKIP: [CallbackQueryHandler(checklist_c3_s3_status_from_skip, pattern="^cl_skip_note$")],
            C3_S3_NOTE: [CallbackQueryHandler(checklist_c3_s3_note, pattern="^cl_(yes|no)$")],

            # Generate
            CHECKLIST_GENERATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, checklist_generate_from_text)],
            CHECKLIST_GENERATE_SKIP: [CallbackQueryHandler(checklist_generate_from_skip, pattern="^cl_skip_note$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(policy_conv_handler)
    application.add_handler(dpia_conv_handler)
    application.add_handler(checklist_conv_handler)
    
    # Головні команди та кнопки меню
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(start, pattern="^start_menu$")) # Кнопка "Назад в меню"
    # (v3.1) Нова кнопка "Повернутись" після генерації
    application.add_handler(CallbackQueryHandler(start, pattern="^start_menu_post_generation$")) 
    
    application.add_handler(CommandHandler("privacy", show_privacy))
    application.add_handler(CallbackQueryHandler(show_privacy_inline, pattern="^show_privacy$"))
    
    application.add_handler(CommandHandler("help", show_help))
    application.add_handler(CallbackQueryHandler(show_help_inline, pattern="^show_help$"))

    # Глобальний fallback 'cancel' (ловить /cancel будь-де)
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