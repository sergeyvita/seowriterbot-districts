import os
import re
import time
from flask import Flask, request, jsonify
from openai import OpenAI
import httpx

# 🔌 Отключаем прокси
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

# 🌐 Клиенты
client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    http_client=httpx.Client()
)
ASSISTANT_ID = os.environ.get("ASSISTANT_ID")

app = Flask(__name__)

@app.route("/generate", methods=["POST"])
def generate():
    try:
        data = request.get_json()
        chunks = data.get("chunks", [])
        if not chunks:
            return jsonify({"error": "Нет чанков"}), 400

        context_text = chunks[0]
        instructions = chunks[1:]

        with open("incoming_chunks_debug.log", "a", encoding="utf-8") as f:
            f.write(f"\n=== Новый запрос от {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            f.write(f"Контекст (первые 1000 символов):\n{context_text[:1000]}\n...\n")
            f.write(f"Инструкций: {len(instructions)}\n")

        # 🧵 Создаём поток один раз
        thread = client.beta.threads.create()

        # 🧠 Отправляем CONTEXT
        client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=context_text
        )

        result_blocks = {
            "element_name": "",
            "meta_title": "",
            "meta_keywords": "",
            "meta_description": "",
            "article_parts": []
        }

        # ⏩ Обработка каждой инструкции
        for i, chunk in enumerate(instructions):
            print(f"📨 Инструкция {i} отправляется...")

            client.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content=chunk
            )

            run = client.beta.threads.runs.create(
                thread_id=thread.id,
                assistant_id=ASSISTANT_ID,
                extra_headers={"OpenAI-Beta": "assistants=v2"}
            )

            while True:
                status = client.beta.threads.runs.retrieve(thread.id, run.id)
                if status.status == "completed":
                    break
                elif status.status == "failed":
                    raise Exception(f"Ошибка выполнения ассистента в инструкции {i}")
                time.sleep(1)

            messages = client.beta.threads.messages.list(thread_id=thread.id)
            content = messages.data[0].content[0].text.value.strip()

            def extract(tag, text):
                m = re.search(rf"==={tag}===\s*(.+?)(?=(?:===|$))", text, re.DOTALL)
                return m.group(1).strip() if m else ""

            if i == 0:
                result_blocks["element_name"] = extract("ELEMENT_NAME", content)
                result_blocks["meta_title"] = extract("META_TITLE", content)
                result_blocks["meta_keywords"] = extract("META_KEYWORDS", content)
                result_blocks["meta_description"] = extract("META_DESCRIPTION", content)
                result_blocks["article_parts"].append(extract("ARTICLE", content))
            else:
                result_blocks["article_parts"].append(extract("ARTICLE", content))

            time.sleep(3)

        article = "\n\n".join(result_blocks["article_parts"])

        with open("render_debug.log", "a", encoding="utf-8") as f:
            f.write(f"\n=== [{time.strftime('%Y-%m-%d %H:%M:%S')}] ===\n")
            f.write(f"NAME: {result_blocks['element_name']}\n")
            f.write(f"META TITLE: {result_blocks['meta_title']}\n")
            f.write(f"ARTICLE (start):\n{article[:1000]}...\n")

        return jsonify({
            "element_name": result_blocks["element_name"],
            "meta_title": result_blocks["meta_title"],
            "meta_keywords": result_blocks["meta_keywords"],
            "meta_description": result_blocks["meta_description"],
            "article": article
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    print("🟢 Flask запущен")
    app.run(host="0.0.0.0", port=10000)
