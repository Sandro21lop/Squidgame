"""
content_pruebas.py — Aquí controlas qué se muestra en la sección
"Resultados en vivo" de la landing page. Es la prueba social: capturas
o clips de tus propios streams mostrando plata en regalos, espectadores, etc.

CÓMO AGREGAR UNA PRUEBA NUEVA
──────────────────────────────
1. Copia tu imagen o video a la carpeta: static/pruebas/
   - Imágenes: .jpg, .png, .webp
   - Videos: .mp4 (que sean cortos y livianos, para que carguen rápido)
2. Agrega un diccionario nuevo a la lista PRUEBAS de abajo, con el nombre
   EXACTO del archivo que copiaste.
3. Guarda. No necesitas tocar nada más — la landing los muestra solos.

Si vas a rotar contenido, puedes dejar la lista con las 3-6 mejores pruebas
y guardar el resto en un archivo aparte para no perderlas.

CAMPOS
──────
tipo:        "imagen" o "video"
archivo:     nombre del archivo dentro de static/pruebas/
resultado:   el número que más vende, corto y directo (ej. "$340 en regalos")
titulo:      una frase de contexto (ej. "Stream del sábado, 45 minutos")
descripcion: opcional, una línea extra si quieres dar más detalle
"""

PRUEBAS = [
    {
        "tipo": "imagen",
        "archivo": "stream-capibara.jpeg",
        "resultado": "306 espectadores en vivo",
        "titulo": "Quid Game TikTok reaccionando en tiempo real a los regalos",
        "descripcion": "Ronda del Capibara activa, toda la audiencia participando desde el chat.",
    },
    {
        "tipo": "imagen",
        "archivo": "stats-live-center.png",
        "resultado": "985 💎 en un solo LIVE",
        "titulo": "Resumen del Centro LIVE de TikTok",
        "descripcion": "36 minutos de transmisión, 3,243 me gusta y $4.82 en recompensas.",
    },

    # Agrega los tuyos debajo siguiendo el mismo formato:
    #
    # {
    #     "tipo": "video",
    #     "archivo": "clip-eliminacion.mp4",
    #     "resultado": "+120 monedas en 1 regalo",
    #     "titulo": "Corazón Coreano activando la ronda de eliminación",
    #     "descripcion": "",
    # },
]
