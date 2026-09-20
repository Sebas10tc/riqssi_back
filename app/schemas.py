from pydantic import BaseModel, HttpUrl
from typing import Optional, List
from datetime import datetime, date

# --- ESQUEMAS PARA USUARIO ---
class UsuarioBase(BaseModel):
    nombreuser: str

class UsuarioLogin(BaseModel):
    correo: str
    clave: str

class UsuarioCreate(BaseModel):
    nombre_usuario: str
    nombre: str
    apellido: str
    fecha_nacimiento: date
    correo: str
    clave: str
    plan: str
    membresia: str | None = None


class PaymentSubmission(BaseModel):
    nombreuser: str
    operation_code: str

class PasswordRecoveryRequest(BaseModel):
    correo: str


class PasswordChangeRequest(BaseModel):
    correo: str
    nueva_clave: str

class UsuarioResponse(UsuarioBase):
    class Config:
        from_attributes = True

# --- ESQUEMAS PARA VIDEO (Descarga y Metadatos) ---
class VideoDownloadRequest(BaseModel):
    url: str  # El enlace de la red social enviado desde React

class VideoBase(BaseModel):
    hash_video: str
    nombrevideo: str
    red_social: str
    duracion: int
    resolucion: str
    thumbnail_path: str
    
    class Config:
        from_attributes = True

# --- ESQUEMAS PARA ANÁLISIS DE AUDIO (Deepfake) ---
class ResultadoAudioBase(BaseModel):
    prediccion_rf: float
    etiqueta: str

class ResultadoAudioResponse(ResultadoAudioBase):
    idresultado_a: int
    extraccion_audio_id_extraccion: int

    class Config:
        from_attributes = True

# --- ESQUEMA DE RESULTADO TOTAL (Veredicto Final) ---
class ResultadoTotalResponse(BaseModel):
    idresultado_total: int
    resultadopvideo: float
    resultadopaudio: str
    veredicto_final: str
    video_hash_video: str

    class Config:
        from_attributes = True

# --- ESQUEMAS PARA MEMBRESÍA ---
class MembresiaResponse(BaseModel):
    idmembresia: int
    nombre: str
    precio: float
    nrovideosdiarios: int
    duracionvideopermitida: int

    class Config:
        from_attributes = True