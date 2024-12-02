import os
import datetime
import dateparser
import anthropic
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
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME")

# Initialize Anthropic client
client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

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
CONTEXT, MISSING_INFO, END = range(3)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Start the conversation and ask for context.
    """
    context.user_data['ID'] = f"{update.effective_chat.id}-{int(datetime.datetime.now().timestamp())}"
    await update.message.reply_text("Hi! Please tell me about the person you met.")
    return CONTEXT

async def extract_fields_from_context(context_message):
    """
    Use Claude to extract Name, Timestamp, and Context from the context message.
    """
    prompt = f"""[
        {{
            "type": "text",
            "text": "<examples>\\n<example>\\n<example_description>\\n<analysis>\\n1. Name: The context message mentions \\"Alice Johnson\\".\\n2. Timestamp: The message states \\"yesterday\\" and mentions \\"boston\\". We'll use this location information to determine the correct date.\\n3. Location: The interaction occurred at the \\"startup boston conference\\", so the location is Boston, MA.\\n4. Context: The message provides details about a discussion on potential collaboration and Alice's interest in solar energy.\\n5. Contact Info: An email address is provided: alice.johnson@example.com.\\n\\nAnalyzing the location and timestamp:\\nThe message mentions \\"boston\\", which refers to Boston, MA, USA. Since the interaction happened \\"yesterday\\" in Boston, we need to calculate the date based on the current date in Boston's time zone (Eastern Time). Assuming the current date is December 1, 2024, \\"yesterday\\" would be November 30, 2024.\\n\\nSummarizing the key points for the Context field:\\nThe interaction involved discussing potential collaboration on a new project. Additionally, Alice expressed interest in solar energy and mentioned having an uncle in the industry.\\n\\nMissing or unclear information:\\nThe context message doesn't provide any phone number or additional contact information beyond the email address.\\n</analysis>\\n</example_description>\\n<context_message>\\nI met Alice Johnson yesterday at the startup boston conference. We discussed potential collaboration on a new project and she mentioned something about how he was really interested in solar and had an uncle in the industry. Her email is alice.johnson@example.com.\\n</context_message>\\n<ideal_output>\\n{{\\n  \\"Name\\": \\"Alice Johnson\\",\\n  \\"Timestamp\\": \\"2024-11-30\\",\\n  \\"Location\\": \\"Boston, MA\\",\\n  \\"Context\\": \\"Discussed potential collaboration on a new project. Interested in solar energy and has an uncle in the industry.\\",\\n  \\"Contact Info\\": \\"alice.johnson@example.com\\"\\n}}\\n</ideal_output>\\n</example>\\n</examples>\\n\\n"
        }},
        {{
            "type": "text",
            "text": {context_message}
        }}
    ]
"""

    try:
        response = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=1000,
            temperature=0,
            tools=[
                {
                    "name": "extract_data",
                    "description": "Record detailed rolodex-styled summary of user messages using well-structured JSON.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Name of main person of topic in the user message or 'None' if not provided",
                            },
                            "context": {
                                "type": "string",
                                "description": "Short hand summary of context of the user's message",
                            },
                            "location": {
                                "type": "string",
                                "description": "Location mentioned in user message or 'None' if not provided",
                            },
                            "timestamp": {
                                "type": "string",
                                "description": "Timestamp mentioned in user message based on time expression or 'None' if not provided",
                            },
                            "contact_info": {
                                "type": "string",
                                "description": "Contact information mentioned in user message or 'None' if not provided",
                            },
                        },
                        "required": ["context"],
                    },
                }
            ],
            tool_choice={"type": "tool", "name": "extract_data"},
            system="You are an AI assistant designed to extract key details from a given context message and populate a virtual rolodex. Your task is to analyze the provided message and return a structured JSON object containing relevant information.\n\nHere is the context message you need to analyze:\n\n<context_message>\n{{context_message}}\n</context_message>\n\nPlease extract the following information from the context message and organize it into a JSON object:\n\n1. Name: The full name of the person mentioned in the context.\n2. Timestamp: The time or date when the interaction occurred. If an exact date is not provided, infer it based on time expressions like \"yesterday\" or \"last week\". Use any location information provided in the message to determine the correct date.\n3. Location: The place where the interaction occurred or where the person is located.\n4. Context: A brief summary of the conversation or relevant details about the interaction.\n5. Contact Info: Any contact information provided, such as email address or phone number.\n\nBefore providing the final JSON output, wrap your analysis process inside <analysis> tags. This will help ensure a thorough interpretation of the data.\n\nIn your analysis process:\n1. For each field (Name, Timestamp, Location, Context, and Contact Info), quote the relevant information from the context message.\n2. Analyze any location information provided and explain how you'll use it to determine the correct timestamp.\n3. Summarize the key points of the interaction for the Context field.\n4. Note any information that is missing or unclear in the context message.\n\nAfter your analysis, provide the final JSON output with the extracted information.\n\nOutput Format:\nThe JSON object should have the following structure:\n\n{\n  \"Name\": \"\",\n  \"Timestamp\": \"\",\n  \"Location\": \"\",\n  \"Context\": \"\",\n  \"Contact Info\": \"\"\n}\n\nPlease proceed with your analysis and provide the only the JSON output for the given context message.",
            messages=[{'role': 'user', 'content': prompt}]
        )
        response_text = response.content
        #extracted_data = json.loads(response_text)
        # Extract the JSON-like object
        if isinstance(response_text, list) and len(response_text) > 0:
            tool_block = response_text[0]  # Access the first ToolUseBlock
            if hasattr(tool_block, 'input'):
                extracted_data = tool_block.input  # Extract the 'input' field
                return extracted_data
            else:
                print("ToolUseBlock does not have an 'input' field.")
                return {}
        else:
            print("Invalid response format.")
            return {}
    except Exception as e:
        print(f"Error parsing Claude response: {e}")
        return {}

async def context_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Save the context provided by the user and attempt to extract fields.
    """
    context_message = update.message.text
    extracted_data = await extract_fields_from_context(context_message)
    print(f"Extracted data: {extracted_data}")
    # Save whatever data was extracted
    context.user_data['Context'] = extracted_data.get('context', context_message)
    context.user_data['Name'] = extracted_data.get('name', '')
    context.user_data['Timestamp'] = extracted_data.get('timestamp', '')
    context.user_data['Contact_Info'] = extracted_data.get('contact_info', '')
    context.user_data['Follow-Up Status'] = 'Pending'

    missing_fields = []
    if not context.user_data['Name']:
        missing_fields.append('Name')
    if not context.user_data['Timestamp']:
        missing_fields.append('Timestamp')
    if not context.user_data['Contact_Info']:
        missing_fields.append('Contact_Info')

    if missing_fields:
        # Ask for missing information
        missing_str = ' and '.join(missing_fields)
        await update.message.reply_text(f"I couldn't find the {missing_str} in your message. Could you please provide it?")
        return MISSING_INFO
    else:
        # All fields are present, save to Google Sheets
        try:
            sheet.append_row([
                context.user_data['ID'],
                context.user_data['Name'],
                context.user_data['Context'],
                context.user_data['Timestamp'],
                context.user_data['Contact_Info'],
                context.user_data['Follow-Up Status']
            ])
            await update.message.reply_text("Thank you! Your information has been saved.")
        except Exception as e:
            print(f"Error logging to Google Sheets: {e}")
            await update.message.reply_text("There was an error saving your information.")
        return ConversationHandler.END

async def missing_info_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Save missing information provided by the user, including contact info.
    """
    user_reply = update.message.text

    # Check which fields are missing
    missing_fields = [key for key in ['Name', 'Timestamp', 'Contact_Info'] 
                     if not context.user_data.get(key)]
    
    # Attempt to extract missing fields from user's reply
    # Update context.user_data with any found information
    for field in missing_fields:
        if field in user_reply:
            context.user_data[field] = user_reply  # Add more sophisticated extraction as needed
    
    # Check if we still have missing fields
    still_missing = [key for key in ['Name', 'Timestamp', 'Contact_Info'] 
                    if not context.user_data.get(key)]
    
    if still_missing:
        # Ask for next missing field
        await update.message.reply_text(f"Please provide the {still_missing[0]}")
        return MISSING_INFO
    
    # All information collected, save to Google Sheets
    try:
        sheet.append_row([
            context.user_data['ID'],
            context.user_data['Name'],
            context.user_data['Context'],
            context.user_data['Timestamp'],
            context.user_data['Contact_Info'],
            context.user_data['Follow-Up Status']
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
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    application.add_handler(conv_handler)
    print("Bot is running. Press Ctrl+C to stop.")
    application.run_polling()

if __name__ == "__main__":
    main()