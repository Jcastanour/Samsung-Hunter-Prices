# Samsung CO Coupon Hunter — instrucciones para el routine

Este repo caza cupones grandes en T&C de Samsung Colombia y manda Telegram diario.

## Tu trabajo cada vez que el routine corra

Sigue estos pasos en orden. Si algo falla, reporta el error pero continúa con los pasos posteriores que no dependan del paso fallido.

### 1. Setup

```bash
pip install -q -r requirements.txt
```

(El environment ya hace esto en setup script, pero por si acaso.)

### 2. Ejecuta el cazador

```bash
python3 samsung_hunter.py
```

Esto genera siempre:
- `state.json` actualizado (qué PDFs ya se vieron)
- `reportes/reporte_<fecha>.md` (legible)
- `alerta.json` (SIEMPRE existe, tiene un campo `es_alerta` true/false según haya anomalías)

Si falla con error 403 al scrapear precios, reintenta con `--no-prices`:
```bash
python3 samsung_hunter.py --no-prices
```

### 3. Manda Telegram (SIEMPRE)

El archivo `alerta.json` siempre existe. Su campo `mensaje_telegram` está pre-formateado:
- Día tranquilo: mensaje breve "😴 Nada nuevo, X PDFs revisados"
- Día con novedades/anomalías: alerta detallada con productos, scores, precios

Manda el mensaje SIEMPRE, sin importar si es alerta o "todo tranquilo":

```bash
MENSAJE=$(jq -r .mensaje_telegram alerta.json)
curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
  --data-urlencode "chat_id=$TELEGRAM_CHAT_ID" \
  --data-urlencode "parse_mode=Markdown" \
  --data-urlencode "text=$MENSAJE"
```

Verifica que la respuesta de Telegram tenga `"ok":true`. Si trae `"ok":false`, imprime el error y sigue.

### 4. Commit y push

```bash
git add state.json reportes/ alerta.json
git -c user.email="claude@anthropic.com" -c user.name="Claude Routine" \
  commit -m "chore: corrida $(date +%Y-%m-%d)" || echo "Sin cambios para commitear"

# Push a rama claude/ (si la branch policy lo restringe)
RAMA="claude/samsung-hunter-$(date +%Y%m%d)"
git push origin HEAD:$RAMA 2>/dev/null || git push origin HEAD
```

Si el push falla por permisos, no es fatal — el reporte ya está mandado por Telegram. Lo importante es que la próxima corrida tenga un `state.json` actualizado, así que intenta resolver el push si puedes.

## Qué cuenta como "anomalía real" (score ≥10)

| Señal | Puntos |
|---|---|
| Descuento monto fijo en pesos (ej: "descuento de $1.300.000") | +12 |
| Bono o voucher con monto fijo | +12 |
| Monto en COP suelto en el T&C | +8-10 |
| Descuento ≥20% | +6 |
| BOGO / 2x1 | +5 |
| "Acumulable con todas las promociones" (stacking abierto) | +5 |
| Promo Live (efímera) | +4 |
| Descuento 15-19% | +3 |
| Producto de interés (S24/S25/S26/lavadora/nevera) | +2 cada match |
| Promo vencida | -5 |

## Lo que el usuario está cazando

El usuario encontró una vez un cupón que tumbó un Galaxy S24 de $2.4M a $1.1M (descuento de $1.3M). Quiere replicar eso. Le interesan:

- Galaxy S24, S25, S26 (todas las variantes)
- Plegables Z Fold, Z Flip
- Lavadoras y secadoras
- Neveras y nevecones (especialmente Bespoke)
- Galaxy Tab S premium

NO le interesan los descuentos rutinarios del 5%, 10%, ni "envío gratis".

## Variables disponibles en el environment

- `TELEGRAM_BOT_TOKEN` — token del bot de Telegram (@samsunghunterbot)
- `TELEGRAM_CHAT_ID` — chat ID del usuario

## Estado del repo

- `state.json` — qué PDFs ya viste y su tamaño/score (NO borrar)
- `reportes/` — historial de reportes diarios
- `alerta.json` — siempre se sobreescribe en cada corrida