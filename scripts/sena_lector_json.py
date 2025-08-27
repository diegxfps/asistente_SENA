from flask import Flask, request, jsonify
import json
import logging
from pathlib import Path

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Cargar datos desde JSON
def cargar_programas():
    try:
        with open('storage_simple/programas.json', 'r', encoding='utf-8') as f:
            programas = json.load(f)
        logger.info(f"✅ JSON cargado: {len(programas)} programas")
        return programas
    except Exception as e:
        logger.error(f"❌ Error cargando JSON: {e}")
        return []

programas = cargar_programas()

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ok", "programas": len(programas)})

@app.route('/chatbot', methods=['POST'])
def chatbot():
    """Endpoint para el chatbot de WhatsApp"""
    try:
        data = request.get_json()
        mensaje = data.get('message', '').lower().strip()
        numero = data.get('number', '')
        
        logger.info(f"📩 Mensaje recibido: '{mensaje}' de {numero}")
        
        # Generar respuesta basada en el mensaje
        respuesta = generar_respuesta(mensaje)
        
        logger.info(f"📤 Respuesta: {respuesta}...")  # Log completo
        return jsonify({"response": respuesta, "to": numero})
        
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        return jsonify({"error": "Error procesando mensaje"}), 500

def generar_respuesta(mensaje: str) -> str:
    """Lógica inteligente de respuesta"""
    logger.info(f"🔍 Analizando mensaje: '{mensaje}'")
    
    # Lista ampliada de palabras que activan búsqueda
    palabras_busqueda = [
        'programa', 'curso', 'formación', 'titulación', 'estudiar', 'aprender',
        'tecnología', 'informática', 'cocina', 'mecánica', 'administración',
        'electricidad', 'salud', 'diseño', 'agro', 'sena', 'técnico', 'tecnólogo',
        'operario', 'auxiliar', 'capacitación', 'educación', 'profesional'
    ]
    
    # Cualquier palabra relacionada con formación activa búsqueda
    if any(palabra in mensaje for palabra in palabras_busqueda):
        logger.info(f"✅ Mensaje reconocido como búsqueda: '{mensaje}'")
        return buscar_programas_json(mensaje)
    
    # Saludos
    elif any(palabra in mensaje for palabra in ['hola', 'buenos días', 'buenas tardes', 'saludos', 'hi', 'hello']):
        logger.info(f"✅ Mensaje reconocido como saludo")
        return "¡Hola! 😊 Soy tu asistente SENA. Puedo ayudarte a encontrar programas de formación. ¿Buscas algo específico?"
    
    # Ayuda
    elif any(palabra in mensaje for palabra in ['ayuda', 'qué puedes hacer', 'opciones', 'funcionas']):
        logger.info(f"✅ Mensaje reconocido como ayuda")
        return "Puedo buscarte programas de formación del SENA. Por ejemplo, pregúntame: 'Programas de tecnología' o 'Cursos de cocina'"
    
    # Default - ahora más inteligente
    else:
        logger.info(f"🤔 Mensaje no reconocido, pero intentando búsqueda: '{mensaje}'")
        # Intenta buscar de todos modos
        return buscar_programas_json(mensaje)

def buscar_programas_json(mensaje: str) -> str:
    """Buscar programas en el JSON con búsqueda inteligente"""
    if not programas:
        return "⚠️ Base de datos no disponible en este momento"
    
    logger.info(f"🔍 Buscando: '{mensaje}' en {len(programas)} programas")
    
    resultados = []
    
    for programa in programas:
        # Buscar en el campo 'programa' (que es el nombre real)
        nombre_programa = programa.get('programa', '').lower()
        nivel_programa = programa.get('nivel', '').lower()
        municipio_programa = programa.get('municipio', '').lower()
        
        # Búsqueda en los campos principales
        if (mensaje in nombre_programa or 
            mensaje in nivel_programa or 
            mensaje in municipio_programa):
            resultados.append(programa)
            continue
            
        # Búsqueda por términos relacionados
        terminos_relacionados = {
            'informática': ['computación', 'software', 'programación', 'tic', 'sistemas'],
            'tecnología': ['tecnico', 'tecnólogo', 'tecnológica', 'tecnológico'],
            'administración': ['administrativo', 'gestión', 'empresarial', 'gerencia'],
            'salud': ['salud', 'medicina', 'enfermería', 'bienestar'],
            'diseño': ['diseño', 'gráfico', 'multimedia', 'creativo'],
            'construcción': ['construcción', 'obra', 'edificación', 'civil'],
            'alimentos': ['alimentos', 'culinaria', 'gastronomía', 'cocina']
        }
        
        for termino, palabras in terminos_relacionados.items():
            if termino in mensaje:
                if any(palabra in nombre_programa for palabra in palabras):
                    resultados.append(programa)
                    break
    
    # Eliminar duplicados
    seen = set()
    resultados_unicos = []
    for programa in resultados:
        identificador = programa.get('programa', '') + str(programa.get('no', ''))
        if identificador not in seen:
            seen.add(identificador)
            resultados_unicos.append(programa)
    
    if len(resultados_unicos) == 0:
        # Mostrar algunos programas de ejemplo
        ejemplos = "\n".join([f"• {p.get('programa', 'Programa SENA')} ({p.get('nivel', 'N/A')})" 
                             for p in programas[:3]])
        return f"❌ No encontré programas para '{mensaje}'. \n\nAlgunos programas disponibles:\n{ejemplos}\n\nIntenta con palabras como: técnico, tecnología, administración, etc."
    
    # Limitar a 3 resultados
    resultados_unicos = resultados_unicos[:3]
    respuesta = "🎓 Programas encontrados:\n\n"
    
    for programa in resultados_unicos:
        nombre = programa.get('programa', 'Programa SENA')
        respuesta += f"• {nombre}\n"
        
        if programa.get('nivel'):
            respuesta += f"  📍 Nivel: {programa['nivel']}\n"
        if programa.get('municipio'):
            respuesta += f"  🏙️ Municipio: {programa['municipio']}\n"
        if programa.get('sede'):
            respuesta += f"  🏫 Sede: {programa['sede']}\n"
        if programa.get('horario'):
            respuesta += f"  ⏰ Horario: {programa['horario']}\n"
        
        respuesta += "\n"
    
    respuesta += "¿Te interesa algún programa en particular?"
    return respuesta

if __name__ == '__main__':
    print("🤖 Iniciando Chatbot IA SENA (con JSON)")
    print("📍 Endpoint: POST /chatbot")
    print("📍 Health: GET /health")
    app.run(host='0.0.0.0', port=8000, debug=True)