# main.py
import os
import logging
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from chat_handler import handle_chat_message

TOKEN = os.environ.get('TOKEN')
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    application = Application.builder().token(TOKEN).build()
    
    # ثبت هندلر چت
    application.add_handler(MessageHandler(
        filters.TEXT | filters.PHOTO | filters.Sticker.ALL | filters.ANIMATION, 
        handle_chat_message
    ))
    
    logger.info("Chat bot started!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
