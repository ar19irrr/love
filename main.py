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
    
    # ============ همه هندلرها ============
    # ... (همون هندلرهای قبلی رو اینجا اضافه کن)
    
    # ============ چت ============
    # اینو عوض کن به:
    application.add_handler(MessageHandler(filters.ALL, handle_chat_message))
    
    logger.info("Chat bot started!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
