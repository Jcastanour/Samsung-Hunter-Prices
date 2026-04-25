# 🎯 Samsung CO Coupon Hunter

Caza diariamente cupones anómalos en términos y condiciones de Samsung Colombia. Diseñado para correr como **Claude Code Routine** en la nube de Anthropic.

Detecta señales como:
- 💰 Cupones con monto fijo en pesos (tipo "descuento de $1.300.000")
- 🎟️ Vouchers con monto específico
- 🔥 Descuentos ≥20%
- 🎁 BOGO, 2x1, productos sin costo
- 🔗 Stacking inusual ("acumulable con todas las promociones")

Productos prioritarios: Galaxy S24/S25/S26, plegables, lavadoras, neveras Bespoke.

---

## Setup paso a paso

### Paso 1 — Sube este repo a GitHub

1. Crea un repo nuevo en GitHub (privado o público, da igual). Por ejemplo: `samsung-hunter`.
2. Sube los archivos de esta carpeta:

```bash
cd samsung-hunter
git init
git add .
git commit -m "init: samsung coupon hunter"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/samsung-hunter.git
git push -u origin main
```

### Paso 2 — Conecta GitHub a tu cuenta Claude.ai

Si no lo has hecho antes:

1. Ve a https://claude.ai/code
2. Corre `/web-setup` en cualquier sesión, o conéctate desde la UI cuando te pida acceso a GitHub.
3. Autoriza Claude para acceder al repo `samsung-hunter`.

### Paso 3 — Conecta Telegram como conector MCP

1. Crea un bot de Telegram con [@BotFather](https://t.me/botfather): `/newbot` → guarda el token.
2. Encuentra tu chat ID con [@userinfobot](https://t.me/userinfobot): te lo da en el primer mensaje.
3. Ve a **Settings → Connectors** en claude.ai.
4. Agrega un conector MCP de Telegram (busca uno publicado o instala el oficial). Pásale tu BOT_TOKEN y CHAT_ID.

> Nota: si no encuentras un MCP de Telegram que te convenza, hay un fallback simple — el routine puede llamar a `https://api.telegram.org/bot<TOKEN>/sendMessage` con un POST. Si prefieres esa ruta, agrégalo como variable de entorno en el cloud environment del routine y modifica el `CLAUDE.md` para que use `curl` en lugar del conector MCP.

### Paso 4 — Crea el routine

1. Ve a https://claude.ai/code/routines
2. Click **New routine**.
3. Configura:
   - **Name**: `Samsung Hunter Diario`
   - **Prompt**: pega el contenido completo de `CLAUDE.md` (o pon: *"Lee `CLAUDE.md` en el repo y sigue las instrucciones al pie de la letra."*)
   - **Repositories**: selecciona el `samsung-hunter` que acabas de subir.
   - **Allow unrestricted branch pushes**: actívalo si quieres que commitee a `main`. Si no, dejará todo en ramas `claude/...`.
   - **Environment**: el default sirve. Si quieres más velocidad, configura uno con setup script `pip install -r requirements.txt`.
   - **Connectors**: deja solo Telegram (quita los demás para reducir superficie).
   - **Trigger**: *Schedule → Daily → 12:00 PM*.
4. Click **Create**.

### Paso 5 — Probar antes del primer schedule

En la página del routine, click **Run now**. Deberías:
- Ver una sesión nueva en `claude.ai/code/sessions`.
- Que Claude clone el repo, instale deps, corra el script.
- Si hay anomalías, recibir Telegram con el resumen.
- Que se cree un commit en rama `claude/samsung-hunter-<fecha>` con el state.json y reporte actualizados.

Si todo OK, queda armado para correr cada día a las 12:00 PM Colombia.

---

## Cómo funciona internamente

```
samsung_hunter.py
    ├─ Descarga lista de PDFs de samsung.com/co/info/tyc/
    ├─ Descarga cada PDF, extrae texto
    ├─ Aplica regex anti-anomalías (montos $, %, BOGO, etc.)
    ├─ Para PDFs interesantes con productos S24-S26/línea blanca:
    │     └─ Busca refs SM-XXX en samsung.com/co
    │     └─ Extrae precio actual (JSON-LD o spans)
    │     └─ Calcula precio final estimado con el % del cupón
    ├─ Guarda state.json (sizes y scores por PDF para detectar cambios)
    ├─ Genera reportes/<fecha>.md
    └─ Si score ≥10 o PDFs nuevos: genera alerta.json para Telegram
```

## Tuning

Edita `samsung_hunter.py`:
- `INTERES_PRODUCTOS` — qué referencias te importan
- `SEÑALES_ANOMALAS` — qué patrones suben score (con su peso)
- `SCORE_ALERTA` — umbral para mandar Telegram (default: 10)

## Limitaciones conocidas

- Samsung CO a veces tira 403 desde IPs de datacenter. Las routines de Anthropic corren desde IPs cloud — si bloquean, el script tiene reintentos y un modo `--no-prices`.
- El scraping de precios depende del HTML actual de samsung.com/co. Si rediseñan, hay que ajustar los selectores en `extraer_precio_de_html()`.
- Routines tienen un cap diario de runs en plan Max. 1 corrida diaria está muy por debajo del límite.

## Test local antes de subir

```bash
pip install -r requirements.txt
python3 samsung_hunter.py
```

(Desde IPs colombianas residenciales debería funcionar sin 403.)
# Samsung-Hunter-Prices
