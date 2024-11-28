import os
import datetime
from openai import OpenAI
import gspread
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

# Load environment variables
load_dotenv()

# Configuration constants
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME")

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# Google Sheets setup
def setup_google_sheets():
    """
    Set up connection to Google Sheets using service account credentials.
    
    Returns:
        gspread.Worksheet: The first worksheet of the specified Google Sheet
    """
    scope = [
        "https://spreadsheets.google.com/feeds", 
        "https://www.googleapis.com/auth/drive"
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        GOOGLE_CREDENTIALS_FILE, 
        scope
    )
    gspread_client = gspread.authorize(creds)
    return gspread_client.open(GOOGLE_SHEET_NAME).sheet1

# Initialize Google Sheets
sheet = setup_google_sheets()

# Function to generate follow-up question using OpenAI
async def generate_follow_up(user_message):
    """
    Generate a follow-up question based on the user's input using OpenAI's API.
    
    Args:
        user_message (str): The original user message
    
    Returns:
        str: Generated follow-up question
    """
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant. Suggest follow-up questions based on user input."
                },
                {
                    "role": "user",
                    "content": f"Based on this input: '{user_message}', suggest follow-up questions to gather more information."
                }
            ],
            max_tokens=100
        )
        
        # Extract the response text
        follow_up_question = response.choices[0].message.content.strip()
        return follow_up_question

    except Exception as e:
        print(f"Error generating follow-up: {e}")
        return "I'm curious to learn more. Could you tell me more about that?"


# Handle user messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle incoming messages, log them, and generate a follow-up question.
    
    Args:
        update (Update): Telegram update object
        context (ContextTypes.DEFAULT_TYPE): Context for the current conversation
    """
    # Extract message details
    user_message = update.message.text
    chat_id = update.effective_chat.id
    user_name = update.message.from_user.first_name
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Generate a unique interaction ID
    interaction_id = f"{chat_id}-{int(datetime.datetime.now().timestamp())}"

    # Save the initial input to Google Sheets
    try:
        sheet.append_row([interaction_id, user_name, "", user_message, timestamp, "Pending"])
    except Exception as e:
        print(f"Error logging to Google Sheets: {e}")

    # Generate a follow-up question using OpenAI
    follow_up = await generate_follow_up(user_message)

    # Respond to the user with confirmation and a follow-up question
    await context.bot.send_message(
        chat_id=chat_id, 
        text=f"Got it! Here's a follow-up question:\n{follow_up}"
    )


def main():
    """
    Set up and run the Telegram bot application.
    """
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    # Handle plain text messages
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Start the bot
    print("Bot is running. Press Ctrl+C to stop.")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()