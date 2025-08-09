from dotenv import load_dotenv
import os
import re
import time
from datetime import datetime, timedelta
from dateutil.parser import parse
from supabase import create_client, Client
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.memory import ConversationBufferMemory
from langchain.chains import ConversationChain

# ---------------------- Setup ----------------------
load_dotenv()
groq_api_key = os.getenv("GROQ_API_KEY")
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")

if not groq_api_key:
    raise ValueError("GROQ_API_KEY not found in .env file")
if not supabase_url or not supabase_key:
    raise ValueError("SUPABASE_URL or SUPABASE_KEY not found in .env file")

# ---------------------- Supabase Setup ----------------------
print("\nInitializing Supabase connection...")
try:
    supabase: Client = create_client(supabase_url, supabase_key)
    print("✅ Supabase client created")
except Exception as e:
    print(f"❌ Failed to create Supabase client: {str(e)}")
    exit(1)

# ---------------------- Helper Functions ----------------------
def parse_date(date_str: str) -> str:
    """Parse various date formats and return ISO format"""
    try:
        # Handle relative dates
        date_str_lower = date_str.lower()
        if 'today' in date_str_lower:
            return datetime.now().strftime('%Y-%m-%d %H:%M:%S+00:00')
        elif 'tomorrow' in date_str_lower:
            return (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S+00:00')
        elif 'next week' in date_str_lower:
            return (datetime.now() + timedelta(weeks=1)).strftime('%Y-%m-%d %H:%M:%S+00:00')
        elif 'next month' in date_str_lower:
            return (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S+00:00')
        
        # Try to parse the date
        parsed_date = parse(date_str)
        # If no time specified, set to 9 AM
        if parsed_date.time() == datetime.min.time():
            parsed_date = parsed_date.replace(hour=9)
        
        return parsed_date.strftime('%Y-%m-%d %H:%M:%S+00:00')
    except:
        # Default to tomorrow if parsing fails
        return (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S+00:00')

def extract_reminder_info(text: str) -> dict:
    """Extract reminder information from natural language text"""
    info = {
        "title": None,
        "amount": 0,
        "due_date": None,
        "category": None,
        "recurrence": None,
        "custom_recurrence_days": None
    }
    
    # Extract amount (look for $X or amount X)
    amount_patterns = [
        r'\$(\d+(?:\.\d{2})?)',  # $100 or $100.50
        r'amount\s+(?:of\s+)?\$?(\d+(?:\.\d{2})?)',  # amount of $100
        r'(\d+(?:\.\d{2})?)\s*dollars?',  # 100 dollars
        r'pay\s+\$?(\d+(?:\.\d{2})?)',  # pay $100
    ]
    
    for pattern in amount_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                info["amount"] = float(match.group(1))
                break
            except ValueError:
                continue
    
    # Extract date information
    date_patterns = [
        r'(?:on|by|due)\s+((?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}(?:,?\s+\d{4})?)',
        r'(?:on|by|due)\s+(\d{1,2}[-/]\d{1,2}(?:[-/]\d{2,4})?)',
        r'(?:on|by|due)\s+(\d{4}-\d{1,2}-\d{1,2})',
        r'(tomorrow|today|next\s+week|next\s+month)',
        r'(?:in\s+)?(\d+)\s+days?',
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            date_str = match.group(1)
            if re.match(r'\d+', date_str):  # Handle "in X days"
                days = int(date_str)
                info["due_date"] = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S+00:00')
            else:
                info["due_date"] = parse_date(date_str)
            break
    
    # If no date found, default to tomorrow
    if not info["due_date"]:
        info["due_date"] = parse_date("tomorrow")
    
    # Extract category
    category_patterns = [
        r'(?:for|category)\s+(rent|electricity|water|gas|credit\s+card|loan|mortgage|insurance|subscription|phone|internet)',
        r'(rent|electricity|water|gas|credit\s+card|loan|mortgage|insurance|subscription|phone|internet)\s+(?:payment|bill)'
    ]
    
    for pattern in category_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            info["category"] = match.group(1).replace(" ", "_")
            break
    
    # Extract recurrence
    recurrence_patterns = [
        r'(weekly|monthly|yearly|daily)\s+(?:reminder|payment)',
        r'(?:every|repeat)\s+(\d+)\s+(days?|weeks?|months?|years?)'
    ]
    
    for pattern in recurrence_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            if match.group(1) in ['weekly', 'monthly', 'yearly', 'daily']:
                info["recurrence"] = match.group(1)
            else:
                info["custom_recurrence_days"] = int(match.group(1))
                if 'day' in match.group(2):
                    info["recurrence"] = "custom"
                elif 'week' in match.group(2):
                    info["custom_recurrence_days"] *= 7
                    info["recurrence"] = "custom"
                elif 'month' in match.group(2):
                    info["custom_recurrence_days"] *= 30
                    info["recurrence"] = "custom"
                elif 'year' in match.group(2):
                    info["custom_recurrence_days"] *= 365
                    info["recurrence"] = "custom"
            break
    
    # Extract the title (everything except amount, date, and category references)
    title_text = text
    # Remove common command words
    title_text = re.sub(r'\b(?:create|add|set|new|reminder|for|to|pay|payment|bill)\b', '', title_text, flags=re.IGNORECASE)
    # Remove amount references
    title_text = re.sub(r'\$?\d+(?:\.\d{2})?\s*(?:dollars?)?', '', title_text)
    # Remove date references
    title_text = re.sub(r'\b(?:on|by|due|tomorrow|today|next\s+week|next\s+month)\b.*', '', title_text, flags=re.IGNORECASE)
    title_text = re.sub(r'\d{1,2}[-/]\d{1,2}(?:[-/]\d{2,4})?', '', title_text)
    title_text = re.sub(r'(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}(?:,?\s+\d{4})?', '', title_text, flags=re.IGNORECASE)
    title_text = re.sub(r'in\s+\d+\s+days?', '', title_text, flags=re.IGNORECASE)
    # Remove category references
    if info["category"]:
        title_text = re.sub(info["category"].replace("_", " "), '', title_text, flags=re.IGNORECASE)
    
    # Clean up the title
    title_text = re.sub(r'\s+', ' ', title_text).strip()
    title_text = title_text.strip('.,!?')
    
    if title_text:
        info["title"] = title_text
    else:
        # Default title based on category if available
        info["title"] = info["category"].replace("_", " ").title() + " Payment" if info["category"] else "Payment Reminder"
    
    return info

def parse_reminder_request(user_input: str) -> dict:
    """Parse user input for reminder commands"""
    try:
        user_input_lower = user_input.lower()
        
        # Enhanced delete patterns
        delete_patterns = [
            r'(?:delete|remove|cancel)\s+reminder(?:\s*:\s*|\s+)(.+)',
            r'(?:delete|remove|cancel)\s+(.+?)(?:\s+reminder)?$',
            r'remove\s+(.+)',
            r'cancel\s+(.+)',
        ]
        
        for pattern in delete_patterns:
            delete_match = re.search(pattern, user_input_lower)
            if delete_match:
                title = delete_match.group(1).strip()
                title = re.sub(r'\b(?:reminder|the|my)\b', '', title).strip()
                if title:
                    return {"action": "delete", "title": title}
                break
        
        # Check for list commands
        if any(cmd in user_input_lower for cmd in ["list reminders", "show reminders", "my reminders", "view reminders"]):
            return {"action": "list"}
        
        # Check for mark as done
        if any(cmd in user_input_lower for cmd in ["mark as done", "complete reminder", "payment done"]):
            mark_match = re.search(r'(?:mark|complete)\s+(.+?)(?:\s+as\s+done)?$', user_input_lower)
            if mark_match:
                title = mark_match.group(1).strip()
                title = re.sub(r'\b(?:reminder|the|my)\b', '', title).strip()
                if title:
                    return {"action": "mark_done", "title": title}
        
        # Check for create command patterns
        create_patterns = [
            r'(?:create|add|set|new)\s+reminder\s+(.+)',
            r'remind\s+me\s+(?:to\s+)?(.+)',
            r'set\s+(?:a\s+)?reminder\s+(.+)',
            r'add\s+reminder\s+(.+)',
        ]
        
        for pattern in create_patterns:
            match = re.search(pattern, user_input, re.IGNORECASE)
            if match:
                reminder_text = match.group(1)
                info = extract_reminder_info(reminder_text)
                return {
                    "action": "create",
                    "title": info["title"],
                    "amount": info["amount"],
                    "due_date": info["due_date"],
                    "category": info["category"],
                    "recurrence": info["recurrence"],
                    "custom_recurrence_days": info["custom_recurrence_days"]
                }
        
        return {"action": "none"}
    
    except Exception as e:
        print(f"Debug - parsing error: {str(e)}")
        return {"action": "none"}

# ---------------------- Reminder Functions ----------------------
def create_reminder(title: str, due_date: str, amount: float = 0, category: str = None, recurrence: str = None, custom_recurrence_days: int = None) -> dict:
    """Create reminder with given details"""
    try:
        reminder_data = {
            "title": title.strip(),
            "due_date": due_date,
            "amount": float(amount),
            "category": category,
            "recurrence": recurrence,
            "custom_recurrence_days": custom_recurrence_days,
            "is_done": False
        }
        
        # Remove None values
        reminder_data = {k: v for k, v in reminder_data.items() if v is not None}
        
        result = supabase.table("payment_reminders").insert(reminder_data).execute()
        
        if result.data:
            return {
                "success": True,
                "data": result.data[0],
                "message": f"✅ Reminder created successfully!"
            }
        return {"success": False, "message": "Failed to create reminder"}
    except Exception as e:
        return {"success": False, "message": f"Database error: {str(e)}"}

def list_reminders(show_all: bool = False) -> dict:
    """List reminders from Supabase"""
    try:
        query = supabase.table("payment_reminders").select("*")
        
        if not show_all:
            query = query.eq("is_done", False)
            
        result = query.order("due_date").execute()
        
        return {"success": True, "data": result.data} if result.data else {"success": True, "data": []}
    except Exception as e:
        return {"success": False, "message": f"Database error: {str(e)}"}

def delete_reminder(reminder_id: str = None, title: str = None) -> dict:
    """Delete a reminder by ID or title"""
    try:
        if reminder_id:
            result = supabase.table("payment_reminders").delete().eq("id", reminder_id).execute()
            return {
                "success": bool(result.data), 
                "message": f"Reminder deleted successfully!" if result.data else f"No reminder found with ID {reminder_id}",
                "deleted_count": len(result.data) if result.data else 0
            }
        elif title:
            search_result = supabase.table("payment_reminders").select("*").ilike("title", f"%{title}%").execute()
            
            if not search_result.data:
                search_result = supabase.table("payment_reminders").select("*").eq("title", title).execute()
            
            if not search_result.data:
                all_reminders = supabase.table("payment_reminders").select("title").execute()
                if all_reminders.data:
                    reminder_titles = [r['title'].lower() for r in all_reminders.data]
                    suggestions = [title for title in reminder_titles if any(word in title for word in title.split())]
                    
                    if suggestions:
                        return {
                            "success": False, 
                            "message": f"No reminder found matching '{title}'. Did you mean: {', '.join(suggestions[:3])}?"
                        }
                
                return {"success": False, "message": f"No reminder found matching '{title}'"}
            
            result = supabase.table("payment_reminders").delete().ilike("title", f"%{title}%").execute()
            
            if not result.data:
                result = supabase.table("payment_reminders").delete().eq("title", title).execute()
            
            deleted_count = len(result.data) if result.data else 0
            
            if deleted_count > 0:
                if deleted_count == 1:
                    deleted_title = result.data[0]['title']
                    return {
                        "success": True, 
                        "message": f"✅ Reminder '{deleted_title}' deleted successfully!",
                        "deleted_count": deleted_count
                    }
                else:
                    return {
                        "success": True, 
                        "message": f"✅ {deleted_count} reminders matching '{title}' deleted successfully!",
                        "deleted_count": deleted_count
                    }
            else:
                return {"success": False, "message": f"Failed to delete reminder matching '{title}'"}
                
        else:
            return {"success": False, "message": "Please specify which reminder to delete by title or ID"}
            
    except Exception as e:
        return {"success": False, "message": f"Database error: {str(e)}"}

def mark_reminder_done(reminder_id: str = None, title: str = None) -> dict:
    """Mark a reminder as done"""
    try:
        if reminder_id:
            result = supabase.table("payment_reminders").update({"is_done": True}).eq("id", reminder_id).execute()
            return {
                "success": bool(result.data),
                "message": f"Reminder marked as done!" if result.data else f"No reminder found with ID {reminder_id}"
            }
        elif title:
            result = supabase.table("payment_reminders").update({"is_done": True}).ilike("title", f"%{title}%").execute()
            
            if not result.data:
                result = supabase.table("payment_reminders").update({"is_done": True}).eq("title", title).execute()
            
            if result.data:
                if len(result.data) == 1:
                    return {
                        "success": True,
                        "message": f"✅ Reminder '{result.data[0]['title']}' marked as done!"
                    }
                else:
                    return {
                        "success": True,
                        "message": f"✅ {len(result.data)} reminders marked as done!"
                    }
            else:
                return {"success": False, "message": f"No reminder found matching '{title}'"}
        else:
            return {"success": False, "message": "Please specify which reminder to mark as done"}
    except Exception as e:
        return {"success": False, "message": f"Database error: {str(e)}"}

# ---------------------- Finance Configuration ----------------------
finance_persona = """You are a helpful financial advisor with reminder management capabilities. You can:

1. Provide financial advice on budgeting, saving, investments, and debt management
2. Create payment reminders from natural language
3. List, delete, and mark reminders as done

When users want to manage reminders, acknowledge their request positively and let the system handle the technical details.

Key reminder fields in our system:
- Title: Short description (e.g., "Electricity Bill")
- Amount: Payment amount
- Due Date: When payment is due
- Category: Type of payment (rent, utilities, etc.)
- Recurrence: For repeating payments

Always be helpful, clear, and encouraging about financial management."""

# ---------------------- Memory Setup ----------------------
memory = ConversationBufferMemory(
    memory_key="history",
    return_messages=True,
    human_prefix="Client",
    ai_prefix="Advisor"
)

# ---------------------- LLM Setup ----------------------
llm = ChatGroq(
    temperature=0.3,
    model_name="llama3-8b-8192",
    groq_api_key=groq_api_key
)

# ---------------------- Conversation Setup ----------------------
prompt = ChatPromptTemplate.from_messages([
    ("system", finance_persona),
    MessagesPlaceholder(variable_name="history"),
    ("human", "{input}"),
])

conversation = ConversationChain(
    llm=llm,
    prompt=prompt,
    memory=memory,
    verbose=False
)

# ---------------------- Main Chat Function ----------------------
def financial_chat(user_input: str) -> str:
    try:
        reminder_request = parse_reminder_request(user_input)
        
        if reminder_request["action"] == "create":
            result = create_reminder(
                title=reminder_request["title"],
                due_date=reminder_request["due_date"],
                amount=reminder_request["amount"],
                category=reminder_request["category"],
                recurrence=reminder_request["recurrence"],
                custom_recurrence_days=reminder_request["custom_recurrence_days"]
            )
            if result["success"]:
                reminder = result["data"]
                due_display = datetime.fromisoformat(reminder['due_date'].replace('+00:00', '')).strftime('%b %d, %Y %I:%M %p')
                response = [
                    f"✅ {result['message']}",
                    f"📝 Title: {reminder['title']}",
                    f"📅 Due: {due_display}",
                    f"💰 Amount: ${reminder['amount']:.2f}",
                ]
                
                if reminder['category']:
                    response.append(f"🏷️ Category: {reminder['category'].replace('_', ' ').title()}")
                
                if reminder['recurrence']:
                    if reminder['recurrence'] == 'custom':
                        response.append(f"🔄 Repeats every {reminder['custom_recurrence_days']} days")
                    else:
                        response.append(f"🔄 Repeats {reminder['recurrence']}")
                
                response.append("\nIs there anything else I can help you with?")
                return "\n".join(response)
            else:
                return f"❌ {result['message']} Please try again with a different format."
        
        elif reminder_request["action"] == "delete":
            result = delete_reminder(title=reminder_request["title"])
            if result["success"]:
                return f"✅ {result['message']}\n\nIs there anything else I can help you with?"
            else:
                return f"❌ {result['message']}\n\nWould you like me to show you your current reminders?"
        
        elif reminder_request["action"] == "mark_done":
            result = mark_reminder_done(title=reminder_request["title"])
            if result["success"]:
                return f"✅ {result['message']}\n\nIs there anything else I can help you with?"
            else:
                return f"❌ {result['message']}\n\nWould you like me to show you your pending reminders?"
        
        elif reminder_request["action"] == "list":
            show_all = "all" in user_input.lower() or "completed" in user_input.lower()
            result = list_reminders(show_all=show_all)
            
            if not result["success"]:
                return f"❌ {result['message']}"
                
            if not result["data"]:
                return "📋 You don't have any reminders set up yet. Would you like to create one?"
                
            reminders = []
            for idx, r in enumerate(result["data"]):
                due_display = datetime.fromisoformat(r['due_date'].replace('+00:00', '')).strftime('%b %d, %Y %I:%M %p')
                status = "✅ Done" if r['is_done'] else "🟡 Pending"
                reminder_str = [
                    f"{idx+1}. {status} - 📝 {r['title']}",
                    f"   📅 Due: {due_display}",
                    f"   💰 Amount: ${r['amount']:.2f}",
                ]
                
                if r['category']:
                    reminder_str.append(f"   🏷️ Category: {r['category'].replace('_', ' ').title()}")
                
                if r['recurrence']:
                    if r['recurrence'] == 'custom':
                        reminder_str.append(f"   🔄 Repeats every {r['custom_recurrence_days']} days")
                    else:
                        reminder_str.append(f"   🔄 Repeats {r['recurrence']}")
                
                reminders.append("\n".join(reminder_str))
                
            header = "📋 Your Reminders" + (" (including completed)" if show_all else " (pending only)")
            return header + "\n\n" + "\n\n".join(reminders)
        
        # Normal financial conversation
        response = conversation.invoke({"input": user_input})
        return response["response"]
        
    except Exception as e:
        return f"⚠️ I encountered an error: {str(e)}\nPlease try again or rephrase your request."

# ---------------------- Main Execution ----------------------
if __name__ == "__main__":
    print("\n💰 Financial Advisor with Smart Reminder Management")
    print("="*55)
    print("Hi! I'm your financial advisor. I can help with:")
    print("• Financial advice and planning")
    print("• Creating and managing payment reminders")
    print("\n💡 Example commands:")
    print("- 'Create reminder to pay electricity bill $150 by August 15'")
    print("- 'Mark rent payment as done'")  
    print("- 'List all reminders'")
    print("- 'Delete my Netflix subscription reminder'")
    print("\nType 'exit' to quit\n")
    
    while True:
        try:
            user_input = input("You: ")
            if user_input.lower() in ['exit', 'quit']:
                print("\nThank you for using our financial services. Have a great day!")
                break
                
            response = financial_chat(user_input)
            print(f"\nAdvisor: {response}\n")
            
        except KeyboardInterrupt:
            print("\nSession ended. Your reminders are saved in the database.")
            break
        except Exception as e:
            print(f"\nError: {str(e)}\n")