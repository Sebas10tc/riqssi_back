import os
import librosa
import numpy as np
import pandas as pd
import joblib
from fastapi import HTTPException
from sqlalchemy.orm import Session
from ..models import Pista_Audio, Extraccion_Audio, Resultado_Audio
from .storage_service import ensure_local_file, persist_file

# --- CARGA DEL MODELO (Lazy Loading) ---
_PIPELINE = None


def _resolve_audio_model_path():
    env_path = os.getenv("MODEL_PATH_AUDIO", "models_ML/modelo_audio.pkl")
    if os.path.isabs(env_path):
        return env_path
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", env_path))

def get_pipeline():
    global _PIPELINE
    if _PIPELINE is None:
        path = _resolve_audio_model_path()
        if not os.path.exists(path):
            raise FileNotFoundError(f"No se encontró el pipeline en {path}")
        _PIPELINE = joblib.load(path)
    return _PIPELINE


def _predict_audio(pipe, mfcc_mean):
    # Formato 1: diccionario con pipeline por etapas
    if isinstance(pipe, dict):
        required_keys = ["gnb_model", "scaler", "nmf_model", "rf_model"]
        if not all(key in pipe for key in required_keys):
            raise HTTPException(
                status_code=500,
                detail="El modelo de audio no contiene las claves esperadas (gnb_model, scaler, nmf_model, rf_model).",
            )

        prob_features = pipe['gnb_model'].predict_proba(mfcc_mean)
        mfcc_scaled = pipe['scaler'].transform(mfcc_mean)
        feature_range = getattr(pipe['scaler'], "feature_range", (0.0, 1.0))
        mfcc_scaled = np.clip(mfcc_scaled, feature_range[0], feature_range[1])
        nmf_features = pipe['nmf_model'].transform(mfcc_scaled)
        X_final = np.hstack((prob_features, nmf_features))
        prediction_prob = pipe['rf_model'].predict_proba(X_final)
        prediction_label = pipe['rf_model'].predict(X_final)
        return prediction_prob, prediction_label

    # Formato 2: clasificador directo (por ejemplo RandomForestClassifier)
    if hasattr(pipe, "predict") and hasattr(pipe, "predict_proba"):
        expected_features = getattr(pipe, "n_features_in_", mfcc_mean.shape[1])
        if expected_features != mfcc_mean.shape[1]:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"El modelo de audio espera {expected_features} features, "
                    f"pero se generan {mfcc_mean.shape[1]}. Regenera modelo_audio.pkl con el pipeline correcto."
                ),
            )

        prediction_prob = pipe.predict_proba(mfcc_mean)
        prediction_label = pipe.predict(mfcc_mean)
        return prediction_prob, prediction_label

    raise HTTPException(status_code=500, detail="Formato de modelo de audio no soportado.")


def _infer_mfcc_count(pipe):
    # Si viene pipeline completo, usamos el tamaño esperado por scaler cuando exista.
    if isinstance(pipe, dict):
        scaler = pipe.get("scaler")
        if scaler is not None and hasattr(scaler, "n_features_in_"):
            return int(scaler.n_features_in_)
        return 40

    # Si viene un clasificador directo (RandomForest, etc), usamos su expectativa.
    if hasattr(pipe, "n_features_in_"):
        return int(pipe.n_features_in_)

    return 40

def analyze_audio_track(paudio_hash: str, db: Session):
    # 1. Obtener datos de la Pista_Audio desde BD
    pista = db.query(Pista_Audio).filter(Pista_Audio.hash_paudio == paudio_hash).first()
    if not pista:
        raise HTTPException(status_code=404, detail="Pista de audio no encontrada")

    try:
        pipe = get_pipeline()
        n_mfcc = _infer_mfcc_count(pipe)

        # 2. Cargar audio y extraer MFCC (Igual que en el entrenamiento)
        y, sr = librosa.load(ensure_local_file(pista.ruta_paudio), sr=16000)
        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=n_mfcc)
        mfcc_mean = np.mean(mfcc.T, axis=0).reshape(1, -1)

        # 3. GUARDAR CSV LOCALMENTE
        csv_filename = f"mfcc_{paudio_hash[:10]}.csv"
        csv_path = os.path.join("storage/mfcc_data", csv_filename)
        
        # Guardamos los coeficientes calculados según el modelo cargado
        df_mfcc = pd.DataFrame(mfcc_mean, columns=[f"mfcc_{i}" for i in range(n_mfcc)])
        df_mfcc.to_csv(csv_path, index=False)
        csv_path = persist_file(csv_path, f"storage/mfcc_data/{csv_filename}")

        # 4. REGISTRAR EN BD (Tabla Extraccion_Audio)
        nueva_extraccion = Extraccion_Audio(
            ruta_mfcc=csv_path,
            pista_audio_hash_paudio=paudio_hash
        )
        db.add(nueva_extraccion)
        db.flush() # Para obtener el ID generado sin terminar la transacción

        # 5. PROCESO DE PREDICCIÓN (Usando el modelo/pipeline .pkl)
        prediction_prob, prediction_label = _predict_audio(pipe, mfcc_mean)

        # En el modelo de audio: 0 = REAL y 1 = FAKE.
        etiqueta = "FAKE" if int(prediction_label[0]) == 1 else "REAL"
        score = float(np.max(prediction_prob))
        fake_score = score if etiqueta == "FAKE" else 1 - score

        # 6. REGISTRAR RESULTADO EN BD (Tabla Resultado_Audio)
        nuevo_resultado = Resultado_Audio(
            prediccion_rf=score,
            etiqueta=etiqueta,
            extraccion_audio_id_extraccion=nueva_extraccion.id_extracciona
        )
        db.add(nuevo_resultado)
        db.commit()

        return {
            "status": "success",
            "extraction_id": nueva_extraccion.id_extracciona,
            "verdict": etiqueta,
            "confidence": f"{score*100:.2f}%",
            "fake_confidence": f"{fake_score*100:.2f}%",
            "csv_path": csv_path
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error en el análisis: {str(e)}")