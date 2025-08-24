# procesar_csv_simple.py
import pandas as pd
import json
from pathlib import Path

def main():
    print("📊 Procesamiento SIMPLE del CSV...")
    
    try:
        df = pd.read_csv('csv/oferta_sena_2025.csv', sep=';')
        
        # Guardar como JSON simple para búsquedas básicas
        datos = df.to_dict(orient='records')
        
        with open('storage_simple/programas.json', 'w') as f:
            json.dump(datos, f, indent=2)
        
        print(f"✅ {len(datos)} programas guardados en JSON")
        print("📍 Usaremos búsquedas directas (sin IA) por ahora")
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")

if __name__ == "__main__":
    main()