import subprocess
import os
import re
import time
from flask import Flask, request, jsonify
from openai import OpenAI
import httpx

os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

# 🛡️ Создаём httpx клиент без прокси
no_proxy_client = httpx.Client()

# 🧠 Создаём OpenAI клиент
client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    http_client=no_proxy_client
)

ASSISTANT_ID = os.environ.get("ASSISTANT_ID")

app = Flask(__name__)

@app.route("/generate", methods=["POST"])
def generate():
    print("📥 POST-запрос получен на /generate")
    
    try:
        data = request.get_json()
        if not data:
            with open("incoming_chunks_debug.log", "a", encoding="utf-8") as f:
                f.write(f"\n❗ Нет JSON-данных в запросе от {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            return jsonify({"error": "Нет данных"}), 400
            
        chunks = data.get("chunks", [])

        generated_blocks = {
            "element_name": "",
            "meta_title": "",
            "meta_keywords": "",
            "meta_description": "",
            "article_parts": []
        }    

        with open("incoming_chunks_debug.log", "a", encoding="utf-8") as f:
            f.write(f"\n=== Новый запрос от {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            f.write(f"Количество чанков: {len(chunks)}\n")
            for i, chunk in enumerate(chunks):
                f.write(f"--- Чанк {i} ---\n")
                f.write(chunk[:1000] + "\n...\n")  # первые 1000 символов каждого чанка
            

        print("📥 POST-запрос получен на /generate")
        print("=== 🧩 ПОЛУЧЕННЫЕ ДАННЫЕ ОТ СЕРВЕРА ===")
        print(f"📦 Количество чанков: {len(chunks)}")
        total_size = 0
        for i, ch in enumerate(chunks):
            ch_len = len(ch.encode('utf-8'))
            total_size += ch_len
            print(f"🔹 Чанк {i}: {ch_len} байт")
        print(f"📏 Общий размер чанков: {total_size} байт")
        print("=== 🔚 ===\n")

        with open("render_debug.log", "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Запрос получен, чанков: {len(chunks)}, размер: {total_size} байт\n")

        print("=== DISTRICT SEO BOT | АНАЛИЗ ЧАНКОВ ===")
        total_chars = 0
        for i, chunk in enumerate(chunks, 1):
            chunk_text = str(chunk)
            chunk_len = len(chunk_text)
            total_chars += chunk_len
            print(f"--- Чанк {i}: {chunk_len} символов ---")
        print(f"Общий объём данных: {total_chars} символов ({total_chars / 1024:.2f} КБ)")
        print("=== КОНЕЦ АНАЛИЗА ЧАНКОВ ===")


        

        cleaned_chunks = []
        for chunk in chunks:
            cleaned = re.sub(r'^https?://\S+\.(?:jpg|jpeg|png|gif)\s*$', '', chunk, flags=re.MULTILINE)
            cleaned_chunks.append(cleaned.strip())

        for i, chunk in enumerate(cleaned_chunks):
            print(f"\n🔁 Создание потока для чанка {i}")
            thread = client.beta.threads.create()
            
            print(f"📨 Отправка чанка {i}")
            client.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content=chunk
            )

            print("🚀 Запуск ассистента")
            run = client.beta.threads.runs.create(
                thread_id=thread.id,
                assistant_id=ASSISTANT_ID,
                extra_headers={"OpenAI-Beta": "assistants=v2"}
            )

            print("⏳ Ожидание ответа от ассистента...")
            while True:
                run_status = client.beta.threads.runs.retrieve(
                    thread_id=thread.id,
                    run_id=run.id
                )
                if run_status.status == "completed":
                    print("✅ Ассистент завершил генерацию")
                    break
                elif run_status.status == "failed":
                    raise Exception(f"Ассистент не справился с задачей для чанка {i}")
                time.sleep(1)

            print("📬 Получение ответа от ассистента")
            messages = client.beta.threads.messages.list(thread_id=thread.id)
            content = messages.data[0].content[0].text.value.strip()

            def extract_block(tag, text):
                match = re.search(rf"==={tag}===\s*(.+?)(?=(?:===|$))", text, re.DOTALL)
                return match.group(1).strip() if match else ""

            if i == 0:
                generated_blocks["element_name"] = extract_block("ELEMENT_NAME", content)
                generated_blocks["meta_title"] = extract_block("META_TITLE", content)
                generated_blocks["meta_keywords"] = extract_block("META_KEYWORDS", content)
                generated_blocks["meta_description"] = extract_block("META_DESCRIPTION", content)
                generated_blocks["article_parts"].append(extract_block("ARTICLE", content))
            else:
                generated_blocks["article_parts"].append(extract_block("ARTICLE", content))
                
            # ⏸️ Пауза между чанками
            time.sleep(5)

        print("=== 📥 ОТВЕТ ОТ OPENAI ===")
        print(content[:1000] + "\n...")  # первые 1000 символов
        print("=== 🔚 ===")
        

        

        result = {
            "element_name": generated_blocks["element_name"],
            "meta_title": generated_blocks["meta_title"],
            "meta_keywords": generated_blocks["meta_keywords"],
            "meta_description": generated_blocks["meta_description"],
            "article": "\n\n".join(generated_blocks["article_parts"])
        }
        with open("render_debug.log", "a", encoding="utf-8") as f:
            f.write(f"\n=== Финальный результат от {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            f.write(f"Название элемента: {result['element_name']}\n")
            f.write(f"META TITLE: {result['meta_title']}\n")
            f.write(f"META DESCRIPTION: {result['meta_description']}\n")
            f.write(f"META KEYWORDS: {result['meta_keywords']}\n")
            f.write("Тело статьи (первые 1000 символов):\n")
            f.write(result["article"][:1000] + "\n...\n")
            
        return jsonify(result)

    except Exception as e:
        print(f"❌ ОШИБКА: {str(e)}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("🟢 Flask сервер запущен. Ожидаем запросы...")
    app.run(host="0.0.0.0", port=10000)
