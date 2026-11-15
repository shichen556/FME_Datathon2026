# Mejoras respecto al baseline original (main → infraestructure / v2)

# v3-Shichen (rama `infraestructure`): checklist actualizado (15-nov, 11:00)

## ✅ Hecho

### Ranking (frente al baseline de `main`)
- [x] Personalización por sesión: los productos vistos van primero (el baseline daba los mismos 10 a todos)
- [x] Co-compras: productos comprados en sesiones donde se vio el producto, con decaimiento 0,8 por antigüedad de la vista
- [x] Más vendidos de las subcategorías vistas
- [x] Más vendidos globales como relleno final (lo que reciben los shoppers sin vistas)
- [x] Diversidad: máximo 5 productos por subcategoría en co-compras y populares globales
- [x] Orden pensado para los slots: lo más probable de comprar va en el slot 1

### Datos y aprendizaje en vivo
- [x] Popularidad con peso reciente: histórico + 7 días (×5) + eventos en vivo (×20) + últimas 3 h (×40)
- [x] Usa `shop.events` en tiempo real (el baseline calculaba el ranking una sola vez)
- [x] Reconstrucción completa del modelo cada 10 min en segundo plano
- [x] No recomienda lo que el usuario ya compró en las últimas 6 h (tienda + tu propio feedback)

### Validez y fiabilidad
- [x] Filtro de agotados (cada ~2 s) e inactivos (`is_active`), que el baseline no comprobaba
- [x] Hilo `Refresher`: responder es solo Python en memoria (<1 ms)
- [x] Logging y manejo de errores; el bucle no se cae
- [x] Conserva el último modelo si falla una actualización

### Calidad del código y repositorio
- [x] ~700 líneas de tests con pytest (fases, casos límite, concurrencia, carga del modelo)
- [x] `MODEL_VERSION` separado ("v3-Shichen" en v2, "baseline" en el starter)
- [x] Clave API antigua quitada de `request.py`, que ahora lee de `.env` (commit `fix apikey`)
- [x] `.env.example` subido y quitado del `.gitignore` (commit `'re'add .env.example`)
- [x] `roadmap.md` añadido al repo
- [x] Notebook `offline_eval.ipynb` ejecutado y guardado con resultados (baseline vs coview)
- [x] Referencia offline obtenida: baseline hit rate@10 = 0,380 y SNIPS slot 1 = 0,047; coview 0,234 y 0,011

## ⏳ Pendiente

### Seguridad (urgente)
- [ ] Revocar la clave antigua de helmcode: sigue en el historial (commits `af33f96` y `c89550b`), borrarla del código no basta
- [ ] `request.py` envía `RAWTREE_API_KEY` a `api.helmcode.com`: usar otra variable (por ejemplo `HELMCODE_API_KEY`)
- [ ] Añadir `openai` y `python-dotenv` a `requirements.txt` si `request.py` se queda
- [ ] Quitar el prefijo `sk-hke_…` citado en `roadmap.md`

### Validación
- [ ] Ejecutar `pytest tests/test_recommender_v2.py -v` y confirmar que pasa
- [ ] Añadir `recommend` de v2 a `POLICIES` del notebook y comparar con IPS/SNIPS frente a baseline y coview
- [ ] Anotar conversión e ingresos por request de la ronda final por `model_version` (desempate)
- [ ] Comprobar en `team_34.feedback` que `served_by = team` y p95 de latencia < 3 s

### Modelo (para después de la final)
- [ ] Cold start: embeddings o similitud de texto de `description` para productos nuevos (hoy entran con puntuación 0)
- [ ] Usar `device`, `region` y `page` (ahora se ignoran)
- [ ] Aprender de `team_34.feedback` (clics y compras), no solo evitar repeticiones
- [ ] Validar con datos los pesos puestos a mano (×5, ×20, ×40, 0,8, tope de 5)
- [ ] Usar cambios de precio de `catalog_updates` (descuentos) como señal
- [ ] Corregir el sesgo de popularidad con `propensity` (IPS) al entrenar
- [ ] Exploración (bandit) para probar productos poco vistos
- [ ] Ideas de `data` (Cristian): carritos en vivo, perfil y precio del usuario, cold start por texto
- [ ] Idea de `algorithm` (Rubén): límite de diversidad por categoría

### Robustez
- [ ] Evitar la carrera en el `Refresher`: sustituir el modelo de golpe en lugar de reasignar campos uno a uno
- [ ] Subir el límite de 50 requests por consulta, por si el bucle se retrasa
- [ ] Mantener el sistema con `systemd` o `tmux` en una máquina que no se suspenda hasta las 12:00

### Repositorio y presentación
- [ ] Quitar `team_34` escrito a mano de `queries.sql` (volver a `team_NN`)
- [ ] Actualizar `roadmap.md`: sigue listando como pendientes cosas ya hechas
- [ ] Fusionar `infraestructure` en `main` o indicar cuál es la rama final
- [ ] Decidir qué recomendador es el final (infraestructure, data o algorithm) y combinar lo mejor de cada uno
- [ ] Resumen de una página para el jurado: idea, datos que la justifican, uso del stream, límites
- [ ] Demo preparada y respuesta a "¿cómo lo validasteis offline?"

# Rama `data` (Cristian): exploración + recomendador más completo

## ✅ Hecho

### Exploración de datos
- [x] `run_sql.py`: ejecuta cualquier .sql contra RawTree, sustituye `team_NN` por tu TEAM_ID e imprime tablas con pandas
- [x] `starter/carga.sql`: consultas de análisis (conversión por página y dispositivo, % de compras de productos ya vistos, embudo view → carrito → compra, precio medio comprado por región y dispositivo, diagnóstico del feedback)
- [x] Lectura de `.env` más robusta (ignora comentarios, busca también en la carpeta superior)

### Recomendador (`recommender_V2.py`, "v3 - Cristian")
- [x] Dos snapshots en hilo de fondo: rápido cada 6 s (catálogo, stock, popularidad, carritos en vivo) y pesado cada 10 min (co-compras, perfiles, precios)
- [x] Catálogo actual aplicando `catalog_updates` (precio, stock, activo, producto nuevo, descuento)
- [x] Popularidad ponderada: compra 5, carrito 2, vista 0,2 en histórico; ×6 y más en eventos de los últimos 90 min
- [x] Vistas de la sesión con decaimiento 0,75 por antigüedad
- [x] Co-compras de los últimos 21 días (vista y carrito → compra, top 25 por producto)
- [x] Carritos en vivo (últimos 20 min) como señal fuerte
- [x] Perfil de usuario: productos comprados, 6 más interactuados y precio medio de compra
- [x] Afinidad de precio por usuario, o por región y dispositivo si el usuario es nuevo
- [x] Boost por descuento
- [x] Cold start: similitud por texto (palabras de marca, subcategoría y descripción, más 0,25 si es la misma marca) para productos nuevos o poco populares
- [x] Excluye productos ya comprados (histórico y en vivo), agotados e inactivos
- [x] Más peso al histórico personal en `home` o sin vistas
- [x] Cadena de relleno por popularidad cuando faltan candidatos
- [x] Dos sesiones HTTP (una para tiempo real y otra para fondo), consulta solo de requests de los últimos 3 s, deduplicación con cola de 20.000 ids y log de edad de la request en ms

## ⏳ Pendiente
- [ ] Sin tests ni evaluación offline (IPS/SNIPS)
- [ ] Los pesos (2,4 / 2,9 / 4,5 / 1,7…) están puestos a mano, sin validar
- [ ] Sin límite de diversidad por subcategoría o categoría
- [ ] Arranque: el bucle espera solo al snapshot rápido, así que las co-compras y perfiles están vacíos hasta el primer refresco pesado (puede tardar hasta decenas de segundos)
- [ ] Consulta de perfiles sobre todo `history_events` (~12 M filas): coste alto, comprobar tiempos
- [ ] Excluye todo lo comprado alguna vez por el usuario: validar que no quita aciertos (el README dice que "tiende" a no recomprar)
- [ ] Los errores de push no se reintentan (aceptable si ya iría tarde, pero no queda registro)
- [ ] `carga.sql` tiene `team_34` escrito a mano en la última consulta
- [ ] No aprende de `team_34.feedback` (clics y compras)
- [ ] Aclarar en el repo qué archivo es el final: `recommender_v1.py` o `recommender_V2.py` (la `V` mayúscula puede dar problemas de importación)


# Rama `algorithm` (Rubén): reescritura del baseline con puntuación híbrida

## ✅ Hecho
- [x] Reescribe `starter/recommender.py` (+469 / −63 líneas), marcado "v2-ruben"
- [x] Puntuación híbrida: compras 0,25, carritos 0,25, vistas 0,10 (logarítmicas, normalizadas por el máximo) + afinidad de categoría 0,20, subcategoría 0,15 y marca 0,05 según lo visto en la sesión
- [x] Tope de 3 productos por categoría en la primera pasada y relleno después
- [x] Filtro de agotados cada 1 s y de productos ya vistos
- [x] Refresco del catálogo y de las estadísticas cada 5 min
- [x] Respuestas acumuladas y enviadas cada 0,5 s; solo se vacía el buffer si el push tiene éxito
- [x] Sondeo cada 0,1 s (más rápido que el baseline, de 0,3 s)
- [x] Cabecera y comentarios por secciones, más legible que el baseline
- [x] `.gitignore` con `.vscode` y `team_34` en `queries.sql`

## ⏳ Pendiente
- [ ] Excluye los productos ya vistos, pero según el análisis de v2 un producto visto en el slot 1 se compra ~17× más: probar a incluirlos
- [ ] Sin co-compras ni señal de sesión más allá de categoría, subcategoría y marca
- [ ] Lee el catálogo de `shop.catalog` pero no aplica `catalog_updates`: no ve productos nuevos, cambios de precio ni inactivos nuevos
- [ ] Las estadísticas vienen solo de `history_events`: ninguna señal de `shop.events` en vivo ni de tendencias
- [ ] Sin cold start (los productos nuevos no están en el catálogo cargado)
- [ ] No excluye lo que el usuario ya compró
- [ ] No usa `device`, `region`, `page` ni precio
- [ ] Recorre todo el catálogo por request y recalcula los máximos cada vez: se puede precalcular
- [ ] `load_catalog` filtra con `is_active is True`: comprobar que el tipo Dynamic devuelve un booleano
- [ ] Sin tests ni evaluación offline
- [ ] Mismo `team_34` escrito a mano en `queries.sql`
- [ ] El docstring dice "V3 Hybrid" y `model_version` dice "v2-ruben": unificar para identificar bien la versión en `submissions`


# Común a las tres ramas (algorithm, data, infraestructure)
- [ ] Decidir qué recomendador es el final y fusionarlo en `main`
- [ ] Comparar los tres con el mismo método offline (IPS/SNIPS del notebook) y con el feedback de la ronda
- [ ] Combinar lo mejor de cada uno: lo visto primero y los tests de v2 (infraestructure), cold start, precio y carritos en vivo de `data`, y el límite de diversidad de `algorithm`
- [ ] Quitar `team_34` y la clave de `request.py` (rama infraestructure) del repo