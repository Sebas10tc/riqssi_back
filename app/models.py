from sqlalchemy import Column, String, Integer, Float, DateTime, Date, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from .database import Base  # Importamos la base declarativa configurada en database.py
import datetime

class Usuario(Base):
    __tablename__ = "usuario"
    nombreuser = Column(String(50), primary_key=True)
    nombre = Column(String(100))
    apellido = Column(String(100))
    fecha_nacimiento = Column(Date)
    correo = Column(String(150), unique=True)
    clave = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default='user')
    membership = Column(String(20), nullable=False, default='free')
    membership_request = Column(String(20))
    payment_status = Column(String(20), nullable=False, default='approved')
    payment_proof_path = Column(String(250))
    payment_operation_code = Column(String(80))
    payment_submitted_at = Column(DateTime)
    payment_reviewed_at = Column(DateTime)
    membership_expiration = Column(DateTime)
    membership_reminder_sent_at = Column(DateTime)
    videos_analyzed_count = Column(Integer, nullable=False, default=0)
    
    # Relaciones
    videos = relationship("Video", back_populates="usuario")
    membresias = relationship("Membresia_Usuario", back_populates="usuario")

class Membresia(Base):
    __tablename__ = "membresia"
    idmembresia = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(20))
    precio = Column(Numeric(10, 2)) # MONEY se mapea mejor como Numeric
    nrovideosdiarios = Column(Integer)
    plan_limit = Column(Integer)
    duracionvideopermitida = Column(Integer)

class Membresia_Usuario(Base):
    __tablename__ = "membresia_usuario"
    idmembresiauser = Column(Integer, primary_key=True, index=True)
    fechasubscripcion = Column(DateTime, default=datetime.datetime.utcnow)
    fechavenc = Column(DateTime)
    usuario_nombreuser = Column(String(15), ForeignKey("usuario.nombreuser"))
    membresia_idmembresi = Column(Integer, ForeignKey("membresia.idmembresia"))
    
    usuario = relationship("Usuario", back_populates="membresias")


class Cancelacion_Membresia(Base):
    __tablename__ = "cancelacion_membresia"
    idcancelacion = Column(Integer, primary_key=True, index=True)
    usuario_nombreuser = Column(String(50), ForeignKey("usuario.nombreuser"), nullable=False)
    membresia_idmembresia = Column(Integer, ForeignKey("membresia.idmembresia"))
    fecha_cancelacion = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    motivo = Column(String(250))

class Video(Base):
    __tablename__ = "video"
    hash_video = Column(String(64), primary_key=True)
    nombrevideo = Column(String(120))
    red_social = Column(String(50))
    fechasubida = Column(DateTime, default=datetime.datetime.utcnow)
    resolucion = Column(String(50))
    duracion = Column(Integer)
    thumbnail_path = Column(String(120))
    video_path = Column(String(250))
    usuario_nombreuser = Column(String(15), ForeignKey("usuario.nombreuser"))

    usuario = relationship("Usuario", back_populates="videos")
    pistas_video = relationship("Pista_Video", back_populates="video")
    pistas_audio = relationship("Pista_Audio", back_populates="video")
    resultado_total = relationship("Resultado_Total", back_populates="video", uselist=True)

class Historial(Base):
    __tablename__ = "historial"
    idhistorial = Column(Integer, primary_key=True, index=True)
    estado = Column(String(20))
    usuario_nombreuser = Column(String(15), ForeignKey("usuario.nombreuser"))
    video_hash_video = Column(String(64), ForeignKey("video.hash_video"))
    fecha_consulta = Column(DateTime, default=datetime.datetime.utcnow)

class Pista_Video(Base):
    __tablename__ = "pista_video"
    hash_pvideo = Column(String(64), primary_key=True)
    ruta_pvideo = Column(String(120))
    nroframes = Column(String(60))
    video_hash_video = Column(String(64), ForeignKey("video.hash_video"))

    video = relationship("Video", back_populates="pistas_video")
    extracciones = relationship("Extraccion_Video", back_populates="pista_video")

class Extraccion_Video(Base):
    __tablename__ = "extraccion_video"
    id_extraccionv = Column(Integer, primary_key=True, index=True)
    ruta_video_frames = Column(String(120))
    pista_video_hash_pvideo = Column(String(64), ForeignKey("pista_video.hash_pvideo"))

    pista_video = relationship("Pista_Video", back_populates="extracciones")

class Resultado_Video(Base):
    __tablename__ = "resultado_video"
    idresultado_v = Column(Integer, primary_key=True, index=True)
    resultado = Column(Float)
    etiqueta = Column(String(20))
    extraccion_video_id_extraccio = Column(Integer, ForeignKey("extraccion_video.id_extraccionv"))

class Pista_Audio(Base):
    __tablename__ = "pista_audio"
    hash_paudio = Column(String(64), primary_key=True)
    frecuencia = Column(Integer)
    ruta_paudio = Column(String(120))
    video_hash_video = Column(String(64), ForeignKey("video.hash_video"))

    video = relationship("Video", back_populates="pistas_audio")
    extracciones = relationship("Extraccion_Audio", back_populates="pista_audio")

class Extraccion_Audio(Base):
    __tablename__ = "extraccion_audio"
    id_extracciona = Column(Integer, primary_key=True, index=True)
    ruta_mfcc = Column(String(120))
    pista_audio_hash_paudio = Column(String(64), ForeignKey("pista_audio.hash_paudio"))

    pista_audio = relationship("Pista_Audio", back_populates="extracciones")

class Resultado_Audio(Base):
    __tablename__ = "resultado_audio"
    idresultado_a = Column(Integer, primary_key=True, index=True)
    prediccion_rf = Column(Float)
    etiqueta = Column(String(20))
    extraccion_audio_id_extraccion = Column(Integer, ForeignKey("extraccion_audio.id_extracciona"))

class Resultado_Total(Base):
    __tablename__ = "resultado_total"
    idresultado_total = Column(Integer, primary_key=True, index=True)
    resultadopvideo = Column(Float)
    resultadopaudio = Column(Float)
    veredicto_final = Column(Float)
    etiqueta_final = Column(String(20))
    video_hash_video = Column(String(64), ForeignKey("video.hash_video"))
    usuario_nombreuser = Column(String(15), ForeignKey("usuario.nombreuser"), nullable=True)

    video = relationship("Video", back_populates="resultado_total")