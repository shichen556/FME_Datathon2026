# Mejoras respecto al baseline original (main → infraestructure / v2)

## ✅ Hecho en v2

### Ranking
- [x] Personalización por sesión: los productos vistos van primero (sustituye a "los mismos 10 más vendidos para todos")
- [x] Co-compras: productos comprados en sesiones donde se vio el producto visto, con decaimiento 0,8 por antigüedad de la vista
- [x] Más vendidos de las subcategorías vistas
- [x] Más vendidos globales como relleno final (lo que reciben los shoppers sin vistas)
- [x] Diversidad: máximo 5 productos por subcategoría en las fases de co-compra y populares globales
- [x] Orden pensado para los slots: lo más probable de comprar va en el slot 1

### Datos y aprendizaje en vivo
- [x] Popularidad con peso reciente: histórico + 7 días (×5) + eventos en vivo (×20) + últimas 3 h (×40)
- [x] Uso de `shop.events` en tiempo real (el baseline solo calculaba una vez al arrancar)
- [x] Modelo reconstruido cada 10 min en segundo plano
- [x] No recomendar lo que el usuario ya compró en las últimas 6 h (tienda + tu propio feedback)

### Validez y fiabilidad
- [x] Filtro de productos agotados (cada ~2 s)
- [x] Filtro de productos inactivos (`is_active`), que el baseline no comprobaba
- [x] Hilo `Refresher` en segundo plano: responder es solo Python en memoria (<1 ms)
- [x] Logging y manejo de errores; el bucle no se cae
- [x] Conserva el último modelo si falla una actualización

### Calidad del código
- [x] ~700 líneas de tests con pytest (fases, casos límite, concurrencia, carga del modelo)
- [x] `MODEL_VERSION` separado, para ver qué versión respondió en `submissions`

## ⏳ Pendiente

### Seguridad y limpieza (urgente)
- [ ] Revocar la clave `sk-hke_…` de `request.py` y borrar el archivo (sigue en el historial de git)
- [ ] Quitar `team_34` escrito a mano en `queries.sql` (volver a `team_NN`)
- [ ] Subir `.env.example` con valores vacíos y quitarlo del `.gitignore`
- [ ] Fusionar `infraestructure` en `main` o indicar cuál es la rama final

### Validación
- [ ] Ejecutar `pytest tests/test_recommender_v2.py -v` y confirmar que pasa
- [ ] Añadir v2 a `POLICIES` del notebook y comparar con IPS/SNIPS frente a baseline y `coview`
- [ ] Anotar conversión e ingresos por request de la ronda final (desempate)

### Modelo
- [ ] Cold start: embeddings de `description` para productos nuevos (hoy entran con puntuación 0)
- [ ] Usar `device`, `region` y `page` (ahora se ignoran)
- [ ] Aprender de `team_34.feedback` (clics y compras), no solo evitar repeticiones
- [ ] Ajustar con datos los pesos fijados a mano (×5, ×20, ×40, 0,8, tope de 5)
- [ ] Filtrar por cambios de precio de `catalog_updates`
- [ ] Corregir el sesgo de popularidad con `propensity` (IPS) al entrenar
- [ ] Exploración (bandit) para probar productos poco vistos

### Robustez
- [ ] Evitar la carrera entre hilos: sustituir el modelo entero de golpe en el `Refresher`, en lugar de reasignar campos uno a uno
- [ ] Aumentar el límite de 50 requests por consulta, por si el bucle se retrasa
- [ ] Ejecutar con `systemd` o `tmux` en una máquina que no se suspenda

### Presentación (jurado)
- [ ] Resumen de una página: idea, datos que la justifican, uso del stream, límites
- [ ] Demo preparada y respuesta a "¿cómo lo validasteis offline?"
- [ ] Repo legible para compartir con el jurado