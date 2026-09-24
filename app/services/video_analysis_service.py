import os
import cv2
import torch
import torch.nn as nn
from torchvision import models, transforms
from fastapi import HTTPException
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from ..models import Pista_Video, Extraccion_Video, Resultado_Video
from ..api.router_auth import consume_video_analysis, require_active_membership
from pathlib import Path
from .storage_service import ensure_local_file, persist_file
import psutil
import gc



FACE_CASCADE = cv2.CascadeClassifier(
    str(Path(cv2.data.haarcascades) / 'haarcascade_frontalface_default.xml')
)

# Cargar las variables de entorno desde el archivo .env
load_dotenv()

# --- CONFIGURACIÓN DE DISPOSITIVO ---
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# --- CARGA DINÁMICA DESDE EL .ENV ---
# Si por alguna razón no lee el .env, toma la ruta por defecto como respaldo (fallback)
MODEL_PATH = os.getenv("MODEL_PATH_VIDEO")
FRAMES_DIR = os.getenv("STORAGE_PATH_FRAMES")

_VIDEO_MODEL = None



def print_memory(label):
    process = psutil.Process(os.getpid())
    print(
        f"{label}: {process.memory_info().rss / 1024 / 1024:.2f} MB"
    )


def _resolve_storage_path(path_value: str | None):
    if not path_value:
        return None

    normalized_path = path_value.replace("\\", "/")
    if os.path.isabs(path_value):
        return ensure_local_file(path_value)

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    if normalized_path.lower().startswith("storage/"):
        return ensure_local_file(os.path.join(project_root, normalized_path))

    if normalized_path.startswith("/"):
        return ensure_local_file(os.path.join(project_root, normalized_path.lstrip("/")))

    return ensure_local_file(os.path.join(project_root, normalized_path))

# --- ARQUITECTURAS DEL MODELO ---
class Model(nn.Module):
    def __init__(self, num_classes=2, latent_dim=2048, lstm_layers=1, hidden_dim=2048, bidirectional=False):
        super(Model, self).__init__()
        backbone = models.resnext50_32x4d(pretrained=False)
        self.backbone = nn.Sequential(*list(backbone.children())[:-1])
        self.lstm = nn.LSTM(latent_dim, hidden_dim, lstm_layers, bidirectional=bidirectional, batch_first=True)
        self.dp = nn.Dropout(0.4)
        self.linearOut = nn.Linear(hidden_dim, num_classes)

    def forward(self, x):
        batch_size, seq_length, c, h, w = x.shape
        x = x.view(batch_size * seq_length, c, h, w)
        fmap = self.backbone(x)
        fmap = fmap.view(batch_size, seq_length, -1)
        lstm_out, (hn, cn) = self.lstm(fmap)
        return self.linearOut(self.dp(lstm_out[:, -1, :]))


class LegacyModel(nn.Module):
    def __init__(self, num_classes=2):
        super(LegacyModel, self).__init__()
        backbone = models.resnext50_32x4d(pretrained=False)
        self.model = nn.Sequential(*list(backbone.children())[:-1])
        self.linear1 = nn.Linear(2048, num_classes)

    def forward(self, x):
        batch_size, seq_length, c, h, w = x.shape
        x = x.view(batch_size * seq_length, c, h, w)
        fmap = self.model(x)
        fmap = fmap.view(batch_size, seq_length, -1)
        pooled = fmap.mean(dim=1)
        return self.linear1(pooled)


def _normalize_state_dict(state_dict):
    normalized = {}
    for key, value in state_dict.items():
        clean_key = key.replace("module.", "", 1)
        normalized[clean_key] = value
    return normalized


def _pick_video_model(state_dict):
    state_keys = list(state_dict.keys())

    if any(key.startswith("backbone.") for key in state_keys) and any(key.startswith("lstm.") for key in state_keys):
        return Model()

    if any(key.startswith("model.") for key in state_keys) and any(key.startswith("linear1.") for key in state_keys):
        return LegacyModel()

    if any(key.startswith("model.") for key in state_keys):
        return LegacyModel()

    return Model()


def _resolve_model_path():
    if MODEL_PATH:
        if os.path.isabs(MODEL_PATH):
            return MODEL_PATH
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", MODEL_PATH))

    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "models_ML", "modelo_video.pt"))


def _resolve_video_track_path(pista: Pista_Video, db: Session):
    resolved = _resolve_storage_path(pista.ruta_pvideo) or pista.ruta_pvideo
    if resolved and os.path.exists(resolved):
        return resolved

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    candidates = list(Path(project_root).glob('storage/video_tracks/track_*'))

    prefixes = []
    if pista.video_hash_video:
        prefixes.append(f"track_{pista.video_hash_video[:10]}")
    if pista.hash_pvideo:
        prefixes.append(f"track_{pista.hash_pvideo[:10]}")

    stored_name = Path(pista.ruta_pvideo).name if pista.ruta_pvideo else None

    for candidate in candidates:
        if stored_name and candidate.name == stored_name:
            pista.ruta_pvideo = str(candidate)
            try:
                db.add(pista)
                db.commit()
            except Exception:
                db.rollback()
            return str(candidate)

        if any(candidate.name.startswith(prefix) for prefix in prefixes):
            pista.ruta_pvideo = str(candidate)
            try:
                db.add(pista)
                db.commit()
            except Exception:
                db.rollback()
            return str(candidate)

    return resolved


# --- FUNCIÓN DE CARGA PEREZOSA (LAZY LOADING) ---
def get_video_model():
    """Carga el modelo de PyTorch usando la ruta del archivo .env."""
    global _VIDEO_MODEL
    model_path = _resolve_model_path()

    if _VIDEO_MODEL is None:
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"No se encontró el archivo del modelo de video en la ruta mapeada: {model_path}")
        
        try:
            checkpoint = torch.load(model_path, map_location=DEVICE)

            if isinstance(checkpoint, nn.Module):
                _VIDEO_MODEL = checkpoint
            else:
                state_dict = checkpoint.get("state_dict", checkpoint) if isinstance(checkpoint, dict) else checkpoint
                cleaned_state_dict = _normalize_state_dict(state_dict)
                _VIDEO_MODEL = _pick_video_model(cleaned_state_dict)

                try:
                    _VIDEO_MODEL.load_state_dict(cleaned_state_dict)
                except RuntimeError:
                    remapped_state_dict = {}
                    for key, value in cleaned_state_dict.items():
                        if key.startswith("model."):
                            remapped_state_dict[key.replace("model.", "backbone.", 1)] = value
                        elif key.startswith("linear1."):
                            remapped_state_dict[key.replace("linear1.", "linearOut.", 1)] = value
                        else:
                            remapped_state_dict[key] = value

                    _VIDEO_MODEL = Model()
                    _VIDEO_MODEL.load_state_dict(remapped_state_dict, strict=False)

            _VIDEO_MODEL.to(DEVICE)
            _VIDEO_MODEL.eval()
        except Exception as e:
            raise RuntimeError(f"Error al reconstruir el modelo de video desde las variables de entorno: {str(e)}")
            
    return _VIDEO_MODEL


def validate_video_track(pvideo_hash: str, db: Session):
    """Verifica que la pista exista, se pueda abrir y tenga suficientes frames."""
    pista = db.query(Pista_Video).filter(Pista_Video.hash_pvideo == pvideo_hash).first()
    if not pista:
        raise HTTPException(status_code=404, detail="Pista de video no encontrada")

    if not pista.video or not pista.video.usuario_nombreuser:
        raise HTTPException(status_code=400, detail="El video no tiene un usuario asociado.")

    user = require_active_membership(pista.video.usuario_nombreuser, db, pista.video.hash_video)

    video_path = _resolve_video_track_path(pista, db)

    # Comprobaciones explícitas antes de usar OpenCV
    if not os.path.exists(video_path):
        # Mostrar información útil para depuración
        parent = os.path.dirname(video_path) or '.'
        try:
            listing = os.listdir(parent)
        except Exception:
            listing = []
        raise HTTPException(status_code=400, detail=f"Error al abrir el video: archivo no encontrado. Intentado: {video_path}. Contenido carpeta: {listing}")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        # Intentar fallback con moviepy para obtener más detalle
        try:
            from moviepy.editor import VideoFileClip
            clip = VideoFileClip(video_path)
            clip.reader.close()
            clip.close()
        except Exception as e:
            size = os.path.getsize(video_path) if os.path.exists(video_path) else 'desconocido'
            raise HTTPException(status_code=400, detail=f"Error al abrir el video con OpenCV y MoviePy fallback. Ruta: {video_path}, tamaño: {size}, error: {str(e)}")
        finally:
            # If moviepy succeeded but OpenCV failed, still report OpenCV cannot open
            if not cap.isOpened():
                raise HTTPException(status_code=400, detail=f"Error al abrir el video con OpenCV aunque MoviePy pudo leerlo. Ruta: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames < 150:
        cap.release()
        raise HTTPException(status_code=400, detail="Video insuficiente (mínimo 150 frames).")

    cap.release()

    return {
        "status": "validated",
        "pvideo_hash": pvideo_hash,
        "ruta_pvideo": pista.ruta_pvideo,
        "total_frames": total_frames,
    }


# --- LÓGICA PRINCIPAL DE ANÁLISIS ---
def analyze_video_track(pvideo_hash: str, db: Session):
    # 1. Ejecutar la validación básica antes de continuar con la inferencia
    pista = db.query(Pista_Video).filter(Pista_Video.hash_pvideo == pvideo_hash).first()
    if not pista:
        raise HTTPException(status_code=404, detail="Pista de video no encontrada")

    if not pista.video or not pista.video.usuario_nombreuser:
        raise HTTPException(status_code=400, detail="El video no tiene un usuario asociado.")

    user = require_active_membership(pista.video.usuario_nombreuser, db, pista.video.hash_video)

    video_path = _resolve_video_track_path(pista, db)

    if not os.path.exists(video_path):
        raise HTTPException(status_code=400, detail=f"Error al abrir el video: archivo no encontrado. Intentado: {video_path}")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        # Fallback try with moviepy to give better diagnostics
        try:
            from moviepy.editor import VideoFileClip
            clip = VideoFileClip(video_path)
            clip.reader.close()
            clip.close()
        except Exception as e:
            size = os.path.getsize(video_path) if os.path.exists(video_path) else 'desconocido'
            raise HTTPException(status_code=400, detail=f"Error al abrir el video con OpenCV y MoviePy fallback. Ruta: {video_path}, tamaño: {size}, error: {str(e)}")
        finally:
            if not cap.isOpened():
                raise HTTPException(status_code=400, detail=f"Error al abrir el video con OpenCV aunque MoviePy pudo leerlo. Ruta: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames < 150:
        cap.release()
        raise HTTPException(status_code=400, detail="Video insuficiente (mínimo 150 frames).")


    try:
        consume_video_analysis(user, db)
    except HTTPException as e:
        print("=================================")
        print("ERROR ANALYSIS")
        print("STATUS:", e.status_code)
        print("DETAIL:", e.detail)
        print("=================================")
        raise

    # 3. EXTRACCIÓN DE ROSTROS Y CREACIÓN DE ARCHIVO .MP4 (Usando la ruta del .env)
    os.makedirs(FRAMES_DIR, exist_ok=True)
    video_faces_path = os.path.join(FRAMES_DIR, f"faces_{pvideo_hash[:10]}.mp4")
    
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(video_faces_path, fourcc, 10.0, (224, 224))

    faces_list = []
    count = 0
    step = total_frames // 20 

    try:
        while count < total_frames and len(faces_list) < 20:
            ret, frame = cap.read()
            if not ret: break
            
            if count % step == 0:
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                detected_faces = FACE_CASCADE.detectMultiScale(
                    gray_frame,
                    scaleFactor=1.1,
                    minNeighbors=5,
                    minSize=(60, 60),
                )

                if len(detected_faces):
                    left, top, width, height = detected_faces[0]
                    right, bottom = left + width, top + height
                    face_image = rgb_frame[top:bottom, left:right]
                    face_image = cv2.resize(face_image, (224, 224))
                    
                    out.write(cv2.cvtColor(face_image, cv2.COLOR_RGB2BGR))
                    faces_list.append(face_image)
            count += 1
    finally:
        cap.release()
        out.release() 

    if len(faces_list) < 10:
        if os.path.exists(video_faces_path): os.remove(video_faces_path)
        raise HTTPException(status_code=400, detail="No se detectaron suficientes rostros en el espacio secuencial.")

    # 4. REGISTRAR EXTRACCIÓN EN BD
    remote_frames_path = persist_file(video_faces_path, f"storage/video_frames/{Path(video_faces_path).name}")
    nueva_extraccion = Extraccion_Video(
        ruta_video_frames=remote_frames_path,
        pista_video_hash_pvideo=pvideo_hash
    )
    db.add(nueva_extraccion)
    db.flush()

    # 5. ANÁLISIS CON PYTORCH
    try:
        print_memory("ANTES DEL MODELO")
        model = get_video_model()
        print_memory("DESPUÉS DEL MODELO")
        transform = transforms.Compose([
            transforms.ToPILImage(),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
        ])
        print_memory("ANTES DEL STACK")
        input_tensor = torch.stack([transform(f) for f in faces_list]).unsqueeze(0).to(DEVICE)
        print_memory("DESPUÉS DEL STACK")
        
        with torch.no_grad():
            output = model(input_tensor)
            prediction = torch.softmax(output, dim=1)
            confidence, label_idx = torch.max(prediction, dim=1)
            
        # El notebook de entrenamiento convierte FAKE -> 0 y REAL -> 1.
        etiqueta = "FAKE" if label_idx.item() == 0 else "REAL"
        resultado_val = float(confidence.item())
        fake_confidence = resultado_val if etiqueta == "FAKE" else 1 - resultado_val
        
        del input_tensor
        del output
        del prediction
        del faces_list
        
        gc.collect()
        
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        # 6. GUARDAR RESULTADOS EN BD
        nuevo_resultado = Resultado_Video(
            resultado=resultado_val,
            etiqueta=etiqueta,
            extraccion_video_id_extraccio=nueva_extraccion.id_extraccionv
        )
        db.add(nuevo_resultado)
        db.commit()

        return {
            "verdict": etiqueta,
            "confidence": f"{resultado_val*100:.2f}%",
            "fake_confidence": f"{fake_confidence*100:.2f}%",
            "video_processed_path": remote_frames_path
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error en inferencia de red neuronal: {str(e)}")