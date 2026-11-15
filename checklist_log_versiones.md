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

# v3 - Cristian (rama `data`): checklist actualizado (15-nov, 11:04)

## ✅ Hecho

### Exploración y herramientas
- [x] `run_sql.py`: ejecuta cualquier .sql contra RawTree, sustituye `team_NN` por tu TEAM_ID y muestra tablas con pandas
- [x] `starter/carga.sql`: análisis del histórico (conversión por página y dispositivo, % de compras de productos ya vistos, embudo view → carrito → compra, precio medio por región y dispositivo)
- [x] Consultas de diagnóstico para la ronda en vivo (nuevo en `a9f4ab9`): respuestas por `model_version`, 15 filas más recientes de `team_34.feedback`, feedback por minuto con p95 de latencia, esquema de las tablas y tipos de `catalog_updates`
- [x] Lectura de `.env` más robusta (ignora comentarios, busca también en la carpeta superior)
- [x] `team_34` en `queries.sql` (a mano, igual que en las otras ramas)

### Recomendador (`recommender_V2.py`, "v3 - Cristian")
- [x] Dos snapshots en hilos de fondo: rápido cada 6 s (catálogo, stock, popularidad, carritos en vivo) y pesado cada 10 min (co-compras, perfiles, precios)
- [x] Catálogo actual aplicando `catalog_updates` (precio, stock, activo, producto nuevo, descuento)
- [x] Popularidad ponderada: compra 5, carrito 2, vista 0,2 en histórico; compra 30, carrito 10, vista 1,5 en eventos de los últimos 90 min
- [x] Vistas de la sesión con decaimiento 0,75 por antigüedad
- [x] Co-compras de los últimos 21 días (vista y carrito → compra, top 25 por producto)
- [x] Carritos en vivo (últimos 20 min) como señal fuerte
- [x] Perfil de usuario: productos comprados, 6 más interactuados y precio medio de compra
- [x] Afinidad de precio por usuario, o por región y dispositivo si el usuario es nuevo
- [x] Boost por descuento
- [x] Cold start: similitud por texto (marca, subcategoría y descripción, más 0,25 si es la misma marca) para productos nuevos o poco populares
- [x] Excluye productos ya comprados (histórico y en vivo), agotados e inactivos
- [x] Más peso al histórico personal en `home` o sin vistas
- [x] Cadena de relleno por popularidad cuando faltan candidatos
- [x] Dos sesiones HTTP (tiempo real y fondo), consulta solo de requests de los últimos 3 s, deduplicación con cola de 20.000 ids y log de la edad de la request en ms

## ⏳ Pendiente

### Fallos a corregir
- [ ] `recommender_v1.py`, línea 379: `refresh_hist_pop()` sin `self.` lanza `NameError` y mata el hilo de fondo; con ese archivo el sistema no responde a ninguna request (todo cae al fallback). Cambiar a `self.refresh_hist_pop()`
- [ ] Confirmar qué archivo está corriendo (`recommender_v1.py` marca "v2 - Cristian"; `recommender_V2.py` marca "v3 - Cristian") y que no es el que tiene el fallo
- [ ] Comprobar con la consulta 1 de `carga.sql` qué `model_version` están respondiendo y cuántas respuestas ha enviado cada una

### Conflicto de equipo
- [ ] Hay dos versiones posibles (v3-Shichen y v3 - Cristian) con el mismo `team_34`: si corren a la vez, cada request recibe dos respuestas, solo cuenta una y el feedback se mezcla
- [ ] Decidir quién corre hasta las 12:00 y apagar la otra
- [ ] Mirar que el semáforo de la leaderboard no esté en verde solo por la otra versión

### Validación
- [ ] Sin tests ni evaluación offline (IPS/SNIPS)
- [ ] Comprobar en `team_34.feedback` que `served_by = team` y que el p95 de latencia está por debajo de 3 s
- [ ] Comparar la conversión por `model_version` en la ronda final

### Modelo
- [ ] Pesos puestos a mano (2,4 / 2,9 / 4,5 / 1,7…), sin validar
- [ ] Sin límite de diversidad por categoría o subcategoría
- [ ] Arranque: el bucle solo espera al snapshot rápido; co-compras y perfiles están vacíos hasta el primer refresco pesado
- [ ] La consulta de perfiles recorre todo `history_events` (~12 M filas): revisar tiempos
- [ ] Excluye todo lo que el usuario compró alguna vez: validar que no quita aciertos
- [ ] Errores de push sin reintento ni registro
- [ ] No aprende de `team_34.feedback` (clics y compras)

### Repositorio
- [ ] `team_34` escrito a mano en `carga.sql` y `queries.sql` (volver a `team_NN`)
- [ ] Aclarar el archivo final (`recommender_v1.py` o `recommender_V2.py`; la `V` mayúscula puede dar problemas de importación)
- [ ] Decidir qué recomendador es el final y fusionarlo en `main`
- [ ] Combinar lo mejor de cada rama: tests y filtros de v3-Shichen, cold start, precio y carritos en vivo de `data`, límite de diversidad de `algorithm`
- [ ] Resumen de una página y demo para el jurado

# v2-ruben (rama `algorithm`): checklist actualizado (15-nov, 11:16)

## ✅ Hecho
- [x] Reescribe `starter/recommender.py` (+469 / −63 líneas), con `model_version = "v2-ruben"`
- [x] Puntuación híbrida: compras 0,25, carritos 0,25, vistas 0,10 (logarítmicas, normalizadas por el máximo) + afinidad de categoría 0,20, subcategoría 0,15 y marca 0,05 según lo visto en la sesión
- [x] Tope de 3 productos por categoría en la primera pasada y relleno después
- [x] Filtro de agotados cada 1 s y de productos ya vistos
- [x] Refresco del catálogo y de las estadísticas cada 5 min
- [x] Respuestas acumuladas y enviadas cada 0,5 s; solo se vacía el buffer si el push tiene éxito
- [x] Sondeo cada 0,1 s (el baseline era de 0,3 s)
- [x] Cabecera y comentarios por secciones, más legible que el baseline
- [x] Cabecera corregida a "V2 Recommendation System" (antes decía V3 y no coincidía con `model_version`) — nuevo en `d480781`
- [x] `.gitignore` reorganizado: `.pytest_cache/` y `.vscode/`, y `.env.example` ya no se ignora — nuevo
- [x] Merge de `infraestructure`: clave quitada del código de `request.py`, `tests/` incorporados — nuevo
- [x] `team_34` en `queries.sql`

## ⏳ Pendiente

### Fallos introducidos por el merge
- [ ] `tests/test_recommender_v2.py` importa `starter.recommender_v2`, que no existe en esta rama: los tests fallan con `ImportError`; escribir tests para `recommender.py` o quitarlos de esta rama
- [ ] `request.py` manda `RAWTREE_API_KEY` a `api.helmcode.com`: usar otra variable (por ejemplo `HELMCODE_API_KEY`) y añadir `openai` y `python-dotenv` a `requirements.txt`
- [ ] La clave antigua de helmcode sigue en el historial (commits `af33f96` y `c89550b`): revocarla

### Modelo (sin cambios desde el commit anterior)
- [ ] Excluye los productos ya vistos, pero en el análisis de `infraestructure` un producto visto puesto en el slot 1 se compra ~17× más: probar a incluirlos
- [ ] Sin co-compras ni señal de sesión más allá de categoría, subcategoría y marca
- [ ] Lee el catálogo de `shop.catalog` pero no aplica `catalog_updates`: no ve productos nuevos, cambios de precio ni inactivos nuevos
- [ ] Estadísticas solo de `history_events`: sin `shop.events` en vivo ni tendencias
- [ ] Sin cold start (los productos nuevos no están en el catálogo cargado)
- [ ] No excluye lo que el usuario ya compró
- [ ] No usa `device`, `region`, `page` ni precio
- [ ] Recorre todo el catálogo por request y recalcula los máximos cada vez: se puede precalcular
- [ ] `load_catalog` filtra con `is_active is True`: comprobar que el tipo Dynamic devuelve un booleano
- [ ] Sin evaluación offline (IPS/SNIPS)
- [ ] Pesos (0,25 / 0,20 / 0,15…) puestos a mano, sin validar

### Repositorio y equipo
- [ ] `team_34` escrito a mano en `queries.sql` (volver a `team_NN`)
- [ ] Decidir qué recomendador es el final y fusionarlo en `main`
- [ ] No ejecutar `v2-ruben` a la vez que otra versión con el mismo `team_34` (cada request recibiría dos respuestas y solo cuenta una)
