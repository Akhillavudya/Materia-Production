from app.core.llm import generate_response

def chat_with_ai(user_message: str):

    response = generate_response(user_message)

    return response