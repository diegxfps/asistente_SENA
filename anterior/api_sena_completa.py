from flask import Flask, request, jsonify
import pandas as pd
import json
from pathlib import Path

app = Flask(__name__)

# Cargar datos del CSV
def cargar_datos():
    try:
        df = pd.read_csv('csv/oferta_sena_2025.csv', sep=';')
        print(f"✅ CSV cargado: {len(df)} programas")
        return df
    except Exception as e:
        print(f"❌ Error cargando CSV: {e}")
        return None

# Cargar datos desde JSON (si existe)
def cargar_json():
    try:
        with open('storage_simple/programas.json', 'r') as f:
            datos = json.load(f)
        print(f"✅ JSON cargado: {len(datos)} programas")
        return datos
    except:
        print("ℹ️  JSON no encontrado, usando CSV directo")
        return None

# Inicializar datos
df = cargar_datos()
datos_json = cargar_json()

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ok", "message": "API SENA funcionando", "programas": len(df) if df is not None else 0})

@app.route('/buscar', methods=['POST'])
def buscar():
    """Búsqueda en todos los campos"""
    try:
        data = request.get_json()
        termino = data.get('termino', '').lower().strip()
        
        if not termino:
            return jsonify({"error": "No se proporcionó término de búsqueda"}), 400
        
        if df is None:
            return jsonify({"error": "Base de datos no disponible"}), 500
        
        # Búsqueda en todos los campos
        resultados = df[df.apply(lambda row: row.astype(str).str.lower().str.contains(termino).any(), axis=1)]
        
        return jsonify({
            "resultados": resultados.to_dict(orient='records'),
            "total": len(resultados),
            "termino": termino
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/buscar_por_tipo', methods=['POST'])
def buscar_por_tipo():
    """Búsqueda por tipo específico"""
    try:
        data = request.get_json()
        termino = data.get('termino', '').lower().strip()
        tipo = data.get('tipo', '').lower().strip()
        
        if not termino or not tipo:
            return jsonify({"error": "Faltan parámetros: término o tipo"}), 400
        
        if df is None:
            return jsonify({"error": "Base de datos no disponible"}), 500
        
        # Buscar en columna específica
        if tipo in df.columns:
            resultados = df[df[tipo].astype(str).str.lower().str.contains(termino)]
        else:
            return jsonify({"error": f"Tipo '{tipo}' no válido. Usa: {list(df.columns)}"}), 400
        
        return jsonify({
            "resultados": resultados.to_dict(orient='records'),
            "total": len(resultados),
            "tipo": tipo,
            "termino": termino
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/programas', methods=['GET'])
def listar_programas():
    """Listar todos los programas"""
    try:
        if datos_json:
            return jsonify({"programas": datos_json, "total": len(datos_json)})
        elif df is not None:
            return jsonify({"programas": df.to_dict(orient='records'), "total": len(df)})
        else:
            return jsonify({"error": "Datos no disponibles"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/programa/<int:id>', methods=['GET'])
def obtener_programa(id):
    """Obtener programa por ID"""
    try:
        if df is not None:
            programa = df[df['no'] == id]
            if not programa.empty:
                return jsonify(programa.to_dict(orient='records')[0])
            else:
                return jsonify({"error": "Programa no encontrado"}), 404
        else:
            return jsonify({"error": "Datos no disponibles"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("🚀 Iniciando API SENA... ")
    print("📊 Endpoints disponibles: ")
    print("   POST /buscar - Búsqueda general ")
    print("   POST /buscar_por_tipo - Búsqueda por campo específico ")
    print("   GET /programas - Listar todos ")
    print("   GET /programa/<id> - Obtener por ID ")
    print("   GET /health - Estado del servicio ")
    app.run(host='0.0.0.0', port=5000, debug=True)