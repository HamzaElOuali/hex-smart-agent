from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()
url = os.getenv("DATABASE_URL")
print("Using:", url)
engine = create_engine(url)

with engine.connect() as conn:
    print("Current DB:", conn.execute(text("SELECT current_database()")).scalar_one())
    print("Test query:", conn.execute(text("SELECT 1")).scalar_one())
