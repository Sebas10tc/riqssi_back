"""Prueba los modelos de audio y video sin usar la API ni el frontend."""

import argparse
import os
import sys

import librosa
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from app.services.audio_analysis_service import _infer_mfcc_count, _predict_audio, get_pipeline


def print_result(model_name, label, confidence, fake_probability):
    print(f"\n=== {model_name} ===")
    print(f"Predicción: {label}")
    print(f"Confianza de la clase predicha: {confidence * 100:.2f}%")
    print(f"Probabilidad de FAKE: {fake_probability * 100:.2f}%")


def test_audio(audio_path):
    pipeline = get_pipeline()
    sample, sample_rate = librosa.load(audio_path, sr=16000)
    mfcc_count = _infer_mfcc_count(pipeline)
    mfcc = librosa.feature.mfcc(y=sample, sr=sample_rate, n_mfcc=mfcc_count)
    mfcc_mean = np.mean(mfcc.T, axis=0).reshape(1, -1)

    probabilities, labels = _predict_audio(pipeline, mfcc_mean)
    label = "FAKE" if int(labels[0]) == 1 else "REAL"
    confidence = float(np.max(probabilities))
    fake_probability = confidence if label == "FAKE" else 1 - confidence
    print_result("MODELO DE AUDIO", label, confidence, fake_probability)


def extract_video_faces(video_path):
    import cv2
    import face_recognition

    capture = cv2.VideoCapture(video_path)
    if not capture.isOpened():
        raise RuntimeError(f"No se pudo abrir el video: {video_path}")

    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        capture.release()
        raise RuntimeError("El video no contiene frames legibles.")

    faces = []
    frame_step = max(1, total_frames // 20)
    frame_number = 0

    try:
        while frame_number < total_frames and len(faces) < 20:
            success, frame = capture.read()
            if not success:
                break

            if frame_number % frame_step == 0:
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                locations = face_recognition.face_locations(rgb_frame)
                if locations:
                    top, right, bottom, left = locations[0]
                    face = rgb_frame[top:bottom, left:right]
                    if face.size:
                        faces.append(cv2.resize(face, (224, 224)))
            frame_number += 1
    finally:
        capture.release()

    if len(faces) < 10:
        raise RuntimeError(f"Solo se detectaron {len(faces)} rostros; se necesitan al menos 10.")

    return faces


def test_video(video_path):
    import torch
    from torchvision import transforms
    from app.services.video_analysis_service import DEVICE, get_video_model

    faces = extract_video_faces(video_path)
    model = get_video_model()
    transform = transforms.Compose([
        transforms.ToPILImage(),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])
    input_tensor = torch.stack([transform(face) for face in faces]).unsqueeze(0).to(DEVICE)

    with torch.no_grad():
        probabilities = torch.softmax(model(input_tensor), dim=1)
        confidence, label_index = torch.max(probabilities, dim=1)

    # El notebook de video usa FAKE -> 0 y REAL -> 1.
    label = "FAKE" if label_index.item() == 0 else "REAL"
    confidence_value = float(confidence.item())
    fake_probability = confidence_value if label == "FAKE" else 1 - confidence_value
    print_result("MODELO DE VIDEO", label, confidence_value, fake_probability)


def main():
    parser = argparse.ArgumentParser(description="Prueba independiente de los modelos RIQSSI.")
    parser.add_argument("--audio", help="Ruta a un archivo de audio (.wav, .mp3, etc.).")
    parser.add_argument("--video", help="Ruta a un archivo de video (.mp4, etc.).")
    arguments = parser.parse_args()

    if not arguments.audio and not arguments.video:
        parser.error("Debes indicar --audio, --video o ambos.")

    if arguments.audio:
        test_audio(os.path.abspath(arguments.audio))
    if arguments.video:
        test_video(os.path.abspath(arguments.video))


if __name__ == "__main__":
    main()