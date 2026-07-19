# Quid Game TikTok — Sistema de venta y licencias

Landing page + backend en Flask para vender **Quid Game TikTok** con un solo
plan (**$5/mes**), con un sistema de licencias propio: cada clave lleva el
**usuario de TikTok del comprador cifrado adentro**, así que no dependes de
ninguna pasarela de pago para emitir y controlar licencias.

El juego (`licencia_cliente/licencia.py`) **solo pide la clave de licencia**,
nunca el usuario de TikTok — así el usuario cifrado dentro de la clave no se
puede tocar ni falsificar desde el juego, y no hay ningún campo editable que
facilite la piratería.

---

## 1. Qué hace cada pieza

- **Landing page** (`/`) — vitrina del juego, 3 planes con precios, sección
  de resultados reales, FAQ.
- **`license_generator.py`** — el corazón del sistema. Genera claves con
  formato `QGT-<PLAN>-XXXXX-XXXXX-...` cifradas (AES-GCM) con tu `SECRET_KEY`.
  El usuario de TikTok, el plan y las fechas van dentro de la clave misma.
  Puedes descifrar cualquier clave sin tocar la base de datos — útil para
  soporte, o para detectar reventa (misma clave, usuario distinto).
- **Panel admin** (`/admin`):
  - **Generar licencia** (`/admin/licencias/generar`) — pones el usuario de
    TikTok y el plan, y te da la clave lista para enviarle al cliente. Úsalo
    mientras no tengas pasarela de pago conectada (pagos por transferencia,
    WhatsApp, etc.), o para siempre si prefieres cobrar así.
  - **Decodificar clave** (`/admin/licencias/decodificar`) — pega cualquier
    clave y ve a quién pertenece, sin buscar en la base de datos.
  - **Tabla de licencias** — bloquear/desbloquear, resetear el equipo
    activado, renovar manualmente.
- **API para el juego** (`/api/activate`, `/api/validate`) — el juego llama
  esto para activarse la primera vez y validarse en cada arranque. Valida
  contra tu propia tabla de licencias (nunca contra la pasarela de pago).
- **Actualizaciones del juego** (`/api/version`, `/api/download`) — el juego
  consulta `/api/version` en cada arranque (sin necesitar la clave) para ver
  si hay una versión más nueva; si la hay, usa la clave que ya tiene guardada
  localmente para bajar el instalador desde `/api/download`, sin pedirle
  nada al usuario. Ver sección 5.
- **Descarga protegida** (`/descargar`) — solo entrega el instalador si la
  licencia está vigente y no bloqueada (versión web, con formulario).
- **Correo automático** (`emailer.py`) — cada vez que se emite una licencia
  nueva (pago por PayPal o generada a mano con correo en el panel),
  se envía por SMTP al comprador. También se avisa por correo cuando se
  renueva un ciclo o se cancela una suscripción. Ver sección 6.
- **PayPal** — pasarela de pago activa. El webhook (`/webhooks/paypal`)
  y el cliente (`paypal_client.py`) emiten y renuevan licencias
  automáticamente en cuanto conectes tus credenciales. Ver sección 4.

---

## 2. Arrancar en local

```bash
cp .env.example .env
# edita .env: pon un SECRET_KEY largo y aleatorio, y tu ADMIN_EMAIL/ADMIN_PASSWORD

pip install -r requirements.txt
python app.py
```

Abre `http://localhost:5000` para la landing, y `http://localhost:5000/admin`
para el panel (usa el `ADMIN_EMAIL`/`ADMIN_PASSWORD` que pusiste en `.env`).

⚠️ **`SECRET_KEY` es la clave con la que se cifra el usuario de TikTok dentro
de cada licencia.** Genérala una sola vez y no la cambies después de emitir
licencias, o dejarán de poder descifrarse (se leerán como "clave inválida").

---

## 3. Vender licencias hoy mismo (sin pasarela de pago)

1. Alguien te escribe / te paga por transferencia, WhatsApp, lo que sea.
2. Entras a `/admin/licencias/generar`, pones su usuario de TikTok y el plan.
3. Le copias la clave generada y se la envías.
4. Él la pega en el juego (`licencia_cliente/licencia.py` ya llama a tu
   propio backend en `/api/activate`).

Cuando quieras renovarle el plan, usas el botón "Renovar" en la tabla del
panel — extiende la fecha de vencimiento sin generar una clave nueva.

---

## 4. Conectar PayPal (pasarela de pago activa)

El proyecto usa **PayPal Subscriptions** para el cobro recurrente. Pasos:

1. Crea una app REST en https://developer.paypal.com/dashboard/applications
   (modo *Sandbox* para probar, *Live* cuando cobres de verdad). Copia
   **Client ID** y **Secret** a `.env`: `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET`,
   y pon `PAYPAL_MODE=sandbox` o `PAYPAL_MODE=live`.
2. Crea un **Producto** y luego un **Plan** de facturación por cada plan que
   vendas (mensual $5, semestral $25, anual $50) — puedes hacerlo desde el
   dashboard de PayPal (Billing Plans) o con la API `/v1/catalogs/products`
   + `/v1/billing/plans`. Copia cada Plan ID (`P-XXXXXXXX...`) a `.env`:
   `PAYPAL_PLAN_ID_MENSUAL` / `_SEMESTRAL` / `_ANUAL`.
3. Ve a **Webhooks** en tu app de PayPal, crea uno apuntando a
   `https://tudominio.com/webhooks/paypal` y suscríbelo (mínimo) a:
   `BILLING.SUBSCRIPTION.ACTIVATED`, `BILLING.SUBSCRIPTION.CANCELLED`,
   `BILLING.SUBSCRIPTION.EXPIRED`, `BILLING.SUBSCRIPTION.SUSPENDED`,
   `PAYMENT.SALE.COMPLETED`. Copia el **Webhook ID** a `.env`:
   `PAYPAL_WEBHOOK_ID`.
4. Esto ya está conectado: `/comprar` pide el usuario de TikTok y crea la
   suscripción vía `paypal_client.crear_suscripcion(...)` con ese usuario
   metido en `custom_id`; el comprador aprueba el pago en PayPal y vuelve a
   `/gracias`. El webhook (`routes/webhooks.py` →
   `_emitir_o_renovar_licencia_paypal`) recibe `BILLING.SUBSCRIPTION.ACTIVATED`
   (primer pago) o `PAYMENT.SALE.COMPLETED` (renovaciones), emite/renueva la
   licencia con `origen="paypal"` y **manda el correo automáticamente**. No
   necesitas tocar código, solo llenar el `.env`.
5. El cliente puede ver el estado de su suscripción y cancelarla él mismo
   en `/mi-cuenta` (a diferencia de Lemon Squeezy, PayPal no da una URL de
   portal firmada, así que esa vista la arma el propio backend). Para
   cambiar de tarjeta, el cliente lo hace desde su cuenta de paypal.com.
6. **Licencias/suscripciones históricas**: no aplica — el proyecto no tenía
   base de datos en uso, así que no hay nada de Lemon Squeezy que migrar.
   Todo lo que se genere de aquí en adelante (pagado o manual) queda
   directamente en el esquema de PayPal.

---

## 5. Correo automático de licencias

`emailer.py` envía los correos por **SMTP directo** (no por una pasarela de
terceros) — funciona bien en un plan de Render de pago, donde el puerto
587/465 saliente no está bloqueado (a diferencia del plan free).

Configura en `.env`:

```
SMTP_HOST=smtp.tu-proveedor.com
SMTP_PORT=587
SMTP_USER=tu-usuario
SMTP_PASSWORD=tu-password-o-app-password
SMTP_SECURITY=starttls        # o "ssl" si usas el puerto 465
EMAIL_FROM=Quid Game TikTok <licencias@tudominio.com>
PUBLIC_BASE_URL=https://tu-app.onrender.com
```

Funciona con Gmail (con una "contraseña de aplicación", no tu contraseña
normal — https://myaccount.google.com/apppasswords), Zoho Mail, o el SMTP
de tu propio dominio/hosting.

**Cuándo se envía correo automáticamente:**

- **Licencia nueva** — al confirmarse el primer pago de una suscripción
  (PayPal), o al generarla a mano desde `/admin/licencias/generar`
  si le pones un correo en el formulario.
- **Renovación** — cuando el ciclo se cobra de nuevo (`PAYMENT.SALE.COMPLETED`
  en una suscripción que ya tenía licencia). **No se genera una clave
  nueva**: la validez de una licencia con `origen="paypal"` depende
  del estado en vivo de la suscripción (`is_effectively_active`), no de una
  fecha fija dentro de la clave — así que la misma clave sigue funcionando
  sola, sin que el jugador tenga que hacer nada. El correo es solo un aviso
  de confirmación. (Si prefieres reemitir la clave en cada renovación en
  vez de reusarla, se puede cambiar, pero perderías la detección de
  reventa por "misma clave activándose en cuentas de TikTok distintas".)
- **Cancelación** — cuando la suscripción se cancela o vence, avisando hasta
  qué fecha sigue teniendo acceso.

Si `SMTP_HOST` está vacío, estas funciones no truenan nada — solo lo anotan
en los logs, para que un problema de correo nunca tumbe un pago o un webhook.

---

## 6. Actualizaciones automáticas del juego

- `GET /api/version` — público, sin necesitar clave. Devuelve la versión
  más reciente (`DOWNLOAD_LATEST_VERSION` en `.env`) y notas opcionales
  (`DOWNLOAD_NOTAS`). El juego lo consulta en cada arranque.
- `POST /api/download` — recibe `{"license_key": "..."}` y, si la licencia
  está vigente, devuelve el instalador. El juego ya tiene la clave guardada
  localmente (`licencia_local.json`), así que puede pedir la actualización
  solo si detecta que su versión es más vieja, sin pedirle nada al jugador.

Cuando subas un instalador nuevo:

1. Sube el `.exe` a `downloads/` (reemplaza el archivo en
   `DOWNLOAD_LATEST_PATH`).
2. Sube también la versión en la constante `VERSION` de
   `licencia_cliente/licencia.py` (o donde la hayas dejado en el juego).
3. Cambia `DOWNLOAD_LATEST_VERSION` en el `.env` de Render al nuevo número
   (ej. `1.1.0`) y, si quieres, `DOWNLOAD_NOTAS` con un resumen del cambio.
4. Listo — todos los juegos ya instalados van a detectar la nueva versión
   en su próximo arranque y ofrecer descargarla.

Por diseño, la descarga es semi-automática (el juego baja el instalador y
te avisa dónde quedó), no un reemplazo silencioso del `.exe` en caliente:
un self-update que se sobreescribe a sí mismo mientras corre es propenso a
fallar (antivirus, archivo bloqueado por el propio proceso, permisos de
Windows) y es mucho más difícil de depurar en remoto si algo sale mal en
la PC de un cliente. Si más adelante quieres un instalador silencioso, se
puede armar con un pequeño updater aparte (un segundo .exe que solo
reemplaza archivos y relanza el juego).

---

## 7. Cambiar precio o duración del plan

Todo vive en un solo lugar: `license_generator.py` → diccionario `PLANES`.
Hoy solo existe `"mensual"` ($5 / 30 días); cambia `precio` o `dias` ahí y
se actualiza en la landing y el panel admin. Si en el futuro quieres
agregar otro plan, agrega la entrada en `PLANES` y en `_PREFIJO_PLAN` /
`_CODIGO_PLAN` (mismo archivo) — el resto del sistema ya está preparado
para varios planes, solo lo dejamos reducido a uno por ahora.

---

## 8. Desplegar a producción

- Usa Postgres en vez de SQLite (`DATABASE_URL=postgresql://...`) si esperas
  volumen alto — SQLite funciona bien para empezar.
- Sirve con `gunicorn app:app` detrás de Nginx/Caddy con HTTPS.
- Sube tu instalador más reciente a `downloads/` y actualiza
  `DOWNLOAD_LATEST_PATH` / `DOWNLOAD_LATEST_VERSION` en `.env`.
- Cambia `ADMIN_PASSWORD` a algo fuerte antes de exponerlo a internet.
- Nunca subas tu `.env` (con `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID`,
  etc.) a un repositorio público — este proyecto no trae ningún `.env` con
  claves reales, solo `config.py` leyendo variables de entorno vacías por
  defecto.

---

## 9. Sobre el nombre

"Quid Game TikTok" se acerca fonéticamente a *Squid Game*, que es una marca
registrada de Netflix. Vale la pena que lo tengas presente: si el negocio
crece, un nombre demasiado parecido puede generar un reclamo de marca o un
retiro del contenido en TikTok. La arquitectura de este proyecto (marca en
`GAME_NAME`, en `config.py`) está pensada para que renombrar el producto más
adelante sea un cambio de una sola línea si decides curarte en salud.
