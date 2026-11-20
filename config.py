
# ============================================================
#  STAR-CAR · configuración
#  Este archivo se empaqueta dentro del .apk junto con main.py
# ============================================================

# Pega aquí tu API key de Groq (https://console.groq.com/keys)
GROQ_API_KEY = ""


# Modelo principal y de respaldo
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_MODEL_RESPALDO = "openai/gpt-oss-20b"

# Potencia que usa la IA en los trucos (50 a 255).
# 255 = tope de los dos motores, para que no se atasquen.
IA_POTENCIA_DIRECCION = 255   # motor de dirección (M1)
IA_POTENCIA_LLANTAS = 255     # llantas traseras (M2)
