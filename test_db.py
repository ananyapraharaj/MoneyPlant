from dotenv import load_dotenv
import os
from supabase import create_client, Client

# Load environment variables
load_dotenv()
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")

print(f"Supabase URL: {supabase_url}")
print(f"Supabase Key: {supabase_key[:20]}..." if supabase_key else "No key found")

try:
    # Create Supabase client
    supabase: Client = create_client(supabase_url, supabase_key)
    print("✅ Supabase client created successfully")
    
    # Test connection by trying to list tables or check reminders table
    print("Testing database connection...")
    
    # Try to select from reminders table
    result = supabase.table("reminders").select("*").limit(1).execute()
    print("✅ Successfully connected to reminders table")
    print(f"Current reminders count: {len(result.data) if result.data else 0}")
    
except Exception as e:
    print(f"❌ Database connection error: {str(e)}")
    print(f"Error type: {type(e).__name__}")
    
    # Check if it's a table not found error
    if "relation" in str(e).lower() and "does not exist" in str(e).lower():
        print("\n🔧 The 'reminders' table doesn't exist in your database.")
        print("You need to create it with the following SQL:")
        print("""
CREATE TABLE reminders (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    due_date TIMESTAMP WITH TIME ZONE,
    completed BOOLEAN DEFAULT FALSE
);
        """)
