## Introductorio

- [x] Credenciales de equipo: en la rama infraestructure aparece team_34 en queries.sql.
- [x] Crear .env con TEAM_ID y RAWTREE_API_KEY, fuera de git (.env está en .gitignore).
- [x] Conocer RawTree y sus tablas: las consultas SQL de v2 ya usan shop.* y team_34.feedback.
- [X] Haber ejecutado el baseline (python starter/recommender.py) y aparecer en la leaderboard.
- [x] Explorar el histórico: el docstring de v2 cita estadísticas reales (17× por producto visto, 7× por co-compra, sesgo de posición).
- [ ] Por confirmar: evaluar offline con offline_eval.ipynb. El notebook no cambió en la rama y v2 no está añadido a sus POLICIES.
- [x] Desplegar y mejorar sobre el baseline: v2 está escrita.
- [ ] Por confirmar: leer team_34.feedback y ajustar con la ronda de práctica del sábado.
- [ ] Dejar el sistema corriendo desatendido en una máquina que no se suspenda, con la mejor versión activa antes de las 10:00.
- [ ] Preparar la presentación con demo para el jurado (30 puntos). Pide método, validación offline, uso del stream, uso de RawTree y comunicación clara.
- [ ] Tener el repo legible para compartirlo con el jurado. Esto incluye un .env.example en el repo, que ahora .gitignore excluye.

## Progreso rama infra

- [x] Recomendador con listas en cuatro fases: vistos, co-comprados, populares de la subcategoría y populares globales.
- [x] Filtros de agotados, inactivos y ya comprados por ese usuario en las últimas 6 horas.
- [x] Límite de 5 productos por subcategoría para diversificar.
- [x] Popularidad con peso reciente y en vivo (×5 / ×20 / ×40).
- [x] Cálculo pesado en SQL dentro de RawTree y refresco en segundo plano (stock y compradores cada ~2 s, reconstrucción completa cada 10 min).
- [x] Logging y manejo de errores para que el bucle no se caiga.
- [x] Suite de tests con pytest (~700 líneas), incluidos los de seguridad entre hilos. Yo no los he ejecutado.
- [x] MODEL_VERSION separado en el baseline y .gitignore actualizado.
- [X] Sin hacer: fusionar infraestructure en main. Hoy main sigue teniendo el baseline original.

## Antes de las 10:00 (lo urgente)

- [ ] Revocar la clave sk-hke_… de request.py y borrar el archivo. Está en el historial de git, así que la revocación es lo importante.
- [ ] Ejecutar python -m pytest tests/test_recommender_v2.py -v y confirmar que pasa.
- [ ] Lanzar python starter/recommender_v2.py en una máquina que no se suspenda (desactivar el reposo, mejor con tmux o nohup).
- [ ] Comprobar en team_34.feedback que served_by = team y que la latencia está bajo 3 s. El semáforo de la leaderboard debe estar en verde.
- [ ] No cambiar nada grande en los últimos minutos. Con el modelo en marcha es mejor que sea estable que “algo mejor y roto”.

## Durante la final (10:00–12:00)

- [ ] Vigilar el semáforo y las consultas 5 y 6 de queries.sql (conversión y fallback). Si hay un error, que se reinicie solo.
- [ ] Anotar la conversión y los ingresos por request, porque son el desempate.

## Después, para la presentación y la limpieza

- [ ] Añadir recommend de v2 al notebook y comparar con IPS/SNIPS frente al baseline y coview. Es la respuesta a “¿cómo lo validasteis offline?”.
- [X] Fusionar infraestructure en main (o dejar claro cuál es la rama final) y quitar team_34 y claves del código.
- [X] Subir un .env.example con valores vacíos y quitarlo del .gitignore.
- [ ] Preparar un resumen de una página para el jurado: la idea (lo visto primero, luego lo co-comprado, luego lo popular), los datos que la justifican, el uso en vivo del stream y los límites conocidos.
- [ ] Mejoras futuras que mencionar: embeddings de description para productos nuevos, ajuste por device y region, y pesos aprendidos con feedback en lugar de fijos.
