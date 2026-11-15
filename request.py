from openai import OpenAI
import os
from dotenv import load_dotenv

# Carga las variables del archivo .env
load_dotenv()

client = OpenAI(
    base_url="https://api.helmcode.com/v1",
    api_key=os.getenv("RAWTREE_API_KEY"),
)

resp = client.chat.completions.create(
    model="qwen3.6",
    messages=[{"role": "user", "content": "Say hello to EU"}],
)

print(resp.choices[0].message.content)
