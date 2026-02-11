from openai import AsyncOpenAI
import gradio as gr

messages = [
  {"role": "system", "content": "You are an AI specialized in Movies. Do not answer anything other than movie-related queries."},
]

credentials = ""

async def chatbot(input):
  if input:
    messages.append({"role": "user", "content": input})
    client = AsyncOpenAI(api_key=credentials)
    chat = await client.chat.completions.create(model="gpt-3.5-turbo", messages=messages)
    reply = chat.choices[0].message.content
    messages.append({"role": "assistant", "content": reply})
    return reply

inputs = gr.components.Textbox(lines=7, label="Chat with AI")
outputs = gr.components.Textbox(label="Reply")

gr.Interface(fn=chatbot, inputs=inputs, outputs=outputs, title="MovieAgent",
             description="Ask me anything about movies!",
             theme="default").launch(share=True)