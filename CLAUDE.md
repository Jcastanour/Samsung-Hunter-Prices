# Samsung CO Coupon Hunter — instrucciones para el routine

Este repositorio contiene un cazador de cupones de Samsung Colombia que se ejecuta diariamente como una **Routine de Claude Code**.

## Tu trabajo cada vez que este routine corra

Sigue estos pasos en orden, sin desviarte. Si algo falla, reporta el error pero continúa con los pasos posteriores que no dependan del paso fallido.

### 1. Setup del entorno

```bash
pip install -q -r requirements.txt
```

### 2. Ejecuta el cazador

```bash
python3 samsung_hunter.py
```

Esto:
- Descarga el listado de T&C de samsung.com/co/info/tyc/
- Detecta PDFs nuevos vs `state.json` (commiteado en el repo)
- Analiza cada PDF buscando anomalías reales (montos fijos en pesos, descuentos altos, BOGOs, stacking abierto)
- Para PDFs con score ≥8 que toquen S24/S25/S26/lavadoras/neveras, scrapea precios reales en samsung.com/co
- Genera `reportes/reporte_<fecha>.md`
- Si encuentra anomalías score ≥10 o PDFs nuevos, genera `alerta.json`

### 3. Si existe `alerta.json`, manda el mensaje por Telegram

Lee el archivo `alerta.json`. Tiene esta estructura:

```json
{
  "timestamp": "...",
  "anomalias_count": N,
  "nuevos_count": M,
  "mensaje_telegram": "🚨 ..."
}
```

Usa el conector MCP de Telegram para enviar el campo `mensaje_telegram` a mi chat. Usa formato Markdown.

**Si NO existe `alerta.json`, no envíes nada.** No mandes "todo bien" ni "sin novedades" — solo silencio cuando no hay nada anómalo.

### 4. Commitea los cambios

```bash
git add state.json reportes/ alerta.json 2>/dev/null || true
git commit -m "chore: corrida $(date +%Y-%m-%d)" || echo "Sin cambios"
git push origin claude/samsung-hunter-$(date +%Y%m%d) || git push
```

(Las routines están autorizadas a empujar a ramas `claude/`. No empujes directo a `main`.)

## Qué cuenta como "anomalía real"

El script asigna puntos así:

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

**Score ≥10 = alertar por Telegram.** Bajo eso es ruido rutinario.

## Lo que el usuario está cazando

El usuario encontró una vez un cupón que tumbó un Galaxy S24 de $2.4M a $1.1M (descuento de $1.3M). Quiere replicar esa caza. Específicamente le interesan:

- Galaxy S24, S25, S26 (todas las variantes)
- Plegables Z Fold, Z Flip
- Lavadoras y secadoras
- Neveras y nevecones (especialmente Bespoke)
- Galaxy Tab S premium

NO le interesan los descuentos rutinarios del 5%, 10%, ni "envío gratis".

## Si el script falla

- 403 al scrapear samsung.com → reintenta una vez. Si vuelve a fallar, corre con `python3 samsung_hunter.py --no-prices` para skip del scraping.
- Errores de PDF parsing → ignora, sigue con el siguiente.
- Si el script no produce `alerta.json` y no hay PDFs nuevos, NO mandes Telegram.

## Estado del repo

- `state.json` — qué PDFs ya viste y su tamaño/score (no borrarlo)
- `reportes/` — historial de reportes diarios
- `alerta.json` — solo existe el día que hay anomalía. Bórralo automáticamente si no hay nada hoy.
