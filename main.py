# main.py
import os
import json
import time
import re
from flask import Flask, request, jsonify
from openai import OpenAI
import httpx

# Убираем системные прокси
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)

# Инициализируем клиентов
client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    http_client=httpx.Client()
)

ASSISTANT_ID = os.environ.get("ASSISTANT_ID")
app = Flask(__name__)

@app.route("/generate", methods=["POST"])
def generate():
    try:
        print("📥 Запрос на /generate")

        prompt = request.form.get("prompt", "").strip()
        delete_after = request.form.get("delete_after", "true").lower() == "true"

        if 'context_file' not in request.files:
            return jsonify({"error": "context_file не передан"}), 400

        uploaded_file = request.files['context_file']
        if uploaded_file.filename == "":
            return jsonify({"error": "Пустое имя файла"}), 400

        # Сохраняем файл временно
        temp_path = f"/tmp/{int(time.time())}_{uploaded_file.filename}"
        uploaded_file.save(temp_path)

        # Загружаем файл на OpenAI
        with open(temp_path, "rb") as f:
            file_response = client.files.create(file=f, purpose="assistants")

        file_id = file_response.id
        print(f"📎 Файл загружен: {file_id}")
        os.remove(temp_path)

        # Создаем thread
        thread = client.beta.threads.create()
        print(f"🧵 Thread создан: {thread.id}")

        # Отправляем сообщение с prompt и прикреплённым файлом
        client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=prompt,
            attachments=[{"file_id": file_id}]
        )

        # Запускаем ассистента (без file_ids!)
        run = client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=ASSISTANT_ID,
            extra_headers={"OpenAI-Beta": "assistants=v2"}
        )    
        

        # Ждем завершения
        while True:
            run_status = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
            if run_status.status == "completed":
                break
            elif run_status.status == "failed":
                return jsonify({"error": "Ассистент не справился"}), 500
            time.sleep(1)

        # Получаем сообщение
        messages = client.beta.threads.messages.list(thread_id=thread.id)
        content = ""
        for msg in messages.data:
            for item in msg.content:
                if hasattr(item, "text") and hasattr(item.text, "value"):
                    content += item.text.value.strip() + "\n"

        print("📦 Ответ получен, начинаем разбор")

        def extract_block(tag, text):
            match = re.search(rf"==={tag}===\s*(.+?)(?=(?:===|$))", text, re.DOTALL)
            return match.group(1).strip() if match else ""

        result = {
            "element_name": extract_block("ELEMENT_NAME", content),
            "meta_title": extract_block("META_TITLE", content),
            "meta_keywords": extract_block("META_KEYWORDS", content),
            "meta_description": extract_block("META_DESCRIPTION", content),
            "article": extract_block("ARTICLE", content) or content.strip()
        }

        # Удаляем файл
        if delete_after:
            try:
                client.files.delete(file_id)
                print(f"🧹 Файл {file_id} удалён")
            except Exception as e:
                print(f"⚠️ Ошибка удаления файла: {e}")

        return jsonify(result)

    except Exception as e:
        print(f"❌ Ошибка в generate(): {e}")
        return jsonify({"error": "Ошибка сервера", "details": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
