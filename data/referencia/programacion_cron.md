---
categoria: referencia
tags: scheduler, cron, periodicas, beat
---
# Programación de tareas periódicas

Además de tareas encoladas bajo demanda, Tasklet incluye un planificador (scheduler) para ejecutar tareas de forma periódica. El proceso que dispara las tareas programadas se llama `beat`.

## Expresiones cron

La clase `Schedule` permite definir una periodicidad con sintaxis cron de cinco campos (minuto, hora, día del mes, mes, día de la semana):

```python
from tasklet import Schedule

# Cada 5 minutos
app.schedule(limpiar_cache, Schedule.cron("*/5 * * * *"))

# Todos los días a las 03:30
app.schedule(generar_reporte, Schedule.cron("30 3 * * *"))
```

## Intervalos fijos

Para intervalos simples se puede usar `Schedule.every`:

```python
app.schedule(heartbeat_externo, Schedule.every(seconds=30))
```

## Zona horaria

Por defecto las expresiones cron se evalúan en UTC. Para usar otra zona horaria se pasa el parámetro `tz`:

```python
Schedule.cron("0 9 * * 1-5", tz="America/Argentina/Buenos_Aires")
```

Esta programación ejecuta la tarea a las 9:00 hora de Buenos Aires, de lunes a viernes.

## Ejecutar el planificador

```bash
tasklet beat --app mi_proyecto:app
```

Importante: debe haber una sola instancia de `beat` activa. Si se ejecutan dos instancias, cada tarea programada se dispararía dos veces. Para entornos con alta disponibilidad se puede activar el bloqueo distribuido con la opción `beat_lock=True`, que usa el broker para garantizar que solo un `beat` esté activo.

## Tareas perdidas (misfire)

Si el planificador estuvo caído cuando debía dispararse una tarea, el parámetro `misfire_grace_time` (en segundos, por defecto 60) define hasta cuánto después se permite ejecutarla igualmente. Pasado ese tiempo, la ejecución se descarta y se espera al próximo ciclo.
