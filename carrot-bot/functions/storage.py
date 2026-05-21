"""
storage.py

Persistencia de historiales en Google Cloud Storage.

Los historiales de conciertos y descubrimientos necesitan sobrevivir entre
ejecuciones semanales de la Cloud Function (el filesystem del contenedor es
efímero y se reinicia en cada cold start).

Requiere la variable de entorno GCS_BUCKET_NAME con el nombre del bucket.
Si no está definida, pull/push son no-op: útil en desarrollo local donde
los ficheros ya existen en disco.

El bucket recomendado es el de Firebase Storage de tu proyecto:
  {project-id}.firebasestorage.app
"""

import os
from pathlib import Path

HISTORY_FILES = [
    "spotify/data/discoveries_history.json",
    "spotify/data/concerts_history.json",
]

BASE_DIR = Path(__file__).parent


def _get_bucket():
    bucket_name = os.getenv("GCS_BUCKET_NAME")
    if not bucket_name:
        return None

    try:
        from google.cloud import storage as gcs
        return gcs.Client().bucket(bucket_name)
    except Exception as e:
        print(f"  ⚠️  GCS no disponible: {e}")
        return None


def pull_histories() -> None:
    """Descarga los historiales desde GCS sobreescribiendo los ficheros locales."""
    bucket = _get_bucket()
    if bucket is None:
        return

    for rel_path in HISTORY_FILES:
        blob  = bucket.blob(rel_path)
        local = BASE_DIR / rel_path
        try:
            if blob.exists():
                local.parent.mkdir(parents=True, exist_ok=True)
                blob.download_to_filename(str(local))
                print(f"  GCS ↓ {rel_path}")
            else:
                print(f"  GCS — {rel_path} no existe en bucket (primera ejecución)")
        except Exception as e:
            print(f"  ⚠️  GCS pull error ({rel_path}): {e}")


def push_histories() -> None:
    """Sube los historiales locales actualizados a GCS."""
    bucket = _get_bucket()
    if bucket is None:
        return

    for rel_path in HISTORY_FILES:
        blob  = bucket.blob(rel_path)
        local = BASE_DIR / rel_path
        try:
            if local.exists():
                blob.upload_from_filename(str(local))
                print(f"  GCS ↑ {rel_path}")
        except Exception as e:
            print(f"  ⚠️  GCS push error ({rel_path}): {e}")
