import os
from openai import OpenAI
from dotenv import load_dotenv
from src.rag_system import RAGSystem

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("OpenAI API key not found. Please set OPENAI_API_KEY in your .env file.")

client = OpenAI(api_key=OPENAI_API_KEY)


SYSTEM_PROMPT = """
Ты — продвинутый ИИ-ассистент продавца в интернет-магазине "АвтоМастерПрофи", специализирующемся на запчастях для немецких автомобилей (например, Volkswagen, BMW, Mercedes, Audi). Твоя главная задача — помогать клиентам находить нужные запчасти, консультировать их и доводить до оформления заказа.

Твой стиль общения:
- **Уверенный и экспертный:** Ты знаешь всё о запчастях из доступной тебе базы знаний. Говори четко, по делу, но дружелюбно.
- **Проактивный и инициативный:** Не жди, пока клиент задаст все вопросы. Предлагай варианты (оригинал/аналог), уточняй детали (модель, год, VIN, если это необходимо для точного подбора, но не злоупотребляй запросом VIN без явной нужды), предлагай сопутствующие товары (например, если покупают тормозные колодки, предложи тормозные диски или датчик износа, если это релевантно).
- **Клиентоориентированный:** Твоя цель — довольный клиент, который совершил покупку. Внимательно слушай потребности, работай с возражениями мягко, но настойчиво.
- **Продающий:** Подчеркивай преимущества товаров, создавай ценность. Используй техники продаж из "книги продаж". Стремись закрыть сделку.

Твои возможности и ограничения:
- Ты имеешь доступ к базе знаний (фрагменты каталога товаров и книги продаж), которая будет предоставлена тебе вместе с запросом клиента. Используй ЭТУ ИНФОРМАЦИЮ как основной источник для ответов.
- Если информации в базе недостаточно, вежливо сообщи об этом и предложи передать запрос менеджеру. Не придумывай информацию.
- Ты можешь вызывать две функции:
    1. `send_invoice(details)`: для отправки счета клиенту, когда он готов к покупке. `details` должны содержать информацию о товарах (артикул, название, количество, цена) и, если удалось собрать, контактные данные клиента.
    2. `handover_to_manager(lead_data)`: для передачи диалога живому менеджеру. `lead_data` должна содержать краткую суть запроса, историю диалога или ключевые моменты, и контактные данные клиента, если есть.
- Начинай диалог с приветствия, если это первое сообщение в сессии.
- После подбора товара и согласования с клиентом, спроси, готов ли он оформить заказ.
- Если клиент согласен, уточни необходимые детали для счета и вызови `send_invoice`.
- Если клиент сомневается, у него сложные вопросы или он просит связаться с человеком, вызови `handover_to_manager`.
- Старайся получить от клиента подтверждение модели автомобиля и года выпуска, если это не очевидно из его первого запроса, чтобы обеспечить точность подбора.
- Всегда указывай цену и наличие (если эта информация есть в контексте). Предлагай оригинал и аналог, если доступны оба, с указанием разницы в цене и потенциальных преимуществ.
- Не используй слишком формальный или роботизированный язык. Будь как опытный, но современный продавец.
- Модели автомобилей могут быть написаны немного по-разному, например "Golf 6", "Гольф 6", "Гольф VI". Учитывай это при поиске. Аналогично "Пассат Б6", "Passat B6".
"""

# Определение доступных функций для GPT
AVAILABLE_FUNCTIONS = [
    {
        "type": "function",
        "function": {
            "name": "send_invoice",
            "description": "Отправляет счет клиенту, когда он готов к покупке и все детали согласованы.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string", "description": "Имя клиента, если известно."},
                    "customer_contact": {"type": "string", "description": "Контакт клиента (email/телефон), если известен."},
                    "items": {
                        "type": "array",
                        "description": "Список товаров для счета.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "article": {"type": "string", "description": "Артикул товара."},
                                "name": {"type": "string", "description": "Название товара."},
                                "quantity": {"type": "integer", "description": "Количество."},
                                "price_per_unit": {"type": "number", "description": "Цена за единицу."}
                            },
                            "required": ["article", "name", "quantity", "price_per_unit"]
                        }
                    },
                    "total_amount": {"type": "number", "description": "Общая сумма заказа."}
                },
                "required": ["items", "total_amount"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "handover_to_manager",
            "description": "Передает диалог и информацию о лиде живому менеджеру.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "Причина передачи менеджеру."},
                    "customer_query": {"type": "string", "description": "Исходный запрос клиента или суть проблемы."},
                    "conversation_summary": {"type": "string", "description": "Краткое содержание диалога."},
                    "customer_name": {"type": "string", "description": "Имя клиента, если известно."},
                    "customer_contact": {"type": "string", "description": "Контакт клиента (email/телефон), если известен."}
                },
                "required": ["reason", "customer_query"]
            }
        }
    }
]


class SalesBot:
    def __init__(self):
        self.rag_system = RAGSystem()
        self.conversation_history = []

    def _get_rag_context(self, user_query):
        search_results = self.rag_system.search(user_query, k=5)
        context_str = "Контекст из базы знаний:\n"
        if not search_results:
            context_str += "Не найдено релевантной информации в базе знаний по данному запросу.\n"
        for res in search_results:
            context_str += f"- {res['text']}\n"
        return context_str

    def _call_openai_api(self, messages_for_api):
        try:
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages_for_api,
                tools=AVAILABLE_FUNCTIONS,
                tool_choice="auto"
            )
            return response.choices[0].message
        except Exception as e:
            print(f"Error calling OpenAI API: {e}")
            return None

    def process_message(self, user_query):
        print(f"\n👤 Клиент: {user_query}")
        self.conversation_history.append({"role": "user", "content": user_query})
        messages_for_api = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages_for_api.extend(self.conversation_history[:-1])
        rag_context = self._get_rag_context(user_query)
        enriched_user_query = f"{rag_context}\n\nЗапрос клиента: {user_query}"
        messages_for_api.append({"role": "user", "content": enriched_user_query})


        ai_response_message = self._call_openai_api(messages_for_api)

        if not ai_response_message:
            return "Извините, произошла ошибка при обработке вашего запроса."

        if ai_response_message.tool_calls:
            self.conversation_history.append(ai_response_message)
            
            for tool_call in ai_response_message.tool_calls:
                function_name = tool_call.function.name
                function_args = tool_call.function.arguments
                
                print(f"🤖 ИИ хочет вызвать функцию: {function_name} с аргументами: {function_args}")
                if function_name == "send_invoice":
                    # send_invoice(json.loads(function_args)) # Реальный вызов
                    print(f"--> МОК: Вызов send_invoice({function_args})")
                    function_response_content = f"Счет успешно сформирован и отправлен (детали: {function_args}). Что-нибудь еще?"
                elif function_name == "handover_to_manager":
                    # handover_to_manager(json.loads(function_args)) # Реальный вызов
                    print(f"--> МОК: Вызов handover_to_manager({function_args})")
                    function_response_content = f"Передаю ваш запрос менеджеру (детали: {function_args}). Он скоро с вами свяжется."
                else:
                    function_response_content = f"Ошибка: неизвестная функция {function_name}"

                self.conversation_history.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": function_response_content,
                })
            
            final_ai_response_message = self._call_openai_api(self.conversation_history)
            if final_ai_response_message and final_ai_response_message.content:
                ai_response_text = final_ai_response_message.content
                self.conversation_history.append(final_ai_response_message)
            else:
                ai_response_text = "Функция была вызвана. Обработка завершена."
        
        elif ai_response_message.content:
            ai_response_text = ai_response_message.content
            self.conversation_history.append(ai_response_message)
        else:
            ai_response_text = "Извините, я не смог сгенерировать ответ."
            self.conversation_history.append({"role": "assistant", "content": ai_response_text})


        print(f"🤖 ИИ-продавец: {ai_response_text}")
        return ai_response_text

if __name__ == "__main__":
    bot = SalesBot()
    bot.process_message("Привет") # Для теста простого приветствия
    bot.process_message("У вас есть моторчик омывателя для Golf 6?")
    bot.process_message("Сколько будет стоить задний фонарь на Пассат Б6?")
    bot.process_message("Это оригинал или аналог?") # Этот вопрос должен быть в контексте предыдущего
    
    # Интерактивный режим для теста
    print("AI Sales Bot запущен. Введите 'выход' для завершения.")
    while True:
        user_input = input("Вы: ")
        if user_input.lower() == 'выход':
            break
        bot.process_message(user_input)