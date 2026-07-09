import os
from dotenv import load_dotenv
load_dotenv()
from groq import Groq
import json

client = Groq(api_key=os.getenv('GROQ_API_KEY'))

prompt = """
Analyze user finances.

Income: 1000
Expenses: {'Food': 200}

Return JSON:

{
"suggestions":"financial advice",
"warnings":"risk alerts",
"savings_tips":"saving ideas"
}
"""

try:
    response=client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role":"system","content":"You are a financial advisor AI. Ensure your response is a valid JSON object."},
            {"role":"user","content":prompt}
        ],
        temperature=0.3,
        response_format={"type": "json_object"}
    )
    print("SUCCESS!")
    print(response.choices[0].message.content)
except Exception as e:
    print("ERROR:")
    print(str(e))
