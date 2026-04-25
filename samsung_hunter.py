#!/usr/bin/env python3
"""
Samsung Colombia - Cazador de Ofertas Anómalas
================================================
Detecta cupones grandes (montos fijos en pesos, descuentos ≥15%, BOGOs,
stacking abierto) en T&C de Samsung CO. Scrapea precios reales para
calcular el ahorro efectivo en pesos.

Foco: S24, S25, S26, plegables, lavadoras, neveras, Bespoke.

Uso:
    python3 samsung_hunter.py [--no-prices]

Salidas:
    state.json                — estado para detectar cambios día a día
    reportes/<fecha>.md       — reporte legible
    alerta.json               — solo se crea si hay anomalía real (score ≥10)
                                 Claude lee este archivo y manda Telegram

Dependencias:
    pip install requests pypdf beautifulsoup4
"""

import argparse
import io
import json
import re
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, quote

import requests
from pypdf import PdfReader
from bs4 import BeautifulSoup

# ============================================================
# CONFIGURACIÓN
# ============================================================

TYC_URL = "https://www.samsung.com/co/info/tyc/"
SAMSUNG_BASE = "https://www.samsung.com"
STATE_FILE = Path("state.json")
REPORTS_DIR = Path("reportes")
ALERT_FILE = Path("alerta.json")
REPORTS_DIR.mkdir(exist_ok=True)

# Productos prioritarios (case insensitive). Score +2 cada match.
INTERES_PRODUCTOS = [
    r"\bS24\b", r"\bS25\b", r"\bS26\b",
    r"\bA5[0-9]\b", r"\bA3[0-9]\b",
    r"\bZ\s?Fold\b", r"\bZ\s?Flip\b",
    r"lavadora", r"secadora",
    r"nevera", r"nevec[oó]n", r"refriger",
    r"\bBESPOKE\b",
    r"Galaxy\s+Tab\s+S\d",
]

# Señales de anomalía REAL — lo que tumba precio
SEÑALES_ANOMALAS = [
    # Montos fijos en pesos (LO QUE MÁS BUSCAS - tipo S24 -1.3M)
    (r"descuento\s+(?:de|por)\s+\$\s*[\d\.,]{6,}", "💰 Descuento monto fijo COP", 12),
    (r"bono\s+(?:de|por)?\s*\$?\s*[\d\.,]{6,}", "🎁 Bono con monto fijo", 12),
    (r"voucher\s+(?:de|por)?\s*\$?\s*[\d\.,]{6,}", "🎟️ Voucher con monto fijo", 12),
    (r"COP\s*\$?\s*[1-9][\.,\d]{6,}", "💰 Monto en COP", 10),
    (r"\$\s*[1-9][\.,]?\d{3}[\.,]?\d{3}", "💰 Monto en pesos suelto", 8),

    # Descuentos altos
    (r"\b(2[0-9]|[3-9][0-9])\s*%", "🔥 Descuento ≥20%", 6),
    (r"\b(1[5-9])\s*%", "⭐ Descuento 15-19%", 3),

    # BOGO / 2x1 / regalos
    (r"\bBOGO\b", "🎁 BOGO (2x1)", 5),
    (r"2x1|dos\s*por\s*uno", "🎁 2x1", 5),
    (r"sin\s+costo\s+adicional", "🎁 Producto adicional sin costo", 4),
    (r"recibirá\s+(?:un|una|unos|unas)\s+\w+\s+\w+\s+(?:gratis|sin\s+costo)", "🎁 Regalo gratis", 4),

    # Stacking inusual
    (r"acumulable\s+con\s+todas\s+las\s+promociones", "🔗 Stacking ABIERTO (raro)", 5),

    # Promos puntuales (suelen tener precios brutales)
    (r"\blive\s+\d", "📺 Promo Live (efímera)", 4),
    (r"\bpreventa\b", "🎯 Preventa", 2),
]

# User-Agent realista para evitar 403
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Score mínimo para alertar por Telegram
SCORE_ALERTA = 10

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

# ============================================================
# DESCARGA
# ============================================================

def fetch(url: str, binary: bool = False, timeout: int = 30):
    """Descarga URL con reintentos."""
    for intento in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r.content if binary else r.text
        except requests.RequestException as e:
            if intento == 2:
                raise
            print(f"   ⚠️  Reintento {intento+1}: {e}", file=sys.stderr)
            time.sleep(2 + intento * 2)


def extraer_pdfs_de_lista(html: str) -> list[dict]:
    """Extrae enlaces a PDFs de la página de T&C."""
    patron = re.compile(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>([^<]+)</a>', re.IGNORECASE)
    pdfs, vistos = [], set()
    for url, texto in patron.findall(html):
        url_abs = urljoin(TYC_URL, url)
        if url_abs in vistos:
            continue
        vistos.add(url_abs)
        nombre = re.sub(r"\s+", " ", texto).strip()
        pdfs.append({"url": url_abs, "nombre": nombre})
    return pdfs


def extraer_texto_pdf(pdf_bytes: bytes) -> str:
    """Texto plano del PDF."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as e:
        return f"[ERROR_PARSING: {e}]"


# ============================================================
# SCRAPING DE PRECIOS EN SAMSUNG.COM/CO
# ============================================================

# Map de referencia SM-XXX a slug aproximado. Como Samsung CO usa URLs raras,
# mejor estrategia: buscar el SKU directamente en su buscador.
PRECIO_CACHE: dict[str, dict] = {}


def buscar_precio_por_referencia(referencia_sm: str) -> dict | None:
    """
    Busca el precio del producto en samsung.com/co usando la API de búsqueda interna.
    Retorna {nombre, precio_normal, precio_actual, descuento_visible, url} o None.
    """
    if referencia_sm in PRECIO_CACHE:
        return PRECIO_CACHE[referencia_sm]

    # Estrategia 1: usar el endpoint de búsqueda de Samsung CO
    # Samsung devuelve JSON-LD en sus páginas de producto
    search_url = f"https://www.samsung.com/co/search/?searchvalue={quote(referencia_sm)}"
    try:
        html = fetch(search_url)
        soup = BeautifulSoup(html, "html.parser")

        # Buscar enlaces a productos que contengan la referencia
        enlaces = soup.find_all("a", href=re.compile(r"/co/[a-z\-]+/[a-z0-9\-]+/", re.IGNORECASE))
        producto_url = None
        for a in enlaces:
            href = a.get("href", "")
            if referencia_sm.lower() in href.lower():
                producto_url = urljoin(SAMSUNG_BASE, href)
                break

        if not producto_url:
            PRECIO_CACHE[referencia_sm] = None
            return None

        # Visitar la página del producto y extraer precio
        time.sleep(0.5)  # cortesía
        html_prod = fetch(producto_url)
        info = extraer_precio_de_html(html_prod, referencia_sm, producto_url)
        PRECIO_CACHE[referencia_sm] = info
        return info
    except Exception as e:
        print(f"   ⚠️  No pude buscar precio de {referencia_sm}: {e}", file=sys.stderr)
        PRECIO_CACHE[referencia_sm] = None
        return None


def extraer_precio_de_html(html: str, referencia: str, url: str) -> dict | None:
    """Busca JSON-LD o spans de precio en el HTML del producto."""
    soup = BeautifulSoup(html, "html.parser")
    info = {"referencia": referencia, "url": url, "nombre": None,
            "precio_normal": None, "precio_actual": None}

    # Estrategia A: JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "{}")
            if isinstance(data, dict) and data.get("@type") == "Product":
                info["nombre"] = data.get("name")
                offers = data.get("offers", {})
                if isinstance(offers, dict):
                    info["precio_actual"] = _to_int(offers.get("price"))
                elif isinstance(offers, list) and offers:
                    info["precio_actual"] = _to_int(offers[0].get("price"))
                if info["precio_actual"]:
                    info["precio_normal"] = info["precio_actual"]
                    break
        except (json.JSONDecodeError, AttributeError):
            continue

    # Estrategia B: meta tags og:price o data-price
    if not info["precio_actual"]:
        meta_price = soup.find("meta", {"property": "product:price:amount"})
        if meta_price:
            info["precio_actual"] = _to_int(meta_price.get("content"))

    # Estrategia C: spans con precios (fallback robusto)
    if not info["precio_actual"]:
        # Samsung suele tener clases tipo "price__current", "s-prc__num"
        selectores = [
            ".s-prc__num", ".price__current", ".s-product-price__num",
            "[class*=price]", "[data-price]"
        ]
        for sel in selectores:
            for el in soup.select(sel):
                txt = el.get_text(strip=True)
                num = _extraer_numero_pesos(txt)
                if num and num > 100000:  # filtrar precios absurdos
                    info["precio_actual"] = num
                    break
            if info["precio_actual"]:
                break

    # Precio "antes" / tachado
    for sel in [".s-prc__before", ".price__before", ".s-product-price__before"]:
        el = soup.select_one(sel)
        if el:
            num = _extraer_numero_pesos(el.get_text(strip=True))
            if num:
                info["precio_normal"] = num
                break

    if not info["precio_normal"] and info["precio_actual"]:
        info["precio_normal"] = info["precio_actual"]

    if not info["nombre"]:
        og_title = soup.find("meta", {"property": "og:title"})
        if og_title:
            info["nombre"] = og_title.get("content")

    return info if info["precio_actual"] else None


def _to_int(val) -> int | None:
    if val is None:
        return None
    try:
        return int(float(str(val).replace(",", "").replace(".", "").replace("$", "").strip()))
    except (ValueError, TypeError):
        return None


def _extraer_numero_pesos(txt: str) -> int | None:
    """Convierte '$5.999.000' → 5999000."""
    m = re.search(r"\$?\s*([\d\.,]+)", txt)
    if not m:
        return None
    num = m.group(1).replace(".", "").replace(",", "")
    try:
        n = int(num)
        return n if 100000 < n < 50000000 else None
    except ValueError:
        return None


def extraer_referencias_sm(texto: str) -> list[str]:
    """Extrae todas las referencias SM-XXXXX del texto del PDF."""
    return list(set(re.findall(r"\bSM-[A-Z][A-Z0-9]+\b", texto)))


# ============================================================
# ANÁLISIS DE ANOMALÍAS
# ============================================================

@dataclass
class Resultado:
    nombre: str
    url: str
    score: int = 0
    productos: list[str] = field(default_factory=list)
    señales: list[str] = field(default_factory=list)
    contextos: list[str] = field(default_factory=list)
    referencias_sm: list[str] = field(default_factory=list)
    precios_estimados: list[dict] = field(default_factory=list)
    vigencia: str = "no detectada"
    activo: bool = True


def extraer_contexto(texto: str, patron: str, ventana: int = 120, max_ctx: int = 2) -> list[str]:
    contextos = []
    for m in re.finditer(patron, texto, re.IGNORECASE):
        ini = max(0, m.start() - ventana)
        fin = min(len(texto), m.end() + ventana)
        frag = re.sub(r"\s+", " ", texto[ini:fin]).strip()
        contextos.append(f"...{frag}...")
        if len(contextos) >= max_ctx:
            break
    return contextos


def extraer_porcentaje_principal(texto: str) -> int | None:
    """Heurística: el % de descuento más mencionado en el PDF."""
    pct = re.findall(r"\b(\d{1,2})\s*%", texto)
    if not pct:
        return None
    from collections import Counter
    nums = [int(p) for p in pct if 1 <= int(p) <= 99]
    if not nums:
        return None
    return Counter(nums).most_common(1)[0][0]


def extraer_vigencia(texto: str) -> str:
    patrones = [
        r"válida desde el día (\d{1,2} de \w+ de \d{4}) hasta el día (\d{1,2} de \w+ de \d{4})",
        r"vigencia[:\s]+desde el (\d{1,2} de \w+ de \d{4}).*?hasta el (\d{1,2} de \w+ de \d{4})",
    ]
    for p in patrones:
        m = re.search(p, texto, re.IGNORECASE)
        if m:
            return f"{m.group(1)} → {m.group(2)}"
    return "no detectada"


def es_vigente(vigencia: str) -> bool:
    if vigencia == "no detectada":
        return True
    m = re.search(r"(\d{1,2}) de (\w+) de (\d{4}).*→.*(\d{1,2}) de (\w+) de (\d{4})", vigencia)
    if not m:
        return True
    try:
        ini = datetime(int(m.group(3)), MESES[m.group(2).lower()], int(m.group(1)))
        fin = datetime(int(m.group(6)), MESES[m.group(5).lower()], int(m.group(4)))
        hoy = datetime.now()
        return ini <= hoy <= fin
    except (KeyError, ValueError):
        return True


def analizar_pdf(nombre: str, url: str, texto: str, scrape_precios: bool = True) -> Resultado:
    r = Resultado(nombre=nombre, url=url)

    # Productos de interés
    for patron in INTERES_PRODUCTOS:
        if re.search(patron, texto, re.IGNORECASE):
            r.productos.append(patron.replace(r"\b", "").replace("\\", ""))
            r.score += 2

    # Señales anómalas
    for patron, descripcion, peso in SEÑALES_ANOMALAS:
        matches = re.findall(patron, texto, re.IGNORECASE)
        if matches:
            ej = matches[0] if isinstance(matches[0], str) else (matches[0][0] if matches[0] else "")
            r.señales.append(f"{descripcion}: {ej!r} (x{len(matches)})")
            es_critico = "monto fijo" in descripcion.lower() or "stacking" in descripcion.lower()
            if es_critico:
                for ctx in extraer_contexto(texto, patron):
                    r.contextos.append(f"📍 {ctx}")
            r.score += peso

    # Vigencia
    r.vigencia = extraer_vigencia(texto)
    r.activo = es_vigente(r.vigencia)
    if not r.activo:
        r.score = max(0, r.score - 5)

    # Referencias SM (para scrapear precios)
    r.referencias_sm = extraer_referencias_sm(texto)[:5]  # máx 5 para no abusar

    # Scrapear precios solo para PDFs de score alto y con productos de interés
    if scrape_precios and r.score >= 8 and r.productos and r.referencias_sm:
        pct = extraer_porcentaje_principal(texto)
        for ref in r.referencias_sm[:3]:  # máx 3 productos por PDF
            info = buscar_precio_por_referencia(ref)
            if info and info.get("precio_actual"):
                precio = info["precio_actual"]
                ahorro = int(precio * pct / 100) if pct else None
                final = precio - ahorro if ahorro else None
                r.precios_estimados.append({
                    "referencia": ref,
                    "nombre": info.get("nombre"),
                    "url": info.get("url"),
                    "precio_actual": precio,
                    "descuento_pct": pct,
                    "ahorro_estimado": ahorro,
                    "precio_final_estimado": final,
                })
            time.sleep(0.5)

    return r


# ============================================================
# ESTADO Y REPORTE
# ============================================================

def cargar_estado() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"pdfs_vistos": {}, "ultima_corrida": None}


def guardar_estado(estado: dict) -> None:
    STATE_FILE.write_text(json.dumps(estado, indent=2, ensure_ascii=False))


def fmt_pesos(n) -> str:
    if n is None:
        return "?"
    return f"${n:,}".replace(",", ".")


def generar_reporte(resultados: list[Resultado], nuevos: list[str], cambiados: list[str]) -> str:
    hoy = datetime.now().strftime("%Y-%m-%d %H:%M")
    L = [f"# 🎯 Reporte Caza Samsung CO — {hoy}\n"]

    activos = sorted([r for r in resultados if r.activo], key=lambda x: x.score, reverse=True)

    if nuevos:
        L.append(f"## 🆕 PDFs NUEVOS ({len(nuevos)})\n")
        L.extend([f"- {n}" for n in nuevos])
        L.append("")

    if cambiados:
        L.append(f"## ♻️  PDFs MODIFICADOS ({len(cambiados)})\n")
        L.extend([f"- {c}" for c in cambiados])
        L.append("")

    top = [r for r in activos if r.score >= SCORE_ALERTA]
    if top:
        L.append(f"## 🔥 ANOMALÍAS (score ≥{SCORE_ALERTA}) — {len(top)}\n")
        L.append("Estas son las que se parecen al cupón de S24 -1.3M\n")
        for r in top[:15]:
            L.append(f"### [{r.score} pts] {r.nombre}")
            L.append(f"- **Vigencia**: {r.vigencia}")
            if r.productos:
                L.append(f"- **Productos**: {', '.join(set(r.productos))}")
            L.append(f"- **PDF**: {r.url}")
            L.append("- **Señales**:")
            for s in r.señales:
                L.append(f"  - {s}")
            if r.contextos:
                L.append("- **Contexto**:")
                for c in r.contextos[:3]:
                    L.append(f"  {c}")
            if r.precios_estimados:
                L.append("- **Precios reales detectados**:")
                L.append("")
                L.append("  | Producto | Precio actual | % | Ahorro | Final |")
                L.append("  |---|---|---|---|---|")
                for p in r.precios_estimados:
                    nombre = (p.get("nombre") or p["referencia"])[:50]
                    L.append(f"  | {nombre} | {fmt_pesos(p['precio_actual'])} | {p.get('descuento_pct') or '?'}% | {fmt_pesos(p.get('ahorro_estimado'))} | {fmt_pesos(p.get('precio_final_estimado'))} |")
                L.append("")
            L.append("")

    medio = [r for r in activos if 5 <= r.score < SCORE_ALERTA]
    if medio:
        L.append(f"## ⭐ Interesantes (5-{SCORE_ALERTA-1} pts) — {len(medio)}\n")
        for r in medio[:15]:
            señales_resumen = "; ".join(r.señales[:2])
            L.append(f"- **[{r.score}]** {r.nombre} — {señales_resumen}")
        L.append("")

    L.append("\n---\n## 📊 Resumen\n")
    L.append(f"- PDFs analizados: {len(resultados)}")
    L.append(f"- Activos hoy: {len(activos)}")
    L.append(f"- Anomalías altas: {len(top)}")
    L.append(f"- Nuevos: {len(nuevos)} | Modificados: {len(cambiados)}")

    return "\n".join(L)


def generar_alerta_telegram(resultados: list[Resultado], nuevos: list[str]) -> dict | None:
    """Si hay anomalías score ≥10, genera estructura JSON para que Claude mande Telegram."""
    activos = [r for r in resultados if r.activo and r.score >= SCORE_ALERTA]
    if not activos and not nuevos:
        return None

    activos.sort(key=lambda x: x.score, reverse=True)
    activos = activos[:5]

    msg = [f"🚨 *Samsung CO — {datetime.now():%d/%m %H:%M}*\n"]

    if nuevos:
        msg.append(f"🆕 *{len(nuevos)} PDFs nuevos detectados*")
        for n in nuevos[:3]:
            msg.append(f"  • {n[:80]}")
        msg.append("")

    if activos:
        msg.append(f"🔥 *{len(activos)} anomalía(s) de alto score*\n")
        for r in activos:
            msg.append(f"*{r.nombre[:90]}*")
            msg.append(f"Score: {r.score} | Vigencia: {r.vigencia}")
            if r.productos:
                msg.append(f"Productos: {', '.join(set(r.productos))}")
            for s in r.señales[:3]:
                msg.append(f"  • {s}")
            if r.precios_estimados:
                p = r.precios_estimados[0]
                nombre = (p.get("nombre") or p["referencia"])[:60]
                msg.append(f"💵 {nombre}")
                msg.append(f"   {fmt_pesos(p['precio_actual'])} → {fmt_pesos(p.get('precio_final_estimado'))} (ahorro {fmt_pesos(p.get('ahorro_estimado'))})")
            msg.append(f"📜 {r.url}")
            msg.append("")

    return {
        "timestamp": datetime.now().isoformat(),
        "anomalias_count": len(activos),
        "nuevos_count": len(nuevos),
        "mensaje_telegram": "\n".join(msg),
    }


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-prices", action="store_true", help="Skip price scraping")
    args = parser.parse_args()
    scrape = not args.no_prices

    print(f"🎯 Cazador Samsung CO — {datetime.now():%Y-%m-%d %H:%M}\n")

    print("📥 Lista de T&C...")
    html = fetch(TYC_URL)
    pdfs = extraer_pdfs_de_lista(html)
    print(f"   {len(pdfs)} PDFs\n")

    estado = cargar_estado()
    vistos_antes = estado.get("pdfs_vistos", {})

    nuevos, cambiados, resultados = [], [], []

    for i, pdf in enumerate(pdfs, 1):
        marker = " 🆕" if pdf["url"] not in vistos_antes else ""
        print(f"[{i}/{len(pdfs)}]{marker} {pdf['nombre'][:75]}")
        try:
            pdf_bytes = fetch(pdf["url"], binary=True)
            tamaño = len(pdf_bytes)

            antes = vistos_antes.get(pdf["url"], {})
            if not antes:
                nuevos.append(pdf["nombre"])
            elif antes.get("size") != tamaño:
                cambiados.append(pdf["nombre"])

            texto = extraer_texto_pdf(pdf_bytes)
            r = analizar_pdf(pdf["nombre"], pdf["url"], texto, scrape_precios=scrape)
            resultados.append(r)

            estado["pdfs_vistos"][pdf["url"]] = {
                "size": tamaño,
                "ultima_revision": datetime.now().isoformat(),
                "score": r.score,
            }
            time.sleep(0.3)
        except Exception as e:
            print(f"   ❌ {e}", file=sys.stderr)

    estado["ultima_corrida"] = datetime.now().isoformat()
    guardar_estado(estado)

    reporte = generar_reporte(resultados, nuevos, cambiados)
    archivo = REPORTS_DIR / f"reporte_{datetime.now():%Y-%m-%d}.md"
    archivo.write_text(reporte)
    print(f"\n✅ Reporte: {archivo}")

    alerta = generar_alerta_telegram(resultados, nuevos)
    if alerta:
        ALERT_FILE.write_text(json.dumps(alerta, indent=2, ensure_ascii=False))
        print(f"🚨 ALERTA generada: {ALERT_FILE}")
    elif ALERT_FILE.exists():
        ALERT_FILE.unlink()  # limpiar alerta vieja si hoy no hay nada
        print("✅ Sin anomalías hoy.")
    else:
        print("✅ Sin anomalías hoy.")


if __name__ == "__main__":
    main()
