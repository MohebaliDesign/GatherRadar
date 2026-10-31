"""Telegram update handlers. Authorization runs before any handler and again inside it."""
from __future__ import annotations

import logging

from telegram import BotCommand, BotCommandScopeChat, BotCommandScopeDefault, Update
from telegram.error import BadRequest, Conflict, TelegramError
from telegram.ext import (Application, ApplicationHandlerStop, CallbackQueryHandler, CommandHandler,
                          ContextTypes, TypeHandler)

from . import presentation as ui
from .auth import OwnerPolicy
from .services import PlannedFeature, SourceCatalog
from .settings import TelegramSettings

LOGGER = logging.getLogger('gatherradar.telegram')
OWNER_COMMANDS = (('menu', 'منوی اصلی'), ('sources', 'فهرست منابع'), ('help', 'راهنما'), ('whoami', 'شناسه من'))


class BotHandlers:
    def __init__(self, settings: TelegramSettings, catalog: SourceCatalog) -> None:
        self.settings, self.catalog = settings, catalog
        self.policy = OwnerPolicy(settings.owner_id)

    # -- authorization -------------------------------------------------------
    async def guard(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Group -1: every update. Only the owner (or bootstrap /whoami) passes."""
        if self.policy.is_owner(update) or self._bootstrap_whoami(update):
            return
        LOGGER.warning('telegram_unauthorized_update', extra={
            'user_id': getattr(update.effective_user, 'id', None),
            'chat_type': getattr(update.effective_chat, 'type', None)})
        if update.callback_query is not None:
            await self._safe(update.callback_query.answer(ui.PRIVATE_ONLY, show_alert=False))
        elif update.effective_message is not None and getattr(update.effective_chat, 'type', None) == 'private':
            await self._safe(update.effective_message.reply_text(
                ui.BOOTSTRAP if self.settings.bootstrap else ui.PRIVATE_ONLY))
        raise ApplicationHandlerStop

    def _bootstrap_whoami(self, update: Update) -> bool:
        message = update.effective_message
        text = (message.text or '') if message is not None and update.callback_query is None else ''
        command = text.split(maxsplit=1)[0].split('@', 1)[0] if text.startswith('/') else ''
        return command == '/whoami' and self.policy.may_ask_whoami(update)

    def _owner(self, update: Update) -> bool:
        # Defence in depth: handlers re-check even though the guard ran first.
        return self.policy.is_owner(update)

    # -- commands --------------------------------------------------------------
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if self._owner(update):
            await update.effective_message.reply_html(ui.main_text(), reply_markup=ui.main_keyboard())

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if self._owner(update):
            await update.effective_message.reply_html(ui.help_text(), reply_markup=ui.back_keyboard())

    async def sources(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if self._owner(update):
            views = self.catalog.list()
            await update.effective_message.reply_html(ui.sources_text(views),
                                                      reply_markup=ui.sources_keyboard(views, 0))

    async def whoami(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if self._owner(update) or self.policy.may_ask_whoami(update):
            await update.effective_message.reply_html(
                ui.whoami_text(update.effective_user.id, self.settings.bootstrap))

    # -- callbacks -------------------------------------------------------------
    async def callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None or not self._owner(update):
            return
        action = ui.parse_callback(query.data)
        if action is None:
            await self._safe(query.answer(ui.INVALID))
            return
        if 'soon' in action:
            known = action['soon'] in {feature.value for feature in PlannedFeature}
            await self._safe(query.answer(ui.NOT_YET if known else ui.INVALID, show_alert=known))
            return
        if 'menu' in action:
            text, markup = ui.main_text(), ui.main_keyboard()
        elif 'help' in action:
            text, markup = ui.help_text(), ui.back_keyboard()
        elif 'page' in action:
            views = self.catalog.list()
            text, markup = ui.sources_text(views), ui.sources_keyboard(views, int(action['page']))
        else:
            view = self.catalog.get(action['source'])
            if view is None:  # a forged or stale id never reaches data
                await self._safe(query.answer(ui.INVALID))
                return
            text, markup = ui.source_text(view), ui.source_keyboard()
        await self._safe(query.answer())
        await self._edit(query, text, markup)

    async def _edit(self, query, text, markup) -> None:
        try:
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=markup,
                                          disable_web_page_preview=True)
        except BadRequest as error:
            # A repeated tap re-renders the same content; Telegram refuses that edit.
            if 'not modified' not in str(error).lower():
                raise

    @staticmethod
    async def _safe(awaitable) -> None:
        try:
            await awaitable
        except TelegramError as error:
            # An expired callback query or a transient network failure: logged, not raised.
            LOGGER.warning('telegram_reply_failed: %s', type(error).__name__)

    # -- errors ----------------------------------------------------------------
    async def on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        error = context.error
        if isinstance(error, Conflict):
            LOGGER.error('telegram_polling_conflict: another process is polling this bot; stopping.')
            context.application.stop_running()
            return
        LOGGER.error('telegram_handler_error: %s', type(error).__name__, exc_info=error)
        if isinstance(update, Update) and self.policy.is_owner(update) and update.effective_chat is not None:
            await self._safe(context.bot.send_message(update.effective_chat.id, ui.ERROR))


def register(application: Application, handlers: BotHandlers) -> None:
    application.add_handler(TypeHandler(Update, handlers.guard), group=-1)
    application.add_handler(CommandHandler(['start', 'menu'], handlers.start))
    application.add_handler(CommandHandler('help', handlers.help))
    application.add_handler(CommandHandler('sources', handlers.sources))
    application.add_handler(CommandHandler('whoami', handlers.whoami))
    application.add_handler(CallbackQueryHandler(handlers.callback))
    application.add_error_handler(handlers.on_error)


async def publish_commands(application: Application, settings: TelegramSettings) -> None:
    """Default scope shows only /whoami; the owner's private chat gets the full list."""
    bot = application.bot
    await bot.set_my_commands([BotCommand('whoami', 'شناسه من')], scope=BotCommandScopeDefault())
    if settings.owner_id is not None:
        await bot.set_my_commands([BotCommand(c, d) for c, d in OWNER_COMMANDS],
                                  scope=BotCommandScopeChat(settings.owner_id))
