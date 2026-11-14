from openai import OpenAI

client = OpenAI(
    base_url="https://api.helmcode.com/v1",
    api_key="sk-hke_E-q0Tp4YzwWLqKUzsb1QUxEpi-3YZnhFptmSGfx5VxY",
)

resp = client.chat.completions.create(
    model="qwen3.6",
    messages=[{"role": "user", "content": "Say hello from the EU."}],
)

print(resp.choices[0].message.content)