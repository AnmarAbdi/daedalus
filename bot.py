import os
import datetime
import dateparser
from openai import OpenAI
import gspread
import json
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes, ConversationHandler,
    MessageHandler, filters
)
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

# Define conversation states
CONTEXT, MISSING_INFO, CONTACT_INFO, END = range(4)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Start the conversation and ask for context.
    """
    context.user_data['ID'] = f"{update.effective_chat.id}-{int(datetime.datetime.now().timestamp())}"
    await update.message.reply_text("Hi! Please tell me about the person you met.")
    return CONTEXT

async def extract_fields_from_context(context_message):
    """
    Use OpenAI to extract Name, Timestamp, and Context from the context message.
    """
    prompt = f"""Extract the following fields from the user's message:

- Name of the person met
- Time expression when they met (as mentioned by the user, e.g., 'last night', 'yesterday')
- Context (any additional details)

User's message:
\"\"\"
{context_message}
\"\"\"

Provide the extracted information in JSON format like:
{{
  "Name": "Name of the person",
  "Timestamp": "Time expression",
  "Context": "Additional details"
}}
If any field is missing, leave it empty like "Name": "".
"""

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{'role': 'user', 'content': prompt}],
            max_tokens=150,
            temperature=0,
        )
        response_text = response.choices[0].message.content.strip()
        extracted_data = json.loads(response_text)
        return extracted_data
    except Exception as e:
        print(f"Error parsing OpenAI response: {e}")
        return {}

async def context_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Save the context provided by the user and attempt to extract fields.
    """
    context_message = update.message.text
    extracted_data = await extract_fields_from_context(context_message)

    # Save whatever data was extracted
    context.user_data['Context'] = extracted_data.get('Context', context_message)
    context.user_data['Name'] = extracted_data.get('Name', '')
    context.user_data['Timestamp'] = extracted_data.get('Timestamp', '')

    missing_fields = []
    if not context.user_data['Name']:
        missing_fields.append('Name')
    if not context.user_data['Timestamp']:
        missing_fields.append('Timestamp')

    if missing_fields:
        # Ask for missing information
        missing_str = ' and '.join(missing_fields)
        await update.message.reply_text(f"I couldn't find the {missing_str} in your message. Could you please provide it?")
        return MISSING_INFO
    else:
        await update.message.reply_text("Do you have any contact information for this person?")
        return CONTACT_INFO

async def missing_info_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Save missing information provided by the user.
    """
    user_reply = update.message.text

    # Attempt to extract missing fields from user's reply
    prompt = f"""Given the user's reply, extract any missing information:

Missing fields: {', '.join([key for key in ['Name', 'Timestamp'] if not context.user_data.get(key)])}

User's reply:
\"\"\"
{user_reply}
\"\"\"

Provide the extracted information in JSON format like:
{{
  "Name": "Name of the person",
  "Timestamp": "YYYY-MM-DD"
}}
If any field is still missing, leave it empty.
"""
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{'role': 'user', 'content': prompt}],
            max_tokens=100,
            temperature=0,
        )
        response_text = response.choices[0].message.content.strip()
        extracted_data = json.loads(response_text)
        # Update context with any new data
        for key in ['Name', 'Timestamp']:
            if extracted_data.get(key):
                context.user_data[key] = extracted_data[key]
    except Exception as e:
        print(f"Error parsing OpenAI response: {e}")

    # Check again for any missing fields
    missing_fields = []
    if not context.user_data['Name']:
        missing_fields.append('Name')
    if not context.user_data['Timestamp']:
        missing_fields.append('Timestamp')

    if missing_fields:
        # If still missing information, ask again
        missing_str = ' and '.join(missing_fields)
        await update.message.reply_text(f"Sorry, I still need the {missing_str}. Could you please provide it?")
        return MISSING_INFO
    else:
        await update.message.reply_text("Do you have any contact information for this person?")
        return CONTACT_INFO

async def contact_info_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Save the contact info and finish the conversation.
    """
    context.user_data['Contact Info'] = update.message.text
    context.user_data['Follow-Up Status'] = "Pending"

    # Parse Timestamp to ensure it's a valid date
    timestamp_str = context.user_data['Timestamp']
    parsed_date = dateparser.parse(timestamp_str, settings={'RELATIVE_BASE': datetime.datetime.now()})
    if parsed_date:
        context.user_data['Timestamp'] = parsed_date.strftime('%Y-%m-%d')
    else:
        # If parsing fails, default to the current date
        context.user_data['Timestamp'] = datetime.datetime.now().strftime('%Y-%m-%d')

    # Save data to Google Sheets
    data = context.user_data
    try:
        sheet.append_row([
            data['ID'],
            data['Name'],
            data['Context'],
            data['Timestamp'],
            data['Contact Info'],
            data['Follow-Up Status']
        ])
        await update.message.reply_text("Thank you! Your information has been saved.")
    except Exception as e:
        print(f"Error logging to Google Sheets: {e}")
        await update.message.reply_text("There was an error saving your information.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Cancel the conversation.
    """
    await update.message.reply_text("Conversation cancelled.")
    return ConversationHandler.END

def main():
    """
    Set up and run the Telegram bot application.
    """
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, start)],
        states={
            CONTEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, context_state)],
            MISSING_INFO: [MessageHandler(filters.TEXT & ~filters.COMMAND, missing_info_state)],
            CONTACT_INFO: [MessageHandler(filters.TEXT & ~filters.COMMAND, contact_info_state)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    application.add_handler(conv_handler)
    print("Bot is running. Press Ctrl+C to stop.")
    application.run_polling()

if __name__ == "__main__":
    main()