# Estudio piloto de APIs

5 nov 2026. Llamadas reales desde el Mac, sin claves de pago. Complementa la [referencia técnica](reference.md): aquí está lo que las APIs devuelven de verdad y lo que hay que tener en cuenta al implementarlas.

## Resumen

| Fuente | ¿Responde? | Lo más importante para implementar |
|---|---|---|
| pdufa.bio | Sí, sin clave | 118 PDUFA (57 decididos, 60 próximos, 1 retirado), solo desde el 18-jun-2026. Plan gratuito: `history_access: false`; solo 9 eventos traen `date_history` |
| SEC submissions | Sí, con `User-Agent` (sin él, 403) | Listado de filings por empresa; arrays paralelos en `filings.recent` |
| SEC búsqueda de texto completo | Sí | Solo metadatos, sin fragmento del texto: hay que descargar cada documento |
| SEC XBRL `companyfacts` | Sí, ~2 MB por empresa | La caja está repartida en varios conceptos; mezcla periodos trimestrales y acumulados |
| SEC 8-K Atom | Sí | Todas las empresas, sin filtro de sector |
| openFDA `drugsfda` | Sí, sin clave | No incluye productos de CBER (terapia celular y génica); ~1 semana de retraso; casi todo genéricos |
| openFDA `transparency/crl` | Sí | `last_updated` 13-ago-2026: casi 3 meses sin actualizar |
| ClinicalTrials.gov v2 | Sí | Buscar por fármaco trae ruido; el historial de versiones no es accesible (403) |
| Europe PMC | **No** (503 en 3 intentos) | Hace falta alternativa |
| PubMed E-utilities | Sí | Sirve como alternativa a Europe PMC |
| yfinance | Sí | Diferenciales enormes en opciones de biotech pequeñas; no tiene precios de empresas que ya no cotizan |
| Kalshi | Sí, sin clave | ~10 mercados de fármacos abiertos, repartidos en muchas series y categorías; volumen de 1.000 a 11.000 $ |
| Polymarket | Sí | Solo 2 mercados de la FDA activos y ninguno de biotech pequeña |
| RSS de la FDA | Sí | 20 entradas por feed |
| RSS de PR Newswire (salud) | Sí | 20 entradas |
| RSS de GlobeNewswire | **No** (403 con la URL de prueba) | Buscar la URL correcta por industria u organización |
| Federal Register | Sí | Mucho ruido: renovaciones de comités y nominaciones |

## Eventos de referencia: comprobación

| Caso | Plan | Datos reales |
|---|---|---|
| SMMT, ivonescimab | PDUFA 14-nov-2026, contrato en Kalshi | Fecha correcta en pdufa.bio (fuente: 8-K 29-ene-2026); `indication` vacío. Kalshi `KXIVONESCIMAB-27-Y`, en la categoría *Financials*, 61–66 % Sí. El contrato dice «decisión en 2026», no la fecha PDUFA |
| SVRA, molgramostim | Extensión 22-ago → 22-nov | Correcto: lo dicen los 10-Q de mayo y agosto. pdufa.bio tiene el 22-nov pero sin historial y con `goal_date_held: true`. Buen caso de «agregador sin historial» |
| NUVL, neladalkib | Prioritaria, 27-nov-2026 | **Desfasado.** GSK compró Nuvalent en julio de 2026; el ticker del evento ahora es GSK y la fecha bajó a precisión de mes (nov-2026). NUVL ya no cotiza |
| CAPR, deramiocel | Comité 29-jul-2026 | Correcto: voto 3–9 en contra. Además, extensión 22-ago → 22-nov (8-K del 24-ago). Es CBER: no aparecerá en `drugsfda` |

Sustituto propuesto para NUVL: **zidesamtinib** (Nuvalent, NDA220185), PDUFA 18-sep-2026 y aprobado el 22-jul-2026 según openFDA. Prueba el caso «decisión antes de la fecha».

## Notas por fuente

### pdufa.bio

- `GET /api/v1/pdufa?limit=1000` devuelve todo en una llamada (172 KB). `/events` junta PDUFA, comités, lecturas y congresos (502 eventos, 729 KB).
- Respuesta: `{meta, data[]}`. `meta` trae `total`, `as_of`, `data_built_at` y la licencia («Attribution + link-back required»).
- `id` es estable aunque cambie la fecha, pero contiene la fecha original (`pdufa_capr_2026-08-22` tiene fecha 22-nov). El `ticker` sí puede cambiar (Nuvalent → GSK). Guardar por `id`, nunca por ticker ni fecha.
- Como el plan gratuito no da historial completo, el sistema debe guardar su propia copia diaria y construir el historial comparando.
- Campos útiles que el plan no menciona: `decision_date`, `fda_action_date`, `decision_source_url`, `outcome` (Approved, CRL), `market_cap_usd`, `cash_runway_months`, `cohort_move_*`, `runup_summary`.
- `/usage` informa de la cuota; las cabeceras `x-ratelimit-*` también.
- En el plan gratuito, 54 de 57 decididos son aprobaciones: no sirve como tasa base sin revisar que no falten CRL.

### SEC EDGAR

- Sin `User-Agent` responde 403. Con uno genérico con email funciona.
- `submissions`: `filings.recent` es un objeto de arrays paralelos (`form[i]`, `filingDate[i]`, `accessionNumber[i]`, `primaryDocument[i]`, `items[i]`).
- Índice de un filing: `/Archives/edgar/data/{cik}/{accession sin guiones}/index.json` lista los anexos (EX-99.1).
- Búsqueda de texto completo: `hits.hits[]._source` trae `ciks`, `display_names`, `form`, `file_date`, `file_type`, `adsh`, `items`, `sics`. El `_id` es `adsh:fichero`. No trae texto: hay que descargar cada documento.
- «PDUFA» en 8-K, últimos 7 días: 34 resultados, casi todos resultados trimestrales. Filtrar por `sics` (2834, 2836) y por `items` (8.01) reduce ruido; el resto lo tiene que leer el LLM.
- XBRL: la caja de Savara es 41,8 M$ en `CashAndCashEquivalentsAtCarryingValue` pero 131 M$ más en `ShortTermInvestments`. Sumar los conceptos de caja e inversiones. Para el gasto trimestral, usar las filas con `frame` tipo `CY2026Q2`; las demás son acumuladas.

### openFDA

- Con `[` en la URL, curl necesita `-g` (o codificar). «Sin resultados» devuelve 404 con `NOT_FOUND`, no una lista vacía.
- `drugsfda`: filtrar `application_number` por `NDA` o `BLA`; el resto son genéricos. Fechas como `20261030`. `review_priority` viene en cada `submission`.
- No están ELEVIDYS ni CASGEVY: los productos de CBER no aparecen. Para CBER, usar la página de aprobaciones de CBER y el 8-K de la empresa.
- CRL: fechas como `08/07/2026` (otro formato). Útil para leer motivos, no para detectar decisiones.

### ClinicalTrials.gov v2

- `query.intr=molgramostim` devuelve también ensayos de sargramostim (expande sinónimos). Mejor `query.spons=<empresa>` y elegir el NCT a mano una vez.
- `fields=` reduce mucho la respuesta. La ficha completa trae `protocolSection`, `derivedSection` y `hasResults`.
- `/api/int/studies/{NCT}/history` responde 403: el historial hay que construirlo con copias diarias.

### Literatura

- Europe PMC devolvió 503 («Search service is temporarily unavailable») en tres intentos seguidos.
- PubMed: `esearch` (lista de PMID) y luego `esummary` (título, revista, fecha, tipo). 98 artículos de molgramostim; los dos más recientes son de septiembre de 2026.

### yfinance

- Precio, capitalización y cadena de opciones en 2–5 s por empresa.
- SVRA: solo 4 vencimientos mensuales. CAPR y SMMT: semanales.
- Diferenciales muy amplios: call ATM de SVRA con oferta 0 y demanda 4,90 $ sobre una acción de 4,37 $; volatilidades implícitas de 200–700 %. El movimiento implícito solo tiene sentido con filtros de diferencial e interés abierto, y con la foto tomada tras el cierre.
- `history` de NUVL: sin datos («possibly delisted»). Un backtest solo con yfinance pierde las empresas compradas o quebradas.

### Kalshi

- Lectura sin autenticación en `external-api.kalshi.com` y en `api.elections.kalshi.com` (mismas respuestas).
- Los contratos de fármacos no están en una sola serie: `KXFDAAPPROVE`, `KXFDAAPPROVAL`, `KXFDAAPPROVALDATE*`, `KXNEWDRUGAPP*`, `KXIVONESCIMAB` (en *Financials*), etc. Para descubrirlos hay que bajar `/series` entero (15.813 series, 20 MB) y filtrar por texto.
- Precios como texto en dólares: `yes_bid_dollars`, `yes_ask_dollars`, `last_price_dollars`; volumen en `volume_fp`. Las reglas vienen en `rules_primary`.

### Polymarket

- `gamma-api.polymarket.com/public-search?q=` busca de forma difusa («Summit Therapeutics» devuelve fútbol).
- `clobTokenIds` y `outcomePrices` son JSON dentro de un texto: hay que decodificarlos dos veces.
- `/midpoint`, `/book` y `/prices-history` funcionan con el token del «Sí».
- Solo dos mercados de la FDA activos (retatrutide y vacuna contra el cáncer de piel). Poco útil para este sistema.

### RSS y Federal Register

- FDA (`press-releases`, `drugs`) y PR Newswire salud: funcionan, 20 entradas cada uno.
- GlobeNewswire: 403 con la URL de industria probada. Business Wire: falta encontrar el identificador del feed de salud.
- Federal Register: responde bien, pero la búsqueda «advisory committee» trae sobre todo renovaciones y nominaciones. Filtrar por tipo de documento y título «Notice of Meeting».

## Precios históricos con empresas que ya no cotizan

yfinance no devuelve nada para un ticker que dejó de cotizar (NUVL tras la compra de GSK). Para un backtest sin sesgo de supervivencia:

- **DoltHub `post-no-preference/stocks`**: gratis (CC BY-SA 4.0), desde ~2011, se actualiza a diario. Comprobado con MRTX, KRTX, CLVS y NUVL (NUVL tiene precios hasta el 14-jul-2026). API SQL: `https://www.dolthub.com/api/v1alpha1/post-no-preference/stocks/master?q=SELECT ... FROM ohlcv WHERE act_symbol='NUVL' AND date IN (...)`. Precios sin ajustar: los splits van en la tabla `split`. La API es lenta con rangos largos; mejor pedir fechas concretas o clonar la base con `dolt clone`. Un ticker reutilizado puede mezclar dos empresas.
- **Sharadar SEP** (de pago, ~299 $/año, uso personal): empresas que ya no cotizan, identificador fijo por empresa, precios ajustados y sin ajustar. Opción si DoltHub se queda corto.
- Hugging Face, GitHub y Kaggle: nada útil (solo grandes empresas, datos hasta 2017 o de pago).
